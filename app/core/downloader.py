import os
import subprocess
import time
import random
import json
import glob
import shutil
import tempfile
import threading
from urllib.parse import urlparse
from app.core.danmaku import DanmakuConverter
from app.core.secure_file import atomic_write_text

IS_WINDOWS = os.name == "nt"

class Downloader:
    def __init__(self, config):
        self.config = config
        # 从配置中读取组件路径
        self.yt_dlp_path = config['components']['yt-dlp']['path']
        self.ffmpeg_path = config['components']['ffmpeg']['path']
        self._owned_temporary_cookies = set()
        self._temporary_cookie_lock = threading.Lock()

    def convert_cookie_to_netscape(self, json_cookie_path):
        """将 JSON 格式的 cookie 转换为 Netscape 格式供 yt-dlp 使用"""
        temporary_cookie_path = None
        try:
            with open(json_cookie_path, 'r', encoding='utf-8') as f:
                cookie_data = json.load(f)
            
            # Netscape 格式头部
            netscape_lines = ["# Netscape HTTP Cookie File", ""]
            
            # B站域名
            domain = ".bilibili.com"
            
            # 转换关键 cookie 字段
            cookie_mapping = {
                'sessdata': 'SESSDATA',
                'bili_jct': 'bili_jct', 
                'buvid3': 'buvid3',
                'dedeuserid': 'DedeUserID',
                'ac_time_value': 'ac_time_value'
            }
            
            for json_key, netscape_name in cookie_mapping.items():
                value = cookie_data.get(json_key, '')
                if value:
                    # Netscape 格式: domain, flag, path, secure, expiration, name, value
                    line = f"{domain}\tTRUE\t/\tTRUE\t0\t{netscape_name}\t{value}"
                    netscape_lines.append(line)

            fd, temporary_cookie_path = tempfile.mkstemp(
                prefix="biliarchive-cookie-",
                suffix=".txt",
            )
            os.close(fd)
            atomic_write_text(temporary_cookie_path, '\n'.join(netscape_lines) + '\n')
            owned_path = os.path.abspath(temporary_cookie_path)
            with self._temporary_cookie_lock:
                self._owned_temporary_cookies.add(owned_path)
            return owned_path
            
        except Exception as e:
            if temporary_cookie_path:
                try:
                    os.remove(temporary_cookie_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            print(f"[-] Cookie 转换失败: {e}")
            return json_cookie_path  # 失败时返回原路径，让 yt-dlp 尝试

    def _remove_temporary_cookie(self, cookie_path):
        if not cookie_path:
            return
        owned_path = os.path.abspath(cookie_path)
        with self._temporary_cookie_lock:
            if owned_path not in self._owned_temporary_cookies:
                return
            self._owned_temporary_cookies.remove(owned_path)
        try:
            os.remove(owned_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"[!] 临时 Cookie 文件清理失败: {e}")

    def random_sleep(self, action_type="download"):
        """【防线1】防封号与风控随机抖动"""
        if action_type == "download":
            delay = random.uniform(15.0, 35.0)  # 下载完大文件后长休眠
        else:
            delay = random.uniform(2.0, 5.0)    # API 请求间短休眠
            
        print(f"[*] 风控保护：随机休眠 {delay:.1f} 秒...")
        time.sleep(delay)

    def has_enough_disk_space(self, save_dir):
        min_disk_gb = self.config.get('system', {}).get('min_disk_gb', 0)
        if not min_disk_gb:
            return True

        usage = shutil.disk_usage(save_dir)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < min_disk_gb:
            print(f"[-] 磁盘空间不足：剩余 {free_gb:.2f}GB，低于配置阈值 {min_disk_gb}GB。")
            return False
        return True

    def print_manual_install_help(self, executable_name, configured_path):
        print(f"[-] 未找到 {executable_name}，未执行自动安装。")
        print(f"[!] 请手动安装 {executable_name}，并确保它可执行。")
        if executable_name == "yt-dlp":
            print("[!] 推荐方式：运行 pip install -r requirements.txt 安装 yt-dlp，或从 https://github.com/yt-dlp/yt-dlp/releases/latest 下载最新稳定版。")
            print(f"[!] 如使用独立文件，请将文件命名为 {os.path.basename(configured_path)} 并放到: {configured_path}")
        elif executable_name == "ffmpeg":
            print("[!] 推荐方式：Ubuntu/Debian 运行 sudo apt install ffmpeg；Windows/Mac 请从 ffmpeg 官网下载稳定版。")
            print(f"[!] 如使用独立文件，请将可执行文件命名为 {os.path.basename(configured_path)} 并放到: {configured_path}")

    def resolve_executable(self, configured_path, executable_name, required=True):
        if configured_path:
            configured_candidates = [configured_path]
            if IS_WINDOWS and not configured_path.lower().endswith(".exe"):
                configured_candidates.append(configured_path + ".exe")
            for candidate in configured_candidates:
                if os.path.exists(candidate):
                    return candidate

        path_executable = shutil.which(executable_name)
        if path_executable:
            return path_executable

        if required:
            self.print_manual_install_help(executable_name, configured_path)
        return None

    def download_video(self, url, save_dir, file_name, cookie_file_path):
        """
        调用 yt-dlp 执行最高画质下载及转码
        """
        parsed_url = urlparse(url)
        if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
            print("[-] 拒绝非 HTTPS 视频 URL。")
            return False

        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        if not self.has_enough_disk_space(save_dir):
            return False

        # 转换 cookie 格式
        netscape_cookie = self.convert_cookie_to_netscape(cookie_file_path)

        try:
            output_template = os.path.join(save_dir, f"{file_name}.%(ext)s")
            yt_dlp_path = self.resolve_executable(self.yt_dlp_path, "yt-dlp")
            if not yt_dlp_path:
                return False
            ffmpeg_path = self.resolve_executable(self.ffmpeg_path, "ffmpeg", required=False)
            ffmpeg_location = os.path.dirname(ffmpeg_path) if ffmpeg_path and os.path.dirname(ffmpeg_path) else "ffmpeg"

            cmd = [
                yt_dlp_path,
                "-f", "bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                "--cookies", netscape_cookie,
                "--write-info-json",
                "--write-thumbnail",
                "--convert-thumbnails", "jpg",
                "--write-subs",
                "--sub-langs", "all",
                "--ffmpeg-location", ffmpeg_location,
                "-o", output_template,
                url
            ]

            print(f"\n[>>>] 开始执行下载任务: {file_name}")
            try:
                subprocess.run(cmd, check=True)
                print(f"[+] 下载顺利完成: {file_name}")

                xml_subs = glob.glob(os.path.join(save_dir, "*.xml"))
                for xml_sub in xml_subs:
                    ass_path = xml_sub.rsplit('.', 1)[0] + ".ass"
                    print(f"[*] 正在将弹幕 {os.path.basename(xml_sub)} 转为 ASS 字幕...")
                    if DanmakuConverter.xml_to_ass(xml_sub, ass_path):
                        print(f"[+成功] 弹幕转换完成: {os.path.basename(ass_path)}")

                self.random_sleep("download")
                return True
            except subprocess.CalledProcessError as e:
                print(f"[-] 下载发生异常: {e}")
                return False
            except FileNotFoundError:
                print(f"[-] 严重错误：找不到 {yt_dlp_path}，请检查 bin 目录或系统 PATH。")
                return False
        finally:
            self._remove_temporary_cookie(netscape_cookie)
