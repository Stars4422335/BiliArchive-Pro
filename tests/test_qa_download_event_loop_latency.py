"""QA 独立验证：下载真的不阻塞事件循环（而不只是"看起来并发"）。

工程师的 `test_download_async.py` 统计 tick 次数；本文件换一把更硬的尺子：

- 用**调度间隔**判定，而不是次数。心跳协程每 0.05 秒调度一次并记录
  `loop.time()`；如果下载把事件循环占住 0.6 秒，相邻两次心跳之间就会留下
  一段 ~0.6 秒的空白间隔，即使总次数勉强够也能被抓住。
- 断言"最大间隔 < 0.2 秒"，即事件循环在整段下载中每一拍都准时。
- 同文件内自带**标定用例**：直接 `time.sleep(0.3)` 必须被同一个探针判为
  阻塞，证明这个断言不是恒真的空测量。
- 异常路径：`asyncio.to_thread` 不改写既有语义——返回 False → None；
  异常则在**单个资产层**被隔离（`_download_video_item` 兜底、登记退避后
  返回 None），只有 `SyncFetchError` 继续上抛以中止整个来源。守护层的
  兜底与退出语义穿透由 `tests/test_main_runtime.py` 覆盖。
"""

import asyncio
import contextlib
import threading
import time

import pytest

from app.core.path_manager import PathManager
from app.scheduler import daemon
from app.scheduler.scanner import FavScanner
from app.scheduler.sources.base import ScannerBase

#: 假下载器的阻塞时长：足够长到任何"串行执行"都会暴露，又不拖慢套件。
BLOCK_SECONDS = 0.6
#: 心跳间隔。
TICK_SECONDS = 0.05
#: 事件循环调度延迟上限（秒）。Windows 定时器粒度约 15.6ms，0.2 秒留足余量。
MAX_ACCEPTABLE_GAP_SECONDS = 0.2


class BlockingDownloader:
    """同步阻塞的下载器替身：与真实实现同构（整段阻塞在工作线程）。"""

    def __init__(self, delay=BLOCK_SECONDS, error=None):
        self.delay = delay
        self.error = error
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
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return True


class FixedPagesParser:
    def __init__(self, pages):
        self.pages = pages

    async def check_multi_p(self, bvid):
        return len(self.pages) > 1, list(self.pages)


class UnusedDatabase:
    """最小数据库替身：记录退避账本调用。"""

    def __init__(self):
        self.failure_calls = []
        self.reset_calls = []

    def get_asset(self, key):
        return None

    def record_download_failure(self, key, reason=""):
        self.failure_calls.append((key, reason))
        return len(self.failure_calls)

    def reset_download_failures(self, key):
        self.reset_calls.append(key)
        return True


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


def build_scanner(tmp_path, pages, monkeypatch, downloader=None):
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=UnusedDatabase(),
        path_mgr=PathManager(str(tmp_path), plex_mode=True),
    )
    scanner.parser = FixedPagesParser(pages)
    scanner.downloader = downloader or BlockingDownloader()
    monkeypatch.setattr(ScannerBase, "_login_gate_open", lambda self: True)
    # 封面与 NFO 是布局细节，这里替换掉以聚焦调度行为。
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
        "bvid": "BV1qaLatency",
        "aid": 1,
        "id": 1,
        "type": "video",
        "intro": "简介",
    }


async def _measure(work):
    """跑 work()，同时用心跳测事件循环的调度间隔。

    返回 ``(结果, 下载期间的心跳次数, 最大相邻心跳间隔)``。
    """
    marks = []

    async def heartbeat():
        while True:
            marks.append(asyncio.get_event_loop().time())
            await asyncio.sleep(TICK_SECONDS)

    beat = asyncio.ensure_future(heartbeat())
    # 先跑几拍建立稳定节奏，避免把"任务启动延迟"算进最大间隔。
    await asyncio.sleep(TICK_SECONDS * 3)
    baseline = len(marks)
    try:
        result = await work()
        # 关键：让心跳再跳几拍，把"阻塞结束"这一拍也记下来。否则跨阻塞区间
        # 的那一段空白永远没有终点标记，探针会漏判串行阻塞（标定用例会失败）。
        ticks_at_work_end = len(marks)
        await asyncio.sleep(TICK_SECONDS * 3)
    finally:
        beat.cancel()
        with contextlib.suppress(BaseException):
            await beat
    gaps = [
        later - earlier
        for earlier, later in zip(marks, marks[1:], strict=False)
    ]
    ticks_during_work = max(0, ticks_at_work_end - baseline)
    return result, ticks_during_work, (max(gaps) if gaps else 0.0)


def test_single_part_download_never_stalls_the_loop(monkeypatch, tmp_path):
    """阻塞 0.6 秒的下载期间，事件循环每一拍都必须准时。"""
    scanner = build_scanner(tmp_path, [{"page": 1, "part": "单集"}], monkeypatch)

    result, ticks, max_gap = asyncio.run(
        _measure(lambda: scanner._download_video_item("测试收藏夹", video_item()))
    )

    assert result is not None
    # 0.6 / 0.05 ≈ 12 拍；门槛设 5 拍，串行实现只会有 0~1 拍。
    assert ticks >= 5, f"下载期间事件循环只推进了 {ticks} 次，疑似串行阻塞"
    assert max_gap < MAX_ACCEPTABLE_GAP_SECONDS, f"事件循环被卡住 {max_gap:.3f} 秒"
    # 确认假下载器真的阻塞过、且跑在工作线程上（否则上面两条没有意义）。
    assert len(scanner.downloader.calls) == 1
    assert scanner.downloader.threads[0] is not threading.main_thread()


