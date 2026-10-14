"""数据库性能相关的测试（M4 性能治理）。

重点不是断言"跑得快"——那在 CI 上不稳定——而是断言**结构性事实**：
1. 启动时确实建了实测有效的索引；
2. 实测有害的旧索引会被主动清理；
3. WebUI 排序查询不再使用阻断索引的 COALESCE 表达式；
4. WAL 可选且失败时静默降级，不让引擎起不来；
5. 排序语义未变（NULL 仍排最后）。
"""

import sqlite3

import pytest

from app.core.database_manager import DatabaseManager
from app.webui.service import WebService


def _indexes(db):
    return {
        row[1]
        for row in db.conn.execute("PRAGMA index_list(assets)").fetchall()
        if row[1].startswith("idx_assets")
    }


def test_startup_creates_benchmarked_indexes(tmp_path):
    db = DatabaseManager(str(tmp_path / "a.db"))
    try:
        names = _indexes(db)
        assert "idx_assets_lastcheck" in names
        assert "idx_assets_type" in names
    finally:
        db.close()


def test_harmful_verify_index_is_not_created(tmp_path):
    """idx_assets_verify 实测让 candidates_for_verify 慢 2~10 倍，不应存在。"""
    db = DatabaseManager(str(tmp_path / "b.db"))
    try:
        assert "idx_assets_verify" not in _indexes(db)
    finally:
        db.close()


def test_existing_harmful_index_is_dropped_on_startup(tmp_path):
    """旧库可能已建过该索引，启动时应主动清理。"""
    path = tmp_path / "c.db"
    db = DatabaseManager(str(path))
    db.conn.execute(
        "CREATE INDEX idx_assets_verify ON assets(status, type, last_verify, last_check)"
    )
    db.conn.commit()
    db.close()

    reopened = DatabaseManager(str(path))
    try:
        assert "idx_assets_verify" not in _indexes(reopened)
        assert "idx_assets_lastcheck" in _indexes(reopened)
    finally:
        reopened.close()


def test_indexes_created_after_column_migration(tmp_path):
    """索引依赖 last_verify 列，必须在 ALTER TABLE 补列之后创建。

    模拟 v1.5.0 之前的老库：缺 integrity_status / last_verify。
    """
    path = tmp_path / "d.db"
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE assets (
            bvid TEXT PRIMARY KEY NOT NULL,
            title TEXT, type TEXT, status INTEGER, path TEXT,
            last_check TEXT, p_count INTEGER
        );
        """
    )
    raw.commit()
    raw.close()

    db = DatabaseManager(str(path))
    try:
        columns = {r[1] for r in db.conn.execute("PRAGMA table_info(assets)")}
        assert "integrity_status" in columns
        assert "last_verify" in columns
        assert "idx_assets_lastcheck" in _indexes(db)
    finally:
        db.close()


def test_repeated_open_is_idempotent(tmp_path):
    path = tmp_path / "e.db"
    for _ in range(3):
        db = DatabaseManager(str(path))
        db.close()

    db = DatabaseManager(str(path))
    try:
        names = _indexes(db)
        assert len(names) == len(
            [n for n in DatabaseManager._INDEXES if n[0] in names]
        )
    finally:
        db.close()


# ---------- WebUI 查询形态 ----------


def test_webui_query_does_not_block_index_with_coalesce():
    """COALESCE(last_check,'') 是表达式，索引无法用于排序。

    SQLite 中 DESC 排序本就把 NULL 放最后，语义与 COALESCE 一致，
    但能走上覆盖索引：2 万资产 9.5ms -> 0.11ms。
    """
    import inspect

    source = inspect.getsource(WebService.assets)
    assert "ORDER BY COALESCE" not in source
    assert "ORDER BY last_check DESC" in source


def test_webui_dashboard_query_does_not_use_coalesce():
    import inspect

    source = inspect.getsource(WebService.dashboard)
    assert "ORDER BY COALESCE" not in source
    assert "ORDER BY last_check DESC" in source


def test_webui_sort_keeps_nulls_last(tmp_path):
    """去掉 COALESCE 后，排序语义必须不变：空 last_check 仍排最后。"""
    db = DatabaseManager(str(tmp_path / "f.db"))
    try:
        db.conn.executemany(
            "INSERT INTO assets (bvid,last_check) VALUES (?,?)",
            [("BV3", "2026-10-01"), ("BV1", None), ("BV2", "2026-10-05")],
        )
        db.conn.commit()
        rows = db.conn.execute(
            "SELECT bvid FROM assets ORDER BY last_check DESC, bvid"
        ).fetchall()
        assert [r[0] for r in rows] == ["BV2", "BV3", "BV1"]
    finally:
        db.close()


# ---------- WAL ----------


def test_wal_disabled_by_default(tmp_path):
    db = DatabaseManager(str(tmp_path / "g.db"))
    try:
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "delete"
    finally:
        db.close()


def test_wal_enabled_when_requested(tmp_path):
    db = DatabaseManager(str(tmp_path / "h.db"), use_wal=True)
    try:
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        db.close()


def test_wal_allows_concurrent_reader(tmp_path):
    """WAL 的核心价值：读者不阻塞写入者。"""
    db = DatabaseManager(str(tmp_path / "i.db"), use_wal=True)
    try:
        db.conn.execute("INSERT INTO assets (bvid,title) VALUES ('BV1','t')")
        db.conn.commit()

        # 另开只读连接模拟 WebUI
        reader = sqlite3.connect(f"file:{tmp_path / 'i.db'}?mode=ro", uri=True, timeout=5)
        try:
            assert reader.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        finally:
            reader.close()
    finally:
        db.close()


def test_wal_failure_degrades_silently(tmp_path, capsys, monkeypatch):
    """无法启用 WAL 时应退回默认模式，而不是让引擎起不来。

    用一个只在该实例上抛错的连接替身，不动全局 sqlite3.connect。
    """
    real = sqlite3.connect(str(tmp_path / "k.db"))

    class FlakyConn:
        def execute(self, sql, *args):
            if "journal_mode" in sql.lower():
                raise sqlite3.OperationalError("disk I/O error")
            return real.execute(sql, *args)

    db = DatabaseManager.__new__(DatabaseManager)
    db.conn = FlakyConn()

    assert db._enable_wal() is False
    assert "WAL" in capsys.readouterr().out
    real.close()


def test_wal_reports_false_when_mode_not_wal(tmp_path, monkeypatch):
    """驱动返回非 wal 模式（如内存库或只读介质）时应报告未启用。"""
    db = DatabaseManager.__new__(DatabaseManager)
    db.conn = sqlite3.connect(":memory:")
    try:
        assert db._enable_wal() is False
    finally:
        db.conn.close()


def test_in_memory_database_ignores_wal():
    db = DatabaseManager(":memory:", use_wal=True)
    try:
        # :memory: 无法用 WAL，但也不能因此崩溃
        db.conn.execute("INSERT INTO assets (bvid) VALUES ('BV1')")
        db.conn.commit()
        assert db.get_asset("BV1") is not None
    finally:
        db.close()


@pytest.mark.parametrize("config", [
    {"db_wal": True},
    {"db_wal": False},
    {},
])
def test_main_passes_wal_flag(config):
    """main.py 必须把配置透传给 DatabaseManager。"""
    import inspect

    import main

    source = inspect.getsource(main.daemon_loop)
    assert "use_wal=" in source
    assert "db_wal" in source