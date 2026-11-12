"""The scanner facade.

Every source pipeline lives in its own mixin under `app/scheduler/sources/`;
this module keeps the constructor, the progress callback and the public
`FavScanner` name that the CLI, the WebUI and the tests all import.
"""

# Re-exported on purpose: the test suite monkeypatches these through the
# `app.scheduler.scanner.*` path, and both `asyncio.sleep` and the
# `MetadataGenerator` methods are attributes of shared objects, so patching
# them here reaches every mixin unchanged.
import asyncio  # noqa: F401

from app.core.downloader import Downloader
from app.core.metadata import MetadataGenerator  # noqa: F401
from app.core.parser import BiliParser

from .sources.articles import ArticlesMixin
from .sources.base import ScannerBase
from .sources.collections import CollectionsMixin
from .sources.download import DownloadMixin
from .sources.favorites import FavoritesMixin
from .sources.following import FollowingMixin
from .sources.history import HistoryMixin
from .sources.integrity import IntegrityMixin
from .sources.redownload import RedownloadMixin
from .sources.watch_later import WatchLaterMixin


class FavScanner(
    RedownloadMixin,
    IntegrityMixin,
    HistoryMixin,
    CollectionsMixin,
    ArticlesMixin,
    FollowingMixin,
    WatchLaterMixin,
    FavoritesMixin,
    DownloadMixin,
    ScannerBase,
):

    def __init__(self, config, credential, db, path_mgr, uid=None, config_path=None):
        self.config = config
        self.config_path = config_path
        network_config = config.get("network", {})
        self.parser = BiliParser(
            credential,
            uid=uid,
            retry_attempts=network_config.get("sync_retry_attempts", 3),
            retry_backoff_seconds=network_config.get(
                "sync_retry_backoff_seconds",
                2,
            ),
            request_timeout_seconds=network_config.get(
                "request_timeout_seconds",
                30,
            ),
        )
        self.downloader = Downloader(config)
        self.db = db
        self.path_mgr = path_mgr
        self.cookie_path = config['system']['cookie_path']
        self.global_download_count = 0  # 全局下载计数器
        self._progress_callback = None
        # 一次性强制重下白名单：由 WebUI 命令通道填充，命中后仅当轮豁免跳过逻辑
        self._forced_redownloads = set()
        # 从配置读取最大下载数量，0或None表示无限制（下载全部）
        self.max_global_downloads = config.get('system', {}).get('max_downloads_per_run', 0)
        # 下载总开关（v1.9.4）：默认 False=停止下载，WebUI 设置页可开（即时生效）
        self.download_enabled = bool(config.get('system', {}).get('download_enabled', False))
        # 清晰度审计开关（v1.9.4）：默认 False；开启后巡检时产出低清清单
        self.quality_audit_enabled = bool(
            config.get('system', {}).get('quality_audit_enabled', False)
        )

    def set_progress_callback(self, callback):
        self._progress_callback = callback if callable(callback) else None

    def reload_config(self) -> bool:
        """Re-read the on-disk config and refresh the parameters that can
        change without a restart (sources list, scan limits, network
        boundaries, archive prefixes, wordcloud/summary switches).

        Restart-only keys (download_path, plex_mode, verify_integrity,
        component paths, proxy) intentionally keep their original values:
        they were baked into long-lived objects at construction time.
        Returns True when the file was read and applied.
        """
        if not self.config_path:
            # 不知配置路径时无从重读（测试或内嵌部署），明确失败而非假成功。
            return False
        try:
            from app.core.config_manager import load_config

            fresh = load_config(self.config_path)
        except Exception as exc:
            print(f"[-] 配置热重载失败: {exc}")
            return False
        if not isinstance(fresh, dict) or "system" not in fresh:
            return False
        self.config = fresh
        network = fresh.get("network", {})
        parser = self.parser
        parser.retry_attempts = network.get("sync_retry_attempts", parser.retry_attempts)
        parser.retry_backoff_seconds = network.get(
            "sync_retry_backoff_seconds", parser.retry_backoff_seconds
        )
        parser.request_timeout_seconds = network.get(
            "request_timeout_seconds", parser.request_timeout_seconds
        )
        # download_timeout 是每次下载时从 downloader 读的即时参数，可以热更。
        self.downloader.download_timeout_seconds = (
            self.downloader._normalize_download_timeout(
                fresh.get("system", {}).get("download_timeout_seconds", 7200)
            )
        )
        self.max_global_downloads = fresh.get("system", {}).get(
            "max_downloads_per_run", self.max_global_downloads
        )
        self.download_enabled = bool(
            fresh.get("system", {}).get("download_enabled", False)
        )
        self.quality_audit_enabled = bool(
            fresh.get("system", {}).get("quality_audit_enabled", False)
        )
        return True

    def purge_low_quality_assets(self, asset_ids):
        """清除低清晰度资产目录并登记重下（每项三重校验）。

        防穿越：目录必须解析后位于 download_root 内，且目录名含该
        bvid（与 path_manager 命名约定一致）。任何校验不过都跳过。
        返回 (成功数, 失败数)。
        """
        import shutil
        from pathlib import Path

        purged = 0
        failed = 0
        root = Path(self.path_mgr.root).resolve()
        for asset_id in asset_ids:
            try:
                recorded_path = self.db.get_asset_path(asset_id)
                if not recorded_path:
                    print(f"[-] 清除跳过（数据库无记录）: {asset_id}")
                    failed += 1
                    continue
                asset_dir = Path(recorded_path)
                if not asset_dir.is_absolute():
                    asset_dir = Path(self.config_path).parent / asset_dir if self.config_path else Path.cwd() / asset_dir
                resolved = asset_dir.resolve()
                # ① 必须在下载根内 ② 目录名必须含 bvid（命名约定）
                if not resolved.is_relative_to(root):
                    print(f"[-] 清除拒绝（路径越界）: {asset_id} -> {resolved}")
                    failed += 1
                    continue
                if asset_id not in resolved.name:
                    print(f"[-] 清除拒绝（目录名与资产不匹配）: {asset_id} -> {resolved.name}")
                    failed += 1
                    continue
                if resolved.exists():
                    shutil.rmtree(resolved)
                else:
                    print(f"[*] 目录已不存在（可能已清理）: {asset_id}")
                if self.db.delete_asset(asset_id):
                    self._forced_redownloads.add(asset_id)
                    purged += 1
                    print(f"[+] 已清除低清资产并登记重下: {asset_id}")
                else:
                    failed += 1
            except Exception as exc:
                print(f"[-] 清除失败 {asset_id}: {type(exc).__name__}: {exc}")
                failed += 1
        return purged, failed
