import math
import os
import unicodedata
import xml.etree.ElementTree as ET


class DanmakuConverter:
    """将 B 站 XML 弹幕转换为带轨道调度的 ASS 字幕。"""

    MAX_TIMESTAMP_SECONDS = 359999.99
    ROLLING_TYPES = {1, 2, 3}
    BOTTOM_TYPE = 4
    TOP_TYPE = 5
    REVERSE_TYPE = 6

    @staticmethod
    def _color_to_ass_hex(dec_color):
        """将十进制 RGB 转为 ASS 使用的 AABBGGRR。"""
        try:
            color = int(dec_color)
            if not 0 <= color <= 0xFFFFFF:
                raise ValueError("color out of range")
            value = f"{color:06X}"
            return f"&H00{value[4:6]}{value[2:4]}{value[0:2]}&"
        except (TypeError, ValueError):
            return "&H00FFFFFF&"

    @staticmethod
    def _format_time(seconds):
        """将秒数转换为 ASS 的 H:MM:SS.cs。"""
        try:
            numeric_seconds = float(seconds)
            if (
                not math.isfinite(numeric_seconds)
                or numeric_seconds < 0
                or numeric_seconds > DanmakuConverter.MAX_TIMESTAMP_SECONDS
            ):
                raise ValueError("time is outside the supported ASS range")
            total_centiseconds = max(0, int(round(numeric_seconds * 100)))
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("invalid ASS timestamp") from exc
        hours, remainder = divmod(total_centiseconds, 360000)
        minutes, remainder = divmod(remainder, 6000)
        whole_seconds, centiseconds = divmod(remainder, 100)
        return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"

    @staticmethod
    def _escape_ass_text(text):
        return (
            str(text)
            .replace("\\", r"\\")
            .replace("{", r"\{")
            .replace("}", r"\}")
            .replace("\r\n", r"\N")
            .replace("\n", r"\N")
            .replace("\r", r"\N")
        )

    @staticmethod
    def _estimate_text_width(text, font_size):
        units = sum(
            2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
            for char in text
        )
        return max(font_size, units * font_size * 0.55)

    @staticmethod
    def _allocate_lane(available_at, start_time, end_time):
        for index, ready_time in enumerate(available_at):
            if ready_time <= start_time:
                available_at[index] = end_time
                return index
        return None

    @staticmethod
    def _parse_comment(element):
        parameters = element.get("p")
        if not parameters or element.text is None:
            return None
        parts = parameters.split(",")
        if len(parts) < 4:
            return None

        try:
            start_time = float(parts[0])
            if (
                not math.isfinite(start_time)
                or start_time > DanmakuConverter.MAX_TIMESTAMP_SECONDS
            ):
                return None
            start_time = max(0.0, start_time)
            type_value = int(parts[1])
            font_size = min(72, max(12, int(float(parts[2]))))
        except (OverflowError, TypeError, ValueError):
            return None

        text = element.text.strip()
        if not text:
            return None
        if type_value not in (
            DanmakuConverter.ROLLING_TYPES
            | {
                DanmakuConverter.BOTTOM_TYPE,
                DanmakuConverter.TOP_TYPE,
                DanmakuConverter.REVERSE_TYPE,
            }
        ):
            return None

        return {
            "start": start_time,
            "type": type_value,
            "font_size": font_size,
            "color": DanmakuConverter._color_to_ass_hex(parts[3]),
            "text": text,
        }

    @staticmethod
    def xml_to_ass(xml_path, ass_path, video_width=1920, video_height=1080):
        if not os.path.exists(xml_path):
            return False

        try:
            width = max(320, int(video_width))
            height = max(180, int(video_height))
        except (OverflowError, TypeError, ValueError):
            width, height = 1920, 1080

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except (ET.ParseError, OSError) as exc:
            print(f"[-] 弹幕 XML 解析失败: {exc}")
            return False

        header = f"""[Script Info]
Title: BiliArchive-Pro Danmaku
ScriptType: v4.00+
Collisions: Normal
PlayResX: {width}
PlayResY: {height}
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,45,&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H00000000&,0,0,0,0,100,100,0,0,1,2,0,7,20,20,20,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        comments = []
        for element in root.findall("d"):
            comment = DanmakuConverter._parse_comment(element)
            if comment:
                comments.append(comment)
        comments.sort(key=lambda comment: comment["start"])

        lane_height = max(24, int(height * 0.05))
        fixed_lane_count = max(1, int(height * 0.18) // lane_height)
        fixed_region_height = 20 + fixed_lane_count * lane_height
        rolling_top = max(int(height * 0.22), fixed_region_height)
        rolling_bottom = min(
            int(height * 0.78),
            height - fixed_region_height,
        )
        rolling_lane_count = max(1, (rolling_bottom - rolling_top) // lane_height)
        rolling_available = [0.0] * rolling_lane_count
        top_available = [0.0] * fixed_lane_count
        bottom_available = [0.0] * fixed_lane_count

        events = []
        dropped = 0
        for comment in comments:
            start_time = comment["start"]
            type_value = comment["type"]
            font_size = min(comment["font_size"], max(12, lane_height - 4))
            color = comment["color"]
            raw_text = comment["text"]
            text = DanmakuConverter._escape_ass_text(raw_text)

            if type_value in DanmakuConverter.ROLLING_TYPES | {DanmakuConverter.REVERSE_TYPE}:
                text_width = DanmakuConverter._estimate_text_width(raw_text, font_size)
                duration = min(15.0, max(6.0, (width + text_width) / 160.0))
                end_time = min(
                    DanmakuConverter.MAX_TIMESTAMP_SECONDS,
                    start_time + duration,
                )
                lane = DanmakuConverter._allocate_lane(
                    rolling_available,
                    start_time,
                    end_time,
                )
                if lane is None:
                    dropped += 1
                    continue
                y_position = rolling_top + lane * lane_height
                edge = int(math.ceil(text_width)) + 10
                if type_value == DanmakuConverter.REVERSE_TYPE:
                    movement = f"\\move(-{edge},{y_position},{width + 10},{y_position})"
                else:
                    movement = f"\\move({width + 10},{y_position},-{edge},{y_position})"
                tags = f"\\an7{movement}\\fs{font_size}\\c{color}"
            else:
                duration = 4.0
                end_time = min(
                    DanmakuConverter.MAX_TIMESTAMP_SECONDS,
                    start_time + duration,
                )
                if type_value == DanmakuConverter.TOP_TYPE:
                    lane = DanmakuConverter._allocate_lane(
                        top_available,
                        start_time,
                        end_time,
                    )
                    if lane is None:
                        dropped += 1
                        continue
                    y_position = 20 + lane * lane_height
                    tags = f"\\an8\\pos({width // 2},{y_position})\\fs{font_size}\\c{color}"
                else:
                    lane = DanmakuConverter._allocate_lane(
                        bottom_available,
                        start_time,
                        end_time,
                    )
                    if lane is None:
                        dropped += 1
                        continue
                    y_position = height - 20 - lane * lane_height
                    tags = f"\\an2\\pos({width // 2},{y_position})\\fs{font_size}\\c{color}"

            start_value = DanmakuConverter._format_time(start_time)
            end_value = DanmakuConverter._format_time(end_time)
            events.append(
                f"Dialogue: 0,{start_value},{end_value},Default,,0000,0000,0000,,"
                f"{{{tags}}}{text}"
            )

        try:
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(header)
                f.write("\n".join(events))
                if events:
                    f.write("\n")
            if dropped:
                print(f"[!] 弹幕轨道容量不足，已跳过 {dropped} 条重叠弹幕。")
            return True
        except OSError as exc:
            print(f"[-] 弹幕 ASS 写入失败: {exc}")
            return False
