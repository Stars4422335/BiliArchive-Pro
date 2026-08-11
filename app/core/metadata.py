import os
import re
import shutil
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from bs4 import BeautifulSoup


class MetadataGenerator:
    @staticmethod
    def _safe_stem(value):
        clean_value = re.sub(r'[\\/:*?"<>|]', '_', str(value or "info"))
        return clean_value.replace("\n", " ").replace("\r", " ").strip()[:100] or "info"

    @staticmethod
    def _add_common_fields(root, video_info, status="Active"):
        title = str(video_info.get("title") or "未知标题")
        unique_id = str(video_info.get("bvid") or "")
        up_name = str(video_info.get("up_name") or "未知UP主")

        ET.SubElement(root, "title").text = title
        if unique_id:
            ET.SubElement(root, "uniqueid", type="bilibili").text = unique_id
        ET.SubElement(root, "studio").text = up_name

        actor = ET.SubElement(root, "actor")
        ET.SubElement(actor, "name").text = up_name
        ET.SubElement(actor, "role").text = "UP主"

        pubtime = video_info.get("pubtime")
        if pubtime:
            try:
                pub_date = datetime.fromtimestamp(float(pubtime)).strftime('%Y-%m-%d')
                ET.SubElement(root, "premiered").text = pub_date
                ET.SubElement(root, "year").text = pub_date[:4]
            except (OSError, OverflowError, TypeError, ValueError):
                pass

        plot_text = str(video_info.get("intro") or "无简介")
        if status == "Tombstoned":
            plot_text = f"【系统警告：此视频已在 B 站失效。仅保留元数据。】\n\n{plot_text}"
            ET.SubElement(root, "genre").text = "已失效备份"
            ET.SubElement(root, "tag").text = "Tombstoned"
        elif status == "Protected":
            plot_text = f"【系统提示：此视频源端已删，本地资产已锁定保护。】\n\n{plot_text}"
            ET.SubElement(root, "tag").text = "Protected"

        ET.SubElement(root, "plot").text = plot_text

    @staticmethod
    def _write_nfo(root, nfo_path):
        try:
            os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
            xml_bytes = ET.tostring(root, encoding='utf-8')
            xml_str = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
            with open(nfo_path, "w", encoding="utf-8") as f:
                f.write(xml_str)
            print(f"[+] NFO 元数据已生成: {nfo_path}")
            return nfo_path
        except Exception as exc:
            print(f"[-] NFO 写入失败: {exc}")
            return None

    @staticmethod
    def create_nfo(video_info, save_path, status="Active", file_stem=None):
        """
        生成与单个媒体文件同名的 movie NFO。
        status: Active(正常), Tombstoned(墓碑), Protected(源端删本地存)
        """
        root = ET.Element("movie")
        MetadataGenerator._add_common_fields(root, video_info, status)
        stem = MetadataGenerator._safe_stem(
            file_stem if file_stem is not None else video_info.get("title", "info")
        )
        return MetadataGenerator._write_nfo(
            root,
            os.path.join(save_path, f"{stem}.nfo"),
        )

    @staticmethod
    def create_tvshow_nfo(video_info, save_path):
        """为 Plex/Jellyfin 多P目录生成剧集级元数据。"""
        root = ET.Element("tvshow")
        MetadataGenerator._add_common_fields(root, video_info)
        return MetadataGenerator._write_nfo(root, os.path.join(save_path, "tvshow.nfo"))

    @staticmethod
    def create_episode_nfo(
        video_info,
        save_path,
        file_stem,
        episode_number,
        episode_title,
    ):
        """为单个分P生成与媒体同名的 episode NFO。"""
        episode_info = dict(video_info)
        episode_info["title"] = episode_title
        bvid = str(video_info.get("bvid") or "")
        if bvid:
            episode_info["bvid"] = f"{bvid}-P{episode_number}"

        root = ET.Element("episodedetails")
        MetadataGenerator._add_common_fields(root, episode_info)
        ET.SubElement(root, "showtitle").text = str(
            video_info.get("title") or "未知标题"
        )
        ET.SubElement(root, "season").text = "1"
        ET.SubElement(root, "episode").text = str(episode_number)
        return MetadataGenerator._write_nfo(
            root,
            os.path.join(save_path, f"{MetadataGenerator._safe_stem(file_stem)}.nfo"),
        )

    @staticmethod
    def copy_artwork(source_dir, file_stem, target_path, overwrite=True):
        """把 yt-dlp 生成的同名 JPG 复制为媒体库约定的封面名称。"""
        source_path = None
        for extension in (".jpg", ".jpeg"):
            candidate = os.path.join(source_dir, f"{file_stem}{extension}")
            try:
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                    source_path = candidate
                    break
            except OSError:
                continue

        if not source_path:
            return None
        if os.path.exists(target_path) and not overwrite:
            return target_path

        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            if os.path.abspath(source_path) != os.path.abspath(target_path):
                shutil.copyfile(source_path, target_path)
            return target_path
        except OSError as exc:
            print(f"[-] 封面整理失败: {exc}")
            return None

    @staticmethod
    def process_article_to_md(article_info, save_path):
        """
        核心逻辑：抓取 B 站专栏 (cv号) 并转换为本地 Markdown
        """
        cv_id = article_info.get("id")
        title = article_info.get("title", f"cv{cv_id}")
        url = f"https://www.bilibili.com/read/cv{cv_id}"
        
        print(f"[*] 正在处理专栏图文: {title} (cv{cv_id})")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/"
        }

        try:
            # 建立图片存放目录
            img_dir = os.path.join(save_path, "images")
            os.makedirs(img_dir, exist_ok=True)

            response = requests.get(url, headers=headers, timeout=15)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            # 定位专栏正文容器
            content_tag = soup.find('div', class_='article-content')
            if not content_tag:
                print(f"[-] 无法解析专栏正文: cv{cv_id}")
                return False

            md_lines = [f"# {title}\n", f"> 原文地址: [{url}]({url})\n", f"> 备份日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "---\n"]

            # 遍历解析段落与图片
            for element in content_tag.find_all(['p', 'figure']):
                if element.name == 'p':
                    # 处理文本
                    text = element.get_text().strip()
                    if text: md_lines.append(f"{text}\n\n")
                
                elif element.name == 'figure':
                    # 处理图片
                    img_tag = element.find('img')
                    if img_tag:
                        img_url = img_tag.get('data-src') or img_tag.get('src')
                        if not img_url: continue
                        if isinstance(img_url, list):
                            img_url = str(img_url[0])
                        else:
                            img_url = str(img_url)
                        if img_url.startswith("//"): img_url = "https:" + img_url
                        
                        # 清理图片后缀下载原图
                        img_name = os.path.basename(img_url).split('@')[0]
                        local_img_path = os.path.join(img_dir, img_name)
                        
                        try:
                            # 下载并保存图片
                            img_data = requests.get(img_url, headers=headers).content
                            with open(local_img_path, 'wb') as f:
                                f.write(img_data)
                            # 在 Markdown 中嵌入本地相对路径
                            md_lines.append(f"![{img_name}](./images/{img_name})\n\n")
                        except Exception as e:
                            print(f"[-] 图片下载失败 {img_url}: {e}")

            # 写入 Markdown 文件
            clean_title = re.sub(r'[\\/:*?"<>|]', '_', title)
            md_path = os.path.join(save_path, f"{clean_title}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.writelines(md_lines)
            
            print(f"[+成功] 专栏已转换为本地 Markdown: {md_path}")
            return True

        except Exception as e:
            print(f"[-] 专栏处理失败 cv{cv_id}: {e}")
            return False
