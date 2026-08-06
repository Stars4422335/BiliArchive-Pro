import hashlib
import hmac
import os
import platform
import re
import shutil
import subprocess

import httpx

from app.core.secure_file import atomic_write_bytes


class ComponentUpdater:
    VALID_STRATEGIES = {"auto", "notify", "off"}

    def __init__(self, config):
        self.config = config
        self.proxy = config.get("network", {}).get("github_proxy_url", "")
        self.bin_path = os.path.abspath("./bin")
        os.makedirs(self.bin_path, exist_ok=True)

    def _get_strategy(self, component_name):
        strategy = str(
            self.config.get("components", {}).get(component_name, {}).get("strategy", "notify")
        ).lower()
        if strategy not in self.VALID_STRATEGIES:
            print(f"[!] {component_name} 更新策略无效，已按 off 处理: {strategy}")
            return "off"
        return strategy

    def _get_component_path(self, component_name, default_name):
        configured_path = self.config.get("components", {}).get(component_name, {}).get("path")
        path = configured_path or os.path.join(self.bin_path, default_name)
        if platform.system() == "Windows" and not path.lower().endswith(".exe"):
            path += ".exe"
        return os.path.abspath(path)

    def get_local_ytdlp_version(self, path):
        if not path or not os.path.exists(path):
            return None
        try:
            result = subprocess.run([path, "--version"], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    async def get_latest_ytdlp_version(self):
        url = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json().get("tag_name", "")
                print(f"[-] 获取 yt-dlp 最新版本失败，HTTP 状态码: {resp.status_code}")
        except Exception as e:
            print(f"[-] 获取 yt-dlp 最新版本失败: {e}")
        return None

    @staticmethod
    def _extract_checksum(checksum_text, target_name):
        for raw_line in checksum_text.splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", raw_line.strip())
            if match and match.group(2) == target_name:
                return match.group(1).lower()
        return None

    async def get_official_ytdlp_checksum(self, target_name):
        """Fetch checksums directly from GitHub so a download proxy cannot replace both files."""
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    print(f"[-] 获取 yt-dlp 官方校验值失败，HTTP 状态码: {resp.status_code}")
                    return None
                checksum = self._extract_checksum(resp.text, target_name)
                if not checksum:
                    print(f"[-] 官方校验文件中未找到目标组件: {target_name}")
                return checksum
        except Exception as e:
            print(f"[-] 获取 yt-dlp 官方校验值失败: {e}")
            return None

    async def _download_file(self, url, save_path, expected_sha256, force=False):
        if not force and os.path.exists(save_path):
            print(f"[#] 组件已存在，跳过下载: {os.path.basename(save_path)}")
            return True
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256 or ""):
            print("[-] 缺少有效的官方 SHA256，已拒绝下载可执行文件。")
            return False

        download_url = f"{self.proxy}{url}" if self.proxy else url
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
                print(f"[+] 正在下载组件: {download_url}")
                resp = await client.get(download_url)
                if resp.status_code != 200:
                    print(f"[-] 下载失败 ({resp.status_code}): {os.path.basename(save_path)}")
                    return False

                actual_sha256 = hashlib.sha256(resp.content).hexdigest()
                if not hmac.compare_digest(actual_sha256, expected_sha256.lower()):
                    print(f"[-] SHA256 校验失败，已拒绝替换: {os.path.basename(save_path)}")
                    return False

                atomic_write_bytes(save_path, resp.content, mode=0o700)
                print(f"[+成功] 已校验并更新: {os.path.basename(save_path)}")
                return True
        except Exception as e:
            print(f"[-] 更新 {os.path.basename(save_path)} 时发生错误: {e}")
            return False

    async def update_yt_dlp(self):
        strategy = self._get_strategy("yt-dlp")
        if strategy == "off":
            print("[#] yt-dlp 检查已关闭。")
            return True

        target_name = "yt-dlp.exe" if platform.system() == "Windows" else "yt-dlp"
        target_path = self._get_component_path("yt-dlp", target_name)
        runtime_path = target_path if os.path.exists(target_path) else shutil.which("yt-dlp")
        local_ver = self.get_local_ytdlp_version(runtime_path)
        print(f"[*] 本地 yt-dlp 版本: {local_ver or '未安装'}")

        latest_ver = await self.get_latest_ytdlp_version()
        if latest_ver:
            print(f"[*] 远程 yt-dlp 最新版本: {latest_ver}")

        if strategy == "notify":
            if not local_ver:
                print("[!] 未发现 yt-dlp，请运行 pip install -r requirements.txt 或手动安装。")
                return False
            if latest_ver and local_ver != latest_ver:
                print("[!] 发现 yt-dlp 新版本；当前策略为 notify，未自动更新。")
            return True

        if local_ver and latest_ver and local_ver == latest_ver:
            print("[#] yt-dlp 已是最新版本，无需更新。")
            return True

        checksum = await self.get_official_ytdlp_checksum(target_name)
        if not checksum:
            print("[-] 无法验证 yt-dlp 完整性，已取消自动更新。")
            return bool(local_ver)

        url = f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{target_name}"
        updated = await self._download_file(url, target_path, checksum, force=True)
        if not updated and local_ver:
            print("[!] 更新失败，继续保留现有 yt-dlp。")
            return True
        return updated

    async def update_ffmpeg(self):
        strategy = self._get_strategy("ffmpeg")
        if strategy == "off":
            print("[#] ffmpeg 检查已关闭。")
            return True

        print("[*] 正在检查 ffmpeg 环境...")
        if shutil.which("ffmpeg"):
            print("[#] 系统已安装 ffmpeg，环境变量可用。")
            return True

        local_ffmpeg = self._get_component_path("ffmpeg", "ffmpeg")
        if os.path.exists(local_ffmpeg):
            print("[#] 已发现配置的 ffmpeg。")
            return True

        print("[!] 未发现 ffmpeg，请确保系统已安装 ffmpeg 或将其放置在配置路径中，否则无法合并高清视频。")
        print("[!] Ubuntu/Debian: sudo apt install ffmpeg")
        print("[!] Windows/Mac: 下载稳定版并配置 components.ffmpeg.path")
        return False

    async def check_all(self):
        """Apply configured component check/update strategies."""
        print("=== 正在检查运行环境 ===")
        await self.update_yt_dlp()
        await self.update_ffmpeg()
        print("=== 环境检查完成 ===\n")
