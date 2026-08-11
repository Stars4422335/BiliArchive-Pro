import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.core.downloader as downloader_module
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
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append(args))

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
    monkeypatch.setattr(downloader, "_convert_downloaded_danmaku", lambda *_: None)
    monkeypatch.setattr(
        "app.core.downloader.shutil.disk_usage",
        lambda path: SimpleNamespace(free=6 * 1024**3),
    )
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append((args, kwargs)))

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
    monkeypatch.setattr(downloader, "_convert_downloaded_danmaku", lambda *_: None)
    monkeypatch.setattr(
        "app.core.downloader.os.path.exists",
        lambda path: path not in {"./bin/yt-dlp", "./bin/yt-dlp.exe"},
    )
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: "/usr/bin/yt-dlp" if name == "yt-dlp" else None)
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append((args, kwargs)))

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
    monkeypatch.setattr(downloader, "_convert_downloaded_danmaku", lambda *_: None)
    monkeypatch.setattr(
        "app.core.downloader.os.path.exists",
        lambda path: path not in {"./bin/ffmpeg", "./bin/ffmpeg.exe"},
    )
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append((args, kwargs)))

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
    monkeypatch.setattr(downloader, "_convert_downloaded_danmaku", lambda *_: None)
    missing_ytdlp_paths = {
        config["components"]["yt-dlp"]["path"],
        config["components"]["yt-dlp"]["path"] + ".exe",
    }


def process_is_running(pid):
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        try:
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
    monkeypatch.setattr(
        "app.core.downloader.os.path.exists",
        lambda path: path not in missing_ytdlp_paths,
    )
    monkeypatch.setattr("app.core.downloader.shutil.which", lambda name: None if name == "yt-dlp" else "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append((args, kwargs)))

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
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append((args, kwargs)))

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
    monkeypatch.setattr(downloader, "_convert_downloaded_danmaku", lambda *_: None)
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append((args, kwargs)))

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


def test_download_video_uses_configured_timeout_and_returns_false(monkeypatch, tmp_path):
    config = make_config(min_disk_gb=0)
    config["system"]["download_timeout_seconds"] = 45
    downloader = Downloader(config)
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda path: path)
    monkeypatch.setattr(
        downloader,
        "resolve_executable",
        lambda configured_path, executable_name, required=True: executable_name,
    )

    def time_out(*args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("app.core.downloader._run_process_tree", time_out)

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video",
        cookie_file_path="cookie.txt",
    )

    assert result is False
    assert calls[0][1]["timeout"] == 45.0
    assert "--continue" in calls[0][0][0]
    assert "--part" in calls[0][0][0]


def test_download_timeout_only_zero_disables_limit():
    assert Downloader._normalize_download_timeout(0) is None
    assert Downloader._normalize_download_timeout(-1) == 7200.0
    assert Downloader._normalize_download_timeout(False) == 7200.0
    assert Downloader._normalize_download_timeout(float("inf")) == 7200.0


def test_download_timeout_cleans_cookie_and_only_empty_partial_files(monkeypatch, tmp_path):
    config = make_config(min_disk_gb=0)
    config["system"]["download_timeout_seconds"] = 30
    downloader = Downloader(config)
    source_cookie = tmp_path / "cookie.json"
    source_cookie.write_text(json.dumps({"sessdata": "session-value"}), encoding="utf-8")
    save_dir = tmp_path / "archive"
    save_dir.mkdir()
    resumable_part = save_dir / "video.f137.mp4.part"
    empty_part = save_dir / "video.f140.m4a.part"
    unrelated_part = save_dir / "other.f140.m4a.part"
    resumable_part.write_bytes(b"partial media")
    empty_part.write_bytes(b"")
    unrelated_part.write_bytes(b"")
    generated_cookies = []

    monkeypatch.setattr(
        downloader,
        "resolve_executable",
        lambda configured_path, executable_name, required=True: executable_name,
    )

    def time_out(*args, **kwargs):
        cmd = args[0]
        generated_cookies.append(cmd[cmd.index("--cookies") + 1])
        assert resumable_part.exists()
        assert not empty_part.exists()
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr("app.core.downloader._run_process_tree", time_out)

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(save_dir),
        file_name="video",
        cookie_file_path=str(source_cookie),
    )

    assert result is False
    assert resumable_part.read_bytes() == b"partial media"
    assert unrelated_part.exists()
    assert generated_cookies and not Path(generated_cookies[0]).exists()


