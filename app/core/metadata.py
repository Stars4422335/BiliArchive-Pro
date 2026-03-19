import os
import re
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from bs4 import BeautifulSoup

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
        
        # 模拟“演员”节点，方便在 Plex 里按 UP 主聚合
        actor = ET.SubElement(root, "actor")
        ET.SubElement(actor, "name").text = video_info.get("up_name", "未知UP主")
        ET.SubElement(actor, "role").text = "UP主"

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

        # 格式化 XML
        xml_bytes = ET.tostring(root, encoding='utf-8')
        xml_str = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
        
        # 文件命名去畸
        clean_title = re.sub(r'[\\/:*?"<>|]', '_', video_info.get('title', 'info'))[:50]
        nfo_path = os.path.join(save_path, f"{clean_title}.nfo")

        try:
            with open(nfo_path, "w", encoding="utf-8") as f:
                f.write(xml_str)
            print(f"[+] NFO 元数据已生成: {nfo_path}")
        except Exception as e:
            print(f"[-] NFO 写入失败: {e}")

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