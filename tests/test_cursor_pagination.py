"""游标分页测试。

深分页时 OFFSET 会扫描并丢弃前面的每一行；游标直接走 (last_check, bvid)
索引。这组用例锁住两件事：游标走出来的顺序与 OFFSET 完全一致，
以及无效游标会被明确拒绝，而不是静默返回第一页。

排序键是 (last_check DESC, bvid ASC)，而 SQLite 把 NULL 排在最后，
所以 last_check 为空的资产排在整个列表的末尾——这一段最容易出错。
"""

import sqlite3

import pytest

from app.webui.service import WebService

TOTAL = 25
NULL_ROWS = 3


def _rows(count):
    rows = []
    for index in range(count):
        last_check = None if index < NULL_ROWS else f"2026-10-{index:02d}T00:00:00+08:00"
        rows.append((f"BV{index:03d}", f"资产 {index}", last_check))
    return rows


def _service(tmp_path, count=TOTAL):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("system:\n  db_path: archive.db\n", encoding="utf-8")
    db_path = tmp_path / "archive.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE assets (bvid TEXT PRIMARY KEY, title TEXT, type TEXT, "
            "status INTEGER, path TEXT, last_check TEXT, p_count INTEGER)"
        )
        conn.executemany(
            "INSERT INTO assets (bvid, title, type, status, path, last_check, p_count)"
            " VALUES (?, ?, 'video', 0, '', ?, 1)",
            _rows(count),
        )
    return WebService(
        project_root=tmp_path,
        config_path=config_path,
        db_path=db_path,
        version="1.7.1",
    )


def _by_offset(service, page_size):
    seen = []
    page = 1
    while True:
        result = service.assets(
            query=None, status=None, asset_type=None, page=page, page_size=page_size
        )
        seen.extend(item["bvid"] for item in result["items"])
        if len(result["items"]) < page_size:
            return seen
        page += 1


def _by_cursor(service, page_size):
    seen = []
    cursor = None
    while True:
        result = service.assets(
            query=None,
            status=None,
            asset_type=None,
            page=1,
            page_size=page_size,
            cursor=cursor,
        )
        seen.extend(item["bvid"] for item in result["items"])
        cursor = result["next_cursor"]
        if not cursor:
            return seen


def test_cursor_visits_every_row_in_the_same_order_as_offset(tmp_path):
    service = _service(tmp_path)

    offset_order = _by_offset(service, 5)
    cursor_order = _by_cursor(service, 5)

    assert len(offset_order) == TOTAL
    assert cursor_order == offset_order


def test_cursor_reaches_the_null_last_check_tail(tmp_path):
    service = _service(tmp_path)

    order = _by_cursor(service, 4)

    # last_check 为空的资产排在最后，并按 bvid 升序。
    assert order[-NULL_ROWS:] == ["BV000", "BV001", "BV002"]


def test_next_cursor_is_absent_on_the_last_page(tmp_path):
    service = _service(tmp_path)

    result = service.assets(
        query=None, status=None, asset_type=None, page=1, page_size=TOTAL
    )

    assert len(result["items"]) == TOTAL
    assert result["next_cursor"] is None


def test_total_counts_every_match_not_only_the_rest(tmp_path):
    service = _service(tmp_path)

    first = service.assets(
        query=None, status=None, asset_type=None, page=1, page_size=5
    )
    second = service.assets(
        query=None,
        status=None,
        asset_type=None,
        page=1,
        page_size=5,
        cursor=first["next_cursor"],
    )

    assert first["total"] == TOTAL
    assert second["total"] == TOTAL


def test_invalid_cursor_is_rejected(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError):
        service.assets(
            query=None,
            status=None,
            asset_type=None,
            page=1,
            page_size=5,
            cursor="not-a-real-cursor",
        )


def test_cursor_and_offset_agree_under_a_filter(tmp_path):
    service = _service(tmp_path)

    offset_order = []
    page = 1
    while True:
        result = service.assets(
            query=None, status=None, asset_type="video", page=page, page_size=7
        )
        offset_order.extend(item["bvid"] for item in result["items"])
        if len(result["items"]) < 7:
            break
        page += 1

    cursor_order = []
    cursor = None
    while True:
        result = service.assets(
            query=None,
            status=None,
            asset_type="video",
            page=1,
            page_size=7,
            cursor=cursor,
        )
        cursor_order.extend(item["bvid"] for item in result["items"])
        cursor = result["next_cursor"]
        if not cursor:
            break

    assert cursor_order == offset_order
