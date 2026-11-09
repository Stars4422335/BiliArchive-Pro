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
from app.core.metadata import MetadataGenerator  # noqa: F401

from app.core.downloader import Downloader
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

    def __init__(self, config, credential, db, path_mgr, uid=None):
        self.config = config
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

    def set_progress_callback(self, callback):
        self._progress_callback = callback if callable(callback) else None
