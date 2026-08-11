import asyncio

import pytest

import app.core.parser as parser_module
from app.core.parser import BiliParser, SyncFetchError


class FakeFavorite:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def get_content(self, page=1):
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeAsyncClient:
    def __init__(self, responses, calls, **kwargs):
        self.responses = responses
        self.calls = calls
        self.calls.append(("init", kwargs))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url):
        self.calls.append(("get", url))
        return self.responses.pop(0)


def test_favorite_list_retries_transient_failure_then_returns_items(monkeypatch):
    favorite = FakeFavorite(
        [
            TimeoutError("first timeout"),
            ConnectionError("temporary disconnect"),
            {
                "medias": [
                    {
                        "type": 2,
                        "title": "Test video",
                        "bvid": "BV123",
                        "id": 123,
                        "upper": {"name": "UP"},
                        "cover": "cover.jpg",
                        "intro": "intro",
                        "pubtime": 1700000000,
                    }
                ],
                "has_more": True,
            },
        ]
    )
    sleeps = []

    async def capture_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(
        "app.core.parser.favorite_list.FavoriteList",
        lambda media_id, credential: favorite,
    )
    monkeypatch.setattr("app.core.parser.asyncio.sleep", capture_sleep)
    parser = BiliParser(
        credential=object(),
        retry_attempts=3,
        retry_backoff_seconds=0.5,
    )

    items, has_more = asyncio.run(parser.get_favorite_list(99, page=2))

    assert favorite.calls == 3
    assert sleeps == [0.5, 1.0]
    assert has_more is True
    assert items[0]["bvid"] == "BV123"


def test_favorite_list_raises_after_retry_exhaustion(monkeypatch):
    favorite = FakeFavorite(
        [TimeoutError("one"), TimeoutError("two"), TimeoutError("three")]
    )
    monkeypatch.setattr(
        "app.core.parser.favorite_list.FavoriteList",
        lambda media_id, credential: favorite,
    )
    parser = BiliParser(
        credential=object(),
        retry_attempts=3,
        retry_backoff_seconds=0,
    )

    with pytest.raises(SyncFetchError, match="3 次尝试后仍失败"):
        asyncio.run(parser.get_favorite_list(99, page=2))

    assert favorite.calls == 3


def test_favorite_list_treats_real_empty_page_as_success(monkeypatch):
    favorite = FakeFavorite([{"medias": [], "has_more": False}])
    monkeypatch.setattr(
        "app.core.parser.favorite_list.FavoriteList",
        lambda media_id, credential: favorite,
    )
    parser = BiliParser(
        credential=object(),
        retry_attempts=3,
        retry_backoff_seconds=0,
    )

    items, has_more = asyncio.run(parser.get_favorite_list(99))

    assert favorite.calls == 1
    assert items == []
    assert has_more is False


def test_favorite_list_retries_invalid_response_shape(monkeypatch):
    favorite = FakeFavorite([{}, {}])
    monkeypatch.setattr(
        "app.core.parser.favorite_list.FavoriteList",
        lambda media_id, credential: favorite,
    )
    parser = BiliParser(
        credential=object(),
        retry_attempts=2,
        retry_backoff_seconds=0,
    )

    with pytest.raises(SyncFetchError, match="缺少 medias"):
        asyncio.run(parser.get_favorite_list(99))

    assert favorite.calls == 2


def test_watch_later_retries_api_business_error(monkeypatch):
    responses = [
        FakeResponse({"code": -101, "message": "not logged in"}),
        FakeResponse({"code": -101, "message": "not logged in"}),
    ]
    calls = []
    monkeypatch.setattr(
        parser_module.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, calls, **kwargs),
    )
    parser = BiliParser(
        credential=None,
        retry_attempts=2,
        retry_backoff_seconds=0,
        request_timeout_seconds=9,
    )

    with pytest.raises(SyncFetchError, match="not logged in"):
        asyncio.run(parser.get_watch_later_list())

    get_calls = [call for call in calls if call[0] == "get"]
    init_calls = [call for call in calls if call[0] == "init"]
    assert len(get_calls) == 2
    assert [call[1]["timeout"] for call in init_calls] == [9.0, 9.0]


def test_collection_falls_back_and_preserves_real_empty_result(monkeypatch):
    responses = [
        FakeResponse({"code": -400, "message": "wrong route"}),
        FakeResponse(
            {
                "code": 0,
                "data": {
                    "archives": [],
                    "page": {
                        "total": 0,
                        "page_num": 1,
                        "page_size": 30,
                    },
                },
            }
        ),
    ]
    calls = []
    monkeypatch.setattr(
        parser_module.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, calls, **kwargs),
    )
    parser = BiliParser(
        credential=None,
        retry_attempts=2,
        retry_backoff_seconds=0,
    )

    items, has_more = asyncio.run(
        parser.get_collection_list(123, page=1, mid=456)
    )

    get_calls = [call[1] for call in calls if call[0] == "get"]
    assert len(get_calls) == 2
    assert "/x/series/archives" in get_calls[0]
    assert "/seasons_archives_list" in get_calls[1]
    assert all("mid=456" in url for url in get_calls)
    assert all("mid=0" not in url and "mid=1" not in url for url in get_calls)
    assert items == []
    assert has_more is False


@pytest.mark.parametrize("mid", [None, 0, -1, "invalid"])
def test_collection_rejects_missing_or_invalid_mid(mid):
    parser = BiliParser(credential=None)

    with pytest.raises(ValueError, match="mid 必须是正整数"):
        asyncio.run(parser.get_collection_list(123, mid=mid))
