"""QA 独立验证：yt-dlp 参数不可注入（配置值不能变成额外命令行参数）。

断言对象始终是**最终拼给 yt-dlp 的 argv**，而不是内部变量：写错位置、
写错格式、被清洗漏掉的注入串，只有在 argv 上才看得出来。

覆盖：
- ``system.subtitle_langs`` / ``system.download_retries`` 的恶意与畸形取值；
- 清洗后 argv 里不出现任何注入片段，且 ``--sub-langs``/``--retries`` 恰好一次；
- ``refresh_config()`` 之后**下一条命令**的取值确实变了（不是只改了配置对象）；
- 同时确认 yt-dlp 是以 argv 列表启动（不经 shell），避免"注入"被误判。
"""

import pytest

from app.core.downloader import (
    DEFAULT_DOWNLOAD_RETRIES,
    DEFAULT_SUBTITLE_LANGS,
    Downloader,
)

INJECTION_PAYLOADS = [
    "--exec=calc",
    "--exec=rm -rf /",
    "; rm -rf /",
    "zh-Hans; rm -rf /",
    "$(calc)",
    "`calc`",
    "zh-Hans\n--exec=calc",
    "zh-Hans\r\n--exec=calc",
    "zh-Hans --exec=calc",
    "zh-Hans,all --config",
    "zh-Hans,%",
    "'quoted'",
    '"quoted"',
    "zh-Hans" + "A" * 500,
    "../../../etc/passwd",
]


def make_config(system=None):
    config = {
        "system": {"min_disk_gb": 0},
        "components": {
            "yt-dlp": {"path": "yt-dlp"},
            "ffmpeg": {"path": "ffmpeg"},
        },
    }
    config["system"].update(system or {})
    return config


