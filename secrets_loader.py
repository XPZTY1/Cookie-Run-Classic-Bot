import json
import os

from config import BASE_DIR

# ---------------------------------------------------------------------------
# โหลดค่าลับ (LINE token, Gemini API key) จากไฟล์ secrets.json แยกต่างหาก
# ---------------------------------------------------------------------------
# เหตุผลที่แยกออกมาจากโค้ด: ป้องกันไม่ให้ token/key หลุดติดไปกับซอร์สโค้ดโดยไม่ตั้งใจ
# วิธีตั้งค่า:
#   1) copy ไฟล์ secrets.example.json -> secrets.json (อยู่โฟลเดอร์เดียวกับ main.py หรือข้างๆ .exe)
#   2) เปิด secrets.json แล้วใส่ค่าจริงของคุณ
#   3) ห้าม commit / แชร์ไฟล์ secrets.json ให้ใครเห็นเด็ดขาด


def load_secrets():
    secrets_path = os.path.join(BASE_DIR, "secrets.json")
    if not os.path.exists(secrets_path):
        print("!! ไม่พบไฟล์ secrets.json")
        print("!! ให้ copy secrets.example.json -> secrets.json แล้วกรอกค่าให้ครบก่อนใช้งาน")
        return {}
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"!! อ่านไฟล์ secrets.json ไม่สำเร็จ: {e}")
        return {}


_secrets = load_secrets()
LINE_CHANNEL_ACCESS_TOKEN = _secrets.get("line_channel_access_token", "")
LINE_USER_ID = _secrets.get("line_user_id", "")
GEMINI_API_KEY = _secrets.get("gemini_api_key", "")
