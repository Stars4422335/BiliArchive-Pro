"""QA 独立验证：账本行过滤没有伤到正常数据，且三处口径完全一致。

一次建四/五种行，覆盖真实世界里会同时出现的组合：

- 正常 Active（``path`` 非空）
- 历史遗留 Active（``path`` 为空串 —— 既有 fixture 就是这么造的）
- 墓碑（``status=1`` 且 ``path`` 非空）
- 账本行（``status=0`` 且 ``path`` 为 NULL，``record_download_failure`` 造的那种）
- 带 ``last_check`` 的账本行（增删交替后可能出现的形态）

断言列表 / ``total`` / 概览的 ``status_counts``、``type_counts``、``recent``
四处口径一致：账本行全部消失，墓碑行**必须仍然出现**，空串 path 不被误杀。
再验证游标翻页在账本行夹在排序中间时既不漏行也不重复行。
"""

import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

from app.webui import create_app

COLUMNS = ["bvid", "title", "type", "status", "path", "last_check", "p_count"]

ROWS = [
    # bvid, title, type, status, path, last_check, p_count
    ("BV1NORMAL", "正常视频", "video", 0,
     "./downloads/fav/normal [BV1NORMAL]", "2024-03-01 10:00:00", 1),
    ("CV2TOMB", "墓碑专栏", "article", 1,
     "./downloads/fav/tomb [CV2TOMB]", "2024-03-02 10:00:00", 1),
    ("BV3EMPTY", "空串路径的历史资产", "video", 0, "", "2024-03-03 10:00:00", 2),
    ("BV4LEDGER", None, None, 0, None, None, 1),
    ("BV5LEDGER", None, None, 0, None, "2024-03-04 10:00:00", 1),
]

VISIBLE_IDS = {"BV1NORMAL", "CV2TOMB", "BV3EMPTY"}
LEDGER_IDS = {"BV4LEDGER", "BV5LEDGER"}


@pytest.fixture
def webui(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "system": {
                    "download_path": str(tmp_path / "downloads"),
                    "db_path": str(tmp_path / "archive.db"),
                    "cookie_path": str(tmp_path / "cookie.json"),
                    "plex_mode": True,
                    "download_enabled": False,
                },
                "network": {},
                "components": {
                    "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
                    "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
                },
                "favorites": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "archive.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE assets (bvid TEXT PRIMARY KEY, title TEXT, type TEXT, "
            "status INTEGER, path TEXT, last_check TEXT, p_count INTEGER)"
        )
        connection.executemany(
            f"INSERT INTO assets ({', '.join(COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in COLUMNS)})",
            ROWS,
        )
        connection.commit()
    finally:
        connection.close()

    (tmp_path / "downloads").mkdir()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>app</html>", encoding="utf-8")

    app = create_app(
        project_root=tmp_path,
        config_path=config_path,
        db_path=db_path,
        static_dir=static_dir,
    )
    return TestClient(app), db_path


def _ids(payload):
    return [item["bvid"] for item in payload["items"]]


def test_asset_list_hides_ledger_rows_but_keeps_tombstones(webui):
    client, _ = webui

    listing = client.get("/api/assets", params={"page_size": 50}).json()

    assert set(_ids(listing)) == VISIBLE_IDS
    assert listing["total"] == 3
    assert not (LEDGER_IDS & set(_ids(listing)))
    # 墓碑行没有被一起过滤掉（否则用户就再也看不到"源端已删"的记录了）
    assert "CV2TOMB" in _ids(listing)


def test_dashboard_counts_match_the_list_and_still_count_tombstones(webui):
    client, _ = webui

    listing = client.get("/api/assets", params={"page_size": 50}).json()
    dashboard = client.get("/api/dashboard").json()

    assert dashboard["assets"]["total"] == listing["total"] == 3
    assert dashboard["assets"]["status_counts"] == {"0": 2, "1": 1}
    assert dashboard["assets"]["type_counts"] == {"video": 2, "article": 1}
    recent_ids = [item["bvid"] for item in dashboard["recent"]]
    assert set(recent_ids) == VISIBLE_IDS
    assert not (LEDGER_IDS & set(recent_ids))
    # 墓碑行必须仍在计数里
    assert dashboard["assets"]["status_counts"]["1"] == 1


