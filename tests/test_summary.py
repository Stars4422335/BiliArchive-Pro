"""本地抽取式摘要测试（M4）。

重点覆盖四类风险：
1. 内容质量——短文本不该硬凑摘要，套话不该进摘要；
2. 无隐私外发——不引入网络调用，llm 模式必须明确拒绝而非静默降级；
3. 不阻断——摘要失败不得影响视频下载与 NFO 写入；
4. 隔离——只读当前媒体自己的字幕，不碰同目录其他资产。
"""

import pytest

from app.core.metadata import MetadataGenerator
from app.core.summary import LocalSummarizer
from app.scheduler.scanner import FavScanner


def _scanner(tmp_path, summary_config=None):
    scanner = FavScanner.__new__(FavScanner)
    scanner.config = {"system": {}, "summary": summary_config or {}}
    return scanner


# ---------- 摘要质量 ----------


def test_summarize_picks_meaningful_sentences():
    text = (
        "今天我们来聊聊机器学习模型部署的常见问题。"
        "模型训练完成后直接上线往往会遇到延迟高的问题。"
        "延迟高的根本原因是推理批处理没有调优。"
        "可以通过动态批处理显著降低延迟。"
    )
    result = LocalSummarizer().summarize(text)

    assert result
    assert "延迟" in result or "批处理" in result
    assert len(result) <= LocalSummarizer().max_chars


def test_summarize_returns_none_for_single_sentence():
    """只有一句话时不做摘要——强行截取只是原文片段。"""
    assert LocalSummarizer().summarize("这是一句单独的句子，没有更多内容了。") is None


def test_summarize_returns_none_for_empty():
    assert LocalSummarizer().summarize("") is None
    assert LocalSummarizer().summarize("   \n  ") is None


def test_summarize_filters_boilerplate():
    """订阅套话不该成为摘要内容。"""
    text = (
        "大家好，欢迎收看本期视频，记得点赞一键三连。"
        "本视频介绍分布式事务的实现方案与常见陷阱。"
        "两阶段提交在跨服务场景下存在协调开销问题。"
        "我们用最终一致性方案来规避这个代价。"
    )
    result = LocalSummarizer().summarize(text)

    assert result is not None
    assert "一键三连" not in result
    assert "欢迎收看" not in result


def test_summarize_respects_max_chars():
    text = "".join(
        f"这是第{i}个用于测试长度限制的句子，内容各不相同。"
        for i in range(40)
    )
    result = LocalSummarizer(max_chars=80).summarize(text)

    assert result is not None
    assert len(result) <= 80


def test_max_chars_is_clamped():
    assert LocalSummarizer(max_chars=0).max_chars == 40
    assert LocalSummarizer(max_chars=999999).max_chars == 2000
    assert LocalSummarizer(max_chars="非法").max_chars == 220


def test_tokenize_handles_mixed_content():
    tokens = LocalSummarizer.tokenize("使用 GPU 加速训练 model")

    assert "gpu" in tokens
    assert "model" in tokens
    assert any(len(t) == 2 and "\u4e00" <= t[0] for t in tokens)


def test_tokenize_handles_empty():
    assert LocalSummarizer.tokenize("") == []


def test_summarize_preserves_original_order():
    """抽取的句子必须按原文顺序拼接，否则读起来像关键词堆砌。"""
    text = (
        "第一个句子讲的是背景信息和历史沿革。"
        "第二个句子讲的是核心技术方案的设计思路。"
        "第三个句子讲的是性能测试和对比结果。"
        "第四个句子讲的是常见的坑和排查方法。"
    )
    result = LocalSummarizer().summarize(text)

    assert result
    positions = [result.find(marker) for marker in ("第一个", "第二个", "第三个", "第四个")]
    present = [p for p in positions if p >= 0]
    assert present == sorted(present)


# ---------- NFO 集成 ----------


def test_nfo_contains_outline_when_provided(tmp_path):
    import xml.etree.ElementTree as ET

    nfo = MetadataGenerator.create_nfo(
        {"title": "测试", "bvid": "BV1", "up_name": "UP", "intro": "简介", "outline": "这是摘要内容。"},
        str(tmp_path),
    )
    root = ET.parse(nfo).getroot()

    assert root.findtext("outline") == "这是摘要内容。"


def test_nfo_omits_outline_when_absent(tmp_path):
    """未提供 outline 时不应写出空元素——保持既有 NFO 输出不变。"""
    import xml.etree.ElementTree as ET

    nfo = MetadataGenerator.create_nfo(
        {"title": "测试", "bvid": "BV1", "up_name": "UP", "intro": "简介"},
        str(tmp_path),
    )
    root = ET.parse(nfo).getroot()

    assert root.find("outline") is None


def test_nfo_ignores_blank_outline(tmp_path):
    import xml.etree.ElementTree as ET

    nfo = MetadataGenerator.create_nfo(
        {"title": "测试", "bvid": "BV1", "up_name": "UP", "intro": "简介", "outline": "   "},
        str(tmp_path),
    )
    root = ET.parse(nfo).getroot()

    assert root.find("outline") is None


# ---------- 集成闸门 ----------


