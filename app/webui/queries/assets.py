"""Asset queries for the WebUI.

The WebUI is a read-only client: it opens the database in `mode=ro` and
never writes, migrates or creates it.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

STATUS_NAMES = {
    "active": 0,
    "tombstoned": 1,
    "protected": 2,
}


def _asset_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["id"] = item["bvid"]
    return item


class AssetsMixin:
    """Listing assets and locating their cover art."""

    def _asset_record(self, row: sqlite3.Row) -> dict[str, Any]:
        item = _asset_from_row(row)
        item["poster_available"] = self._poster_from_asset_path(item.get("path")) is not None
        return item

    def assets(
        self,
        *,
        query: str | None,
        status: str | int | None,
        asset_type: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        if page < 1 or page_size < 1 or page_size > 200:
            raise ValueError("page 必须大于 0，page_size 必须在 1 到 200 之间")
        conditions = []
        parameters: list[Any] = []
        if query:
            if len(query) > 200:
                raise ValueError("query 不能超过 200 个字符")
            conditions.append("(bvid LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.extend([f"%{escaped}%", f"%{escaped}%"])
        if status is not None:
            normalized_status = self._status_value(status)
            conditions.append("status=?")
            parameters.append(normalized_status)
        if asset_type:
            if asset_type not in {"video", "article"}:
                raise ValueError("type 必须是 video 或 article")
            conditions.append("type=?")
            parameters.append(asset_type)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        database = self._database()
        total = database.scalar(f"SELECT COUNT(*) FROM assets{where}", parameters)
        # 直接按 last_check 排序而非 COALESCE(last_check,'')。
        # 二者语义一致（SQLite 中 DESC 排序把 NULL 放在最后），但
        # COALESCE 是表达式，索引无法用于排序：2 万资产下 2.0ms -> 0.09ms。
        rows = database.query(
            "SELECT bvid, title, type, status, path, last_check, p_count "
            f"FROM assets{where} ORDER BY last_check DESC, bvid "
            "LIMIT ? OFFSET ?",
            [*parameters, page_size, (page - 1) * page_size],
        )
        items = [self._asset_record(row) for row in rows]
        return {"items": items, "assets": items, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def _status_value(status: str | int) -> int:
        if isinstance(status, bool):
            raise ValueError("status 无效")
        if isinstance(status, int):
            value = status
        else:
            normalized = status.lower()
            value = int(normalized) if normalized.isdigit() else STATUS_NAMES.get(normalized, -1)
        if value not in {0, 1, 2}:
            raise ValueError("status 必须是 active、tombstoned、protected 或 0、1、2")
        return value

    def poster_path(self, asset_id: str) -> Path | None:
        rows = self._database().query("SELECT path FROM assets WHERE bvid=?", [asset_id])
        if not rows or not rows[0]["path"]:
            return None
        return self._poster_from_asset_path(rows[0]["path"])

    def _poster_from_asset_path(self, asset_path: Any) -> Path | None:
        if not asset_path:
            return None
        root = self.download_root()
        try:
            asset_dir = Path(os.fspath(asset_path))
            if not asset_dir.is_absolute():
                asset_dir = self.project_root / asset_dir
            asset_dir = asset_dir.resolve()
            if not asset_dir.is_relative_to(root):
                return None
            poster = (asset_dir / "poster.jpg").resolve(strict=True)
            if poster.parent != asset_dir or not poster.is_relative_to(root) or not poster.is_file():
                return None
            return poster
        except (OSError, RuntimeError, ValueError):
            return None


__all__ = ["AssetsMixin", "STATUS_NAMES"]
