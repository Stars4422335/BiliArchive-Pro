import json
import os
import threading
from pathlib import Path
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
    monkeypatch.setattr(
        downloader,
        "resolve_executable",
        lambda configured_path, executable_name, required=True: executable_name,
    )
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
    monkeypatch.setattr(
        "app.core.downloader.os.path.exists",
        lambda path: path not in {"./bin/yt-dlp", "./bin/yt-dlp.exe"},
    )
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


def test_resolve_executable_finds_windows_exe_for_extensionless_config(monkeypatch, tmp_path):
    downloader = Downloader(make_config(min_disk_gb=0))
    configured_path = tmp_path / "bin" / "yt-dlp"
    executable_path = Path(str(configured_path) + ".exe")
    executable_path.parent.mkdir(parents=True)
    executable_path.write_bytes(b"executable")

    monkeypatch.setattr("app.core.downloader.IS_WINDOWS", True)
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: None)

    assert downloader.resolve_executable(str(configured_path), "yt-dlp") == str(executable_path)


def test_download_video_uses_path_ffmpeg_when_configured_file_is_missing(monkeypatch, tmp_path):
    config = make_config(min_disk_gb=0)
    config["components"]["ffmpeg"]["path"] = "./bin/ffmpeg"
    downloader = Downloader(config)
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda cookie_path: cookie_path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr("app.core.downloader.glob.glob", lambda pattern: [])
    monkeypatch.setattr(
        "app.core.downloader.os.path.exists",
        lambda path: path not in {"./bin/ffmpeg", "./bin/ffmpeg.exe"},
    )
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


def test_download_video_does_not_auto_install_ytdlp_when_missing_from_path(monkeypatch, tmp_path, capsys):
    config = make_config(min_disk_gb=0)
    config["components"]["yt-dlp"]["path"] = str(tmp_path / "bin" / "yt-dlp")
    downloader = Downloader(config)
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda cookie_path: cookie_path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr("app.core.downloader.glob.glob", lambda pattern: [])
    missing_ytdlp_paths = {
        config["components"]["yt-dlp"]["path"],
        config["components"]["yt-dlp"]["path"] + ".exe",
    }
    monkeypatch.setattr(
        "app.core.downloader.os.path.exists",
        lambda path: path not in missing_ytdlp_paths,
    )
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: None if name == "yt-dlp" else "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video",
        cookie_file_path="cookie.txt",
    )

    output = capsys.readouterr().out
    assert result is False
    assert calls == []
    assert "未执行自动安装" in output


def test_download_video_prints_manual_install_guidance_when_tool_resolution_fails(monkeypatch, tmp_path, capsys):
    config = make_config(min_disk_gb=0)
    config["components"]["yt-dlp"]["path"] = "./bin/yt-dlp"
    downloader = Downloader(config)
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda cookie_path: cookie_path)
    monkeypatch.setattr(
        "app.core.downloader.os.path.exists",
        lambda path: path not in {"./bin/yt-dlp", "./bin/yt-dlp.exe"},
    )
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: None)
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video",
        cookie_file_path="cookie.txt",
    )

    output = capsys.readouterr().out
    assert result is False
    assert calls == []
    assert "yt-dlp" in output
    assert "./bin/yt-dlp" in output
    assert "pip install -r requirements.txt" in output
    assert "手动" in output


def test_download_video_removes_generated_netscape_cookie(monkeypatch, tmp_path):
    downloader = Downloader(make_config(min_disk_gb=0))
    source_cookie = tmp_path / "cookie.json"
    source_cookie.write_text(
        json.dumps(
            {
                "sessdata": "session-value",
                "bili_jct": "csrf-value",
                "dedeuserid": "123",
            }
        ),
        encoding="utf-8",
    )
    calls = []

    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr(
        downloader,
        "resolve_executable",
        lambda configured_path, executable_name, required=True: executable_name,
    )
    monkeypatch.setattr("app.core.downloader.glob.glob", lambda pattern: [])
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path / "archive"),
        file_name="video",
        cookie_file_path=str(source_cookie),
    )

    assert result is True
    assert len(calls) == 1
    generated_cookie = calls[0][0][0][calls[0][0][0].index("--cookies") + 1]
    assert not Path(generated_cookie).exists()


def test_concurrent_cookie_conversions_are_unique_and_secure(tmp_path):
    downloader = Downloader(make_config(min_disk_gb=0))
    source_cookie = tmp_path / "cookie.json"
    source_cookie.write_text(json.dumps({"sessdata": "session-value"}), encoding="utf-8")
    paths = []

    def convert_cookie():
        paths.append(downloader.convert_cookie_to_netscape(str(source_cookie)))

    threads = [threading.Thread(target=convert_cookie) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(paths) == 2
    assert len(set(paths)) == 2
    for path in paths:
        content = Path(path).read_text(encoding="utf-8")
        assert ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tsession-value" in content
    for path in paths:
        downloader._remove_temporary_cookie(path)
    assert downloader._owned_temporary_cookies == set()


def test_concurrent_cleanup_removes_owned_cookie_only_once(monkeypatch, tmp_path):
    downloader = Downloader(make_config(min_disk_gb=0))
    source_cookie = tmp_path / "cookie.json"
    source_cookie.write_text(json.dumps({"sessdata": "session-value"}), encoding="utf-8")
    generated_cookie = downloader.convert_cookie_to_netscape(str(source_cookie))
    remove_started = threading.Event()
    release_remove = threading.Event()
    remove_calls = []
    original_remove = os.remove

    def delayed_remove(path):
        remove_calls.append(path)
        if len(remove_calls) == 1:
            remove_started.set()
            release_remove.wait(timeout=2)
        original_remove(path)

    monkeypatch.setattr("app.core.downloader.os.remove", delayed_remove)
    first = threading.Thread(target=downloader._remove_temporary_cookie, args=(generated_cookie,))
    second = threading.Thread(target=downloader._remove_temporary_cookie, args=(generated_cookie,))

    first.start()
    assert remove_started.wait(timeout=2)
    second.start()
    second.join(timeout=2)
    release_remove.set()
    first.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert remove_calls == [generated_cookie]
    assert downloader._owned_temporary_cookies == set()


def test_cleanup_does_not_remove_unowned_cookie(tmp_path):
    downloader = Downloader(make_config(min_disk_gb=0))
    foreign_cookie = tmp_path / "foreign-cookie.txt"
    foreign_cookie.write_text("do not delete", encoding="utf-8")

    downloader._remove_temporary_cookie(str(foreign_cookie))

    assert foreign_cookie.read_text(encoding="utf-8") == "do not delete"


def test_download_video_rejects_http_before_cookie_conversion_or_process(monkeypatch, tmp_path):
    downloader = Downloader(make_config(min_disk_gb=0))
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda path: calls.append("cookie"))
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append("process"))

    result = downloader.download_video(
        url="http://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path / "archive"),
        file_name="video",
        cookie_file_path="cookie.json",
    )

    assert result is False
    assert calls == []
    assert not (tmp_path / "archive").exists()


def test_download_video_rejects_https_url_without_host(monkeypatch, tmp_path):
    downloader = Downloader(make_config(min_disk_gb=0))
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda path: calls.append("cookie"))
    monkeypatch.setattr("app.core.downloader.subprocess.run", lambda *args, **kwargs: calls.append("process"))

    result = downloader.download_video(
        url="https:///video/BV1",
        save_dir=str(tmp_path / "archive"),
        file_name="video",
        cookie_file_path="cookie.json",
    )

    assert result is False
    assert calls == []
    assert not (tmp_path / "archive").exists()
