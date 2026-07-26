import requests

import config
from secrets_loader import DISCORD_WEBHOOK_URL

# ---------------------------------------------------------------------------
# Discord Webhook Notifier: ส่งรายงานสรุปผลการทำงานของบอทเข้า Discord
# ---------------------------------------------------------------------------
# วิธีตั้งค่า:
#   1) ไปที่ Discord Server -> Channel Settings -> Integrations -> Webhooks -> Create Webhook
#   2) Copy Webhook URL แล้วใส่ใน secrets.json ที่ key "discord_webhook_url"
#   3) ตั้งค่า DISCORD_REPORT_ENABLED = True และ DISCORD_REPORT_EVERY_N_RUNS ใน config.py

# สีของ Embed แต่ละแบบ (Discord ใช้ค่า integer ของ hex สี)
COLOR_SUCCESS = 0x22c55e   # เขียว — รายงานปกติ / สำเร็จ
COLOR_WARNING = 0xf59e0b   # เหลืองส้ม — แจ้งเตือน
COLOR_INFO    = 0x3b82f6   # น้ำเงิน — ข้อมูลทั่วไป
COLOR_ERROR   = 0xef4444   # แดง — error / crash


def _check_enabled_and_url() -> bool:
    """ตรวจสอบว่า Discord Report เปิดอยู่และมี Webhook URL ก่อนส่งทุกครั้ง"""
    if not getattr(config, "DISCORD_REPORT_ENABLED", True):
        return False
    if not DISCORD_WEBHOOK_URL:
        print("[Discord] ยังไม่ได้ตั้งค่า discord_webhook_url ใน secrets.json — ข้ามการรายงาน")
        print("[Discord] ให้เพิ่ม \"discord_webhook_url\": \"https://discord.com/api/webhooks/...\" ใน secrets.json")
        return False
    return True


def send_discord_embed(title: str, fields: list, color: int = COLOR_SUCCESS, description: str = ""):
    """
    ส่งข้อมูลรายงานเข้า Discord ในรูปแบบ Embed (สวยกว่า plain text มาก)

    title       : หัวข้อของ Embed
    fields      : list ของ dict {"name": str, "value": str, "inline": bool}
    color       : สีขอบซ้ายของ Embed (ใช้ค่า int เช่น COLOR_SUCCESS)
    description : ข้อความบรรทัดสรุปด้านบนของ Embed (optional)
    """
    if not _check_enabled_and_url():
        return

    from datetime import datetime, timezone
    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {
            "text": "🍪 Cookie Run Classic Auto Bot"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if description:
        embed["description"] = description

    payload = {
        "username": "🍪 Cookie Run Bot",
        "embeds": [embed],
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            print("[Discord] ส่ง Embed สำเร็จ ✅")
        else:
            print(f"[Discord] ส่ง Embed ไม่สำเร็จ ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        print(f"[Discord] เกิดข้อผิดพลาดตอนส่ง Embed: {e}")


def send_discord_report(text: str):
    """
    ส่งข้อความรายงานแบบ plain text ผ่าน Discord Webhook (backward compatibility)
    text: ข้อความที่ต้องการส่ง (รองรับ Discord Markdown)
    """
    if not _check_enabled_and_url():
        return

    payload = {
        "content": text,
        "username": "🍪 Cookie Run Bot",
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            print("[Discord] ส่งรายงานสำเร็จ ✅")
        else:
            print(f"[Discord] ส่งรายงานไม่สำเร็จ ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        print(f"[Discord] เกิดข้อผิดพลาดตอนส่งรายงาน: {e}")
