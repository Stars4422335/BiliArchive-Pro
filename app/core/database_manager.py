import os
import re
import sqlite3
from datetime import datetime


class DatabaseManager:
    SCHEMA_VERSION = 1
    _MIGRATABLE_COLUMNS = {
        "title": "TEXT",
        "type": "TEXT",
        "status": "INTEGER NOT NULL DEFAULT 0",
        "path": "TEXT",
        "last_check": "TEXT",
        "p_count": "INTEGER NOT NULL DEFAULT 1",
        # F3 完整性巡检：0=未校验 1=通过 2=损坏
        "integrity_status": "INTEGER NOT NULL DEFAULT 0",
        "last_verify": "TEXT",
    }

    #: 面向真实查询的索引（万级资产实测后保留的只有这两个）。
    #:
    #: 刻意**不**为 candidates_for_verify 建索引：它的排序键
    #: `ORDER BY last_verify IS NOT NULL` 是表达式，SQLite 无法用索引排序，
    #: 反而要为每个匹配行回表再排临时 B-tree。实测 2 万资产下：
    #: 0% 填充 6.4->13.9ms，50% 填充 5.7->18.1ms，100% 填充 11.3->108.4ms，
    #: 全部更慢。扫描 + 排序在这个查询上本就更快。
    _INDEXES = (
        # WebUI 资产列表：ORDER BY last_check DESC, bvid（覆盖索引，无需回表）
        ("idx_assets_lastcheck", "assets(last_check DESC, bvid)"),
        # WebUI 按 type 筛选与 COUNT(*)
        ("idx_assets_type", "assets(type)"),
    )

    def __init__(self, db_path, *, use_wal: bool = False):
        parent_dir = os.path.dirname(os.path.abspath(db_path))
        if db_path != ":memory:" and parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        try:
            if use_wal:
                self._enable_wal()
            self._init_db()
        except Exception:
            self.conn.close()
            self.conn = None
            raise

    def _enable_wal(self):
        """开启 WAL：读者不再阻塞写入者。

        万级资产实测，写入被并发读事务阻塞 5.5s -> 15ms。
        失败时静默退回默认日志模式——WAL 需要在库同目录创建
        -wal/-shm，网络盘或只读挂载会失败，不应因此让引擎起不来。
        """
        if not self.conn:
            return False
        try:
            mode = self.conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if not mode or str(mode[0]).lower() != "wal":
                return False
            # NORMAL 在 WAL 下仍能保证崩溃安全，仅放宽 fsync 频率
            self.conn.execute("PRAGMA synchronous=NORMAL")
            return True
        except sqlite3.Error as exc:
            print(f"[!] 启用 WAL 失败，继续使用默认日志模式: {exc}")
            return False

    def _init_db(self):
        # status: 0-Active, 1-Tombstoned, 2-Protected
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    bvid TEXT PRIMARY KEY NOT NULL CHECK (length(trim(bvid)) > 0),
                    title TEXT,
                    type TEXT,
                    status INTEGER NOT NULL DEFAULT 0,
                    path TEXT,
                    last_check TEXT,
                    p_count INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watch_history (
                    bvid TEXT PRIMARY KEY NOT NULL CHECK (length(trim(bvid)) > 0),
                    title TEXT,
                    up_name TEXT,
                    view_at INTEGER NOT NULL DEFAULT 0,
                    last_sync TEXT
                )
                """
            )
            columns = {
                row[1]: row
                for row in self.conn.execute("PRAGMA table_info(assets)").fetchall()
            }
            if "bvid" not in columns:
                raise RuntimeError("assets 表缺少 bvid 主键，无法自动迁移")

            for column_name, definition in self._MIGRATABLE_COLUMNS.items():
                if column_name not in columns:
                    if not re.fullmatch(r"[a-z_][a-z0-9_]*", column_name):
                        raise RuntimeError(f"迁移列名不合法，已拒绝执行: {column_name}")
                    self.conn.execute(
                        f"ALTER TABLE assets ADD COLUMN {column_name} {definition}"
                    )

            self._repair_legacy_rows()
            self._ensure_bvid_unique(columns)
            # 索引必须在列迁移与旧行修复之后创建：
            # last_verify / integrity_status 是 v1.5.0 才补的列，
            # 提前建索引会在旧库上直接失败。
            self._ensure_indexes()
            self.conn.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _ensure_indexes(self):
        """补齐查询索引，并清理实测有害的旧索引。已存在则跳过。

        索引名与列定义都来自模块内常量，不接受外部输入。
        """
        existing = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(assets)").fetchall()
        }

        # 早期版本建过 idx_assets_verify，实测它让 candidates_for_verify
        # 慢 2~10 倍（排序键是表达式，用不上索引）。这里主动清理。
        if "idx_assets_verify" in existing:
            self.conn.execute('DROP INDEX IF EXISTS "idx_assets_verify"')
            existing.discard("idx_assets_verify")

        for name, definition in self._INDEXES:
            if name in existing:
                continue
            if not re.fullmatch(r"idx_assets_[a-z_]+", name):
                raise RuntimeError(f"索引名不合法，已拒绝创建: {name}")
            self.conn.execute(
                f'CREATE INDEX IF NOT EXISTS "{name}" ON {definition}'
            )

    def _repair_legacy_rows(self):
        invalid_rows = self.conn.execute(
            "SELECT rowid FROM assets WHERE bvid IS NULL OR trim(bvid) = ''"
        ).fetchall()
        for (row_id,) in invalid_rows:
            base_key = f"legacy-invalid-{row_id}"
            replacement = base_key
            suffix = 1
            while self.conn.execute(
                "SELECT 1 FROM assets WHERE bvid=?",
                (replacement,),
            ).fetchone():
                suffix += 1
                replacement = f"{base_key}-{suffix}"
            self.conn.execute(
                "UPDATE assets SET bvid=? WHERE rowid=?",
                (replacement, row_id),
            )

        self.conn.execute("UPDATE assets SET status=0 WHERE status IS NULL")
        self.conn.execute(
            "UPDATE assets SET p_count=1 WHERE p_count IS NULL OR p_count < 1"
        )

    def _ensure_bvid_unique(self, columns):
        if columns["bvid"][5]:
            return

        for index_row in self.conn.execute("PRAGMA index_list(assets)").fetchall():
            index_name = index_row[1]
            is_unique = bool(index_row[2])
            is_partial = bool(index_row[4]) if len(index_row) > 4 else False
            if not is_unique or is_partial:
                continue
            escaped_name = index_name.replace('"', '""')
            indexed_columns = [
                row[2]
                for row in self.conn.execute(
                    f'PRAGMA index_info("{escaped_name}")'
                ).fetchall()
            ]
            if indexed_columns == ["bvid"]:
                return

        duplicate = self.conn.execute(
            """
            SELECT bvid
            FROM assets
            GROUP BY bvid
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate:
            raise RuntimeError("assets 表存在重复 bvid，无法自动建立唯一约束")

        self.conn.execute(
            "CREATE UNIQUE INDEX idx_assets_bvid_unique ON assets(bvid)"
        )

    @staticmethod
    def _validate_asset_key(asset_key):
        if asset_key is None:
            raise ValueError("资产主键不能为空")
        normalized = str(asset_key).strip()
        if not normalized:
            raise ValueError("资产主键不能为空")
        return normalized

    def get_asset(self, bvid):
        asset_key = self._validate_asset_key(bvid)
        row = self.conn.execute(
            """
            SELECT bvid, title, type, status, path, last_check, p_count,
                   integrity_status, last_verify
            FROM assets
            WHERE bvid=?
            """,
            (asset_key,),
        ).fetchone()
        if row:
            return {
                "bvid": row[0],
                "title": row[1],
                "type": row[2],
                "status": row[3],
                "path": row[4],
                "last_check": row[5],
                "p_count": row[6],
                "integrity_status": row[7],
                "last_verify": row[8],
            }
        return None

    def update_asset(self, bvid, title, asset_type, status, path, p_count=1):
        asset_key = self._validate_asset_key(bvid)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO assets (bvid, title, type, status, path, last_check, p_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bvid) DO UPDATE SET
                    title=excluded.title,
                    type=excluded.type,
                    status=excluded.status,
                    path=excluded.path,
                    last_check=excluded.last_check,
                    p_count=excluded.p_count
                """,
                (asset_key, title, asset_type, status, path, now, p_count),
            )

    def update_last_check(self, bvid):
        asset_key = self._validate_asset_key(bvid)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            self.conn.execute(
                "UPDATE assets SET last_check=? WHERE bvid=?",
                (now, asset_key),
            )

    def update_status(self, bvid, status):
        asset_key = self._validate_asset_key(bvid)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            self.conn.execute(
                "UPDATE assets SET status=?, last_check=? WHERE bvid=?",
                (status, now, asset_key),
            )

    def record_watch_history(self, bvid, title, up_name, view_at):
        """记录/更新一条观看历史（仅元数据，不涉及下载资产）。"""
        asset_key = self._validate_asset_key(bvid)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO watch_history (bvid, title, up_name, view_at, last_sync)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bvid) DO UPDATE SET
                    title=excluded.title,
                    up_name=excluded.up_name,
                    view_at=excluded.view_at,
                    last_sync=excluded.last_sync
                """,
                (asset_key, title, up_name, int(view_at or 0), now),
            )

    def oldest_history_view_at(self):
        """返回已记录历史中最早（最小）的观看时间，用于停止翻页。"""
        row = self.conn.execute(
            "SELECT MIN(view_at) FROM watch_history"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    # F3 完整性巡检相关
    INTEGRITY_UNKNOWN = 0
    INTEGRITY_OK = 1
    INTEGRITY_CORRUPT = 2

    def candidates_for_verify(self, limit=20):
        """挑选下一批完整性校验候选：已完成的 Active 视频资产，最久未校验优先。"""
        rows = self.conn.execute(
            """
            SELECT bvid, path, p_count
            FROM assets
            WHERE status = 0 AND type = 'video'
              AND path IS NOT NULL AND trim(path) != ''
            ORDER BY last_verify IS NOT NULL, last_verify ASC, last_check ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [
            {"bvid": row[0], "path": row[1], "p_count": int(row[2] or 1)}
            for row in rows
        ]

    def update_integrity(self, bvid, integrity_status):
        """写回单个资产的完整性校验结论。"""
        asset_key = self._validate_asset_key(bvid)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            self.conn.execute(
                "UPDATE assets SET integrity_status=?, last_verify=? WHERE bvid=?",
                (int(integrity_status), now, asset_key),
            )

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False
