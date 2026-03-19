import os
import xml.etree.ElementTree as ET

class DanmakuConverter:
    """简单的 B站 XML 弹幕转 ASS 字幕转换器"""
    
    @staticmethod
    def _color_to_ass_hex(dec_color):
        """将十进制颜色转为 ASS 格式的 AABBGGRR (反序)"""
        try:
            h = f"{int(dec_color):06x}"
            return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&"
        except:
            return "&H00FFFFFF&"
            
    @staticmethod
    def _format_time(seconds):
        """将秒数转换为 H:MM:SS.cs"""
        h = int(seconds / 3600)
        m = int((seconds % 3600) / 60)
        s = seconds % 60
        cs = int((s - int(s)) * 100)
        return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"

    @staticmethod
    def xml_to_ass(xml_path, ass_path, video_width=1920, video_height=1080):
        if not os.path.exists(xml_path):
            return False
            
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception as e:
            print(f"[-] 弹幕 XML 解析失败: {e}")
            return False

        header = f"""[Script Info]
Title: BiliArchive-Pro Danmaku
ScriptType: v4.00+
Collisions: Normal
PlayResX: {video_width}
PlayResY: {video_height}
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,45,&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H00000000&,0,0,0,0,100,100,0,0,1,2,0,2,20,20,20,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        events = []
        for d in root.findall('d'):
            p = d.get('p')
            if not p or not d.text:
                continue
                
            parts = p.split(',')
            if len(parts) < 8:
                continue
                
            # p 参数格式: time, type, size, color, unix, pool, hash, rowid
            try:
                start_time = float(parts[0])
                # 简单计算一个显示时长，弹幕越长显示越久
                duration = max(3.0, len(d.text) * 0.2)
                end_time = start_time + duration
                
                type_val = int(parts[1]) # 1,2,3 是滚动，4 是底端，5 是顶端
                color_ass = DanmakuConverter._color_to_ass_hex(parts[3])
                text = d.text.strip().replace("\n", " ").replace("\r", "")
                
                start_str = DanmakuConverter._format_time(start_time)
                end_str = DanmakuConverter._format_time(end_time)
                
                # 简单处理滚动弹幕：固定在屏幕不同高度
                # （更完美的防重叠需要复杂算法，这里为了简便只做基础转换和颜色）
                margin_v = 20
                if type_val in (4, 5):
                    # 顶部或底部
                    margin_v = 20
                
                # 在文本前增加颜色指令
                formatted_text = f"{{\\c{color_ass}}}{text}"
                
                # 构建 event 行
                events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0000,0000,{margin_v:04d},,{formatted_text}")
                
            except:
                continue

        # 按时间排序
        events.sort(key=lambda x: x.split(",")[1])

        try:
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(header)
                f.write("\n".join(events))
            return True
        except Exception as e:
            print(f"[-] 弹幕 ASS 写入失败: {e}")
            return False
