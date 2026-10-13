import os
import sys
# 切换工作目录到程序所在目录，避免在其他路径运行脚本时相对路径解析错误。
# PyInstaller 打包后 __file__ 指向 bootloader 临时目录，必须改用 exe 自身路径。
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
else:
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
from app.core.integrity import IntegrityVerifier
from app.core.parser import SyncFetchError
from app.core.path_manager import PathManager
from app.core.runtime_state import RuntimeStateWriter, runtime_state_path
from app.core.commands import (
    COMMAND_REDOWNLOAD_ASSET,
    COMMAND_RESTART,
    COMMAND_TRIGGER_SCAN,
    CommandError,
    CommandNotFound,
    open_channel,
)
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


# 命令通道轮询间隔（秒）。休眠期用分片睡眠，保证 trigger_scan 能及时唤醒。
COMMAND_POLL_INTERVAL = 5.0


class RestartRequested(Exception):
    """由 WebUI 的 restart 命令触发，提示运维层重启进程。"""


async def _dispatch_commands(channel, scanner, runtime, pending_scan=None):
    """消费一轮命令，返回是否请求退出守护循环。

    所有命令都在 try/except 中执行并回执，单条失败不会中断扫描循环。
    """
    if channel is None:
        return False
    try:
        commands = channel.take_pending()
    except Exception as exc:
        print(f"[!] 命令通道读取失败，本轮跳过: {exc}")
        return False

    for command in commands:
        name = command.get("command")
        payload = command.get("payload") or {}
        try:
            if name == COMMAND_TRIGGER_SCAN:
                _update_runtime(
                    runtime,
                    message="已收到 WebUI 触发的即时扫描指令",
                )
                print("[*] 已收到即时扫描指令。")
                channel.complete(command, ok=True, result="已排入当前巡检轮次")
                # 置位事件：若当前正处于休眠分片，则提前唤醒开始下一轮；
                # 若正处于扫描中，本轮结束后的休眠检查会立即消费该事件。
                if pending_scan is not None:
                    pending_scan.set()
                # 必须继续处理本批剩余命令：它们已被 claim，若不回执会永远
                # 停留在 running 状态而无法被审计或重试。
                continue
            if name == COMMAND_REDOWNLOAD_ASSET:
                asset_id = payload.get("asset_id")
                if not asset_id:
                    raise CommandError("redownload_asset 缺少 asset_id")
                keys = scanner.request_redownload(asset_id)
                if not keys:
                    raise CommandError("无效的 asset_id")
                print(f"[*] 已登记重下载请求: {asset_id}（将在下一轮巡检命中）")
                channel.complete(
                    command,
                    ok=True,
                    result=f"已登记 {asset_id}，下轮巡检命中时重下",
                )
                continue
            if name == COMMAND_RESTART:
                # 不在守护进程内自重启，避免半途中断下载；交由运维层处理。
                _update_runtime(
                    runtime,
                    status="restart_requested",
                    message="已收到重启指令，请在完成当前轮次后重启核心进程",
                )
                print("[!] 已收到重启指令：请在当前轮次结束后重启核心进程。")
                channel.complete(command, ok=True, result="已提示运维层重启核心进程")
                return True
            raise CommandError(f"不支持的命令: {name}")
        except CommandError as exc:
            print(f"[-] 命令执行失败: {exc}")
            channel.complete(command, ok=False, result=str(exc))
        except Exception as exc:
            print(f"[-] 命令执行异常: {type(exc).__name__}: {exc}")
            channel.complete(command, ok=False, result=f"{type(exc).__name__}: {exc}"[:200])
    return False


def _loop_time():
    """当前事件循环的单调时钟；抽成函数便于测试注入确定性时钟。"""
    return asyncio.get_event_loop().time()


