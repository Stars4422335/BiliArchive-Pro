"""下载必须离开事件循环：否则 WebUI 命令通道与状态刷新整轮假死。

`Downloader.download_video` 是纯阻塞实现（`subprocess.wait()` 等 yt-dlp
退出，成功后还有 15~35 秒 `time.sleep`）。它一旦在协程里被直接调用，
事件循环就无法调度任何其它任务——WebUI 的 5 秒命令轮询随之停摆。

这里的断言方式是"心跳"：下载进行期间另起一个 0.05 秒间隔的 ticker，
如果事件循环被阻塞，ticker 只可能跑到 1 次。
"""

import asyncio
import threading
import time

from app.core.path_manager import PathManager
from app.scheduler.scanner import FavScanner
from app.scheduler.sources.base import ScannerBase

#: 假下载器的阻塞时长：足够让 0.05 秒间隔的 ticker 至少跳几次，
#: 又不会明显拖慢测试套件。
FAKE_DOWNLOAD_SECONDS = 0.3
TICK_INTERVAL_SECONDS = 0.05


class SlowDownloader:
    """同步阻塞的下载器替身，记录调用线程与调用参数。"""

    def __init__(self, delay=FAKE_DOWNLOAD_SECONDS):
        self.delay = delay
        self.calls = []
        self.threads = []

    def download_video(self, url, save_dir, file_name, cookie_file_path):
        self.threads.append(threading.current_thread())
        self.calls.append(
            {
                "url": url,
                "save_dir": save_dir,
                "file_name": file_name,
                "cookie_file_path": cookie_file_path,
            }
        )
        # 与真实实现同构：整段阻塞在工作线程里发生。
        time.sleep(self.delay)
        return True


class FixedPagesParser:
    """固定分 P 结构的解析器替身，不触网。"""

    def __init__(self, pages):
        self.pages = pages

    async def check_multi_p(self, bvid):
        return len(self.pages) > 1, list(self.pages)


class UnusedDatabase:
    """下载流程不写库，这里只满足构造签名。"""

    def get_asset(self, key):
        return None


def scanner_config():
    return {
        "system": {
            "cookie_path": "cookie.json",
            "min_disk_gb": 0,
            "max_downloads_per_run": 0,
            "plex_mode": True,
        },
        "network": {
            "sync_retry_attempts": 1,
            "sync_retry_backoff_seconds": 0,
            "request_timeout_seconds": 10,
        },
        "components": {
            "yt-dlp": {"path": "yt-dlp"},
            "ffmpeg": {"path": "ffmpeg"},
        },
        "archive_protection": {
            "tombstone_prefix": "[Tombstone]",
            "mark_deleted_prefix": "[Deleted]",
        },
    }


def build_scanner(tmp_path, pages, monkeypatch):
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=UnusedDatabase(),
        path_mgr=PathManager(str(tmp_path), plex_mode=True),
    )
    scanner.parser = FixedPagesParser(pages)
    scanner.downloader = SlowDownloader()
    # 下载门禁默认拦截无 cookie 的下载；门禁自身行为由 test_v194 覆盖。
    monkeypatch.setattr(ScannerBase, "_login_gate_open", lambda self: True)
    # 封面与 NFO 只是布局细节，这里替换掉以聚焦调度行为。
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.copy_artwork",
        lambda *args, **kwargs: "/archive/poster.jpg",
    )
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.create_nfo",
        lambda *args, **kwargs: "/archive/video.nfo",
    )
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.create_episode_nfo",
        lambda *args, **kwargs: "/archive/episode.nfo",
    )
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.create_tvshow_nfo",
        lambda *args, **kwargs: "/archive/tvshow.nfo",
    )
    return scanner


def video_item():
    return {
        "title": "测试视频",
        "bvid": "BV1async001",
        "aid": 1,
        "id": 1,
        "type": "video",
        "intro": "简介",
    }


def run_with_ticker(scanner, item):
    """在下载进行期间跑一个 ticker，返回 (下载结果, tick 次数)。"""

    async def scenario():
        ticks = {"count": 0}

        async def ticker():
            while True:
                ticks["count"] += 1
                await asyncio.sleep(TICK_INTERVAL_SECONDS)

        ticker_task = asyncio.ensure_future(ticker())
        try:
            result = await scanner._download_video_item("测试收藏夹", item)
        finally:
            ticker_task.cancel()
            await asyncio.gather(ticker_task, return_exceptions=True)
        return result, ticks["count"]

    return asyncio.run(scenario())


def test_single_part_download_keeps_event_loop_responsive(monkeypatch, tmp_path):
    scanner = build_scanner(tmp_path, [{"page": 1, "part": "单集"}], monkeypatch)

    result, tick_count = run_with_ticker(scanner, video_item())

    assert result is not None
    # 事件循环仍在调度：阻塞 0.3 秒、间隔 0.05 秒的 ticker 一定不止 1 次。
    assert tick_count > 1
    assert len(scanner.downloader.threads) == 1
    assert scanner.downloader.threads[0] is not threading.main_thread()


def test_multi_part_download_keeps_event_loop_responsive(monkeypatch, tmp_path):
    scanner = build_scanner(
        tmp_path,
        [{"page": 1, "part": "第一集"}, {"page": 2, "part": "第二集"}],
        monkeypatch,
    )

    result, tick_count = run_with_ticker(scanner, video_item())

    assert result is not None
    assert tick_count > 1
    assert len(scanner.downloader.threads) == 2
    # 两次下载都在工作线程，主线程始终留给事件循环。
    assert all(thread is not threading.main_thread() for thread in scanner.downloader.threads)


def test_failed_download_returns_none_without_marking_complete(monkeypatch, tmp_path):
    """线程化的调用不改变失败语义：返回 None，调用方不写完成状态。"""
    scanner = build_scanner(tmp_path, [{"page": 1, "part": "单集"}], monkeypatch)
    scanner.downloader = SlowDownloader()
    scanner.downloader.download_video = lambda **kwargs: False

    async def scenario():
        return await scanner._download_video_item("测试收藏夹", video_item())

    assert asyncio.run(scenario()) is None
