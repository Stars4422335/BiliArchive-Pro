import asyncio
import hashlib

from app.scheduler.updater import ComponentUpdater


def make_config(tmp_path, strategy="auto"):
    return {
        "network": {"github_proxy_url": "https://proxy.example/"},
        "components": {
            "yt-dlp": {
                "strategy": strategy,
                "path": str(tmp_path / "bin" / "yt-dlp"),
            },
            "ffmpeg": {
                "strategy": "notify",
                "path": str(tmp_path / "bin" / "ffmpeg"),
            },
        },
    }


class FakeResponse:
    def __init__(self, content=b"", status_code=200, text=""):
        self.content = content
        self.status_code = status_code
        self.text = text


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.requested_urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        self.requested_urls.append(url)
        return self.response


def test_extract_checksum_matches_exact_asset_name():
    expected = "a" * 64
    text = f"{expected}  yt-dlp\n{'b' * 64} *yt-dlp.exe\n"

    assert ComponentUpdater._extract_checksum(text, "yt-dlp") == expected
    assert ComponentUpdater._extract_checksum(text, "missing") is None


def test_official_checksum_bypasses_download_proxy(monkeypatch, tmp_path):
    expected = "a" * 64
    response = FakeResponse(text=f"{expected}  yt-dlp\n")
    client = FakeAsyncClient(response)
    monkeypatch.setattr("app.scheduler.updater.httpx.AsyncClient", lambda **kwargs: client)
    updater = ComponentUpdater(make_config(tmp_path))

    checksum = asyncio.run(updater.get_official_ytdlp_checksum("yt-dlp"))

    assert checksum == expected
    assert client.requested_urls == [
        "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
    ]


def test_download_file_writes_only_when_sha256_matches(monkeypatch, tmp_path):
    content = b"verified executable"
    response = FakeResponse(content=content)
    client = FakeAsyncClient(response)
    monkeypatch.setattr("app.scheduler.updater.httpx.AsyncClient", lambda **kwargs: client)
    updater = ComponentUpdater(make_config(tmp_path))
    target = tmp_path / "bin" / "yt-dlp"

    result = asyncio.run(
        updater._download_file(
            "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp",
            str(target),
            hashlib.sha256(content).hexdigest(),
            force=True,
        )
    )

    assert result is True
    assert target.read_bytes() == content
    assert client.requested_urls == [
        "https://proxy.example/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    ]


def test_download_file_hash_mismatch_preserves_existing_file(monkeypatch, tmp_path):
    response = FakeResponse(content=b"unexpected executable")
    monkeypatch.setattr(
        "app.scheduler.updater.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(response),
    )
    updater = ComponentUpdater(make_config(tmp_path))
    target = tmp_path / "bin" / "yt-dlp"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing executable")

    result = asyncio.run(
        updater._download_file(
            "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp",
            str(target),
            hashlib.sha256(b"expected executable").hexdigest(),
            force=True,
        )
    )

    assert result is False
    assert target.read_bytes() == b"existing executable"


def test_update_ytdlp_off_skips_network(monkeypatch, tmp_path):
    updater = ComponentUpdater(make_config(tmp_path, strategy="off"))

    async def unexpected_call(*args, **kwargs):
        raise AssertionError("network method must not be called")

    monkeypatch.setattr(updater, "get_latest_ytdlp_version", unexpected_call)
    monkeypatch.setattr(updater, "get_official_ytdlp_checksum", unexpected_call)

    assert asyncio.run(updater.update_yt_dlp()) is True


def test_update_ytdlp_notify_never_downloads(monkeypatch, tmp_path):
    updater = ComponentUpdater(make_config(tmp_path, strategy="notify"))
    calls = []

    monkeypatch.setattr("app.scheduler.updater.shutil.which", lambda name: None)

    async def latest_version():
        return "2026.08.01"

    async def download(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(updater, "get_latest_ytdlp_version", latest_version)
    monkeypatch.setattr(updater, "_download_file", download)

    assert asyncio.run(updater.update_yt_dlp()) is False
    assert calls == []


def test_update_ytdlp_auto_passes_official_checksum_to_download(monkeypatch, tmp_path):
    updater = ComponentUpdater(make_config(tmp_path, strategy="auto"))
    expected_checksum = "c" * 64
    calls = []

    monkeypatch.setattr("app.scheduler.updater.shutil.which", lambda name: None)

    async def latest_version():
        return "2026.08.01"

    async def checksum(target_name):
        return expected_checksum

    async def download(url, save_path, expected_sha256, force=False):
        calls.append((url, save_path, expected_sha256, force))
        return True

    monkeypatch.setattr(updater, "get_latest_ytdlp_version", latest_version)
    monkeypatch.setattr(updater, "get_official_ytdlp_checksum", checksum)
    monkeypatch.setattr(updater, "_download_file", download)

    assert asyncio.run(updater.update_yt_dlp()) is True
    assert len(calls) == 1
    assert calls[0][2:] == (expected_checksum, True)
