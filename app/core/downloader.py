import os
import subprocess
import time
import random

class Downloader:
    def __init__(self, config):
        self.config = config
        # 从配置中读取组件路径
        self.yt_dlp_path = config['components']['yt-dlp']['path']
        self.ffmpeg_path = config['components']['ffmpeg']['path']

    def random_sleep(self, action_type="download"):
        """【防线1】防封号与风控随机抖动"""
        if action_type == "download":
            delay = random.uniform(15.0, 35.0)  # 下载完大文件后长休眠
        else:
            delay = random.uniform(2.0, 5.0)    # API 请求间短休眠
            
        print(f"[*] 风控保护：随机休眠 {delay:.1f} 秒...")
        time.sleep(delay)

    def download_video(self, url, save_dir, file_name, cookie_file_path):
        """
        调用 yt-dlp 执行最高画质下载及转码
        """
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # 拼接输出模板 (yt-dlp 会自动替换 %(ext)s 为 mp4)
        output_template = os.path.join(save_dir, f"{file_name}.%(ext)s")

        cmd = [
            self.yt_dlp_path,
            # 强制最高画质视频流 + 最高音质音频流
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            # 注入大会员 Cookie
            "--cookies", cookie_file_path,
            # 抓取元数据、封面、弹幕/字幕
            "--write-info-json",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--write-subs",
            "--sub-langs", "all",
            # 指向 ffmpeg 所在目录进行合并
            "--ffmpeg-location", os.path.dirname(self.ffmpeg_path) if self.ffmpeg_path else "ffmpeg",
            "-o", output_template,
            url
        ]

        print(f"\n[>>>] 开始执行下载任务: {file_name}")
        try:
            # 执行下载，控制台会实时输出进度条
            subprocess.run(cmd, check=True)
            print(f"[+] 下载顺利完成: {file_name}")
            
            # 下载成功后执行长休眠防风控
            self.random_sleep("download")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"[-] 下载发生异常: {e}")
            return False
        except FileNotFoundError:
            print(f"[-] 严重错误：找不到 {self.yt_dlp_path}，请检查 bin 目录下是否存在该文件。")
            return False
