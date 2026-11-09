"""B 站扫码登录：申请二维码、轮询状态、解析凭据。

`bilibili_api` 自带的 `QrCodeLogin` 用字符串切分解析凭据 URL：

    if cookie[:8] == "SESSDATA": sessdata = cookie[9:]

它假设 cookie 串是 `NAME=value` 且用 `&` 紧挨分隔。B 站现在返回的
URL 里每个 cookie 前面带一个空格（`& SESSDATA=...`），于是
`" SESSDATA"[:8] == "SESSDATA"` 永远不成立，凭据里 sessdata / bili_jct /
dedeuserid 三个字段**全是空字符串**——登录看起来成功了，其实拿不到任何
可用的凭据。

这里自己发请求、自己解析，不依赖那套切分：分隔符容忍 `&` 与 `;`，
每个字段先 strip 再取名，cookie 名大小写不敏感。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bilibili_api.utils.network import Api, Credential
from bilibili_api.utils.utils import get_api

#: 登录相关的接口表。bilibili_api 把它们放在 login_v2 内部，没有对外导出。
#: 库给 get_api 的返回类型标注不准，这里显式声明为 Any。
_API: Any = get_api("login")


#: B 站可能用 `&` 或 `;` 分隔，且字段前后可能有空格。
_COOKIE_SEPARATOR = re.compile(r"[&;]")


class QrCodeStates:
    """`get_events` 返回的 code 与登录阶段。"""

    SCANNED = 86101
    CONFIRMED = 86090
    EXPIRED = 86038


async def create_web_qrcode() -> tuple[str, str]:
    """申请一个网页端登录二维码，返回 (qrcode_key, 二维码里的链接)。"""
    api = _API["qrcode"]["web"]["get_qrcode_and_token"]
    data = await Api(credential=Credential(), **api).result
    if not isinstance(data, dict):
        raise RuntimeError("B 站没有返回二维码信息")
    qrcode_key = str(data.get("qrcode_key") or "")
    url = str(data.get("url") or "")
    if not qrcode_key or not url:
        raise RuntimeError("B 站没有返回二维码信息")
    return qrcode_key, url


async def poll_qrcode(qrcode_key: str) -> tuple[str, dict[str, Any] | None]:
    """查询一次扫码状态。

    返回 (状态, 凭据)。状态是 "scanned" / "confirmed" / "expired" /
    "done"；只有在 "done" 时凭据才非空。
    """
    api = _API["qrcode"]["web"]["get_events"]
    events = await Api(credential=Credential(), **api).update_params(
        **{"qrcode_key": qrcode_key}
    ).result
    if not isinstance(events, dict):
        return "expired", None
    code = events.get("code")
    if code == QrCodeStates.SCANNED:
        return "scanned", None
    if code == QrCodeStates.CONFIRMED:
        return "confirmed", None
    if code == QrCodeStates.EXPIRED:
        return "expired", None
    credential = parse_credential_url(str(events.get("url") or ""))
    credential["ac_time_value"] = str(events.get("refresh_token") or "")
    return "done", credential


def parse_credential_url(url: str) -> dict[str, str]:
    """从 B 站的凭据 URL 里取出各 cookie。

    容忍 `&` / `;` 两种分隔符、字段前后的空格，以及 cookie 名的大小写。
    永远返回同样的三个键，缺的就是空串。
    """
    cookies: dict[str, str] = {}
    query = urlparse(url or "").query or ""
    for part in _COOKIE_SEPARATOR.split(query):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip().lower()
        if name:
            cookies[name] = value.strip()
    return {
        "sessdata": cookies.get("sessdata", ""),
        "bili_jct": cookies.get("bili_jct", ""),
        "dedeuserid": cookies.get("dedeuserid", ""),
    }


def credential_is_usable(credential: dict[str, Any] | None) -> bool:
    """凭据至少要有 sessdata 与 dedeuserid 才算可用。"""
    if not credential:
        return False
    return bool(credential.get("sessdata")) and bool(credential.get("dedeuserid"))


__all__ = [
    "QrCodeStates",
    "create_web_qrcode",
    "credential_is_usable",
    "parse_credential_url",
    "poll_qrcode",
]
