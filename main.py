import os
import json
import yaml
import asyncio
import argparse
from bilibili_api import clients, register_client, Credential, user

# 关键：注册 httpx 客户端
register_client(clients.HTTPXClient())

from app.core.database_manager import DatabaseManager
from app.core.path_manager import PathManager
from app.scheduler.scanner import FavScanner

def load_config():
    """读取用户配置"""
    if not os.path.exists("config.yaml"):
        print("[-] 找不到 config.yaml！请确保在项目根目录执行。")
        exit(1)
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

import json

async def check_cookie(cookie_path):
    """验证登录凭证健康度"""
    if not os.path.exists(cookie_path):
        print("[-] 尚未登录！(未发现 cookie.json)")
        print("[!] 请先运行 python login.py 扫码生成凭据！")
        return None
        
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
    
    # 测试凭证是否有效
    try:
        my_info = await user.get_self_info(cred)
        print(f"[+] 登录验证成功！当前账号: {my_info['name']}")
        return cred
    except Exception as e:
        print(f"[-] 凭证失效或验证报错: {e}")
        print("[!] 建议重新运行 python login.py 扫码登录。")
        return cred # 即使失败也返回，部分公开视频仍可强行下载

async def daemon_loop(config, cred):
    """主循环守护进程"""
    print("\n=== 🚀 BiliArchive-Pro 核心引擎启动 ===")
    
    # 初始化核心组件
    db = DatabaseManager(config['system']['db_path'])
    path_mgr = PathManager(config['system']['download_path'], config['system']['plex_mode'])
    scanner = FavScanner(config, cred, db, path_mgr)

    # 临时写死一个公开测试的收藏夹ID进行演示 (后续可在 WebUI 中配置)
    target_favs = [
        {"id": 81102601, "name": "公开测试收藏夹"} # 你可以把 81102601 换成你自己的公开收藏夹ID
    ]

    while True:
        for fav in target_favs:
            await scanner.scan_favorite(fav['id'], fav['name'])

        print("\n[*] 本轮全量扫描完毕，进入休眠阶段 (避免被封IP)...")
        await asyncio.sleep(3600) # 休眠1小时后再次扫描

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BiliArchive-Pro 启动器")
    parser.add_argument("--cli", action="store_true", help="强制以纯命令行无界面模式运行")
    args = parser.parse_args()

    config = load_config()

    if args.cli:
        print("[*] 正在以 CLI 守护进程模式运行...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cred = loop.run_until_complete(check_cookie(config['system']['cookie_path']))
        
        try:
            loop.run_until_complete(daemon_loop(config, cred))
        except KeyboardInterrupt:
            print("\n[+] 接收到 Ctrl+C，正在安全关闭数据库与下载任务...")
            exit(0)
    else:
        print("[!] 请加上 --cli 参数运行： python main.py --cli")
        print("[!] 桌面 GUI 托盘模式正在开发中。")
