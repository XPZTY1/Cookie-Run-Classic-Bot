import os
import requests  # pip install requests  (ยังใช้สำหรับ LINE Messaging API)

import src.config.settings as config
import src.config.secrets as secrets_loader

# ---------------------------------------------------------------------------
# LINE Messaging API: ส่งข้อความแจ้งเตือน
# ---------------------------------------------------------------------------


def send_line_message(text):
    """
    ส่งข้อความแจ้งเตือนแบบ push message ไปยัง LINE_USER_ID ที่ตั้งไว้
    ใช้ LINE Messaging API: POST https://api.line.me/v2/bot/message/push
    """
    if not getattr(config, "ENABLE_LINE_NOTIFY", True):
        return

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or getattr(secrets_loader, "LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID") or getattr(secrets_loader, "LINE_USER_ID", "")

    if not token:
        print("[LINE] ยังไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN ใน .env — ข้ามการแจ้งเตือน")
        return
    if not user_id:
        print("[LINE] ยังไม่ได้ตั้งค่า LINE_USER_ID ใน .env — ข้ามการแจ้งเตือน")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[LINE] ส่งข้อความแจ้งเตือนสำเร็จ")
        else:
            print(f"[LINE] ส่งข้อความไม่สำเร็จ ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[LINE] เกิดข้อผิดพลาดตอนส่งข้อความ: {e}")

