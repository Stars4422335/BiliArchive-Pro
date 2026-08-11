import os
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
    }

    def __init__(self, db_path):
        parent_dir = os.path.dirname(os.path.abspath(db_path))
        if db_path != ":memory:" and parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        try:
            self._init_db()
        except Exception:
            self.conn.close()
            self.conn = None
            raise

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
            columns = {
                row[1]: row
                for row in self.conn.execute("PRAGMA table_info(assets)").fetchall()
            }
            if "bvid" not in columns:
                raise RuntimeError("assets 表缺少 bvid 主键，无法自动迁移")

            for column_name, definition in self._MIGRATABLE_COLUMNS.items():
                if column_name not in columns:
                    self.conn.execute(
                        f"ALTER TABLE assets ADD COLUMN {column_name} {definition}"
                    )

            self._repair_legacy_rows()
            self._ensure_bvid_unique(columns)
            self.conn.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

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
            SELECT bvid, title, type, status, path, last_check, p_count
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

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False
