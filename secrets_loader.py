import json
import os

from config import BASE_DIR

# ---------------------------------------------------------------------------
# โหลดค่าลับ (LINE token, Gemini API key, ADB Device) จากไฟล์ secrets.json
# ---------------------------------------------------------------------------


def get_secrets_path():
    return os.path.join(BASE_DIR, "secrets.json")


def load_secrets():
    secrets_path = get_secrets_path()
    if not os.path.exists(secrets_path):
        return {}
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"!! อ่านไฟล์ secrets.json ไม่สำเร็จ: {e}")
        return {}


def save_secret(key, value):
    """บันทึกหรืออัปเดตค่าลับลงไฟล์ secrets.json อัตโนมัติ"""
    secrets_path = get_secrets_path()
    data = load_secrets()
    data[key] = value
    try:
        with open(secrets_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _secrets[key] = value
        return True
    except Exception as e:
        print(f"!! บันทึกไฟล์ secrets.json ไม่สำเร็จ: {e}")
        return False


def get_discord_webhooks():
    """
    ดึงรายการ Discord Webhooks ทั้งหมด [{'name': str, 'url': str, 'enabled': bool}]
    พร้อมระบบ Backward Compatibility หากเดิมมีเฉพาะ 'discord_webhook_url'
    """
    secrets = load_secrets()
    webhooks = secrets.get("discord_webhooks")
    if isinstance(webhooks, list) and len(webhooks) > 0:
        return webhooks

    old_url = secrets.get("discord_webhook_url", "")
    if old_url:
        return [{"name": "Default Webhook", "url": old_url, "enabled": True}]
    return []


def save_discord_webhooks(webhooks_list):
    """
    บันทึกรายการ Discord Webhooks ลงใน secrets.json
    """
    secrets_path = get_secrets_path()
    data = load_secrets()
    data["discord_webhooks"] = webhooks_list
    if webhooks_list:
        enabled_urls = [w["url"] for w in webhooks_list if w.get("enabled", True) and w.get("url")]
        if enabled_urls:
            data["discord_webhook_url"] = enabled_urls[0]
    try:
        with open(secrets_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _secrets["discord_webhooks"] = webhooks_list
        return True
    except Exception as e:
        print(f"!! บันทึก Discord Webhooks ไม่สำเร็จ: {e}")
        return False


_secrets = load_secrets()
LINE_CHANNEL_ACCESS_TOKEN = _secrets.get("line_channel_access_token", "")
LINE_USER_ID = _secrets.get("line_user_id", "")
GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or _secrets.get("gemini_api_key", "")
DISCORD_WEBHOOK_URL = _secrets.get("discord_webhook_url", "")
ADB_DEVICE_ID = _secrets.get("adb_device_id", "127.0.0.1:5559")