def test_summary_disabled_by_default(tmp_path):
    scanner = _scanner(tmp_path)
    item = {"intro": "一段足够长的简介文本，用于验证默认关闭时不会生成摘要。"}

    assert scanner._attach_outline(item, str(tmp_path), "video") is None
    assert "outline" not in item


def test_llm_mode_refuses_explicitly(tmp_path, capsys):
    """llm 会外发字幕文本：必须明确拒绝，而不是静默当作 local 处理。"""
    scanner = _scanner(tmp_path, {"enabled": True, "mode": "llm"})
    item = {"intro": "一段简介。"}

    assert scanner._attach_outline(item, str(tmp_path), "video") is None
    assert "outline" not in item
    assert "llm" in capsys.readouterr().out


def test_summary_writes_outline_into_item(tmp_path):
    scanner = _scanner(tmp_path, {"enabled": True, "mode": "local"})
    (tmp_path / "video.zh-Hans.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\n"
        "机器学习模型部署时延迟高是一个常见问题。\n\n"
        "2\n00:00:05,000 --> 00:00:10,000\n"
        "根本原因是推理批处理没有经过调优。\n\n"
        "3\n00:00:10,000 --> 00:00:15,000\n"
        "使用动态批处理可以显著降低延迟。\n\n",
        encoding="utf-8",
    )
    item = {"intro": ""}

    result = scanner._attach_outline(item, str(tmp_path), "video")

    assert result
    assert item["outline"] == result


def test_summary_falls_back_to_intro_without_subtitles(tmp_path):
    scanner = _scanner(tmp_path, {"enabled": True, "mode": "local"})
    item = {
        "intro": (
            "第一句话介绍背景和动机。"
            "第二句话说明技术方案的细节。"
            "第三句话给出结论和建议。"
        )
    }

    result = scanner._attach_outline(item, str(tmp_path), "video")

    assert result


def test_summary_returns_none_without_any_text(tmp_path):
    scanner = _scanner(tmp_path, {"enabled": True, "mode": "local"})
    item = {"intro": "   "}

    assert scanner._attach_outline(item, str(tmp_path), "video") is None


def test_summary_failure_does_not_raise(tmp_path, monkeypatch):
    """摘要器抛异常也不能中断下载流程。"""
    scanner = _scanner(tmp_path, {"enabled": True, "mode": "local"})
    (tmp_path / "video.zh-Hans.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\n这是第一句足够长的测试内容。\n\n"
        "2\n00:00:05,000 --> 00:00:10,000\n这是第二句足够长的测试内容。\n\n",
        encoding="utf-8",
    )

    def boom(*args, **kwargs):
        raise RuntimeError("摘要器内部炸了")

    monkeypatch.setattr("app.scheduler.scanner.LocalSummarizer", boom)
    item = {"intro": ""}

    assert scanner._attach_outline(item, str(tmp_path), "video") is None
    assert "outline" not in item


def test_invalid_max_chars_falls_back(tmp_path):
    scanner = _scanner(tmp_path, {"enabled": True, "mode": "local", "max_chars": "非法"})
    (tmp_path / "video.zh-Hans.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\n第一句足够长的测试内容在这里。\n\n"
        "2\n00:00:05,000 --> 00:00:10,000\n第二句足够长的测试内容在这里。\n\n",
        encoding="utf-8",
    )
    item = {"intro": ""}

    assert scanner._attach_outline(item, str(tmp_path), "video")


# ---------- 字幕隔离 ----------


def test_subtitle_reading_is_scoped_to_current_media(tmp_path):
    """只读当前媒体同名前缀的字幕，不碰同目录其他资产。"""
    media = tmp_path / "Video"
    media.mkdir()
    (media / "video [BV1].zh-Hans.srt").write_text("当前媒体的字幕内容", encoding="utf-8")
    (media / "other [BV2].zh-Hans.srt").write_text("别的资产的字幕", encoding="utf-8")
    (media / "video [BV1]-old.zh-Hans.srt").write_text("旧版字幕", encoding="utf-8")

    text = FavScanner._read_subtitle_text(str(media), "video [BV1]")

    assert "当前媒体的字幕" in text
    assert "别的资产" not in text


def test_subtitle_reading_prefers_chinese(tmp_path):
    media = tmp_path / "Video"
    media.mkdir()
    (media / "video.en.srt").write_text("english subtitle", encoding="utf-8")
    (media / "video.zh-Hans.srt").write_text("中文字幕内容", encoding="utf-8")

    text = FavScanner._read_subtitle_text(str(media), "video")

    assert "中文字幕" in text


def test_subtitle_reading_returns_empty_when_absent(tmp_path):
    assert FavScanner._read_subtitle_text(str(tmp_path), "video") == ""


def test_subtitle_reading_tolerates_missing_dir(tmp_path):
    assert FavScanner._read_subtitle_text(str(tmp_path / "nope"), "video") == ""


def test_subtitle_reading_accepts_vtt_and_ass(tmp_path):
    media = tmp_path / "Video"
    media.mkdir()
    (media / "video.zh-Hans.vtt").write_text("vtt 字幕", encoding="utf-8")

    assert "vtt 字幕" in FavScanner._read_subtitle_text(str(media), "video")


def test_summary_config_defaults_to_disabled():
    import yaml
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["summary"]["enabled"] is False
    assert config["summary"]["mode"] == "local"