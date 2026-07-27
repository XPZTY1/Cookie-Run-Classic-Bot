import json
import os

from config import BASE_DIR

# ---------------------------------------------------------------------------
# โหลดค่าลับ (LINE token, Gemini API key, Discord webhook, ADB device) จาก .env
# รองรับไฟล์ secrets.json เดิมเป็น fallback เผื่อยังไม่ได้ย้ายมาใช้ .env
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    print("!! ไม่พบไลบรารี python-dotenv กรุณาติดตั้งด้วย: pip install python-dotenv")


def get_secrets_path():
    """path ของไฟล์ secrets.json เดิม (fallback เท่านั้น ถ้ายังมีอยู่)"""
    return os.path.join(BASE_DIR, "secrets.json")


def load_legacy_secrets():
    """โหลดค่าจาก secrets.json แบบเดิม ใช้เป็น fallback ถ้าไม่มีค่าใน .env"""
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
    """
    บันทึกค่าลับลงไฟล์ .env (เขียนทับ/เพิ่มบรรทัดของ key นั้น)
    key ที่รับเข้ามาเป็นตัวพิมพ์เล็กแบบเดิม (เช่น 'line_channel_access_token')
    จะถูกแปลงเป็นชื่อ env var ตัวพิมพ์ใหญ่ให้อัตโนมัติ
    """
    env_path = os.path.join(BASE_DIR, ".env")
    env_key = key.upper()

    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{env_key}="):
            lines[i] = f"{env_key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{env_key}={value}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.environ[env_key] = str(value)
        globals()[env_key] = value
        return True
    except Exception as e:
        print(f"!! บันทึกไฟล์ .env ไม่สำเร็จ: {e}")
        return False


_legacy = load_legacy_secrets()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or _legacy.get("line_channel_access_token", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID") or _legacy.get("line_user_id", "")
GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
    or _legacy.get("gemini_api_key", "")
)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL") or _legacy.get("discord_webhook_url", "")
ADB_DEVICE_ID = os.environ.get("ADB_DEVICE_ID") or _legacy.get("adb_device_id", "127.0.0.1:5559")
ADB_PATH = os.environ.get("ADB_PATH") or _legacy.get("adb_path", "")


# ---------------------------------------------------------------------------
# Discord Webhook Profiles (รองรับหลาย Webhook พร้อมเปิด/ปิดใช้งานแยกตัว)
# เก็บเป็น JSON string ไว้ใน .env ภายใต้ key DISCORD_WEBHOOKS_JSON
# รูปแบบ: [{"name": str, "url": str, "enabled": bool}, ...]
# ---------------------------------------------------------------------------

DISCORD_WEBHOOKS_JSON = os.environ.get("DISCORD_WEBHOOKS_JSON") or _legacy.get("discord_webhooks_json", "")


def get_discord_webhooks():
    """
    คืนค่ารายการ Discord Webhook Profile ทั้งหมด เป็น list ของ dict:
    [{"name": str, "url": str, "enabled": bool}, ...]
    """
    raw = os.environ.get("DISCORD_WEBHOOKS_JSON", "") or DISCORD_WEBHOOKS_JSON
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"!! อ่าน DISCORD_WEBHOOKS_JSON ไม่สำเร็จ: {e}")

    # fallback: ถ้ายังไม่เคยตั้งค่าแบบ multi-profile แต่มี DISCORD_WEBHOOK_URL เดิมอยู่
    if DISCORD_WEBHOOK_URL:
        return [{"name": "Default", "url": DISCORD_WEBHOOK_URL, "enabled": True}]

    return []


def save_discord_webhooks(webhooks: list):
    """
    บันทึกรายการ Discord Webhook Profile ทั้งหมดลง .env (คีย์ DISCORD_WEBHOOKS_JSON)
    webhooks: list ของ dict [{"name": str, "url": str, "enabled": bool}, ...]
    """
    try:
        raw = json.dumps(webhooks, ensure_ascii=False)
    except Exception as e:
        print(f"!! แปลง webhooks เป็น JSON ไม่สำเร็จ: {e}")
        return False

    ok = save_secret("discord_webhooks_json", raw)
    if ok:
        global DISCORD_WEBHOOKS_JSON
        DISCORD_WEBHOOKS_JSON = raw
    return ok