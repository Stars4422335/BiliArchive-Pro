"""清晰度审计：识别「掉登录期间下载的低清晰度资产」。

判定采用对比法而非绝对阈值：只有当
    本地已下载 height < 源端当前可拿到的最高 height
（两者都成功探测到）才判定为降级。源本身就只有低清晰度的视频
（源端最高 <= 本地）永不标记——宁漏删不误删。

数据来源：
* 本地：资产目录内的 info.json（yt-dlp --write-info-json 产出，
  含 height / requested_formats）。多 P 取各分集的最大 height。
* 源端：登录态下 Video.get_download_url() 返回的 accept_quality
  （B 站 playurl 接口），映射到 height 后取最大值。

删除不在本模块内：审计只产出证据清单；真正的清除由用户在 WebUI
确认后通过 purge_low_quality 命令执行（daemon 侧二次校验）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# B 站清晰度编号（qn）到像素高度的映射，官方档位。
QN_TO_HEIGHT = {
    127: 4320,  # 超高清 8K
    126: 2160,  # 杜比视界
    125: 2160,  # HDR 真彩
    120: 2160,  # 超高清 4K
    116: 1080,  # 高清 1080P60
    112: 1080,  # 高清 1080P+
    80: 1080,   # 高清 1080P
    74: 720,    # 高清 720P60
    64: 720,    # 高清 720P
    32: 480,    # 清晰 480P
    16: 360,    # 流畅 360P
}


def _height_from_quality_entry(entry: Any) -> int | None:
    """从 info.json 的一个流描述里尽力提取高度。"""
    if not isinstance(entry, dict):
        return None
    for key in ("height",):
        value = entry.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return None


def read_local_height(asset_dir: os.PathLike[str] | str, p_count: int = 1) -> int | None:
    """读取资产目录内 info.json 记录的实际下载高度。

    多 P 资产取各分集 info.json 的最大高度。找不到 info.json 或
    解析失败返回 None（调用方应跳过，不判定）。
    """
    directory = Path(asset_dir)
    if not directory.is_dir():
        return None
    heights: list[int] = []
    try:
        candidates = sorted(directory.glob("*.info.json"))
    except OSError:
        return None
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        found = _height_from_quality_entry(data)
        if found is None and isinstance(data.get("requested_formats"), list):
            # DASH 双流：取视频流的高度。
            for stream in data["requested_formats"]:
                found = _height_from_quality_entry(stream)
                if found:
                    break
        if found:
            heights.append(found)
    if not heights:
        return None
    return max(heights)


async def probe_source_height(bvid: str, credential, parser=None) -> int | None:
    """登录态下探测源端当前可拿到的最高清晰度高度。

    探测失败（视频失效/私有/风控/网络）返回 None——调用方必须跳过，
    宁漏删不误删。
    """
    if not credential:
        return None
    try:
        from bilibili_api import video as bili_video

        video = bili_video.Video(bvid=bvid, credential=credential)
        if parser is not None:
            # 复用 parser 的分P信息（若调用方有），减少一次请求由调用方决定；
            # 这里默认取第一分P。
            pass
        data = await video.get_download_url(page_index=0)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    accept = data.get("accept_quality")
    if not isinstance(accept, list) or not accept:
        return None
    heights = [
        QN_TO_HEIGHT.get(int(qn))
        for qn in accept
        if isinstance(qn, (int, float)) and int(qn) in QN_TO_HEIGHT
    ]
    heights = [h for h in heights if h]
    if not heights:
        return None
    return max(heights)


def audit_asset(local_height: int | None, source_height: int | None) -> dict[str, Any]:
    """对比法判定。两端都有值且本地严格低于源端才判降级。"""
    if local_height is None or source_height is None:
        return {"downgraded": False, "reason": "insufficient_evidence"}
    if local_height >= source_height:
        return {"downgraded": False, "reason": "source_not_higher"}
    return {
        "downgraded": True,
        "local_height": local_height,
        "source_height": source_height,
    }


__all__ = [
    "QN_TO_HEIGHT",
    "audit_asset",
    "probe_source_height",
    "read_local_height",
]
