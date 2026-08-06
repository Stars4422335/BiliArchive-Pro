import os
# 切换工作目录到项目根目录，避免在其他路径运行脚本时相对路径解析错误
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import json
import yaml
import asyncio
import argparse
from bilibili_api import register_client, Credential, user
from bilibili_api.clients.HTTPXClient import HTTPXClient
from app import __version__

# 关键：注册 httpx 客户端
register_client("httpx", HTTPXClient, {})

from app.core.database_manager import DatabaseManager
from app.core.path_manager import PathManager
from app.scheduler.scanner import FavScanner
from app.scheduler.updater import ComponentUpdater

def _load_yaml_mapping(path):
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    if not isinstance(config, dict):
        raise ValueError(f"配置文件顶层必须是映射结构: {path}")
    return config


def _merge_config(base, overrides):
    """递归合并配置；字典递归处理，列表和标量由本地配置覆盖。"""
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_config(base[key], value)
        else:
            base[key] = value
    return base


def load_config():
    """读取默认配置，并应用不受 Git 管理的本地覆盖配置。"""
    if not os.path.exists("config.yaml"):
        print("[-] 找不到 config.yaml！请确保在项目根目录执行。")
        raise SystemExit(1)

    config = _load_yaml_mapping("config.yaml")
    local_config_path = "config.local.yaml"
    if os.path.exists(local_config_path):
        local_config = _load_yaml_mapping(local_config_path)
        _merge_config(config, local_config)
        print(f"[*] 已加载本地配置覆盖: {local_config_path}")

    return config

async def check_cookie(cookie_path):
    """验证登录凭证健康度"""
    if not os.path.exists(cookie_path):
        print("[-] 尚未登录！(未发现 cookie.json)")
        print("[!] 请先运行 python login.py 扫码生成凭据！")
        return None, None
        
    # 读取真实的 JSON 数据
    with open(cookie_path, "r", encoding="utf-8") as f:
        cookie_data = json.load(f)
        
    # 注入到 Credential 对象中
    cred = Credential(
        sessdata=cookie_data.get("sessdata"),
        bili_jct=cookie_data.get("bili_jct"),
        buvid3=cookie_data.get("buvid3"),
        dedeuserid=cookie_data.get("dedeuserid"),
        ac_time_value=cookie_data.get("ac_time_value", "")
    )
    
    # 从 cookie 中提取 uid
    uid = int(cookie_data.get("dedeuserid", 0))
    
    # 测试凭证是否有效
    try:
        my_info = await user.get_self_info(cred)
        print(f"[+] 登录验证成功！当前账号: {my_info['name']}")
        return cred, uid
    except Exception as e:
        print(f"[-] 凭证失效或验证报错: {e}")
        print("[!] 建议重新运行 python login.py 扫码登录。")
        return cred, uid # 即使失败也返回，部分公开视频仍可强行下载

async def daemon_loop(config, cred, uid):
    """主循环守护进程"""
    print(f"\n=== 🚀 BiliArchive-Pro v{__version__} 核心引擎启动 ===")
    
    if config.get('system', {}).get('check_update_on_start', False):
        await ComponentUpdater(config).check_all()

    # 初始化核心组件
    db = DatabaseManager(config['system']['db_path'])
    path_mgr = PathManager(config['system']['download_path'], config['system']['plex_mode'])
    scanner = FavScanner(config, cred, db, path_mgr, uid=uid)

    # 从配置文件读取收藏夹列表
    target_favs = config.get('favorites', [])
    
    # 如果配置文件中没有收藏夹，尝试自动获取
    if not target_favs:
        print("[*] 配置文件中未指定收藏夹，正在自动获取您的收藏夹列表...")
        target_favs = await scanner.parser.get_user_favorite_lists()
        
        if not target_favs:
            print("[-] 错误：无法获取收藏夹列表！")
            print("[!] 可能原因：")
            print("    1. 登录凭证已过期")
            print("    2. 账号没有创建收藏夹")
            print("[!] 建议：")
            print("    1. 重新运行 python login.py 登录")
            print("    2. 或在 config.yaml 中手动添加 favorites 配置")
            return
        
        print(f"[*] 发现 {len(target_favs)} 个收藏夹，将自动备份所有收藏夹")
        # 询问用户是否继续
        try:
            confirm = input("\n是否备份所有收藏夹? (Y/n): ").strip().lower()
            if confirm == 'n':
                print("[!] 已取消，请在 config.yaml 中手动指定要备份的收藏夹")
                return
        except EOFError:
            # 非交互式环境，自动继续
            print("[*] 非交互式环境，自动备份所有收藏夹...")
    else:
        print(f"[*] 使用配置文件中指定的 {len(target_favs)} 个收藏夹")

    while True:
        for fav in target_favs:
            await scanner.scan_favorite(fav['id'], fav['name'])
            # 若达到全局限制，提前跳出收藏夹遍历
            if scanner.max_global_downloads and scanner.global_download_count >= scanner.max_global_downloads:
                break

        # 接续处理稍后再看
        if config.get('system', {}).get('sync_watch_later', False):
            if not scanner.max_global_downloads or scanner.global_download_count < scanner.max_global_downloads:
                await scanner.scan_watch_later()

        # 接续处理稍后再看
        sync_collections = config.get('sync_collections', [])
        if sync_collections:
            for coll in sync_collections:
                if not scanner.max_global_downloads or scanner.global_download_count < scanner.max_global_downloads:
                    await scanner.scan_collection(coll['id'], coll.get('name', f"合集_{coll['id']}"))

        # 如果达到了 limit，则直接退出整个程序
        if scanner.max_global_downloads and scanner.global_download_count >= scanner.max_global_downloads:
            print("\n[+] 达到指定下载数量，任务完毕，安全退出。")
            break

        scan_interval = config.get('system', {}).get('scan_interval_seconds', 21600)
        print(f"\n[*] 本轮全量扫描完毕，进入休眠阶段 ({scan_interval} 秒后再次扫描)...")
        await asyncio.sleep(scan_interval)

if __name__ == "__main__":
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

    if args.cli:
        print("[*] 正在以 CLI 守护进程模式运行...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cred, uid = loop.run_until_complete(check_cookie(config['system']['cookie_path']))
        
        if not cred:
            exit(1)
        
        try:
            loop.run_until_complete(daemon_loop(config, cred, uid))
        except KeyboardInterrupt:
            print("\n[+] 接收到 Ctrl+C，正在安全关闭数据库与下载任务...")
            exit(0)
    else:
        print("[!] 请加上 --cli 参数运行： python main.py --cli")
        print("[!] 桌面 GUI 托盘模式正在开发中。")
