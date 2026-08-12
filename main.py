import os
# 切换工作目录到项目根目录，避免在其他路径运行脚本时相对路径解析错误
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import json
import asyncio
import argparse
from bilibili_api import register_client, request_settings, Credential, user
from bilibili_api.clients.HTTPXClient import HTTPXClient
from app import __version__

# 关键：注册 httpx 客户端
register_client("httpx", HTTPXClient, {})

from app.core.database_manager import DatabaseManager
from app.core.config_manager import (
    get_local_config_path,
    load_config as _load_config,
    load_yaml_mapping as _load_yaml_mapping,
    merge_config as _merge_config,
)
from app.core.parser import SyncFetchError
from app.core.path_manager import PathManager
from app.core.runtime_state import RuntimeStateWriter, runtime_state_path
from app.scheduler.scanner import FavScanner
from app.scheduler.updater import ComponentUpdater

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


def _update_runtime(runtime, **changes):
    if runtime is not None:
        runtime.update(**changes)

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


async def _run_source_scan(label, operation):
    """隔离单个同步来源的读取失败，避免阻断后续来源。"""
    try:
        await operation()
        return True
    except SyncFetchError as exc:
        print(f"[-] 同步来源读取失败，已中止当前来源: {label}: {exc}")
        return False

async def daemon_loop(config, cred, uid):
    """主循环守护进程"""
    print(f"\n=== 🚀 BiliArchive-Pro v{__version__} 核心引擎启动 ===")

    state_path = runtime_state_path(config)
    runtime = RuntimeStateWriter(state_path) if state_path else None

    request_timeout = min(
        300.0,
        max(
            1.0,
            float(config.get("network", {}).get("request_timeout_seconds", 30)),
        ),
    )
    request_settings.set_timeout(request_timeout)
    
    db = None
    try:
        if config.get('system', {}).get('check_update_on_start', False):
            _update_runtime(
                runtime,
                status="starting",
                phase="component_check",
                message="正在检查下载组件",
            )
            await ComponentUpdater(config).check_all()

        db = DatabaseManager(config['system']['db_path'])
        await _run_scan_loop(config, cred, uid, db, runtime=runtime)
    except asyncio.CancelledError:
        _update_runtime(
            runtime,
            status="stopped",
            phase="cancelled",
            message="核心引擎已安全停止",
            next_scan_at=None,
        )
        raise
    except Exception as exc:
        _update_runtime(
            runtime,
            status="error",
            phase="failed",
            message=f"{type(exc).__name__}: {exc}"[:300],
            next_scan_at=None,
        )
        raise
    else:
        _update_runtime(
            runtime,
            status="stopped",
            phase="complete",
            message="本次运行已完成",
            next_scan_at=None,
        )
    finally:
        if db is not None:
            db.close()


