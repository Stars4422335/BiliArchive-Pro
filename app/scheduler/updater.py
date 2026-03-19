import os
import platform
import stat
import httpx
import shutil
import subprocess

class ComponentUpdater:
    def __init__(self, config):
        self.config = config
        self.proxy = config.get("network", {}).get("github_proxy_url", "")
        self.bin_path = os.path.abspath("./bin")
        os.makedirs(self.bin_path, exist_ok=True)

    def get_local_ytdlp_version(self, path):
        if not os.path.exists(path):
            return None
        try:
            result = subprocess.run([path, "--version"], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except:
            return None

    async def get_latest_ytdlp_version(self):
        url = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("tag_name", "")
        except Exception as e:
            print(f"[-] 获取 yt-dlp 最新版本失败: {e}")
        return None

    async def _download_file(self, url, save_name, force=False):
        """通用下载逻辑"""
        save_path = os.path.join(self.bin_path, save_name)
        
        # 存在性检查：如果不是强制下载且文件已存在，则跳过
        if not force and os.path.exists(save_path):
            print(f"[#] 组件已存在，跳过下载: {save_name}")
            return True

        download_url = f"{self.proxy}{url}" if self.proxy else url
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
                print(f"[+] 正在从源下载: {download_url}")
                resp = await client.get(download_url)
                if resp.status_code == 200:
                    # 先写到临时文件，再替换，防止写一半出错
                    temp_path = save_path + ".tmp"
                    with open(temp_path, "wb") as f:
                        f.write(resp.content)
                    
                    if os.path.exists(save_path):
                        os.remove(save_path)
                    os.rename(temp_path, save_path)
                    
                    # 赋予执行权限
                    if platform.system() != "Windows":
                        os.chmod(save_path, os.stat(save_path).st_mode | stat.S_IEXEC)
                    print(f"[+成功] 已就绪: {save_name}")
                    return True
                else:
                    print(f"[-] 下载失败 ({resp.status_code}): {save_name}")
                    return False
        except Exception as e:
            print(f"[-] 更新 {save_name} 时发生错误: {e}")
            return False

    async def update_yt_dlp(self):
        suffix = ".exe" if platform.system() == "Windows" else ""
        target = f"yt-dlp{suffix}"
        target_path = os.path.join(self.bin_path, target)
        
        local_ver = self.get_local_ytdlp_version(target_path)
        print(f"[*] 本地 yt-dlp 版本: {local_ver or '未安装'}")
        
        latest_ver = await self.get_latest_ytdlp_version()
        if latest_ver:
            print(f"[*] 远程 yt-dlp 最新版本: {latest_ver}")
            # 版本比较（简单相等性判断）
            if local_ver == latest_ver:
                print("[#] yt-dlp 已是最新版本，无需更新。")
                return True
            else:
                print("[!] 发现 yt-dlp 新版本，准备更新...")
        else:
            print("[-] 无法获取远程版本，将尝试基于存在性进行下载...")
            if local_ver:
                return True # 本地有，远程获取失败，先用本地的
        
        url = f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{target}"
        return await self._download_file(url, target, force=True)

    async def update_ffmpeg(self):
        """
        FFmpeg 检查逻辑
        """
        print("[*] 正在检查 ffmpeg 环境...")
        if shutil.which("ffmpeg"):
            print("[#] 系统已安装 ffmpeg，环境变量可用。")
            return True
        
        local_ffmpeg = os.path.join(self.bin_path, "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
        if os.path.exists(local_ffmpeg):
            print("[#] 本地 bin 目录已存在 ffmpeg。")
            return True
            
        print("[!] 未发现 ffmpeg，请确保系统已安装 ffmpeg 或将其放置在 bin/ 目录下，否则无法合并高清视频。")
        print("[!] Ubuntu/Debian: sudo apt install ffmpeg")
        print("[!] Windows/Mac: 下载后将可执行文件放至 BiliArchive-Pro/bin/ 目录")
        return False

    async def check_all(self):
        """一键初始化环境"""
        print("=== 正在同步运行环境 ===")
        # 1. 确保 yt-dlp 存在并更新
        await self.update_yt_dlp()
        # 2. 检查 ffmpeg
        await self.update_ffmpeg()
        print("=== 环境检查完成 ===\n")