def run_download(monkeypatch, tmp_path, config, downloader=None):
    """跑一次 download_video，返回 (argv, downloader)。"""
    downloader = downloader or Downloader(config)
    calls = []

    monkeypatch.setattr(downloader, "convert_cookie_to_netscape", lambda path: path)
    monkeypatch.setattr(downloader, "random_sleep", lambda action_type="download": None)
    monkeypatch.setattr(
        downloader,
        "resolve_executable",
        lambda configured_path, executable_name, required=True: executable_name,
    )
    monkeypatch.setattr(downloader, "_convert_downloaded_danmaku", lambda *_: None)
    monkeypatch.setattr(
        "app.core.downloader._run_process_tree",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = downloader.download_video(
        url="https://www.bilibili.com/video/BV1qa",
        save_dir=str(tmp_path),
        file_name="video [BV1qa]",
        cookie_file_path="cookie.txt",
    )

    assert result is True
    assert len(calls) == 1, "yt-dlp 应当只启动一次"
    return calls[0][0][0], downloader


def value_of(argv, flag):
    assert argv.count(flag) == 1, f"{flag} 在命令行里出现了 {argv.count(flag)} 次"
    return argv[argv.index(flag) + 1]


def assert_payload_absent(argv, payload):
    """注入片段不得以任何形式出现在任何一个 argv 元素里。"""
    text = payload if isinstance(payload, str) else str(payload)
    for fragment in (text, text.strip("\"'"), "exec=calc", "rm -rf"):
        if not fragment:
            continue
        assert all(fragment not in str(part) for part in argv), (
            f"注入片段 {fragment!r} 出现在命令行里: {argv}"
        )
    assert not any("\n" in str(part) or "\r" in str(part) for part in argv)


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_subtitle_langs_payload_never_reaches_the_command_line(monkeypatch, tmp_path, payload):
    argv, _ = run_download(
        monkeypatch, tmp_path, make_config({"subtitle_langs": payload})
    )

    # 整串作废，回退默认白名单
    assert value_of(argv, "--sub-langs") == DEFAULT_SUBTITLE_LANGS
    assert_payload_absent(argv, payload)
    # 除了白名单本身，不允许出现任何 --exec / -exec 之类的额外开关
    assert not any(str(part).startswith("--exec") for part in argv)


@pytest.mark.parametrize("payload", [123, None, True, 1.5, ["zh-Hans"], {"a": 1}, b"zh-Hans", ()])
def test_non_string_subtitle_langs_falls_back_to_default(monkeypatch, tmp_path, payload):
    argv, _ = run_download(
        monkeypatch, tmp_path, make_config({"subtitle_langs": payload})
    )

    assert value_of(argv, "--sub-langs") == DEFAULT_SUBTITLE_LANGS
    assert not any("zh-Hans" in str(part) for part in argv if part != DEFAULT_SUBTITLE_LANGS)


@pytest.mark.parametrize(
    "payload",
    [
        "--retries=99",
        "10; rm -rf /",
        "10\n--exec=calc",
        "1e9",
        "0x10",
        " 10 ",
        "10 " * 100,
    ],
)
def test_retry_payload_never_reaches_the_command_line(monkeypatch, tmp_path, payload):
    argv, _ = run_download(
        monkeypatch, tmp_path, make_config({"download_retries": payload})
    )

    retries = value_of(argv, "--retries")
    assert retries.isdigit(), f"--retries 不是纯数字: {retries!r}"
    assert int(retries) <= 50
    assert value_of(argv, "--fragment-retries") == retries
    assert_payload_absent(argv, payload)
    assert not any(str(part).startswith("--retries=") for part in argv)


@pytest.mark.parametrize(
    "payload,expected",
    [
        (9999, 50),
        (10**9, 50),
        # 浮点大数也走 cap，而不是溢成天文数字
        (1e9, 50),
        (-1, DEFAULT_DOWNLOAD_RETRIES),
        (-0.5, DEFAULT_DOWNLOAD_RETRIES),
        (-1e9, DEFAULT_DOWNLOAD_RETRIES),
        # NaN/inf 是"非法配置"，不是"0 次重试"
        (float("nan"), DEFAULT_DOWNLOAD_RETRIES),
        (float("inf"), DEFAULT_DOWNLOAD_RETRIES),
        (float("-inf"), DEFAULT_DOWNLOAD_RETRIES),
        # 字符串形式的负数与小数的行为必须一致（不能只防住数字类型）
        ("-0.5", DEFAULT_DOWNLOAD_RETRIES),
        ("3.7", 3),
        (True, DEFAULT_DOWNLOAD_RETRIES),
        (False, DEFAULT_DOWNLOAD_RETRIES),
        (None, DEFAULT_DOWNLOAD_RETRIES),
        (object(), DEFAULT_DOWNLOAD_RETRIES),
        (0, 0),
        (0.0, 0),
        (50, 50),
        (51, 50),
    ],
)
def test_retries_are_clamped_not_trusted(monkeypatch, tmp_path, payload, expected):
    argv, _ = run_download(
        monkeypatch, tmp_path, make_config({"download_retries": payload})
    )

    assert value_of(argv, "--retries") == str(expected)
    # 0 必须被尊重（显式关闭重试），不能被当成"缺失"回退默认
    if expected == 0:
        assert value_of(argv, "--retries") == "0"


def test_negative_fraction_falls_back_to_default_not_zero(monkeypatch, tmp_path):
    """负数小数已修复：不再被截断成"关闭重试"。

    QA 首轮记录的小瑕疵（P4）：``_normalize_retries`` 的 docstring 写"负数
    一律回退默认"，但实现先 ``int(value)`` 再判 ``< 0``，于是 ``-0.5`` 被截断
    成 0，等价于"关闭重试"。修复后改为先判负再取整，``-0.5``/``-1``/``-1e9``
    都回退默认 10，与 docstring 一致。
    """
    for value in (-0.5, -1, -1e9):
        argv, _ = run_download(
            monkeypatch, tmp_path, make_config({"download_retries": value})
        )
        assert value_of(argv, "--retries") == "10", f"{value} 应回退默认 10"
        assert 0 <= int(value_of(argv, "--retries")) <= 50

    # 0 仍然是"显式关闭重试"，没有被这次修复误伤
    argv, _ = run_download(
        monkeypatch, tmp_path, make_config({"download_retries": 0})
    )
    assert value_of(argv, "--retries") == "0"


def test_command_line_is_an_argv_list_without_shell(monkeypatch, tmp_path):
    """确认传给进程的是列表 argv（不经 shell），注入面只剩"多一个开关"。"""
    argv, _ = run_download(monkeypatch, tmp_path, make_config({"subtitle_langs": "zh-Hans,en-US"}))

    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert value_of(argv, "--sub-langs") == "zh-Hans,en-US"
    # 合法配置仍然原样生效（清洗不是"一律回退默认"）
    assert value_of(argv, "--retries") == str(DEFAULT_DOWNLOAD_RETRIES)


def test_refresh_config_changes_the_next_command_not_just_the_object(monkeypatch, tmp_path):
    """热更后下一条命令的 --retries / --sub-langs 必须真的变了。"""
    downloader = Downloader(make_config({"download_retries": 2, "subtitle_langs": "zh-CN"}))

    first_argv, _ = run_download(monkeypatch, tmp_path, None, downloader=downloader)
    assert value_of(first_argv, "--retries") == "2"
    assert value_of(first_argv, "--sub-langs") == "zh-CN"

    fresh = make_config({"download_retries": 7, "subtitle_langs": "en-US,ai-zh"})
    assert downloader.refresh_config(fresh) is True

    second_argv, _ = run_download(monkeypatch, tmp_path, None, downloader=downloader)
    assert value_of(second_argv, "--retries") == "7"
    assert value_of(second_argv, "--sub-langs") == "en-US,ai-zh"
    # 旧的取值不该残留在新命令里
    assert "zh-CN" not in second_argv


def test_refresh_config_rejects_non_mapping_and_keeps_old_behaviour():
    downloader = Downloader(make_config({"download_retries": 4}))
    original = downloader.config

    for bad in (None, ["x"], "config", 42):
        assert downloader.refresh_config(bad) is False
    assert downloader.config is original


def test_injected_values_are_rejected_by_the_webui_validation_too():
    """纵深防御：WebUI 保存入口就拦住多行/超范围的值。"""
    from app.webui.queries.settings import ConfigValidationError, validate_config_payload

    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"subtitle_langs": "zh\n--exec=calc"}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"download_retries": 51}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"download_retries": -1}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"subtitle_langs": 123}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"subtitle_langs": "x" * 201}})

    ok = validate_config_payload(
        {"system": {"subtitle_langs": "zh-Hans,en-US", "download_retries": 0}}
    )
    assert ok["system"] == {"subtitle_langs": "zh-Hans,en-US", "download_retries": 0}
