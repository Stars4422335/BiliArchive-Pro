import asyncio
import json
import os
import sys

# 切换工作目录到项目根目录，避免在其他路径运行脚本时相对路径解析错误
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from bilibili_api import register_client
from bilibili_api.clients.HTTPXClient import HTTPXClient
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

# 关键：注册 httpx 客户端
register_client("httpx", HTTPXClient)

async def save_credential(credential):
    """保存凭证到文件"""
    cookie_data = {
        "sessdata": credential.sessdata,
        "bili_jct": credential.bili_jct,
        "buvid3": credential.buvid3,
        "dedeuserid": credential.dedeuserid,
        "ac_time_value": credential.ac_time_value
    }
    
    os.makedirs("./data", exist_ok=True)
    with open("./data/cookie.json", "w", encoding="utf-8") as f:
        json.dump(cookie_data, f, indent=4)
        
    print("\n" + "=" * 60)
    print("[+] 登录成功！凭据已保存至 ./data/cookie.json")
    print("[+] 你现在可以运行: python main.py --cli")
    print("=" * 60)

async def login_by_qrcode():
    """方式1：二维码登录"""
    print("\n[*] 正在初始化二维码登录...")
    
    qr = QrCodeLogin()
    
    try:
        await qr.generate_qrcode()
        
        print("\n请使用 B 站手机 App 扫描下方二维码：")
        print("(打开 App → 我的 → 扫一扫)\n")
        print(qr.get_qrcode_terminal())
        print()
        
        print("[*] 等待扫码中...")
        while True:
            state = await qr.check_state()
            
            if state == QrCodeLoginEvents.DONE:
                break
            elif state == QrCodeLoginEvents.SCAN:
                print("[*] 二维码已扫描，请在手机上确认登录...")
            elif state == QrCodeLoginEvents.TIMEOUT:
                print("[-] 二维码已过期，请重新运行此脚本。")
                return False
            elif state == QrCodeLoginEvents.CONF:
                print("[*] 正在确认登录...")
            
            await asyncio.sleep(1.5)
        
        credential = qr.get_credential()
        await save_credential(credential)
        return True
        
    except Exception as e:
        print(f"\n[-] 二维码登录失败: {e}")
        return False

async def login_by_sms():
    """方式2：手机号+验证码登录"""
    print("\n=== 手机号验证码登录 ===")
    print("[!] 注意：此方式需要完成验证码验证")
    
    try:
        from bilibili_api.login_v2 import PhoneNumber, send_sms, login_with_sms
        from bilibili_api.utils.geetest import Geetest
        
        # 获取手机号
        phone = input("\n请输入手机号: ").strip()
        if not phone:
            print("[-] 手机号不能为空")
            return False
        
        # 创建 PhoneNumber 对象
        phonenumber = PhoneNumber(phone, country='+86')
        
        # 创建 Geetest 对象（用于验证码）
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
        code = input("请输入短信验证码: ").strip()
        if not code:
            print("[-] 验证码不能为空")
            return False
        
        print("[*] 正在登录...")
        
        # 执行登录
        credential = await login_with_sms(phonenumber, code, captcha_id)
        
        await save_credential(credential)
        return True
        
    except Exception as e:
        print(f"\n[-] 短信登录失败: {e}")
        print("[!] 可能原因：")
        print("    1. 手机号格式错误")
        print("    2. 验证码错误或已过期") 
        print("    3. 需要完成滑块验证（当前环境可能不支持）")
        print("    4. B站账号安全限制")
        print("\n[!] 建议：在 Windows/Mac 本地使用二维码方式登录")
        return False

async def main():
    print("=" * 60)
    print("       BiliArchive-Pro 登录系统")
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
            print("\n[!] 非交互式环境，默认选择二维码登录...")
            choice = "1"
        
        if choice == "0":
            print("[!] 已退出")
            return
        elif choice == "1":
            success = await login_by_qrcode()
            if success:
                return
            print("\n[!] 登录失败，请重试或选择其他方式")
        elif choice == "2":
            success = await login_by_sms()
            if success:
                return
            print("\n[!] 登录失败，请重试或选择其他方式")
        else:
            print("[-] 无效选项，请重新输入")

if __name__ == "__main__":
    asyncio.run(main())
