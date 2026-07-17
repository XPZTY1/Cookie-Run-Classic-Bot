import requests  # pip install requests  (ยังใช้สำหรับ LINE Messaging API)

from secrets_loader import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

# ---------------------------------------------------------------------------
# LINE Messaging API: ส่งข้อความแจ้งเตือน
# ---------------------------------------------------------------------------


def send_line_message(text):
    """
    ส่งข้อความแจ้งเตือนแบบ push message ไปยัง LINE_USER_ID ที่ตั้งไว้
    ใช้ LINE Messaging API: POST https://api.line.me/v2/bot/message/push
    """
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[LINE] ยังไม่ได้ตั้งค่า line_channel_access_token ใน secrets.json — ข้ามการแจ้งเตือน")
        return
    if not LINE_USER_ID:
        print("[LINE] ยังไม่ได้ตั้งค่า line_user_id ใน secrets.json — ข้ามการแจ้งเตือน")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID,
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
