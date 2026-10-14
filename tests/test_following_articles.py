"""关注源图文（专栏）投稿同步测试。

覆盖三类风险：
1. API 解析——cv 号归一、无效条目跳过、分页判断；
2. 扫描语义——已归档跳过、NFO 失败不写完成状态、全局上限；
3. 配置闸门——article_types 默认关闭，只想要视频的用户不受打扰。
"""

import asyncio

import pytest

from app.core.parser import BiliParser, SyncFetchError
from app.scheduler.scanner import FavScanner


class _FakeCredential:
    def get_cookies(self):
        return {"SESSDATA": "test"}

    @property
    def sessdata(self):
        return "test"


def _patch_httpx(monkeypatch, payload):
    """按 tests/test_followings.py 的既有模式替换 httpx.AsyncClient。"""

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            return FakeResponse()

    import app.core.parser as parser_module

    monkeypatch.setattr(parser_module.httpx, "AsyncClient", FakeClient)


def _parser(monkeypatch, payload):
    _patch_httpx(monkeypatch, payload)
    return BiliParser(
        _FakeCredential(),
        uid=42,
        retry_attempts=1,
        retry_backoff_seconds=0,
        request_timeout_seconds=5,
    )


def _async_items(items, has_more):
    async def _call(self, mid, page=1):
        return items, has_more
    return _call


def _async_value(value):
    async def _call(self, mid):
        return value
    return _call


def _scanner_stub(tmp_path, *, existing=(), config=None):
    scanner = FavScanner.__new__(FavScanner)
    scanner.config = config or {
        "system": {"download_path": str(tmp_path), "plex_mode": True},
        "archive_protection": {
            "mark_deleted_prefix": "[源端已删]",
            "tombstone_prefix": "[失效墓碑]",
        },
    }
    scanner.path_mgr = type(
        "PathMgr",
        (),
        {"get_article_dir": staticmethod(lambda *a: str(tmp_path / a[1]))},
    )()
    scanner.db = type(
        "Db",
        (),
        {
            "records": dict(existing),
            "get_asset": lambda self, k: self.records.get(k),
            "update_last_check": lambda self, k: None,
            "update_asset": lambda self, k, *a: None,
        },
    )()
    scanner.global_download_count = 0
    scanner.max_global_downloads = 0
    scanner._progress_callback = None
    scanner._forced_redownloads = set()
    return scanner


# ---------- API 解析 ----------


def test_get_user_articles_normalizes_entries(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "list": [
                {"id": 12345, "title": "专栏一", "author": "UP", "publish_time": 1700000000},
                {"id": "67890", "title": "专栏二", "author": "UP", "publish_time": 1700000001},
            ],
            "page": {"count": 2},
        },
    }
    parser = _parser(monkeypatch, payload)

    items, has_more = asyncio.run(parser.get_user_articles(946974))

    assert has_more is False
    assert [i["id"] for i in items] == [12345, 67890]
    assert all(i["type"] == "article" for i in items)
    assert items[0]["title"] == "专栏一"


def test_get_user_articles_skips_invalid_ids(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "list": [
                {"id": 0, "title": "无效"},
                {"id": -5, "title": "负数"},
                {"id": None, "title": "空"},
                {"id": 999, "title": "有效"},
            ],
            "page": {"count": 4},
        },
    }
    parser = _parser(monkeypatch, payload)

    items, _ = asyncio.run(parser.get_user_articles(946974))

    assert [i["id"] for i in items] == [999]


def test_get_user_articles_handles_missing_list(monkeypatch):
    parser = _parser(monkeypatch, {"code": 0, "data": {}})

    items, has_more = asyncio.run(parser.get_user_articles(946974))

    assert items == []
    assert has_more is False


def test_get_user_articles_propagates_api_error(monkeypatch):
    """B 站返回错误码时，有限重试耗尽后抛 SyncFetchError。"""
    parser = _parser(monkeypatch, {"code": -403, "message": "访问权限不足"})

    with pytest.raises(SyncFetchError, match="访问权限不足"):
        asyncio.run(parser.get_user_articles(946974))


def test_get_user_articles_raises_for_invalid_mid_without_request(monkeypatch):
    """非法 mid 应在发请求前就失败，不消耗重试预算。"""
    parser = _parser(monkeypatch, {"code": 0, "data": {}})

    for bad in (0, -1, "abc", None):
        with pytest.raises(ValueError):
            asyncio.run(parser.get_user_articles(bad))


