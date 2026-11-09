import argparse
import asyncio
import json
import os
import sys
import time

# 切换工作目录到程序所在目录，避免在其他路径运行脚本时相对路径解析错误。
# PyInstaller 打包后 __file__ 指向 bootloader 临时目录，必须改用 exe 自身路径。
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

from bilibili_api import register_client
from bilibili_api.clients.HTTPXClient import HTTPXClient

from app import __version__
from app.core.bili_login import (
    create_web_qrcode,
    credential_is_usable,
    poll_qrcode,
)
from app.core.secure_file import atomic_write_text

# 关键：注册 httpx 客户端
register_client("httpx", HTTPXClient)

def _credential_fields(credential):
    """把凭据统一成字典，兼容库返回的对象与自己解析出的字典。"""
    if isinstance(credential, dict):
        return {
            key: (credential.get(key) or "")
            for key in ("sessdata", "bili_jct", "buvid3", "dedeuserid", "ac_time_value")
        }
    return {
        "sessdata": getattr(credential, "sessdata", "") or "",
        "bili_jct": getattr(credential, "bili_jct", "") or "",
        "buvid3": getattr(credential, "buvid3", "") or "",
        "dedeuserid": getattr(credential, "dedeuserid", "") or "",
        "ac_time_value": getattr(credential, "ac_time_value", "") or "",
    }

async def save_credential(credential):
    """保存凭证到文件"""
    cookie_data = _credential_fields(credential)

    serialized_cookie = json.dumps(cookie_data, ensure_ascii=False, indent=4) + "\n"
    atomic_write_text("./data/cookie.json", serialized_cookie)

    print("\n" + "=" * 60)
    print("[+] 登录成功！凭据已保存至 ./data/cookie.json")
    print("[+] 你现在可以运行: python main.py --cli")
    print("=" * 60)

def _write_qrcode_png(url, path):
    """把登录链接画成二维码图片，交给用户用手机扫。"""
    import qrcode

    image = qrcode.QRCode()
    image.add_data(url)
    image.make_image().save(path)

async def login_by_qrcode():
    """方式1：二维码登录"""
    print("\n[*] 正在初始化二维码登录...")
    qrcode_key, url = await create_web_qrcode()

    print("\n请使用 B 站手机 App 扫描下方二维码：")
    print("(打开 App → 我的 → 扫一扫)\n")

    target = os.path.abspath("./data/login-qr-terminal.png")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    _write_qrcode_png(url, target)
    print(f"[*] 二维码图片同时写入: {target}")

    print("[*] 等待扫码中...")
    while True:
        state, credential = await poll_qrcode(qrcode_key)
        if state == "done":
            if not credential_is_usable(credential):
                print("[-] 登录回调缺少凭据字段，请重新扫码。")
                return False
            await save_credential(credential)
            return True
        if state == "expired":
            print("[-] 二维码已过期，请重新运行本脚本。")
            return False
        if state == "confirmed":
            print("[*] 正在确认登录...")
        await asyncio.sleep(1.5)

async def login_by_qrcode_png(out_path, timeout_seconds=180):
    """非交互扫码：把二维码写成 PNG 文件，等待手机 App 确认后保存凭据。

    终端二维码在自动化流程里没法被人扫到，所以这条路径把二维码落到
    一个图片文件里，由调用方把它交给用户扫。
    """
    qrcode_key, url = await create_web_qrcode()

    target = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    _write_qrcode_png(url, target)
    print(f"[*] 二维码已写入: {target}")
    print("[*] 请用 B 站手机 App 扫描该图片并确认登录。")

    deadline = time.monotonic() + max(1, int(timeout_seconds))
    while time.monotonic() < deadline:
        state, credential = await poll_qrcode(qrcode_key)
        if state == "done":
            if not credential_is_usable(credential):
                print("[-] 登录回调缺少凭据字段，请重新扫码。")
                return False
            await save_credential(credential)
            return True
        if state == "expired":
            print("[-] 二维码已过期，请重新运行。")
            return False
        if state == "confirmed":
            print("[*] 已在手机上确认，等待登录完成...")
        await asyncio.sleep(1.5)

    print("[-] 等待扫码确认超时，请重新运行。")
    return False

