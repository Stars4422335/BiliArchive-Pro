"""Asset queries for the WebUI.

The WebUI is a read-only client: it opens the database in `mode=ro` and
never writes, migrates or creates it.
"""

from __future__ import annotations

import base64
import os
import sqlite3
from pathlib import Path
from typing import Any

STATUS_NAMES = {
    "active": 0,
    "tombstoned": 1,
    "protected": 2,
}

#: Separator between the two cursor fields. It cannot appear in an ISO
#: timestamp nor in a bvid, so the pair never becomes ambiguous.
_CURSOR_SEPARATOR = "\x1f"


def _asset_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["id"] = item["bvid"]
    return item


class AssetsMixin:
    """Listing assets and locating their cover art."""

    @staticmethod
    def _encode_cursor(row: sqlite3.Row) -> str:
        """Encode the sort key of the last row of a page.

        The sort key is (last_check, bvid): the assets table has an index on
        exactly that pair, so a cursor walks the index instead of scanning
        and discarding the rows before it.
        """
        raw = f"{row['last_check'] or ''}{_CURSOR_SEPARATOR}{row['bvid']}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[str | None, str]:
        """Decode a cursor back into (last_check, bvid)."""
        padding = "=" * (-len(cursor) % 4)
        try:
            raw = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("cursor 无效") from exc
        last_check, _, bvid = raw.partition(_CURSOR_SEPARATOR)
        if not bvid:
            raise ValueError("cursor 无效")
        return (last_check or None), bvid

    def _asset_record(self, row: sqlite3.Row) -> dict[str, Any]:
        item = _asset_from_row(row)
        item["poster_available"] = self._poster_from_asset_path(item.get("path")) is not None
        return item

    def _has_source_column(self) -> bool:
        """Old databases (pre v1.9.1) lack the source column; degrade cleanly."""
        rows = self._database().query("PRAGMA table_info(assets)")
        return any(row["name"] == "source" for row in rows)

    def assets(
        self,
        *,
        query: str | None,
        status: str | int | None,
        asset_type: str | None,
        page: int,
        page_size: int,
        cursor: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        if page < 1 or page_size < 1 or page_size > 200:
            raise ValueError("page 必须大于 0，page_size 必须在 1 到 200 之间")
        has_source = self._has_source_column()
        filter_conditions = []
        filter_parameters: list[Any] = []
        if query:
            if len(query) > 200:
                raise ValueError("query 不能超过 200 个字符")
            filter_conditions.append("(bvid LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filter_parameters.extend([f"%{escaped}%", f"%{escaped}%"])
        if status is not None:
            normalized_status = self._status_value(status)
            filter_conditions.append("status=?")
            filter_parameters.append(normalized_status)
        if asset_type:
            if asset_type not in {"video", "article"}:
                raise ValueError("type 必须是 video 或 article")
            filter_conditions.append("type=?")
            filter_parameters.append(asset_type)
        if source:
            if len(source) > 128:
                raise ValueError("source 不能超过 128 个字符")
            if not has_source:
                raise ValueError("数据库尚未升级（缺少 source 列），请先启动一次核心引擎完成迁移")
            filter_conditions.append("source=?")
            filter_parameters.append(source)

        row_conditions = list(filter_conditions)
        row_parameters = list(filter_parameters)
        if cursor:
            last_check, bvid = self._decode_cursor(cursor)
            if last_check is None:
                # 已经走完有 last_check 的部分，剩下的是 last_check 为空的尾巴。
                row_conditions.append("last_check IS NULL AND bvid > ?")
                row_parameters.append(bvid)
            else:
                # 排序是 last_check DESC, bvid ASC，而 SQLite 把 NULL 排在最后，
                # 所以比游标更靠后的行是：时间更早的、时间相同但 bvid 更大的，
                # 以及所有 last_check 为空的行。
                row_conditions.append(
                    "(last_check < ? OR (last_check = ? AND bvid > ?)"
                    " OR last_check IS NULL)"
                )
                row_parameters.extend([last_check, last_check, bvid])
            offset_value = 0
        else:
            offset_value = (page - 1) * page_size

        filter_where = f" WHERE {' AND '.join(filter_conditions)}" if filter_conditions else ""
        rows_where = f" WHERE {' AND '.join(row_conditions)}" if row_conditions else ""
        database = self._database()
        # The total counts every match, not only the ones left after the
        # cursor, so the filter and the cursor are kept apart.
        total = database.scalar(f"SELECT COUNT(*) FROM assets{filter_where}", filter_parameters)

        # 多取一行用来判断还有没有下一页，返回给调用方的仍然只有 page_size 条。
        source_column = "source" if has_source else "NULL AS source"
        rows = database.query(
            f"SELECT bvid, title, type, status, path, last_check, p_count, {source_column} "
            f"FROM assets{rows_where} ORDER BY last_check DESC, bvid LIMIT ? OFFSET ?",
            [*row_parameters, page_size + 1, offset_value],
        )
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        items = [self._asset_record(row) for row in rows]
        return {
            "items": items,
            "assets": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "next_cursor": self._encode_cursor(rows[-1]) if has_more and rows else None,
        }

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

    def distinct_sources(self) -> list[dict[str, Any]]:
        """Source names seen in the database, for the asset filter dropdown.

        The count helps the operator spot a source whose assets vanished
        (a non-zero count is also the upgrade safety signal: the number
        never drops after a migration). On a pre-1.9.1 database the source
        column does not exist yet; derive names from the stored path so the
        dropdown still works before the daemon's first migration run.
        """
        database = self._database()
        if not self._has_source_column():
            rows = database.query(
                "SELECT path FROM assets WHERE path IS NOT NULL AND path != ''"
            )
            counts: dict[str, int] = {}
            for row in rows:
                source = self._derive_source_from_path(row["path"])
                if source:
                    counts[source] = counts.get(source, 0) + 1
            return [
                {"source": name, "count": count}
                for name, count in sorted(counts.items())
            ]
        rows = database.query(
            "SELECT source, COUNT(*) AS asset_count FROM assets "
            "WHERE source IS NOT NULL AND source != '' "
            "GROUP BY source ORDER BY source"
        )
        return [
            {"source": row["source"], "count": row["asset_count"]}
            for row in rows
        ]

    @staticmethod
    def _derive_source_from_path(path_text: Any) -> str | None:
        if not path_text:
            return None
        normalized = str(path_text).replace("\\", "/")
        parts = [p for p in normalized.split("/") if p and p != "."]
        for index, part in enumerate(parts):
            if part.lower() == "downloads" and index + 1 < len(parts):
                return parts[index + 1]
        return None

    def poster_path(self, asset_id: str) -> Path | None:
        rows = self._database().query("SELECT path FROM assets WHERE bvid=?", [asset_id])
        if not rows or not rows[0]["path"]:
            return None
        return self._poster_from_asset_path(rows[0]["path"])

    def _poster_from_asset_path(self, asset_path: Any) -> Path | None:
        asset_dir = self._asset_dir(asset_path)
        if asset_dir is None:
            return None
        try:
            poster = (asset_dir / "poster.jpg").resolve(strict=True)
            if poster.parent != asset_dir or not poster.is_relative_to(self.download_root()) or not poster.is_file():
                return None
            return poster
        except (OSError, RuntimeError, ValueError):
            return None

    def _asset_dir(self, asset_path: Any) -> Path | None:
        """Resolve an asset path and refuse anything outside the download root."""
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
            return asset_dir
        except (OSError, RuntimeError, ValueError):
            return None

    def wordcloud_path(self, asset_id: str) -> Path | None:
        """Locate the danmaku word cloud side car of an asset.

        The word cloud is written next to the media file as
        "<stem>.wordcloud.svg"; the stem depends on the media layout, so the
        asset directory is scanned for it.
        """
        rows = self._database().query("SELECT path FROM assets WHERE bvid=?", [asset_id])
        if not rows or not rows[0]["path"]:
            return None
        asset_dir = self._asset_dir(rows[0]["path"])
        if asset_dir is None:
            return None
        try:
            candidates = sorted(asset_dir.glob("*.wordcloud.svg"))
        except OSError:
            return None
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if resolved.parent == asset_dir and resolved.is_file():
                return resolved
        return None


__all__ = ["AssetsMixin", "STATUS_NAMES"]
