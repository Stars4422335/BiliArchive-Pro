"""B 站扫码登录：申请二维码、轮询状态、换取凭据。

B 站的扫码登录响应**不再直接给出 cookie**。扫完码之后 `get_events` 返回的
`code` 是 0，`url` 是一次性的 ticket 地址：

    https://passport.biligame.com/x/passport-login/web/crossDomain
        ?ticket=…&gourl=…&first_domain=…

真正的 cookie 要**访问这个地址**，从响应的 `Set-Cookie` 头里读。

`bilibili_api` 自带的 `QrCodeLogin` 还在按老格式找 cookie
（`if cookie[:8] == "SESSDATA"`），所以它拿到的是三个空字符串——登录看起来
成功了，实际什么都没拿到。

这里自己发请求、自己换凭据：新流程走 ticket 交换，老格式（cookie 直接在
URL 里）仍然能解析，两种都认。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bilibili_api.utils.network import Api, Credential
from bilibili_api.utils.utils import get_api

#: 登录相关的接口表。bilibili_api 把它们放在 login_v2 内部，没有对外导出。
#: 库给 get_api 的返回类型标注不准，这里显式声明为 Any。
_API: Any = get_api("login")

#: B 站可能用 `&` 或 `;` 分隔，且字段前后可能有空格。
_COOKIE_SEPARATOR = re.compile(r"[&;]")

#: 凭据 cookie 在响应里的名字，大小写不敏感。
_COOKIE_NAMES = {
    "sessdata": "sessdata",
    "bili_jct": "bili_jct",
    "dedeuserid": "dedeuserid",
    "buvid3": "buvid3",
    "buvid4": "buvid4",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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

    credential_url = str(events.get("url") or "")
    if not credential_url:
        return "expired", None

    if "ticket=" in credential_url:
        # 新流程：一次性 ticket 地址，cookie 在它的响应头里。
        credential = await exchange_credential_url(credential_url)
    else:
        # 老流程：cookie 直接写在 URL 的查询串里。
        credential = parse_credential_url(credential_url)
    credential["ac_time_value"] = str(events.get("refresh_token") or "")
    return "done", credential


async def exchange_credential_url(url: str) -> dict[str, str]:
    """访问 ticket 地址，从响应头里取出 B 站下发的 cookie。

    这是跨域登录的标准做法：B 站在这个地址上用 `Set-Cookie` 把凭据发下来，
    而不是把凭据写在响应体里。

    cookie 有两个地方可能藏着，两个都得看：

    - `client.cookies` 是整个重定向链累积下来的 cookie jar；
      `response.cookies` 只有最后一条响应，前面被重定向掉的那些不在里面。
    - 按域匹配的 cookie jar 可能**拒收**跨域下发的凭据
      （ticket 地址在 passport.biligame.com，凭据却是 .bilibili.com 的），
      所以再直接读原始 `Set-Cookie` 头兜底。
    """
    headers = {
        "User-Agent": _USER_AGENT,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "*/*",
    }
    found: dict[str, str] = {}
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        response = await client.get(url, headers=headers)

        for cookie in client.cookies.jar:
            key = _COOKIE_NAMES.get(cookie.name.strip().lower())
            if key and cookie.value:
                found[key] = cookie.value

        for resp in [*response.history, response]:
            for raw in resp.headers.get_list("set-cookie"):
                name, _, rest = raw.partition("=")
                key = _COOKIE_NAMES.get(name.strip().lower())
                if not key:
                    continue
                value = rest.split(";")[0].strip()
                if value:
                    found[key] = value

    if not found:
        received = sorted(
            {
                raw.partition("=")[0].strip().lower()
                for resp in [*response.history, response]
                for raw in resp.headers.get_list("set-cookie")
            }
        )
        print(f"[!] ticket 交换没有拿到凭据；收到的 cookie 名字: {received}")

    return {
        "sessdata": found.get("sessdata", ""),
        "bili_jct": found.get("bili_jct", ""),
        "dedeuserid": found.get("dedeuserid", ""),
        "buvid3": found.get("buvid3", ""),
        "buvid4": found.get("buvid4", ""),
    }


def parse_credential_url(url: str) -> dict[str, str]:
    """从老格式的凭据 URL 里取出各 cookie。

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
    "exchange_credential_url",
    "parse_credential_url",
    "poll_qrcode",
]