async def _run_scan_loop(config, cred, uid, db, runtime=None):
    path_mgr = PathManager(config['system']['download_path'], config['system']['plex_mode'])
    scanner = FavScanner(config, cred, db, path_mgr, uid=uid)
    if runtime is not None and hasattr(scanner, "set_progress_callback"):
        scanner.set_progress_callback(runtime.update)

    # 从配置文件读取收藏夹列表
    target_favs = config.get('favorites', [])
    
    # 如果配置文件中没有收藏夹，尝试自动获取
    if not target_favs:
        _update_runtime(
            runtime,
            status="scanning",
            phase="favorite_discovery",
            message="正在读取账号收藏夹列表",
            next_scan_at=None,
        )
        print("[*] 配置文件中未指定收藏夹，正在自动获取您的收藏夹列表...")
        try:
            target_favs = await scanner.parser.get_user_favorite_lists()
        except SyncFetchError as exc:
            print(f"[-] 自动获取收藏夹列表失败: {exc}")
            print("[!] 本次未将读取失败当作空收藏夹，请稍后重试。")
            return
        
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
        _update_runtime(
            runtime,
            status="scanning",
            phase="cycle",
            source=None,
            current_title=None,
            current_asset=None,
            downloaded_count=scanner.global_download_count,
            message="正在执行全量巡检",
            next_scan_at=None,
        )
        incomplete_sources = []
        for fav in target_favs:
            label = f"收藏夹 {fav['name']} ({fav['id']})"
            _update_runtime(
                runtime,
                phase="source",
                source=label,
                current_title=None,
                current_asset=None,
                message=f"正在扫描{label}",
            )
            completed = await _run_source_scan(
                label,
                lambda fav=fav: scanner.scan_favorite(fav['id'], fav['name']),
            )
            if not completed:
                incomplete_sources.append(label)
            # 若达到全局限制，提前跳出收藏夹遍历
            if scanner.max_global_downloads and scanner.global_download_count >= scanner.max_global_downloads:
                break

        # 接续处理稍后再看
        if config.get('system', {}).get('sync_watch_later', False):
            if not scanner.max_global_downloads or scanner.global_download_count < scanner.max_global_downloads:
                label = "稍后再看"
                _update_runtime(
                    runtime,
                    phase="source",
                    source=label,
                    current_title=None,
                    current_asset=None,
                    message="正在扫描稍后再看",
                )
                completed = await _run_source_scan(label, scanner.scan_watch_later)
                if not completed:
                    incomplete_sources.append(label)

        # 接续处理合集
        sync_collections = config.get('sync_collections', [])
        if sync_collections:
            for coll in sync_collections:
                if scanner.max_global_downloads and scanner.global_download_count >= scanner.max_global_downloads:
                    break
                if not isinstance(coll, dict):
                    label = "无效合集配置"
                    print("[-] 合集配置必须是包含 id、mid 和 name 的映射。")
                    incomplete_sources.append(label)
                    continue

                try:
                    collection_id = int(coll.get('id'))
                    collection_mid = int(coll.get('mid'))
                    if collection_id <= 0 or collection_mid <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    label = f"合集 {coll.get('name', '未命名')}"
                    print(
                        f"[-] {label} 缺少有效的 id 或 mid；"
                        "mid 必须是合集所属 UP 主的 UID。"
                    )
                    incomplete_sources.append(label)
                    continue

                collection_name = coll.get('name') or f"合集_{collection_id}"
                label = f"合集 {collection_name} ({collection_id})"
                _update_runtime(
                    runtime,
                    phase="source",
                    source=label,
                    current_title=None,
                    current_asset=None,
                    message=f"正在扫描{label}",
                )
                completed = await _run_source_scan(
                    label,
                    lambda collection_id=collection_id,
                    collection_mid=collection_mid,
                    collection_name=collection_name: scanner.scan_collection(
                        collection_id,
                        collection_name,
                        collection_mid,
                    ),
                )
                if not completed:
                    incomplete_sources.append(label)

        # 如果达到了 limit，则直接退出整个程序
        if scanner.max_global_downloads and scanner.global_download_count >= scanner.max_global_downloads:
            print("\n[+] 达到指定下载数量，任务完毕，安全退出。")
            break

        scan_interval = config.get('system', {}).get('scan_interval_seconds', 21600)
        if incomplete_sources:
            failed_labels = "、".join(incomplete_sources)
            runtime_message = f"本轮扫描不完整：{failed_labels}"
            print(
                f"\n[!] 本轮扫描不完整，失败来源: {failed_labels}。"
                f"{scan_interval} 秒后重试。"
            )
        else:
            runtime_message = "本轮全量扫描完成，等待下一轮"
            print(
                f"\n[*] 本轮全量扫描完毕，进入休眠阶段 "
                f"({scan_interval} 秒后再次扫描)..."
            )
        if runtime is not None:
            runtime.schedule_next_scan(
                scan_interval,
                status="idle",
                phase="sleeping",
                source=None,
                current_title=None,
                current_asset=None,
                downloaded_count=scanner.global_download_count,
                message=runtime_message,
            )
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
        daemon_task = None
        try:
            cred, uid = loop.run_until_complete(
                check_cookie(config['system']['cookie_path'])
            )
            if not cred:
                raise SystemExit(1)

            daemon_task = loop.create_task(daemon_loop(config, cred, uid))
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
    else:
        print("[!] 请加上 --cli 参数运行： python main.py --cli")
        print("[!] 桌面 GUI 托盘模式正在开发中。")