async def _sleep_until_next_scan(channel, scanner, runtime, scan_interval, pending_scan):
    """分片休眠：期间持续消费命令，trigger_scan 可提前唤醒。

    返回 True 表示被 trigger_scan 唤醒，应立即开始下一轮巡检。
    """
    deadline = _loop_time() + max(0.0, float(scan_interval))
    while True:
        remaining = deadline - _loop_time()
        if remaining <= 0:
            return False
        should_exit = await _dispatch_commands(channel, scanner, runtime, pending_scan)
        if should_exit:
            raise RestartRequested
        if pending_scan.is_set():
            pending_scan.clear()
            print("[*] 提前结束休眠，立即开始下一轮巡检。")
            return True
        await asyncio.sleep(min(COMMAND_POLL_INTERVAL, remaining))


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
    except RestartRequested:
        # restart 命令是"提示运维层重启"而非自杀重启：安全退出循环并
        # 关闭数据库，让 systemd / Docker / supervisor 按自己的策略拉起。
        _update_runtime(
            runtime,
            status="stopped",
            phase="restart_requested",
            message="已响应重启指令，核心引擎安全退出，请由运维层重新拉起",
            next_scan_at=None,
        )
        print("[*] 已响应重启指令，核心引擎安全退出（数据库已关闭）。")
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

    # 命令通道：WebUI 写入 commands.json，守护循环轮询消费。
    try:
        channel = open_channel(config)
    except CommandNotFound as exc:
        print(f"[*] 命令通道不可用，WebUI 将无法下发指令: {exc}")
        channel = None
    pending_scan = asyncio.Event()

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
        # 轮次开始前消费命令：让 redownload_asset 在本轮巡检即命中
        await _dispatch_commands(channel, scanner, runtime, pending_scan)
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

        # 接续处理关注 UP 主投稿
        followings_config = config.get('followings') or {}
        followings_mode = str(followings_config.get('mode', 'off')).strip().lower()
        if followings_config and followings_mode != 'off':
            known_names = {}
            if followings_mode == 'all':
                # 全量同步所有关注 UP 主（首轮拉取量大，受 max_downloads_per_run 保护）
                if not scanner.max_global_downloads or scanner.global_download_count < scanner.max_global_downloads:
                    label = "关注列表"
                    _update_runtime(
                        runtime,
                        phase="source",
                        source=label,
                        current_title=None,
                        current_asset=None,
                        message="正在读取账号关注列表",
                    )
                    try:
                        page = 1
                        while True:
                            follows, has_more = await scanner.parser.get_followings(page=page)
                            for follow in follows:
                                known_names[follow['mid']] = follow['uname']
                            if not has_more:
                                break
                            page += 1
                            await asyncio.sleep(1.5)
                    except SyncFetchError as exc:
                        print(f"[-] 关注列表读取失败，本轮跳过关注源: {exc}")
                    print(f"[*] 共发现 {len(known_names)} 个关注 UP 主")
            elif followings_mode == 'list':
                for entry in followings_config.get('list', []):
                    if isinstance(entry, dict):
                        try:
                            known_names[int(entry.get('mid'))] = str(
                                entry.get('name') or f"UP_{int(entry.get('mid'))}"
                            )
                        except (TypeError, ValueError):
                            print(f"[-] 关注源列表条目缺少有效 mid，跳过: {entry}")
                    else:
                        try:
                            known_names[int(entry)] = f"UP_{int(entry)}"
                        except (TypeError, ValueError):
                            print(f"[-] 关注源列表条目不是有效 UID，跳过: {entry}")
            else:
                print(f"[-] followings.mode 配置无效（应为 off/all/list）: {followings_mode}")

            for follow_mid, follow_name in known_names.items():
                if scanner.max_global_downloads and scanner.global_download_count >= scanner.max_global_downloads:
                    break
                label = f"关注 {follow_name} ({follow_mid})"
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
                    lambda follow_mid=follow_mid, follow_name=follow_name: scanner.scan_following(
                        follow_mid,
                        follow_name,
                    ),
                )
                if not completed:
                    incomplete_sources.append(label)

        # 接续同步观看历史（仅记元数据，不下载视频本体——用户已拍板）
        if config.get('system', {}).get('sync_watch_history', False):
            if not scanner.max_global_downloads or scanner.global_download_count < scanner.max_global_downloads:
                label = "观看历史"
                _update_runtime(
                    runtime,
                    phase="source",
                    source=label,
                    current_title=None,
                    current_asset=None,
                    message="正在同步观看历史元数据",
                )
                completed = await _run_source_scan(
                    label,
                    lambda: scanner.sync_watch_history(),
                )
                if not completed:
                    incomplete_sources.append(label)

        # 完整性巡检：抽样校验已完成资产，抓"存在但损坏"的静默失败
        verifier = IntegrityVerifier(config)
        if verifier.enabled and (
            not scanner.max_global_downloads
            or scanner.global_download_count < scanner.max_global_downloads
        ):
            label = "完整性巡检"
            _update_runtime(
                runtime,
                phase="source",
                source=label,
                current_title=None,
                current_asset=None,
                message=f"正在抽样校验资产完整性（{verifier.mode}）",
            )
            await _run_source_scan(
                label,
                lambda: scanner.verify_integrity(verifier),
            )

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
        # 分片休眠：期间持续轮询命令，trigger_scan 可提前唤醒
        await _sleep_until_next_scan(
            channel,
            scanner,
            runtime,
            scan_interval,
            pending_scan,
        )

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
