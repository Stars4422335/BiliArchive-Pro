import sqlite3
import os
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path):
        # 确保 data 目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._init_db()

    def _init_db(self):
        # status: 0-Active(正常), 1-Tombstoned(墓碑), 2-Protected(源端删本地存孤本)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                bvid TEXT PRIMARY KEY,
                title TEXT,
                type TEXT,
                status INTEGER,
                path TEXT,
                last_check TEXT,
                p_count INTEGER
            )
        ''')
        self.conn.commit()

    def get_asset(self, bvid):
        self.cursor.execute("SELECT * FROM assets WHERE bvid=?", (bvid,))
        row = self.cursor.fetchone()
        if row:
            return {
                "bvid": row[0], "title": row[1], "type": row[2],
                "status": row[3], "path": row[4], "last_check": row[5], "p_count": row[6]
            }
        return None

    def update_asset(self, bvid, title, asset_type, status, path, p_count=1):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute('''
            INSERT OR REPLACE INTO assets (bvid, title, type, status, path, last_check, p_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (bvid, title, asset_type, status, path, now, p_count))
        self.conn.commit()
        
    def update_status(self, bvid, status):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("UPDATE assets SET status=?, last_check=? WHERE bvid=?", (status, now, bvid))
        self.conn.commit()

    def close(self):
        self.conn.close()
