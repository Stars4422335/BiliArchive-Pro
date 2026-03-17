import os
import platform
import stat
import httpx
import shutil

class ComponentUpdater:
    def __init__(self, config):
        self.config = config
        self.proxy = config.get("network", {}).get("github_proxy_url", "")
        self.bin_path = os.path.abspath("./bin")
        os.makedirs(self.bin_path, exist_ok=True)

    async def _download_file(self, url, save_name):
        """通用下载逻辑"""
        save_path = os.path.join(self.bin_path, save_name)
        
        # 存在性检查：如果文件已经存在，跳过下载（除非以后增加强制更新逻辑）
        if os.path.exists(save_path):
            print(f"[#] 组件已存在，跳过下载: {save_name}")
            return True

        download_url = f"{self.proxy}{url}"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
                print(f"[+] 正在从源下载: {download_url}")
                resp = await client.get(download_url)
                if resp.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(resp.content)
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
        url = f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{target}"
        return await self._download_file(url, target)

    async def update_ffmpeg(self):
        """
        FFmpeg 下载逻辑（这里以常用架构为例，FFmpeg 较大，通常建议用户手动安装，
        但为了自动化，我们可以提供一个基础版本的自动下载路径）
        """
        system = platform.system()
        # 注意：FFmpeg 的官方发布通常是压缩包，自动解压逻辑较复杂
        # 这里演示针对不同系统的下载建议
        print("[*] 正在检查 ffmpeg 环境...")
        if shutil.which("ffmpeg"):
            print("[#] 系统已安装 ffmpeg，无需下载。")
            return True
        
        # 提示：由于 ffmpeg 跨平台构建较多，建议在 README 中说明让用户手动安装或由程序引导
        print("[!] 未发现 ffmpeg，请确保系统已安装 ffmpeg，否则无法合并高清视频。")
        return False

    async def check_all(self):
        """一键初始化环境"""
        print("=== 正在同步运行环境 ===")
        # 1. 确保 yt-dlp 存在
        await self.update_yt_dlp()
        # 2. 检查 ffmpeg
        await self.update_ffmpeg()
        print("=== 环境检查完成 ===\n")