import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

class MetadataGenerator:
    @staticmethod
    def create_nfo(video_info, save_path, status="Active"):
        """
        生成符合 Kodi/Plex 标准的 .nfo 元数据文件
        status: Active(正常), Tombstoned(墓碑), Protected(源端删本地存)
        """
        os.makedirs(save_path, exist_ok=True)
        root = ET.Element("movie")

        # 核心基础信息
        ET.SubElement(root, "title").text = video_info.get("title", "未知标题")
        ET.SubElement(root, "uniqueid", type="bilibili").text = video_info.get("bvid", "")
        ET.SubElement(root, "studio").text = video_info.get("up_name", "未知UP主")

        # 时间戳处理 (转为 Plex 认的 YYYY-MM-DD)
        if "pubtime" in video_info and video_info["pubtime"]:
            try:
                pub_date = datetime.fromtimestamp(video_info["pubtime"]).strftime('%Y-%m-%d')
                ET.SubElement(root, "premiered").text = pub_date
                ET.SubElement(root, "year").text = pub_date[:4]
            except Exception:
                pass

        # 简介与状态标记逻辑
        plot_text = video_info.get("intro", "无简介")
        if status == "Tombstoned":
            plot_text = f"【系统警告：此视频已在 B 站失效。仅保留元数据。】\n\n{plot_text}"
            ET.SubElement(root, "genre").text = "已失效备份"
            ET.SubElement(root, "tag").text = "Tombstoned"
        elif status == "Protected":
            plot_text = f"【系统提示：此视频源端已删，本地资产已锁定保护。】\n\n{plot_text}"
            ET.SubElement(root, "tag").text = "Protected"

        ET.SubElement(root, "plot").text = plot_text

        # 格式化 XML 并安全写入文件
        xmlstr = minidom.parseString(ET.tostring(root, 'utf-8')).toprettyxml(indent="  ")
        nfo_filename = f"{video_info.get('title', 'info')[:50].replace('/', '_')}.nfo"
        nfo_path = os.path.join(save_path, nfo_filename)

        try:
            with open(nfo_path, "w", encoding="utf-8") as f:
                f.write(xmlstr)
            print(f"[+] NFO 元数据已生成: {nfo_filename}")
        except Exception as e:
            print(f"[-] NFO 写入失败: {e}")

    @staticmethod
    def process_article_to_md(article_info, save_path):
        """预留的图文专栏转 Markdown 接口"""
        print(f"[*] 图文专栏保存逻辑已就绪，等待后续插件接入: {article_info.get('title')}")
        pass
