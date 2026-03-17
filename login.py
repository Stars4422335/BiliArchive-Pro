import asyncio
import json
import os
from bilibili_api import register_client
from bilibili_api.clients.HTTPXClient import HTTPXClient
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

# 关键：注册 httpx 客户端
register_client("httpx", HTTPXClient)

async def main():
    print("=== BiliArchive-Pro 终端扫码登录 ===")
    
    # 初始化二维码登录对象
    qr = QrCodeLogin()
    
    try:
        # 生成二维码
        await qr.generate_qrcode()
        
        # 在控制台打印二维码
        print("\n请使用 B 站手机 App 扫描下方二维码：\n")
        print(qr.get_qrcode_terminal())
        
        # 轮询等待
        print("\n等待扫码中...")
        while True:
            state = await qr.check_state()
            
            if state == QrCodeLoginEvents.DONE:
                break
            elif state == QrCodeLoginEvents.SCAN:
                print("[*] 二维码已扫描，请在手机上确认登录...")
            elif state == QrCodeLoginEvents.TIMEOUT:
                print("[-] 二维码已过期，请重新运行此脚本。")
                return
            elif state == QrCodeLoginEvents.CONFIRM:
                print("[*] 正在确认登录...")
            
            await asyncio.sleep(1.5)
            
        # 登录成功，获取凭证
        credential = qr.get_credential()
        
        # 提取数据
        cookie_data = {
            "sessdata": credential.sessdata,
            "bili_jct": credential.bili_jct,
            "buvid3": credential.buvid3,
            "dedeuserid": credential.dedeuserid,
            "ac_time_value": credential.ac_time_value
        }
        
        # 写入文件
        os.makedirs("./data", exist_ok=True)
        with open("./data/cookie.json", "w", encoding="utf-8") as f:
            json.dump(cookie_data, f, indent=4)
            
        print("\n[+] 登录成功！凭据已永久保存至 ./data/cookie.json")
        print("[+] 你现在可以运行 python main.py --cli 启动核心引擎了！")
        
    except Exception as e:
        print(f"\n[-] 登录时发生意外错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())
