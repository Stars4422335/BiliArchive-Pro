"""下载失败的退避账本策略（纯函数，便于单测覆盖边界）。

`assets` 表只有 status 0/1/2，没有"失败"这一状态。对 404、版权、付费、
地区限制这类永久失败项，每轮扫描（默认 6 小时）重试一次纯属浪费请求与
日志。这里用失败次数驱动的阶梯冷却来止损：

- 第 1 次失败：冷却 1 小时
- 第 2 次失败：冷却 6 小时
- 第 3 次失败：冷却 24 小时
- 第 4 次及以后：冷却 7 天（封顶）

策略本身不读写数据库、不打印、不依赖时钟单例，`now` 显式传入以便测试
"时钟前进后解冻"。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Mapping

#: 阶梯倍数：序号 n 的倍数 × base。最后一档之后保持恒定（不再指数增长）。
_BACKOFF_MULTIPLIERS = (1, 6, 24, 168)

#: 默认基准与封顶（秒）。
DEFAULT_BACKOFF_BASE_SECONDS = 3600
DEFAULT_BACKOFF_CAP_SECONDS = 604800


def failure_count(record: Mapping[str, Any] | None) -> int:
    """读取失败次数；缺失、布尔、负数或非法值一律按 0（=未失败）。"""
    if not isinstance(record, Mapping):
        return 0
    raw_value = record.get("fail_count")
    if raw_value is None or isinstance(raw_value, bool):
        return 0
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _normalize_seconds(value: Any, fallback: float) -> float:
    """把 base/cap 规范成正的有限浮点数；非法值回退默认。"""
    if isinstance(value, bool):
        return fallback
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(seconds) or seconds <= 0:
        return fallback
    return seconds


def backoff_seconds(
    fail_count: Any,
    *,
    base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
) -> int:
    """第 `fail_count` 次失败后的冷却时长（秒）。

    `fail_count <= 0` 返回 0，表示从未失败、不需要冷却。
    超过阶梯长度后固定在最后一档，避免退避无限增长。
    """
    steps = failure_count({"fail_count": fail_count})
    if steps <= 0:
        return 0
    base_seconds = _normalize_seconds(base, float(DEFAULT_BACKOFF_BASE_SECONDS))
    cap_seconds = _normalize_seconds(cap, float(DEFAULT_BACKOFF_CAP_SECONDS))
    multiplier = _BACKOFF_MULTIPLIERS[min(steps, len(_BACKOFF_MULTIPLIERS)) - 1]
    return int(min(cap_seconds, base_seconds * multiplier))


def parse_last_fail(value: Any) -> datetime | None:
    """解析 last_fail；缺失或格式非法返回 None。

    新写入统一用 ``%Y-%m-%d %H:%M:%S``（与 last_check 一致），但历史数据
    可能带时区或是 ISO 字符串，所以走 `fromisoformat` 而非固定格式。
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _align_clock(reference: datetime, now: datetime | None) -> datetime:
    """把 now 与参考时间的"带不带时区"对齐，避免 naive/aware 相减报错。"""
    if now is None:
        return datetime.now().astimezone() if reference.tzinfo else datetime.now()
    if reference.tzinfo is None and now.tzinfo is not None:
        return now.replace(tzinfo=None)
    if reference.tzinfo is not None and now.tzinfo is None:
        return now.astimezone()
    return now


def remaining_backoff_seconds(
    record: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> int:
    """剩余冷却秒数；不在冷却期返回 0。"""
    steps = failure_count(record)
    if steps <= 0 or not isinstance(record, Mapping):
        return 0
    last_fail = parse_last_fail(record.get("last_fail"))
    if last_fail is None:
        # 时间戳缺失或损坏：账本不可用，不冻结资产（宁可多试一次）。
        return 0
    reference = _align_clock(last_fail, now)
    elapsed = (reference - last_fail).total_seconds()
    if elapsed < 0:
        # 系统时钟被回拨：按"刚失败"处理，避免负剩余时长绕过冷却。
        elapsed = 0.0
    return max(0, backoff_seconds(steps) - int(elapsed))


def should_skip_for_backoff(
    record: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> bool:
    """该资产是否仍处于失败冷却期（True = 本轮跳过）。

    - 没有记录、从未失败（fail_count <= 0）→ False，永不跳过。
    - last_fail 缺失/非法 → False：账本不可用时宁可重试，也不要把资产
      永久冻结在"跳过"分支里。
    """
    return remaining_backoff_seconds(record, now) > 0


def format_duration(seconds: Any) -> str:
    """把秒数转成便于日志阅读的中文时长（用于打印冷却原因）。"""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        total = 0
    if total >= 86400:
        return f"{total // 86400} 天 {(total % 86400) // 3600} 小时"
    if total >= 3600:
        return f"{total // 3600} 小时 {(total % 3600) // 60} 分钟"
    if total >= 60:
        return f"{total // 60} 分钟"
    return f"{total} 秒"


__all__ = [
    "DEFAULT_BACKOFF_BASE_SECONDS",
    "DEFAULT_BACKOFF_CAP_SECONDS",
    "backoff_seconds",
    "failure_count",
    "format_duration",
    "parse_last_fail",
    "remaining_backoff_seconds",
    "should_skip_for_backoff",
]
