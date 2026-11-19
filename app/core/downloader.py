import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlparse

from app.core.danmaku import DanmakuConverter
from app.core.secure_file import atomic_write_text
from app.core.wordcloud import DanmakuWordCloud

IS_WINDOWS = os.name == "nt"

#: yt-dlp 重试与字幕语言白名单的默认值：配置缺失、为空或非法时一律回退到这里。
DEFAULT_DOWNLOAD_RETRIES = 10
MAX_DOWNLOAD_RETRIES = 50
DEFAULT_SUBTITLE_LANGS = "zh-Hans,zh-CN,zh,ai-zh"
MAX_SUBTITLE_LANGS_LENGTH = 200
#: 语言标签只允许字母、数字、下划线与连字符：顺带挡掉换行、空格、分号等
#: 会被 yt-dlp 当成额外参数的异常字符。
_SUBTITLE_LANG_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


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

    @staticmethod
    def _normalize_retries(value):
        """把重试次数规范到 0~50 的整数；非法值（含负数）回退默认 10。

        0 是合法值（显式关闭重试），由用户自己承担风险；负数、布尔、
        非数字、NaN/inf 与超出上限一律当作配置错误处理。

        负数必须先判再取整：`int(-0.5) == 0`，先取整会把 -0.5 误当成
        "关闭重试"，与本函数的契约相反。
        """
        if isinstance(value, bool):
            return DEFAULT_DOWNLOAD_RETRIES
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return DEFAULT_DOWNLOAD_RETRIES
        if not math.isfinite(numeric) or numeric < 0:
            return DEFAULT_DOWNLOAD_RETRIES
        return min(MAX_DOWNLOAD_RETRIES, int(numeric))

    @staticmethod
    def _normalize_subtitle_langs(value):
        """把字幕语言白名单清洗成逗号分隔串；空值/异常字符回退默认。

        清洗规则：去首尾空白、丢掉空项、每一项必须是合法语言标签。
        任何一项含换行、空格、分号等字符时整串作废回到默认值——宁可少下
        字幕，也不让手工改坏的配置变成额外的 yt-dlp 参数。
        """
        if not isinstance(value, str):
            return DEFAULT_SUBTITLE_LANGS
        text = value.strip()
        if not text or len(text) > MAX_SUBTITLE_LANGS_LENGTH:
            return DEFAULT_SUBTITLE_LANGS
        langs = []
        for raw_lang in text.split(","):
            lang = raw_lang.strip()
            if not lang:
                continue
            if not _SUBTITLE_LANG_PATTERN.fullmatch(lang):
                return DEFAULT_SUBTITLE_LANGS
            langs.append(lang)
        if not langs:
            return DEFAULT_SUBTITLE_LANGS
        return ",".join(langs)

    def refresh_config(self, config):
        """热更新配置快照：只换字典引用，构造期解析的组件路径保持不变。

        reload_config 会重建扫描器的 config，而 Downloader 一直持有旧
        引用；不刷新的话下载重试次数、字幕白名单、词云与空间阈值永远
        读旧值（WebUI 显示"立即生效"却没有效果）。yt-dlp/ffmpeg 路径
        在 __init__ 里已落到实例属性上，仍属于重启生效的字段。
        """
        if isinstance(config, dict):
            self.config = config
            return True
        return False

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

    def _convert_downloaded_danmaku(self, save_dir, file_name):
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
            # 词云是衍生品：失败只提示，不影响下载与 NFO 的成功判定
            self._generate_wordcloud(xml_sub)

    def _generate_wordcloud(self, xml_path):
        """按配置生成弹幕词云。默认关闭，失败不影响主流程。"""
        wordcloud_config = self.config.get("wordcloud", {}) or {}
        if not wordcloud_config.get("enabled", False):
            return False
        try:
            max_terms = int(wordcloud_config.get("max_terms", 60) or 60)
        except (TypeError, ValueError):
            max_terms = 60
        svg_path = os.fspath(xml_path).rsplit('.', 1)[0] + ".wordcloud.svg"
        print(f"[*] 正在生成弹幕词云: {os.path.basename(svg_path)}...")
        try:
            generated = DanmakuWordCloud(max_terms=max_terms).generate(xml_path, svg_path)
        except Exception as exc:
            print(f"[-] 词云生成异常，已跳过: {exc}")
            return False
        if generated:
            print(f"[+成功] 词云生成完成: {os.path.basename(svg_path)}")
        return generated

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

            # 每次下载都从当前配置快照现读：WebUI 保存后无需重启即可生效。
            system_config = self.config.get("system", {}) or {}
            retries = self._normalize_retries(
                system_config.get("download_retries", DEFAULT_DOWNLOAD_RETRIES)
            )
            subtitle_langs = self._normalize_subtitle_langs(
                system_config.get("subtitle_langs", DEFAULT_SUBTITLE_LANGS)
            )

            cmd = [
                yt_dlp_path,
                "-f", "bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--continue",
                "--part",
                # 单个视频失败后不再直接放弃：默认重试 10 次，可用
                # system.download_retries 调整（0 表示不重试）。
                "--retries", str(retries),
                "--fragment-retries", str(retries),
                "--cookies", netscape_cookie,
                "--write-info-json",
                "--write-thumbnail",
                "--convert-thumbnails", "jpg",
                "--write-subs",
                "--write-auto-subs",
                # 只下白名单语言：--sub-langs all 会把上百种机器翻译一起拉下来，
                # 既慢又占空间。默认覆盖 B 站简中人工字幕与 AI 字幕。
                "--sub-langs", subtitle_langs,
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
