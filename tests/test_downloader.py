from types import SimpleNamespace

from app.core.downloader import Downloader


def make_config(min_disk_gb):
    return {
        "system": {"min_disk_gb": min_disk_gb},
        "components": {
            "yt-dlp": {"path": "yt-dlp"},
            "ffmpeg": {"path": "ffmpeg"},
        },
    }


def test_download_video_skips_ytdlp_when_free_disk_below_threshold(monkeypatch, tmp_path):
    downloader = Downloader(make_config(min_disk_gb=5))
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda cookie_path: cookie_path)
    monkeypatch.setattr(
        "app.core.downloader.shutil.disk_usage",
        lambda path: SimpleNamespace(free=4 * 1024**3),
    )
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append(args))

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video",
        cookie_file_path="cookie.txt",
    )

    assert result is False
    assert calls == []


def test_download_video_runs_ytdlp_when_free_disk_meets_threshold(monkeypatch, tmp_path):
    downloader = Downloader(make_config(min_disk_gb=5))
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda cookie_path: cookie_path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr("app.core.downloader.glob.glob", lambda pattern: [])
    monkeypatch.setattr(
        "app.core.downloader.shutil.disk_usage",
        lambda path: SimpleNamespace(free=6 * 1024**3),
    )
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video",
        cookie_file_path="cookie.txt",
    )

    assert result is True
    assert len(calls) == 1


def test_download_video_falls_back_to_path_ytdlp_when_configured_file_is_missing(monkeypatch, tmp_path):
    config = make_config(min_disk_gb=0)
    config["components"]["yt-dlp"]["path"] = "./bin/yt-dlp"
    downloader = Downloader(config)
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda cookie_path: cookie_path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr("app.core.downloader.glob.glob", lambda pattern: [])
    monkeypatch.setattr("app.core.downloader.os.path.exists", lambda path: False if path == "./bin/yt-dlp" else True)
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: "/usr/bin/yt-dlp" if name == "yt-dlp" else None)
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video",
        cookie_file_path="cookie.txt",
    )

    assert result is True
    assert calls[0][0][0][0] == "/usr/bin/yt-dlp"


def test_download_video_uses_path_ffmpeg_when_configured_file_is_missing(monkeypatch, tmp_path):
    config = make_config(min_disk_gb=0)
    config["components"]["ffmpeg"]["path"] = "./bin/ffmpeg"
    downloader = Downloader(config)
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda cookie_path: cookie_path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr("app.core.downloader.glob.glob", lambda pattern: [])
    monkeypatch.setattr("app.core.downloader.os.path.exists", lambda path: False if path == "./bin/ffmpeg" else True)
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video",
        cookie_file_path="cookie.txt",
    )

    assert result is True
    cmd = calls[0][0][0]
    ffmpeg_location_index = cmd.index("--ffmpeg-location") + 1
    assert cmd[ffmpeg_location_index] == "/usr/bin"
