import requests

import config
from secrets_loader import get_discord_webhooks

# ---------------------------------------------------------------------------
# Discord Webhook Notifier: ส่งรายงานสรุปผลการทำงานของบอทเข้า Discord (รองรับ Multi-Profile)
# ---------------------------------------------------------------------------

COLOR_SUCCESS = 0x22c55e   # เขียว — รายงานปกติ / สำเร็จ
COLOR_WARNING = 0xf59e0b   # เหลืองส้ม — แจ้งเตือน
COLOR_INFO    = 0x3b82f6   # น้ำเงิน — ข้อมูลทั่วไป
COLOR_ERROR   = 0xef4444   # แดง — error / crash


def get_active_discord_webhooks(target_webhook=None):
    """ดึงรายชื่อ (name, url) ของ Webhook ที่เปิดใช้งาน (enabled=True) ตามโปรไฟล์ที่เลือก"""
    if not getattr(config, "DISCORD_REPORT_ENABLED", True):
        return []

    selected_target = target_webhook or getattr(config, "SELECTED_DISCORD_WEBHOOK", "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน")
    if selected_target == "[NONE] ปิดใช้งาน":
        return []

    all_webhooks = get_discord_webhooks()
    active = []
    for item in all_webhooks:
        if isinstance(item, dict) and item.get("enabled", True) and item.get("url"):
            name = item.get("name", "Webhook Profile")
            url = item.get("url")
            if selected_target.startswith("[ALL]") or selected_target == name:
                active.append((name, url))

    if not active:
        print("[Discord] ไม่มี Discord Webhook Profile ตรงตามเงื่อนไขที่เลือก — ข้ามการรายงาน")
    return active


def send_discord_embed(title: str, fields: list, color: int = COLOR_SUCCESS, description: str = "", target_webhook: str = None):
    """
    ส่งข้อมูลรายงานเข้า Discord ให้ทุก Webhook Profile ที่เปิดใช้งานอยู่ในรูปแบบ Embed
    """
    active_webhooks = get_active_discord_webhooks(target_webhook=target_webhook)
    if not active_webhooks:
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

    for name, url in active_webhooks:
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                print(f"[Discord ({name})] ส่ง Embed สำเร็จ ✅")
            else:
                print(f"[Discord ({name})] ส่ง Embed ไม่สำเร็จ ({resp.status_code}): {resp.text[:150]}")
        except Exception as e:
            print(f"[Discord ({name})] เกิดข้อผิดพลาด: {e}")


def send_discord_report(text: str, target_webhook: str = None):
    """
    ส่งข้อความรายงานแบบ plain text ให้ทุก Webhook Profile ที่เปิดใช้งานอยู่
    """
    active_webhooks = get_active_discord_webhooks(target_webhook=target_webhook)
    if not active_webhooks:
        return

    payload = {
        "content": text,
        "username": "🍪 Cookie Run Bot",
    }

    for name, url in active_webhooks:
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                print(f"[Discord ({name})] ส่งรายงานสำเร็จ ✅")
            else:
                print(f"[Discord ({name})] ส่งรายงานไม่สำเร็จ ({resp.status_code}): {resp.text[:150]}")
        except Exception as e:
            print(f"[Discord ({name})] เกิดข้อผิดพลาด: {e}")


def send_discord_test_to_url(url: str, name: str = "Test Profile") -> bool:
    """
    ส่งข้อความทดสอบไปยัง Webhook URL รายโปรไฟล์แบบเฉพาะเจาะจง (ใช้ทดสอบใน GUI)
    """
    if not url:
        return False

    from datetime import datetime, timezone
    embed = {
        "title": f"🔔 ทดสอบการเชื่อมต่อ — โปรไฟล์ '{name}'",
        "color": COLOR_SUCCESS,
        "fields": [
            {"name": "สถานะการเชื่อมต่อ", "value": "`ใช้งานได้ปกติ ✅`", "inline": True},
            {"name": "ชื่อโปรไฟล์", "value": f"`{name}`", "inline": True}
        ],
        "footer": {
            "text": "🍪 Cookie Run Classic Auto Bot • Multi-Webhook Manager"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    payload = {
        "username": "🍪 Cookie Run Bot",
        "embeds": [embed]
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code in (200, 204)
    except Exception:
        return False
