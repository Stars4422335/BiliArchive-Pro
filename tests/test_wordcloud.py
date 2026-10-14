"""弹幕词云测试（M4）。

重点覆盖三类风险：
1. 分词噪声——弹幕里大量应答词与纯符号，不能进入词云；
2. 失败语义——词云是衍生品，任何异常都不得影响视频下载的成功判定；
3. 输出安全——SVG 内容来自用户可见的弹幕文本，必须做 XML 转义。
"""

import xml.etree.ElementTree as ET

import pytest

from app.core.danmaku import DanmakuConverter
from app.core.downloader import Downloader
from app.core.wordcloud import DanmakuWordCloud


def _write_danmaku(path, texts, *, timestamp="1.0,1,25,16777215,0,0,0,0"):
    """写一个最小可用的弹幕 XML。p 字段格式与 B 站一致。"""
    root = ET.Element("i")
    for text in texts:
        element = ET.SubElement(root, "d")
        element.set("p", f"{timestamp},1,25,16777215,0,0,0,0")
        element.text = text
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


# ---------- 分词 ----------


def test_tokenize_keeps_meaningful_chinese_bigrams():
    terms = DanmakuWordCloud.tokenize("前排观众")

    assert "前排观众" in terms
    assert "前排" in terms
    assert "观众" in terms


def test_tokenize_filters_laughter_and_fillers():
    for noise in ("哈哈哈", "awsl", "2333"):
        assert DanmakuWordCloud.tokenize(noise) == []


def test_tokenize_keeps_meaningful_frequent_words():
    """「前排」「打卡」虽高频但有语义，不能当成噪声滤掉。"""
    assert "前排" in DanmakuWordCloud.tokenize("前排")
    assert "打卡" in DanmakuWordCloud.tokenize("打卡")


def test_tokenize_drops_pure_symbols_and_empty():
    assert DanmakuWordCloud.tokenize("!!!???...") == []
    assert DanmakuWordCloud.tokenize("   ") == []
    assert DanmakuWordCloud.tokenize("") == []


def test_tokenize_drops_single_char():
    assert DanmakuWordCloud.tokenize("我") == []


def test_tokenize_lowercases_ascii_and_requires_two_chars():
    terms = DanmakuWordCloud.tokenize("GPU FOMO")

    assert "gpu" in terms
    assert "fomo" in terms
    # 单个字母无信息量
    assert "g" not in terms


def test_tokenize_deduplicates_within_one_comment():
    terms = DanmakuWordCloud.tokenize("弹幕弹幕弹幕")

    assert len(terms) == len(set(terms))


def test_tokenize_caps_terms_per_comment():
    # 一条超长弹幕不能独占整个词云
    terms = DanmakuWordCloud.tokenize("一二三四五六七八九十" * 10)

    assert len(terms) <= 6


def test_tokenize_handles_none_input():
    assert DanmakuWordCloud.tokenize(None) == []


# ---------- 统计 ----------


def test_extract_terms_ranks_by_frequency(tmp_path):
    xml = _write_danmaku(
        tmp_path / "a.danmaku.xml",
        ["模型训练", "模型推理", "模型部署", "随便说点别的"],
    )

    terms = DanmakuWordCloud.extract_terms(xml)

    assert terms[0] == "模型"
    assert "模型训练" in terms


def test_extract_terms_skips_invalid_entries(tmp_path):
    root = ET.Element("i")
    for bad in ("", "not-enough,params"):
        element = ET.SubElement(root, "d")
        element.set("p", bad)
        element.text = "内容"
    # 时间戳非法（超过上限）
    bad_time = ET.SubElement(root, "d")
    bad_time.set("p", "999999.0,1,25,16777215,0,0,0,0")
    bad_time.text = "内容"
    ET.ElementTree(root).write(tmp_path / "b.danmaku.xml", encoding="utf-8")

    assert DanmakuWordCloud.extract_terms(tmp_path / "b.danmaku.xml") == []


