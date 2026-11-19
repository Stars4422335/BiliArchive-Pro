"""QA 独立验证：退避账本在**真实旧库**上的安全性（迁移 + 边界）。

自带一份"只含旧 schema 的 SQLite"（没有 fail_count / last_fail，也没有
integrity_status / source 等后加列），逐字节比对迁移前后的既有数据，
并重复打开确认迁移幂等。边界覆盖 fail_count 极大值、last_fail 为
脏字符串 / 空串 / 未来时间（时钟回拨），以及"从没下载成功过"的最小行。
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from app.core.database_manager import DatabaseManager
from app.core.retry_policy import (
    DEFAULT_BACKOFF_CAP_SECONDS,
    backoff_seconds,
    remaining_backoff_seconds,
    should_skip_for_backoff,
)

LEGACY_COLUMNS = ["bvid", "title", "type", "status", "path", "last_check", "p_count"]

LEGACY_ROWS = [
    # 正常已归档资产
    ("BV1legacyA", "旧资产甲", "video", 0, "./downloads/fav/a [BV1legacyA]",
     "2024-01-01 00:00:00", 1),
    # 墓碑行（源端已删）
    ("BV1legacyB", "旧资产乙", "video", 1, "./downloads/fav/b [BV1legacyB]",
     "2024-01-02 00:00:00", 2),
    # 多 P 资产
    ("BV1legacyC", "旧资产丙", "video", 0, "./downloads/fav/c [BV1legacyC]",
     "2023-12-31 23:59:59", 7),
]


def _make_legacy_db(db_path):
    """造一个"改造前"的库：只有旧列，没有任何账本列。"""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE assets (
                bvid TEXT PRIMARY KEY NOT NULL,
                title TEXT,
                type TEXT,
                status INTEGER NOT NULL DEFAULT 0,
                path TEXT,
                last_check TEXT,
                p_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.executemany(
            f"INSERT INTO assets ({', '.join(LEGACY_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in LEGACY_COLUMNS)})",
            LEGACY_ROWS,
        )
        connection.commit()
    finally:
        connection.close()


def _dump_legacy_columns(db_path):
    """按 bvid 排序导出旧列的全部取值，用于迁移前后逐字段比对。"""
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            f"SELECT {', '.join(LEGACY_COLUMNS)} FROM assets ORDER BY bvid"
        ).fetchall()
    finally:
        connection.close()
    return rows


def _columns(db_path):
    connection = sqlite3.connect(db_path)
    try:
        return {row[1] for row in connection.execute("PRAGMA table_info(assets)")}
    finally:
        connection.close()


def test_legacy_database_migrates_without_touching_existing_rows(tmp_path):
    """旧库升级：新列默认 0/NULL，原有行一字不变。"""
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)
    before = _dump_legacy_columns(db_path)

    manager = DatabaseManager(db_path)
    try:
        columns = {
            row[1] for row in manager.conn.execute("PRAGMA table_info(assets)").fetchall()
        }
        assert {"fail_count", "last_fail"} <= columns, "账本列没有迁移出来"

        for bvid, _title, _type, _status, _path, _last_check, _p_count in before:
            record = manager.get_asset(bvid)
            assert record is not None, f"迁移后丢了旧行: {bvid}"
            assert record["fail_count"] == 0, f"{bvid} 的 fail_count 不是默认 0"
            assert record["last_fail"] is None, f"{bvid} 的 last_fail 不是 NULL"

        # 旧列逐字段比对：迁移绝不能改写任何既有值。
        assert _dump_legacy_columns(db_path) == before
    finally:
        manager.close()

    assert _dump_legacy_columns(db_path) == before, "关闭数据库后旧数据被改动了"


def test_migration_is_idempotent_across_repeated_opens(tmp_path):
    """重复打开三次：列集合、行数据与 user_version 全部稳定。"""
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)
    before = _dump_legacy_columns(db_path)

    snapshots = []
    for _ in range(3):
        manager = DatabaseManager(db_path)
        try:
            snapshots.append(
                (
                    frozenset(
                        row[1]
                        for row in manager.conn.execute("PRAGMA table_info(assets)").fetchall()
                    ),
                    manager.conn.execute("PRAGMA user_version").fetchone()[0],
                    _dump_legacy_columns(db_path),
                )
            )
        finally:
            manager.close()

    assert snapshots[0] == snapshots[1] == snapshots[2], "迁移不幂等"
    assert snapshots[0][2] == before
    assert snapshots[0][1] == DatabaseManager.SCHEMA_VERSION


def test_ledger_is_usable_immediately_after_migration(tmp_path):
    """迁移后账本立刻可用，且失败计数不会污染旧的 status/path。"""
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)

    manager = DatabaseManager(db_path)
    try:
        assert manager.record_download_failure("BV1legacyA", "源端 404") == 1
        assert manager.record_download_failure("BV1legacyA") == 2

        record = manager.get_asset("BV1legacyA")
        assert record["fail_count"] == 2
        assert record["last_fail"] is not None
        # 账本只动两个新列：已归档资产仍然是 Active 且带路径
        assert record["status"] == 0
        assert record["path"] == "./downloads/fav/a [BV1legacyA]"

        assert manager.reset_download_failures("BV1legacyA") is True
        assert manager.get_asset("BV1legacyA")["fail_count"] == 0
        assert manager.get_asset("BV1legacyA")["last_fail"] is None
    finally:
        manager.close()


def test_failure_for_unknown_key_creates_minimal_row_with_null_path(tmp_path):
    """首次就失败（从未下载成功）：必须能建档，且 path 为 NULL / status 为 0。"""
    manager = DatabaseManager(tmp_path / "archive.db")
    try:
        assert manager.record_download_failure("BV1never", "版权限制") == 1

        record = manager.get_asset("BV1never")
        assert record is not None
        assert record["fail_count"] == 1
        assert record["path"] is None
        assert record["status"] == 0
        assert record["title"] is None
        assert record["type"] is None

        # 第二次失败在同一行上累加，而不是新建一行
        assert manager.record_download_failure("BV1never") == 2
        count = manager.conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        assert count == 1
    finally:
        manager.close()


def test_reset_on_missing_key_does_not_create_a_row(tmp_path):
    manager = DatabaseManager(tmp_path / "archive.db")
    try:
        assert manager.reset_download_failures("BV1ghost") is False
        assert manager.get_asset("BV1ghost") is None
    finally:
        manager.close()


# ---------- 边界：极大值 / 脏时间戳 / 时钟回拨 ----------


@pytest.mark.parametrize("huge", [9999, 10**6, 2**31 - 1])
def test_huge_fail_count_does_not_overflow_and_respects_cap(huge):
    """极大失败次数：不溢出，且金额封顶在 cap。"""
    assert backoff_seconds(huge) == DEFAULT_BACKOFF_CAP_SECONDS
    assert backoff_seconds(huge) == 7 * 24 * 3600

    recent = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    record = {"fail_count": huge, "last_fail": recent}
    remaining = remaining_backoff_seconds(record)
    assert 0 < remaining <= DEFAULT_BACKOFF_CAP_SECONDS
    assert should_skip_for_backoff(record) is True


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "not-a-date",
        "",
        "   ",
        None,
        "2024-13-45 99:99:99",
        "0000-00-00 00:00:00",
        12345,
    ],
)
def test_corrupted_last_fail_never_freezes_the_asset(bad_timestamp):
    """账本时间戳坏掉时宁可再试一次，也不能让资产永久卡在冷却里。"""
    record = {"fail_count": 4, "last_fail": bad_timestamp}

    assert should_skip_for_backoff(record) is False
    assert remaining_backoff_seconds(record) == 0


@pytest.mark.parametrize("hours_ahead", [1, 24, 24 * 30])
def test_future_last_fail_from_clock_rollback_does_not_bypass_or_freeze(hours_ahead):
    """时钟回拨（last_fail 在未来）：按"刚失败"处理，冷却完整生效但不永生。"""
    now = datetime.now()
    record = {
        "fail_count": 1,
        "last_fail": (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 负的 elapsed 被夹到 0：拿到的是完整的一档冷却，而不是被负剩余时长绕过
    assert remaining_backoff_seconds(record, now) == 3600
    assert should_skip_for_backoff(record, now) is True
    # 时间走过"未来那条记录"之后自然解冻，不会因为时间戳在未来而永生
    later = now + timedelta(hours=hours_ahead + 2)
    assert should_skip_for_backoff(record, later) is False


def test_timezone_aware_last_fail_survives_the_round_trip(tmp_path):
    """WebUI/历史数据里带时区的时间戳不能把冷却判定弄崩。"""
    aware = datetime.now().astimezone()
    record = {"fail_count": 1, "last_fail": aware.isoformat()}

    assert should_skip_for_backoff(record, aware) is True
    assert should_skip_for_backoff(record, aware + timedelta(hours=2)) is False
    # naive 时钟也不能因为 aware/naive 相减而抛异常
    assert isinstance(remaining_backoff_seconds(record, aware.replace(tzinfo=None)), int)