async def login_by_sms():
    """方式2：手机号+验证码登录"""
    print("\n=== 手机号验证码登录 ===")
    print("[!] 注意：此方式需要完成验证码验证")

    try:
        from bilibili_api.login_v2 import PhoneNumber, login_with_sms, send_sms
        from bilibili_api.utils.geetest import Geetest

        # 获取手机号
        phone = input("\n请输入手机号: ").strip()
        if not phone:
            print("[-] 手机号不能为空")
            return False
        phonenumber = PhoneNumber(phone, country='+86')

        # 获取 Geetest 对象
        geetest = Geetest()

        print("[*] 正在请求发送验证码...")
        print("[!] 如果需要完成滑块验证，请按提示操作...")

        # 发送短信
        captcha_id = await send_sms(phonenumber, geetest)

        if not captcha_id:
            print("[-] 发送验证码失败")
            return False
        print("[+] 验证码已发送，请查收短信")

        # 获取用户输入的验证码
        code = input("\n请输入短信验证码: ").strip()
        if not code:
            print("[-] 验证码不能为空")
            return False

        print("[*] 正在登录...")

        # 执行登录
        credential = await login_with_sms(phonenumber, code, captcha_id)

        await save_credential(credential)
        return True

    except Exception as e:
        print(f"[-] 短信登录失败: {e}")
        print("[!] 可能原因：")
        print("    1. 手机号格式错误")
        print("    2. 验证码错误或已过期")
        print("    3. 需要完成滑块验证（当前环境可能不支持）")
        print("    4. B站账号安全限制")
        print("\n[!] 建议：在 Windows/Mac 本地使用二维码方式登录")
        return False

def parse_args():
    parser = argparse.ArgumentParser(description="BiliArchive-Pro 登录")
    parser.add_argument(
        "--qr",
        action="store_true",
        help="非交互扫码：把二维码写成 PNG 图片后等待手机确认",
    )
    parser.add_argument(
        "--qr-out",
        default="./data/login-qr.png",
        help="--qr 模式下二维码 PNG 的输出路径",
    )
    parser.add_argument(
        "--qr-timeout",
        type=int,
        default=180,
        help="--qr 模式下等待扫码确认的秒数",
    )
    return parser.parse_args()

async def main():
    args = parse_args()

    if args.qr:
        success = await login_by_qrcode_png(args.qr_out, args.qr_timeout)
        raise SystemExit(0 if success else 1)

    print("=" * 60)
    print(f"       BiliArchive-Pro 登录系统 (v{__version__})")
    print("=" * 60)

    # 检查是否在WSL环境
    import platform
    in_wsl = "microsoft" in platform.release().lower() or "WSL" in platform.release()

    if in_wsl:
        print("\n[!] 检测到 WSL 环境")
        print("[!] 提示：WSL中可能无法显示二维码或完成滑块验证")
        print("[!] 建议在 Windows/Mac 本地运行此脚本\n")

    print("\n请选择登录方式：")
    print("  1. 二维码登录（推荐，最稳定）")
    print("  2. 手机号+验证码登录")
    print("  0. 退出")

    while True:
        try:
            choice = input("\n请输入选项 [0-2]: ").strip()
        except EOFError:
            # 非交互式环境，默认选择二维码登录...
            print("[!] 非交互式环境，默认选择二维码登录...")
            choice = "1"

        if choice == "0":
            print("[!] 已退出")
            return
        elif choice == "1":
            success = await login_by_qrcode()
            if success:
                return
            print("[!] 登录失败，请重试或选择其他方式")
        elif choice == "2":
            success = await login_by_sms()
            if success:
                return
            print("[!] 登录失败，请重试或选择其他方式")
        else:
            print("[-] 无效选项，请重新输入")

if __name__ == "__main__":
    asyncio.run(main())
