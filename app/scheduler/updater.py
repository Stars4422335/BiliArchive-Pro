import os
import platform
import stat
import httpx

class ComponentUpdater:
    def __init__(self, config):
        self.config = config
        self.proxy = config.get("network", {}).get("github_proxy_url", "")
        self.bin_path = "./bin"
        os.makedirs(self.bin_path, exist_ok=True)

    async def update_yt_dlp(self):
        """自动检测并下载最新的 yt-dlp，支持加速代理"""
        print("[*] 正在检查 yt-dlp 组件...")
        # 确定系统对应的文件名
        suffix = ".exe" if platform.system() == "Windows" else ""
        target_file = f"yt-dlp{suffix}"
        save_path = os.path.join(self.bin_path, target_file)

        # 拼接 GitHub 原始地址
        base_url = f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{target_file}"
        # 注入你在 config.yaml 里配置的加速前缀
        download_url = f"{self.proxy}{base_url}"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
                print(f"[+] 正在通过代理下载: {download_url}")
                resp = await client.get(download_url)
                if resp.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(resp.content)
                    
                    # 给 Linux/WSL 环境赋予执行权限
                    if platform.system() != "Windows":
                        os.chmod(save_path, os.stat(save_path).st_mode | stat.S_IEXEC)
                    print(f"[+成功] yt-dlp 已就绪: {save_path}")
                else:
                    print(f"[-] 下载失败，HTTP 状态码: {resp.status_code}")
        except Exception as e:
            print(f"[-] 更新组件时发生错误: {e}")