def test_multi_part_download_never_stalls_the_loop(monkeypatch, tmp_path):
    """多 P 逐集下载同样不得占用事件循环。"""
    scanner = build_scanner(
        tmp_path,
        [{"page": 1, "part": "第一集"}, {"page": 2, "part": "第二集"}],
        monkeypatch,
    )

    result, ticks, max_gap = asyncio.run(
        _measure(lambda: scanner._download_video_item("测试收藏夹", video_item()))
    )

    assert result is not None
    assert ticks >= 5, f"多P下载期间事件循环只推进了 {ticks} 次"
    assert max_gap < MAX_ACCEPTABLE_GAP_SECONDS, f"事件循环被卡住 {max_gap:.3f} 秒"
    assert len(scanner.downloader.threads) == 2
    assert all(t is not threading.main_thread() for t in scanner.downloader.threads)


def test_probe_itself_detects_a_serial_block():
    """标定：同一探针对"协程里直接 sleep"必须报出大间隔，否则断言恒真。"""

    async def serial_block():
        time.sleep(0.3)
        return "done"

    result, _ticks, max_gap = asyncio.run(_measure(serial_block))

    assert result == "done"
    assert max_gap >= 0.25, f"探针灵敏度不足：串行阻塞只测出 {max_gap:.3f} 秒"


def test_failed_download_still_returns_none(monkeypatch, tmp_path):
    """线程化不改变失败语义：download_video 返回 False → None。"""
    downloader = BlockingDownloader(delay=0)
    downloader.download_video = lambda **kwargs: False
    scanner = build_scanner(tmp_path, [{"page": 1, "part": "单集"}], monkeypatch, downloader)

    assert asyncio.run(scanner._download_video_item("测试收藏夹", video_item())) is None


def test_download_exception_is_isolated_and_scan_continues(monkeypatch, tmp_path):
    """异常被隔离在单个资产内：返回 None，不向上穿透。

    修复前（QA 首轮记录）：工作线程里的 RuntimeError 原样穿过
    `_download_video_item` → `_run_source_scan` 只隔离 SyncFetchError →
    整轮报废 → daemon 记 status=error 后退出 → 进程退出（Docker 会拉起再撞
    同一失败，形成重启循环）。
    修复后：`_download_video_item` 自己兜底、登记退避账本并返回 None，
    调用方按"下载未完成"处理，扫描继续。
    """
    downloader = BlockingDownloader(delay=0, error=RuntimeError("yt-dlp 崩了"))
    scanner = build_scanner(tmp_path, [{"page": 1, "part": "单集"}], monkeypatch, downloader)
    database = UnusedDatabase()
    scanner.db = database
    reports = []
    scanner.set_progress_callback(lambda **payload: reports.append(payload))

    assert asyncio.run(scanner._download_video_item("测试收藏夹", video_item())) is None
    # 账本登记放在调用方（favorites 的失败分支），不在这一层重复登记：
    # 一次异常只应让 fail_count +1，否则冷却会被错抬（如 1h → 6h）。
    # 调用方口径由 tests/test_qa_failure_accounting.py 断言。
    assert database.failure_calls == []
    # WebUI 要能看出这是"异常隔离"，而不是普通下载失败或空转
    assert any(payload.get("phase") == "asset_error" for payload in reports)
    assert any(payload.get("current_asset") == "BV1qaLatency" for payload in reports)

    async def operation():
        # 该资产的异常不再影响本源其它资产：操作本身正常返回
        await scanner._download_video_item("测试收藏夹", video_item())

    assert asyncio.run(daemon._run_source_scan("收藏夹 测试", operation)) is True


def test_sync_fetch_error_still_propagates_to_abort_the_source(monkeypatch, tmp_path):
    """来源读取失败必须继续上抛：它代表整个来源不可读，不是单个资产的问题。"""
    from app.core.parser import SyncFetchError

    class ExplodingParser:
        async def check_multi_p(self, bvid):
            raise SyncFetchError("page 2 failed")

    scanner = build_scanner(tmp_path, [{"page": 1, "part": "单集"}], monkeypatch)
    scanner.parser = ExplodingParser()

    with pytest.raises(SyncFetchError, match="page 2 failed"):
        asyncio.run(scanner._download_video_item("测试收藏夹", video_item()))


@pytest.mark.parametrize(
    "exception",
    [asyncio.CancelledError("用户中断"), KeyboardInterrupt("Ctrl+C")],
    ids=["cancelled", "keyboard_interrupt"],
)
def test_isolation_shell_does_not_swallow_exit_signals(monkeypatch, tmp_path, exception):
    """资产级兜底只捕 Exception 的语义必须成立：取消与中断绝不能变成"已隔离"。

    吞掉 CancelledError 会让守护进程停不下来，吞掉 KeyboardInterrupt 会让
    Ctrl+C 无效——两者都是比"少一个资产"更严重的故障。
    """
    scanner = build_scanner(tmp_path, [{"page": 1, "part": "单集"}], monkeypatch)

    async def explode(*_args, **_kwargs):
        raise exception

    monkeypatch.setattr(scanner, "_download_video_asset", explode)

    with pytest.raises(type(exception)):
        asyncio.run(scanner._download_video_item("测试收藏夹", video_item()))
