import json
import math
import os
import random
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlparse
from app.core.danmaku import DanmakuConverter
from app.core.secure_file import atomic_write_text

IS_WINDOWS = os.name == "nt"


def _terminate_process_tree(process):
    if process.poll() is not None:
        return

    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            process.kill()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if IS_WINDOWS:
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()


def _run_process_tree(cmd, check=False, timeout=None):
    popen_kwargs = {}
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0,
        )
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(cmd, **popen_kwargs)
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        raise
    except BaseException:
        _terminate_process_tree(process)
        raise

    if check and return_code:
        raise subprocess.CalledProcessError(return_code, cmd)
    return subprocess.CompletedProcess(cmd, return_code)


class Downloader:
    def __init__(self, config):
        self.config = config
        # 从配置中读取组件路径
        self.yt_dlp_path = config['components']['yt-dlp']['path']
        self.ffmpeg_path = config['components']['ffmpeg']['path']
        self.download_timeout_seconds = self._normalize_download_timeout(
            config.get('system', {}).get('download_timeout_seconds', 7200)
        )
        self._owned_temporary_cookies = set()
        self._temporary_cookie_lock = threading.Lock()

    @staticmethod
    def _normalize_download_timeout(value):
        """将下载超时限制在 1 秒到 7 天；0 表示不限制。"""
        if isinstance(value, bool):
            return 7200.0
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            return 7200.0
        if not math.isfinite(timeout):
            return 7200.0
        if timeout == 0:
            return None
        if timeout < 0:
            return 7200.0
        return min(604800.0, max(1.0, timeout))

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

    @staticmethod
    def _cleanup_empty_partial_files(save_dir, file_name):
        """清理不可续传的空残留，保留非空 .part 文件供 yt-dlp 续传。"""
        prefix = f"{file_name}."
        try:
            entries = list(os.scandir(save_dir))
        except OSError as exc:
            print(f"[!] 检查下载残留失败: {exc}")
            return

        for entry in entries:
            is_partial = entry.name.endswith(".part") or ".part-Frag" in entry.name
            if not entry.name.startswith(prefix) or not is_partial:
                continue
            try:
                if entry.is_file() and entry.stat().st_size == 0:
                    os.remove(entry.path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"[!] 清理空下载残留失败: {entry.path}: {exc}")

    def random_sleep(self, action_type="download"):
        """【防线1】防封号与风控随机抖动"""
        if action_type == "download":
            delay = random.uniform(15.0, 35.0)  # 下载完大文件后长休眠
        else:
            delay = random.uniform(2.0, 5.0)    # API 请求间短休眠
            
        print(f"[*] 风控保护：随机休眠 {delay:.1f} 秒...")
        time.sleep(delay)

    @staticmethod
    def _convert_downloaded_danmaku(save_dir, file_name):
        """只转换当前下载任务生成的 .danmaku.xml，避免扫描其他资产。"""
        prefix = f"{file_name}."
        try:
            entries = list(os.scandir(save_dir))
        except OSError as exc:
            print(f"[-] 弹幕文件扫描失败: {exc}")
            return

        for entry in entries:
            try:
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            if not is_file or not entry.name.startswith(prefix):
                continue
            if not entry.name.lower().endswith(".danmaku.xml"):
                continue
            xml_sub = entry.path
            ass_path = xml_sub.rsplit('.', 1)[0] + ".ass"
            print(f"[*] 正在将弹幕 {os.path.basename(xml_sub)} 转为 ASS 字幕...")
            try:
                converted = DanmakuConverter.xml_to_ass(xml_sub, ass_path)
            except Exception as exc:
                print(f"[-] 弹幕转换异常，已保留原 XML: {exc}")
                continue
            if converted:
                print(f"[+成功] 弹幕转换完成: {os.path.basename(ass_path)}")

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
            template_file_name = file_name.replace("%", "%%")
            output_template = os.path.join(save_dir, f"{template_file_name}.%(ext)s")
            yt_dlp_path = self.resolve_executable(self.yt_dlp_path, "yt-dlp")
            if not yt_dlp_path:
                return False
            ffmpeg_path = self.resolve_executable(self.ffmpeg_path, "ffmpeg", required=False)
            ffmpeg_location = os.path.dirname(ffmpeg_path) if ffmpeg_path and os.path.dirname(ffmpeg_path) else "ffmpeg"

            cmd = [
                yt_dlp_path,
                "-f", "bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--continue",
                "--part",
                "--cookies", netscape_cookie,
                "--write-info-json",
                "--write-thumbnail",
                "--convert-thumbnails", "jpg",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", "all",
                "--ffmpeg-location", ffmpeg_location,
                "-o", output_template,
                url
            ]

            print(f"\n[>>>] 开始执行下载任务: {file_name}")
            self._cleanup_empty_partial_files(save_dir, file_name)
            try:
                _run_process_tree(
                    cmd,
                    check=True,
                    timeout=self.download_timeout_seconds,
                )
                print(f"[+] 下载顺利完成: {file_name}")

                self._convert_downloaded_danmaku(save_dir, file_name)

                self.random_sleep("download")
                return True
            except subprocess.TimeoutExpired as exc:
                self._cleanup_empty_partial_files(save_dir, file_name)
                print(f"[-] 下载超过配置时限（{exc.timeout:g} 秒），已终止: {file_name}")
                return False
            except subprocess.CalledProcessError as e:
                self._cleanup_empty_partial_files(save_dir, file_name)
                print(f"[-] 下载发生异常: {e}")
                return False
            except FileNotFoundError:
                self._cleanup_empty_partial_files(save_dir, file_name)
                print(f"[-] 严重错误：找不到 {yt_dlp_path}，请检查 bin 目录或系统 PATH。")
                return False
        finally:
            self._remove_temporary_cookie(netscape_cookie)