def test_get_user_articles_rejects_malformed_structure(monkeypatch):
    """结构异常必须在有限重试耗尽后显式失败，不能静默返回空列表。"""
    parser = _parser(monkeypatch, {"code": 0, "data": {"list": "not-a-list"}})

    with pytest.raises(SyncFetchError, match="list 不是列表"):
        asyncio.run(parser.get_user_articles(946974))


# ---------- 扫描语义 ----------


def test_scan_following_archives_new_article(tmp_path, monkeypatch):
    scanner = _scanner_stub(tmp_path)
    scanner.parser = type(
        "P",
        (),
        {
            "get_user_articles": _async_items([{"id": 555, "title": "新专栏", "type": "article"}], False),
            "get_user_info": _async_value({"name": "测试UP"}),
        },
    )()

    captured = {}
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.process_article_to_md",
        lambda item, path: captured.setdefault("md", (item["id"], path)) and True,
    )
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.create_nfo",
        lambda *a, **k: captured.setdefault("nfo", True) and str(tmp_path / "a.nfo"),
    )

    asyncio.run(scanner.scan_following_articles(946974, "测试UP"))

    assert captured["md"][0] == 555
    assert captured.get("nfo") is True
    assert scanner.global_download_count == 1


def test_scan_following_articles_skips_archived(tmp_path, monkeypatch):
    existing = {"cv555": {"status": 0, "title": "已归档", "type": "article"}}
    scanner = _scanner_stub(tmp_path, existing=existing)
    scanner.parser = type(
        "P",
        (),
        {
            "get_user_articles": _async_items([{"id": 555, "title": "已归档"}], False),
            "get_user_info": _async_value({"name": "UP"}),
        },
    )()

    def should_not_run(*args, **kwargs):
        raise AssertionError("已归档的专栏不应重新抓取")

    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.process_article_to_md", should_not_run
    )

    asyncio.run(scanner.scan_following_articles(946974, "UP"))


def test_nfo_failure_does_not_record_completion(tmp_path, monkeypatch):
    """NFO 写入失败时不得写入数据库完成状态，下轮应重试。"""
    scanner = _scanner_stub(tmp_path)
    scanner.parser = type(
        "P",
        (),
        {
            "get_user_articles": _async_items([{"id": 777, "title": "专栏"}], False),
            "get_user_info": _async_value({"name": "UP"}),
        },
    )()

    updates = []
    scanner.db.update_asset = lambda *a: updates.append(a)

    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.process_article_to_md",
        lambda item, path: True,
    )
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.create_nfo",
        lambda *a, **k: None,
    )

    asyncio.run(scanner.scan_following_articles(946974, "UP"))

    assert updates == []
    assert scanner.global_download_count == 0


def test_body_fetch_failure_is_retried_next_round(tmp_path, monkeypatch):
    scanner = _scanner_stub(tmp_path)
    scanner.parser = type(
        "P",
        (),
        {
            "get_user_articles": _async_items([{"id": 888, "title": "专栏"}], False),
            "get_user_info": _async_value({"name": "UP"}),
        },
    )()

    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.process_article_to_md",
        lambda item, path: False,
    )
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.create_nfo",
        lambda *a, **k: "should-not-reach.nfo",
    )

    asyncio.run(scanner.scan_following_articles(946974, "UP"))

    assert scanner.global_download_count == 0


def test_invalid_mid_is_skipped(tmp_path):
    scanner = _scanner_stub(tmp_path)

    for bad in ("abc", 0, -3, None):
        asyncio.run(scanner.scan_following_articles(bad, "UP"))
    # 不应抛出异常
    assert scanner.global_download_count == 0


def test_global_limit_stops_article_scan(tmp_path, monkeypatch):
    scanner = _scanner_stub(tmp_path)
    scanner.max_global_downloads = 5
    scanner.global_download_count = 5
    scanner.parser = type(
        "P",
        (),
        {
            "get_user_articles": _async_items([{"id": 1, "title": "x"}], False),
            "get_user_info": _async_value({"name": "UP"}),
        },
    )()

    def should_not_run(*args, **kwargs):
        raise AssertionError("达到全局上限后不应再抓取")

    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.process_article_to_md", should_not_run
    )

    asyncio.run(scanner.scan_following_articles(946974, "UP"))


# ---------- 配置闸门 ----------


def test_article_types_defaults_to_off():
    """默认关闭：只想要视频的用户不会被专栏请求打扰。"""
    import yaml
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["followings"]["article_types"] == "off"


def test_main_gates_article_scan_on_config():
    import inspect

    import main

    source = inspect.getsource(main._run_scan_loop)
    assert "article_types" in source
    assert "scan_following_articles" in source
    assert "'article', 'all'" in source