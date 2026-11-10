"""BiliArchive-Pro 的命令行入口。

这里只做三件事：解析参数、读取配置、装配并启动核心引擎。

真正的守护循环在 `app/scheduler/daemon.py`，凭据校验在 `app/core/auth.py`，
命令通道的消费在 `app/core/commands.py`，扫描管线在
`app/scheduler/scanner.py` 与它的各个来源 mixin。
"""

import argparse
import asyncio
import os
import sys

# 切换工作目录到程序所在目录，避免在其他路径运行脚本时相对路径解析错误。
# PyInstaller 打包后 __file__ 指向 bootloader 临时目录，必须改用 exe 自身路径。
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

from bilibili_api import register_client, request_settings, user  # noqa: F401
from bilibili_api.clients.HTTPXClient import HTTPXClient

from app import __version__
from app.core.auth import check_cookie, is_auth_failure as _is_auth_failure  # noqa: F401
from app.core.commands import dispatch_commands as _dispatch_commands  # noqa: F401
from app.core.config_manager import (
    get_local_config_path,
    load_config as _load_config,
)
from app.scheduler.daemon import _mark_core_stopped, daemon_loop
from app.scheduler.scanner import FavScanner  # noqa: F401

# 关键：注册 httpx 客户端
register_client("httpx", HTTPXClient, {})


def load_config():
    """读取默认配置，并应用不受 Git 管理的本地覆盖配置。"""
    if not os.path.exists("config.yaml"):
        print("[-] 找不到 config.yaml！请确保在项目根目录执行。")
        raise SystemExit(1)

    local_config_path = get_local_config_path("config.yaml")
    config = _load_config("config.yaml", local_config_path)
    if os.path.exists(local_config_path):
        print(f"[*] 已加载本地配置覆盖: {local_config_path}")

    return config


def main():
    parser = argparse.ArgumentParser(description="BiliArchive-Pro 启动器")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--cli", action="store_true", help="强制以纯命令行无界面模式运行")
    parser.add_argument("--limit", type=int, help="本次运行最大下载数量，覆盖 config.yaml 的设置", default=None)
    args = parser.parse_args()

    config = load_config()

    # 覆盖配置中的最大下载数
    if args.limit is not None:
        if 'system' not in config:
            config['system'] = {}
        config['system']['max_downloads_per_run'] = args.limit

    if not args.cli:
        print("[!] 请加上 --cli 参数运行： python main.py --cli")
        print("[!] 桌面 GUI 托盘模式正在开发中。")
        return

    print("[*] 正在以 CLI 守护进程模式运行...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    daemon_task = None
    try:
        cred, uid = loop.run_until_complete(
            check_cookie(config['system']['cookie_path'])
        )
        if not cred:
            # check_cookie 已经打印了具体原因（未登录 / 凭据失效），
            # 这里只补一句退出说明，避免用户以为是程序崩溃。
            print("[!] 核心引擎未启动：请先完成登录后重试。")
            _mark_core_stopped(config, "核心引擎未启动：登录凭据不可用")
            raise SystemExit(1)

        daemon_task = loop.create_task(daemon_loop(config, cred, uid, config_path="config.yaml"))
        loop.run_until_complete(daemon_task)
    except KeyboardInterrupt:
        print("\n[+] 接收到 Ctrl+C，正在安全关闭数据库与下载任务...")
        if daemon_task is not None and not daemon_task.done():
            daemon_task.cancel()
            try:
                loop.run_until_complete(daemon_task)
            except asyncio.CancelledError:
                pass
    finally:
        loop.close()
        # bilibili_api 的 atexit 清理写反了分支：它在 loop 已关闭时反而
        # 调用 run_until_complete，导致每次正常退出都抛
        # "Event loop is closed" 并刷出一段看不懂的 traceback。
        # 置空当前事件循环后，它的 except RuntimeError 分支会安静返回。
        # 只影响本进程内的清理时机，不改变任何业务行为。
        asyncio.set_event_loop(None)


if __name__ == "__main__":
    main()