def test_process_tree_timeout_terminates_spawned_child(tmp_path):
    child_pid_path = tmp_path / "child.pid"
    launcher = tmp_path / "spawn_child.py"
    launcher.write_text(
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        "with open(sys.argv[1], 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    with pytest.raises(subprocess.TimeoutExpired):
        downloader_module._run_process_tree(
            [sys.executable, str(launcher), str(child_pid_path)],
            check=True,
            timeout=3,
        )

    assert child_pid_path.exists()
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while process_is_running(child_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert process_is_running(child_pid) is False


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
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append("process"))

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
    monkeypatch.setattr("app.core.downloader._run_process_tree", lambda *args, **kwargs: calls.append("process"))

    result = downloader.download_video(
        url="https:///video/BV1",
        save_dir=str(tmp_path / "archive"),
        file_name="video",
        cookie_file_path="cookie.json",
    )

    assert result is False
    assert calls == []
    assert not (tmp_path / "archive").exists()


def test_download_video_forces_single_item_and_requests_manual_and_auto_subtitles(
    monkeypatch,
    tmp_path,
):
    downloader = Downloader(make_config(min_disk_gb=0))
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda path: path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr(
        downloader,
        "resolve_executable",
        lambda configured_path, executable_name, required=True: executable_name,
    )
    monkeypatch.setattr(
        downloader,
        "_convert_downloaded_danmaku",
        lambda save_dir, file_name: None,
    )
    monkeypatch.setattr(
        "app.core.downloader._run_process_tree",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1?p=2",
        save_dir=str(tmp_path),
        file_name="S01E02 - 第二集 [BV1-P2]",
        cookie_file_path="cookie.txt",
    )

    assert result is True
    cmd = calls[0][0][0]
    assert "--no-playlist" in cmd
    assert "--write-subs" in cmd
    assert "--write-auto-subs" in cmd
    assert cmd[cmd.index("-o") + 1].endswith(
        "S01E02 - 第二集 [BV1-P2].%(ext)s"
    )


def test_danmaku_conversion_only_processes_current_download_prefix(monkeypatch, tmp_path):
    media_dir = tmp_path / "Video [BV1]"
    media_dir.mkdir()
    current = media_dir / "video [BV1].danmaku.xml"
    ordinary_subtitle = media_dir / "video [BV1].zh-Hans.xml"
    similar_prefix = media_dir / "video [BV1]-old.danmaku.xml"
    unrelated = media_dir / "other.danmaku.xml"
    for path in (current, ordinary_subtitle, similar_prefix, unrelated):
        path.write_text("<i />", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        "app.core.downloader.DanmakuConverter.xml_to_ass",
        lambda source, target: calls.append((source, target)) or True,
    )

    Downloader._convert_downloaded_danmaku(str(media_dir), "video [BV1]")

    assert calls == [
        (str(current), str(media_dir / "video [BV1].danmaku.ass"))
    ]


def test_danmaku_conversion_exception_does_not_escape(monkeypatch, tmp_path, capsys):
    current = tmp_path / "video [BV1].danmaku.xml"
    current.write_text("<i />", encoding="utf-8")

    monkeypatch.setattr(
        "app.core.downloader.DanmakuConverter.xml_to_ass",
        lambda source, target: (_ for _ in ()).throw(OverflowError("bad time")),
    )

    Downloader._convert_downloaded_danmaku(str(tmp_path), "video [BV1]")

    assert current.exists()
    assert "已保留原 XML" in capsys.readouterr().out


def test_download_video_escapes_percent_only_in_ytdlp_output_template(
    monkeypatch,
    tmp_path,
):
    downloader = Downloader(make_config(min_disk_gb=0))
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda path: path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr(
        downloader,
        "resolve_executable",
        lambda configured_path, executable_name, required=True: executable_name,
    )
    monkeypatch.setattr(
        downloader,
        "_convert_downloaded_danmaku",
        lambda save_dir, file_name: None,
    )
    monkeypatch.setattr(
        "app.core.downloader._run_process_tree",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="100%完成 [BV1]",
        cookie_file_path="cookie.txt",
    )

    assert result is True
    cmd = calls[0][0][0]
    assert cmd[cmd.index("-o") + 1].endswith("100%%完成 [BV1].%(ext)s")
