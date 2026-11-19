"""yt-dlp 参数加固：重试次数与字幕语言白名单。

断言的是最终拼给 yt-dlp 的 `cmd`，而不是内部变量——这两个参数写错位置
或写错格式，只有真的下发给进程时才暴露。
"""

import pytest

from app.core.downloader import (
    DEFAULT_DOWNLOAD_RETRIES,
    DEFAULT_SUBTITLE_LANGS,
    Downloader,
)


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


def run_download(monkeypatch, tmp_path, config):
    """跑一次 download_video，返回拼出的 cmd 与 process 调用参数。"""
    downloader = Downloader(config)
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
        url="https://www.bilibili.com/video/BV1",
        save_dir=str(tmp_path),
        file_name="video [BV1]",
        cookie_file_path="cookie.txt",
    )

    assert result is True
    assert len(calls) == 1
    return calls[0][0][0], downloader


def cmd_value(cmd, flag):
    """取 flag 后面紧跟的取值；不存在返回 None。"""
    if flag not in cmd:
        return None
    return cmd[cmd.index(flag) + 1]


# ---------- 重试参数 ----------


def test_default_command_contains_retry_flags(monkeypatch, tmp_path):
    cmd, _ = run_download(monkeypatch, tmp_path, make_config())

    assert cmd_value(cmd, "--retries") == str(DEFAULT_DOWNLOAD_RETRIES)
    assert cmd_value(cmd, "--fragment-retries") == str(DEFAULT_DOWNLOAD_RETRIES)
    assert DEFAULT_DOWNLOAD_RETRIES == 10


def test_retry_count_is_configurable(monkeypatch, tmp_path):
    cmd, _ = run_download(monkeypatch, tmp_path, make_config({"download_retries": 3}))

    assert cmd_value(cmd, "--retries") == "3"
    assert cmd_value(cmd, "--fragment-retries") == "3"


def test_zero_retries_is_honoured(monkeypatch, tmp_path):
    cmd, _ = run_download(monkeypatch, tmp_path, make_config({"download_retries": 0}))

    assert cmd_value(cmd, "--retries") == "0"


@pytest.mark.parametrize("invalid", ["abc", None, -1, True, [], {}, -0.5, -1e9, float("nan"), float("inf")])
def test_invalid_retry_count_falls_back_to_default(monkeypatch, tmp_path, invalid):
    cmd, _ = run_download(
        monkeypatch, tmp_path, make_config({"download_retries": invalid})
    )

    assert cmd_value(cmd, "--retries") == str(DEFAULT_DOWNLOAD_RETRIES)


@pytest.mark.parametrize("negative", [-0.5, -1, -1e9, "-2", float("-inf")])
def test_negative_fractional_retries_never_mean_disable(monkeypatch, tmp_path, negative):
    """负数必须先判再取整：int(-0.5)==0 会把"负值"误当成"关闭重试"。"""
    assert Downloader._normalize_retries(negative) == DEFAULT_DOWNLOAD_RETRIES

    cmd, _ = run_download(
        monkeypatch, tmp_path, make_config({"download_retries": negative})
    )
    assert cmd_value(cmd, "--retries") == str(DEFAULT_DOWNLOAD_RETRIES)


def test_retry_count_is_capped(monkeypatch, tmp_path):
    cmd, _ = run_download(monkeypatch, tmp_path, make_config({"download_retries": 9999}))

    assert cmd_value(cmd, "--retries") == "50"


# ---------- 字幕语言白名单 ----------


def test_default_subtitle_whitelist_replaces_all(monkeypatch, tmp_path):
    cmd, _ = run_download(monkeypatch, tmp_path, make_config())

    assert cmd_value(cmd, "--sub-langs") == DEFAULT_SUBTITLE_LANGS
    assert "all" not in cmd
    # 人工字幕与自动字幕仍然都要
    assert "--write-subs" in cmd
    assert "--write-auto-subs" in cmd


def test_subtitle_whitelist_is_configurable_and_cleaned(monkeypatch, tmp_path):
    cmd, _ = run_download(
        monkeypatch,
        tmp_path,
        make_config({"subtitle_langs": " zh-Hans , ,en-US, ai-zh "}),
    )

    assert cmd_value(cmd, "--sub-langs") == "zh-Hans,en-US,ai-zh"


@pytest.mark.parametrize("empty", ["", "   ", ",", ", ,"])
def test_empty_subtitle_whitelist_falls_back_to_default(monkeypatch, tmp_path, empty):
    cmd, _ = run_download(
        monkeypatch, tmp_path, make_config({"subtitle_langs": empty})
    )

    assert cmd_value(cmd, "--sub-langs") == DEFAULT_SUBTITLE_LANGS


