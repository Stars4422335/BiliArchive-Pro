"""Login credential checks for the core engine.

The engine talks to four sources that all need a signed-in account
(favourites, watch later, followings and watch history). When the cookie
expires, every one of them fails, so the daemon must notice that up front
instead of looping with a dead credential for the whole sleep interval.

The distinction that matters here is *expired* versus *temporarily
unreachable*: only the first one means "stop and ask the user to log in
again". Network hiccups and 5xx responses leave the credential usable, so
public videos can still be downloaded.
"""

from __future__ import annotations

import json
import os

from bilibili_api import Credential, user


def is_auth_failure(exc) -> bool:
    """判断异常是否代表"凭据确定已失效"，而非临时故障。

    B 站在 Cookie 过期时返回 -101 账号未登录。此时所有需要登录的来源
    （收藏夹 / 稍后再看 / 关注列表 / 观看历史）都会失败，守护进程会
    带着死凭据空转整个休眠周期。与其这样，不如在启动时明确失败并
    提示重新登录。

    区分标准：
    - 明确的未登录语义（-101 / 未登录 / SESSDATA 失效 / 登录已过期）
    - 明确的鉴权异常类型（LoginError）

    网络抖动、超时、5xx 等临时故障不算鉴权失败——那类问题下
    公开视频仍可下载，保持原有的宽松行为。
    """
    from bilibili_api.exceptions import LoginError

    if isinstance(exc, LoginError):
        return True

    # bilibili_api 的 ResponseCodeException 把整段 raw 塞进 .code
    raw = getattr(exc, "code", None)
    if isinstance(raw, dict):
        code = raw.get("code")
        message = str(raw.get("message") or "")
    else:
        code = raw
        message = ""

    # B 站错误码（见 bilibili-API-collect）：
    #   -101 账号未登录 / -111 csrf 校验失败 —— 两者都源于凭据失效
    #   -400 请求错误 / -509 请求过于频繁 —— 都不是鉴权问题，不能据此退出
    if code in (-101, -111):
        return True

    text = f"{message} {exc}".lower()
    markers = ("未登录", "账号未登录", "sessdata", "登录已过期", "登录过期", "not logged in")
    return any(marker in text for marker in markers)


async def check_cookie(cookie_path):
    """校验登录凭据。

    返回 (credential, uid)：
    - 凭据有效时返回真实对象；
    - 凭据确定失效（未登录）时返回 (None, None)，调用方应终止——
      所有需要登录的来源都会失败，继续空转没有意义；
    - 临时故障（网络抖动等）时仍返回凭据对象，公开视频仍可下载。
    """
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
        if is_auth_failure(e):
            print("[!] 登录凭据已失效，收藏夹 / 稍后再看 / 关注列表等来源都需要登录。")
            print("[!] 请重新运行 python login.py 扫码登录后重启核心进程。")
            return None, None
        # 临时故障（网络抖动等）：公开视频仍可强行下载，保持宽松处理
        print("[!] 建议重新运行 python login.py 扫码登录。")
        return cred, uid


__all__ = ["check_cookie", "is_auth_failure"]