def test_extract_terms_returns_empty_for_missing_file(tmp_path):
    assert DanmakuWordCloud.extract_terms(tmp_path / "missing.xml") == []


def test_extract_terms_returns_empty_for_corrupt_xml(tmp_path):
    broken = tmp_path / "broken.xml"
    broken.write_text("<i><d>未闭合", encoding="utf-8")

    assert DanmakuWordCloud.extract_terms(broken) == []


def test_extract_terms_sees_same_comments_as_ass_converter(tmp_path):
    """词云与 ASS 转换必须看到同一批弹幕，否则两处产物会对不上。"""
    xml = _write_danmaku(tmp_path / "c.danmaku.xml", ["模型训练", "模型推理", "模型部署"])

    terms = DanmakuWordCloud.extract_terms(xml)
    root = ET.parse(xml).getroot()
    parsed = [DanmakuConverter.parse_comment(e) for e in root]

    assert terms
    assert all(c is not None for c in parsed)
    assert len(parsed) == 3


# ---------- SVG 渲染 ----------


def test_render_svg_contains_expected_structure():
    svg = DanmakuWordCloud().render_svg(["模型", "训练", "推理", "部署", "加速"])

    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert svg.count("<text") == 5
    assert 'font-family=' in svg


def test_render_svg_escapes_xml_special_characters():
    """弹幕文本来自外部，SVG 必须转义，否则可注入标签。"""
    svg = DanmakuWordCloud().render_svg(
        ["<script>", "&", '"', "模型训练推理部署加速", "测试内容"]
    )

    assert "<script>" not in svg
    assert "&lt;" in svg or "&amp;" in svg
    assert svg.count("<text") == 5  # 没有多出额外元素


def test_render_svg_head_terms_are_larger():
    svg = DanmakuWordCloud(max_terms=10).render_svg(
        [f"词{i}" for i in range(10)]
    )
    import re

    sizes = [int(m) for m in re.findall(r'font-size="(\d+)"', svg)]

    assert sizes[0] > sizes[-1]


def test_render_svg_is_deterministic_for_same_input():
    terms = [f"词{i}" for i in range(20)]

    first = DanmakuWordCloud().render_svg(terms)
    second = DanmakuWordCloud().render_svg(terms)

    assert first == second


def test_render_svg_rejects_empty_terms():
    with pytest.raises(ValueError):
        DanmakuWordCloud().render_svg([])


def test_max_terms_is_clamped():
    assert DanmakuWordCloud(max_terms=0).max_terms == 1
    assert DanmakuWordCloud(max_terms=99999).max_terms == 500


def test_max_terms_limits_rendered_words():
    terms = [f"词{i}" for i in range(50)]

    svg = DanmakuWordCloud(max_terms=10).render_svg(terms)

    assert svg.count("<text") == 10


# ---------- 生成入口 ----------


def test_generate_writes_svg(tmp_path):
    xml = _write_danmaku(
        tmp_path / "d.danmaku.xml",
        ["模型训练"] * 5 + ["模型推理"] * 3 + ["显卡加速"] * 2,
    )
    out = tmp_path / "d.wordcloud.svg"

    assert DanmakuWordCloud().generate(xml, out) is True
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("<svg")


def test_generate_skips_when_too_few_terms(tmp_path):
    xml = _write_danmaku(tmp_path / "e.danmaku.xml", ["模型训练"])
    out = tmp_path / "e.wordcloud.svg"

    assert DanmakuWordCloud().generate(xml, out) is False
    assert not out.exists()


def test_generate_handles_missing_source(tmp_path):
    out = tmp_path / "f.wordcloud.svg"

    assert DanmakuWordCloud().generate(tmp_path / "missing.xml", out) is False