@pytest.mark.parametrize(
    "bad_value",
    [
        "zh-Hans\n--exec=rm -rf /",  # 换行注入
        "zh Hans",  # 空格
        "zh-Hans;en",  # 分号
        "zh-Hans,all --config",  # 试图夹带参数
        123,
        None,
        ["zh-Hans"],
        "x" * 500,  # 超长
    ],
)
def test_malformed_subtitle_whitelist_falls_back_to_default(
    monkeypatch, tmp_path, bad_value
):
    cmd, _ = run_download(
        monkeypatch, tmp_path, make_config({"subtitle_langs": bad_value})
    )

    assert cmd_value(cmd, "--sub-langs") == DEFAULT_SUBTITLE_LANGS
    # 注入内容一个字都不许进入命令行
    assert not any("\n" in str(part) for part in cmd)


# ---------- 规范化函数边界 ----------


def test_normalize_retries_boundaries():
    assert Downloader._normalize_retries(5) == 5
    assert Downloader._normalize_retries("7") == 7
    # 浮点按取整处理（"3.7" 以前会因 int("3.7") 抛 ValueError 而回退默认）
    assert Downloader._normalize_retries("3.7") == 3
    assert Downloader._normalize_retries(0) == 0
    assert Downloader._normalize_retries(60) == 50
    assert Downloader._normalize_retries(-3) == DEFAULT_DOWNLOAD_RETRIES
    # 关键边界：负数小数必须先判负再取整，否则 int(-0.5)==0 被当成"关闭重试"
    assert Downloader._normalize_retries(-0.5) == DEFAULT_DOWNLOAD_RETRIES
    assert Downloader._normalize_retries(-1) == DEFAULT_DOWNLOAD_RETRIES
    assert Downloader._normalize_retries(-1e9) == DEFAULT_DOWNLOAD_RETRIES
    assert Downloader._normalize_retries(float("nan")) == DEFAULT_DOWNLOAD_RETRIES
    assert Downloader._normalize_retries(float("inf")) == DEFAULT_DOWNLOAD_RETRIES
    assert Downloader._normalize_retries(None) == DEFAULT_DOWNLOAD_RETRIES
    assert Downloader._normalize_retries(True) == DEFAULT_DOWNLOAD_RETRIES
    assert Downloader._normalize_retries(object()) == DEFAULT_DOWNLOAD_RETRIES


def test_normalize_subtitle_langs_boundaries():
    assert Downloader._normalize_subtitle_langs("zh-CN") == "zh-CN"
    assert Downloader._normalize_subtitle_langs("zh-CN,en") == "zh-CN,en"
    assert Downloader._normalize_subtitle_langs("") == DEFAULT_SUBTITLE_LANGS
    assert Downloader._normalize_subtitle_langs(None) == DEFAULT_SUBTITLE_LANGS
    assert (
        Downloader._normalize_subtitle_langs("zh-CN\nen") == DEFAULT_SUBTITLE_LANGS
    )


# ---------- 配置热更：downloader 换快照后参数立即改变 ----------


def test_refreshed_config_changes_the_next_command(monkeypatch, tmp_path):
    config = make_config({"download_retries": 2, "subtitle_langs": "zh-CN"})
    first_cmd, downloader = run_download(monkeypatch, tmp_path, config)
    assert cmd_value(first_cmd, "--retries") == "2"

    fresh = make_config({"download_retries": 7, "subtitle_langs": "en-US"})
    assert downloader.refresh_config(fresh) is True
    second_cmd, _ = run_download(monkeypatch, tmp_path, fresh)

    assert cmd_value(second_cmd, "--retries") == "7"
    assert cmd_value(second_cmd, "--sub-langs") == "en-US"


def test_refresh_config_ignores_non_mapping():
    downloader = Downloader(make_config())
    original = downloader.config

    assert downloader.refresh_config(None) is False
    assert downloader.refresh_config(["not", "a", "dict"]) is False
    assert downloader.config is original


# ---------- WebUI 配置契约 ----------


def test_new_keys_are_exposed_and_immediate():
    from app.webui.queries.settings import (
        CONFIG_SCHEMA,
        effect_for,
        validate_config_payload,
    )

    assert "download_retries" in CONFIG_SCHEMA["system"]
    assert "subtitle_langs" in CONFIG_SCHEMA["system"]
    assert effect_for("system", "download_retries") == "immediate"
    assert effect_for("system", "subtitle_langs") == "immediate"

    ok = validate_config_payload(
        {"system": {"download_retries": 3, "subtitle_langs": "zh-Hans,en-US"}}
    )
    assert ok["system"] == {"download_retries": 3, "subtitle_langs": "zh-Hans,en-US"}


def test_settings_reject_out_of_range_retries_and_multiline_langs():
    from app.webui.queries.settings import ConfigValidationError, validate_config_payload

    with pytest.raises(ConfigValidationError, match="download_retries"):
        validate_config_payload({"system": {"download_retries": 51}})
    with pytest.raises(ConfigValidationError, match="subtitle_langs"):
        validate_config_payload({"system": {"subtitle_langs": "zh\nen"}})


def test_every_effect_key_is_declared_once():
    """同一个键不能既算即时又算重启（UI 提示会自相矛盾）。"""
    from app.webui.queries.settings import EFFECT_METADATA

    overlap = EFFECT_METADATA["immediate"] & EFFECT_METADATA["restart"]
    assert overlap == set()