def test_status_and_type_filters_agree_with_the_exclusion(webui):
    client, _ = webui

    active = client.get("/api/assets", params={"status": "active", "page_size": 50}).json()
    assert set(_ids(active)) == {"BV1NORMAL", "BV3EMPTY"}, "空串 path 的历史资产被误杀了"
    assert active["total"] == 2

    tombstoned = client.get(
        "/api/assets", params={"status": "tombstoned", "page_size": 50}
    ).json()
    assert _ids(tombstoned) == ["CV2TOMB"]
    assert tombstoned["total"] == 1

    articles = client.get("/api/assets", params={"type": "article", "page_size": 50}).json()
    assert _ids(articles) == ["CV2TOMB"]
    assert articles["total"] == 1

    videos = client.get("/api/assets", params={"type": "video", "page_size": 50}).json()
    assert set(_ids(videos)) == {"BV1NORMAL", "BV3EMPTY"}
    assert videos["total"] == 2


def test_search_cannot_resurrect_a_ledger_row(webui):
    """搜索走的是同一组过滤条件，账本行不能靠 bvid 搜索被翻出来。"""
    client, _ = webui

    for term in ("BV4LEDGER", "BV5LEDGER", "LEDGER"):
        payload = client.get(
            "/api/assets", params={"query": term, "page_size": 50}
        ).json()
        assert payload["total"] == 0
        assert _ids(payload) == []


@pytest.mark.parametrize("page_size", [1, 2, 3])
def test_cursor_pagination_neither_drops_nor_repeats_rows(webui, page_size):
    """账本行夹在排序中间时，游标翻页必须刚好翻出可见行全集。"""
    client, _ = webui

    reference = _ids(client.get("/api/assets", params={"page_size": 50}).json())
    assert len(reference) == 3

    collected = []
    cursor = None
    for _ in range(10):  # 防死循环上限
        params = {"page_size": page_size}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/api/assets", params=params).json()
        collected.extend(_ids(page))
        cursor = page["next_cursor"]
        if not cursor:
            break

    assert collected == reference, f"翻页顺序/内容与一次性读取不一致: {collected}"
    assert len(collected) == len(set(collected)), "翻页出现了重复行"
    assert not (LEDGER_IDS & set(collected))


def test_total_ignores_the_cursor_but_respects_the_exclusion(webui):
    """total 是"过滤后的全量"，与游标位置无关，但同样排除账本行。"""
    client, _ = webui

    first = client.get("/api/assets", params={"page_size": 1}).json()
    assert first["total"] == 3
    assert first["next_cursor"]

    second = client.get(
        "/api/assets", params={"page_size": 1, "cursor": first["next_cursor"]}
    ).json()
    assert second["total"] == 3
    assert second["items"][0]["bvid"] != first["items"][0]["bvid"]


def test_ledger_rows_are_still_reachable_by_direct_key(webui):
    """过滤只作用于列表/计数：单条读取路径不该被牵连（避免误伤详情页）。"""
    client, db_path = webui

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT bvid, path FROM assets WHERE path IS NULL ORDER BY bvid"
        ).fetchall()
    finally:
        connection.close()

    assert [row[0] for row in rows] == ["BV4LEDGER", "BV5LEDGER"]
    # 概览不展示它们，但数据仍在库里——过滤是查询层的口径，不是删数据
    assert client.get("/api/dashboard").json()["assets"]["total"] == 3


def test_source_filter_counts_only_real_archives(webui):
    """第四个计数面（来源下拉）同样不该把账本行算进去。"""
    client, _ = webui

    sources = client.get("/api/assets/sources").json()["sources"]

    # 两条真实路径都在 downloads/fav/ 下；空串路径与账本行都不产生来源计数
    assert sources == [{"source": "fav", "count": 2}]
