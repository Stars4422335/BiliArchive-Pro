import re

import pytest

from app.core.danmaku import DanmakuConverter


def write_xml(path, comments):
    body = "".join(
        f'<d p="{parameters}">{text}</d>'
        for parameters, text in comments
    )
    path.write_text(f"<i>{body}</i>", encoding="utf-8")


def dialogue_lines(path):
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("Dialogue:")
    ]


def test_danmaku_converter_sorts_and_positions_supported_comment_types(tmp_path):
    xml_path = tmp_path / "video.danmaku.xml"
    ass_path = tmp_path / "video.danmaku.ass"
    write_xml(
        xml_path,
        [
            ("10,1,25,16711680,0,0,0,1", r"滚动{测试}\\路径"),
            ("2,5,30,16777215,0,0,0,2", "顶部"),
            ("3,4,30,16777215,0,0,0,3", "底部"),
            ("4,6,25,16777215,0,0,0,4", "反向"),
        ],
    )

    assert DanmakuConverter.xml_to_ass(xml_path, ass_path) is True

    lines = dialogue_lines(ass_path)
    assert [line.split(",")[1] for line in lines] == [
        "0:00:02.00",
        "0:00:03.00",
        "0:00:04.00",
        "0:00:10.00",
    ]
    assert "\\an8\\pos(" in lines[0]
    assert "\\an2\\pos(" in lines[1]
    assert "\\move(-" in lines[2]
    assert "\\move(1930" in lines[3]
    assert r"\{测试\}" in lines[3]
    assert r"\\路径" in lines[3]
    assert "\\c&H000000FF&" in lines[3]


def test_danmaku_converter_uses_unique_lanes_and_drops_overflow(tmp_path, capsys):
    xml_path = tmp_path / "dense.danmaku.xml"
    ass_path = tmp_path / "dense.danmaku.ass"
    write_xml(
        xml_path,
        [
            (f"1,1,25,16777215,0,0,0,{index}", f"弹幕{index}")
            for index in range(6)
        ],
    )

    assert DanmakuConverter.xml_to_ass(
        xml_path,
        ass_path,
        video_width=320,
        video_height=180,
    ) is True

    lines = dialogue_lines(ass_path)
    y_positions = [
        int(re.search(r"\\move\([^,]+,(\d+),", line).group(1))
        for line in lines
    ]
    assert 0 < len(lines) < 6
    assert len(set(y_positions)) == len(lines)
    assert "条重叠弹幕" in capsys.readouterr().out


def test_danmaku_converter_ignores_malformed_and_unsupported_comments(tmp_path):
    xml_path = tmp_path / "invalid.danmaku.xml"
    ass_path = tmp_path / "invalid.danmaku.ass"
    write_xml(
        xml_path,
        [
            ("bad", "参数不足"),
            ("1,7,25,16777215,0,0,0,1", "高级弹幕"),
            ("1,1,25,16777215,0,0,0,2", "有效弹幕"),
        ],
    )

    assert DanmakuConverter.xml_to_ass(xml_path, ass_path) is True
    assert len(dialogue_lines(ass_path)) == 1


@pytest.mark.parametrize("invalid_time", ["inf", "-inf", "nan", "1e308"])
def test_danmaku_converter_ignores_non_finite_timestamps(tmp_path, invalid_time):
    xml_path = tmp_path / "invalid-time.danmaku.xml"
    ass_path = tmp_path / "invalid-time.danmaku.ass"
    write_xml(
        xml_path,
        [
            (f"{invalid_time},1,25,16777215,0,0,0,1", "异常时间"),
            ("1,1,25,16777215,0,0,0,2", "有效弹幕"),
        ],
    )

    assert DanmakuConverter.xml_to_ass(xml_path, ass_path) is True
    lines = dialogue_lines(ass_path)
    assert len(lines) == 1
    assert "有效弹幕" in lines[0]