def test_generate_uses_atomic_writer(tmp_path, monkeypatch):
    xml = _write_danmaku(
        tmp_path / "g.danmaku.xml",
        ["模型训练"] * 4 + ["模型推理"] * 3 + ["显卡加速"] * 2,
    )
    out = tmp_path / "g.wordcloud.svg"
    captured = {}

    def fake_atomic(path, content):
        captured["path"] = path
        captured["content"] = content
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    monkeypatch.setattr("app.core.wordcloud.atomic_write_text", fake_atomic)

    assert DanmakuWordCloud().generate(xml, out) is True
    assert captured["path"] == out
    assert captured["content"].startswith("<svg")


# ---------- downloader 集成 ----------


def test_wordcloud_disabled_by_default(tmp_path):
    downloader = Downloader.__new__(Downloader)
    downloader.config = {"system": {}}

    assert downloader._generate_wordcloud(tmp_path / "x.xml") is False


def test_wordcloud_enabled_generates_file(tmp_path):
    xml = _write_danmaku(
        tmp_path / "video [BV1].danmaku.xml",
        ["模型训练"] * 4 + ["模型推理"] * 3 + ["显卡加速"] * 2,
    )
    downloader = Downloader.__new__(Downloader)
    downloader.config = {"system": {}, "wordcloud": {"enabled": True}}

    assert downloader._generate_wordcloud(xml) is True
    # 侧车沿用 ASS 的命名习惯：X.danmaku.xml -> X.danmaku.ass / X.danmaku.wordcloud.svg
    assert (tmp_path / "video [BV1].danmaku.wordcloud.svg").exists()


def test_wordcloud_failure_does_not_raise(tmp_path):
    """词云是衍生品：异常必须被吞掉，不能打断下载流程。"""
    xml = tmp_path / "broken.danmaku.xml"
    xml.write_text("<i><d>未闭合", encoding="utf-8")
    downloader = Downloader.__new__(Downloader)
    downloader.config = {"system": {}, "wordcloud": {"enabled": True}}

    assert downloader._generate_wordcloud(xml) is False


def test_wordcloud_invalid_max_terms_falls_back(tmp_path):
    xml = _write_danmaku(
        tmp_path / "h.danmaku.xml",
        ["模型训练"] * 4 + ["模型推理"] * 3 + ["显卡加速"] * 2,
    )
    downloader = Downloader.__new__(Downloader)
    downloader.config = {
        "system": {},
        "wordcloud": {"enabled": True, "max_terms": "非法值"},
    }

    assert downloader._generate_wordcloud(xml) is True


def test_wordcloud_exception_inside_generator_is_contained(tmp_path, monkeypatch):
    """即使词云模块自身抛异常，下载器也不应被拖垮。"""
    xml = _write_danmaku(
        tmp_path / "i.danmaku.xml",
        ["模型训练"] * 4 + ["模型推理"] * 3 + ["显卡加速"] * 2,
    )
    downloader = Downloader.__new__(Downloader)
    downloader.config = {"system": {}, "wordcloud": {"enabled": True}}

    def boom(*args, **kwargs):
        raise RuntimeError("词云内部炸了")

    monkeypatch.setattr(DanmakuWordCloud, "generate", staticmethod(boom))

    assert downloader._generate_wordcloud(xml) is False


def test_danmaku_conversion_triggers_wordcloud_when_enabled(tmp_path, monkeypatch):
    """弹幕转换后应顺带触发词云（同一 .danmaku.xml）。"""
    media_dir = tmp_path / "Video [BV1]"
    media_dir.mkdir()
    _write_danmaku(
        media_dir / "video [BV1].danmaku.xml",
        ["模型训练"] * 4 + ["模型推理"] * 3 + ["显卡加速"] * 2,
    )
    calls = []
    monkeypatch.setattr(
        "app.core.downloader.DanmakuConverter.xml_to_ass",
        lambda source, target: calls.append((source, target)) or True,
    )

    downloader = Downloader.__new__(Downloader)
    downloader.config = {"system": {}, "wordcloud": {"enabled": True}}
    downloader._convert_downloaded_danmaku(str(media_dir), "video [BV1]")

    assert len(calls) == 1
    assert (media_dir / "video [BV1].danmaku.wordcloud.svg").exists()