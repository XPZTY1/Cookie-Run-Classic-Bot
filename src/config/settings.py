import os
import sys

# ---------------------------------------------------------------------------
# ตั้งค่าการเชื่อมต่อ MuMu Player (ADB)
# ---------------------------------------------------------------------------

def get_base_dir():
    """
    หาโฟลเดอร์ฐานสำหรับอ้างอิงไฟล์ template/debug/.env
    - ถ้ารันเป็น .exe (PyInstaller): ใช้โฟลเดอร์ที่ตัว .exe วางอยู่จริง
    - ถ้ารันเป็น .py ปกติ: ถอยขึ้นไปยังโฟลเดอร์โปรเจ็กต์หลัก (Project Root)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # ไฟล์ settings.py อยู่ที่ src/config/settings.py -> ถอยขึ้น 2 ชั้นไป Root
    config_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(config_dir, "..", ".."))


# BASE_DIR ต้องถูกกำหนดก่อน import src.config.secrets as secrets_loader เสมอ
BASE_DIR = get_base_dir()

try:
    from src.config.secrets import ADB_DEVICE_ID, ADB_PATH as SECRET_ADB_PATH
    DEVICE_ID = ADB_DEVICE_ID
except Exception as e:
    print(f"!! โหลดค่าจาก secrets_loader ไม่สำเร็จ ใช้ค่า default แทน: {e}")
    DEVICE_ID = "127.0.0.1:5559"
    SECRET_ADB_PATH = ""


def find_adb_path():
    """
    หา path ของ adb.exe ตามลำดับ:
    1. ค่าที่ตั้งไว้ใน .env (ADB_PATH)
    2. ค้นหาอัตโนมัติจาก PATH ของระบบ
    3. ค้นหาในตำแหน่งติดตั้งทั่วไปของ MuMu / LDPlayer
    4. fallback: path adb
    """
    if SECRET_ADB_PATH and os.path.exists(SECRET_ADB_PATH):
        return SECRET_ADB_PATH

    from shutil import which
    found = which("adb") or which("adb.exe")
    if found:
        return found

    common_paths = [
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\adb.exe",
        r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
        r"D:\MUMU\MuMuPlayerGlobal\nx_main\adb.exe",
        r"C:\Microvirt\MEmu\adb.exe",
        r"C:\LDPlayer\LDPlayer9\adb.exe",
        r"D:\LDPlayer\LDPlayer9\adb.exe",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p

    return "adb"


ADB_PATH = find_adb_path()

TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DATA_DIR = os.path.join(BASE_DIR, "data")  # โฟลเดอร์เก็บข้อมูล stats/profiles/screenshots
PAUSE_SCREENSHOT_DIR = os.path.join(DATA_DIR, "pause_screenshots")  # โฟลเดอร์เก็บภาพตอนหยุดทำงาน

MATCH_THRESHOLD = 0.70         # ความมั่นใจขั้นต่ำ (0-1) ที่จะถือว่า "เจอ" ปุ่ม/ภาพ
TAP_DELAY_RANGE = (0.03, 0.16)  # หน่วงเวลาสุ่มระหว่างแต่ละครั้งที่แตะ ใน tap_loop ขณะวิ่งเกม (วินาที)
RANDOM_TAP_DELAY_RANGE = (0.03, 0.15)  # หน่วงเวลาสุ่มระหว่างการสุ่มแตะขณะรอ over_game (วินาที)

HOLD_DURATION_RANGE = (150, 200)     # ระยะเวลากดค้างแบบสุ่ม (มิลลิวินาที) เพื่อเลียนแบบมนุษย์
HOLD_CHANCE = 0.6                   # โอกาส (0.0-1.0) ที่แต่ละครั้งจะเป็น "กดค้าง" แทน tap ธรรมดา

# ขอบเขต (สัดส่วนของหน้าจอ) ที่อนุญาตให้สุ่มแตะระหว่างรอ เพื่อไม่ให้แตะโดนขอบจอ/แถบระบบ/ปุ่มล่างจอ
# จำกัดแกน Y ห้ามเกิน 400 px (สัดส่วนไม่เกิน 0.55 ของจอ 720p) เพื่อเว้นพื้นที่ครึ่งล่างอย่างปลอดภัย
RANDOM_TAP_X_RANGE = (0.2, 0.8)
RANDOM_TAP_Y_RANGE = (0.15, 0.55)
RANDOM_TAP_MAX_Y_PX = 400  # เพดานสูงสุดของแกน Y (px อ้างอิงจอ 1280x720) ห้ามสุ่มแตะต่ำกว่าระดับนี้


# โมเดล Gemini ที่ใช้ (ฟรีเทียร์)
GEMINI_MODEL = "gemini-3.1-flash-lite"

# state เริ่มต้นทุกครั้งที่กด F6 (ใช้ร่วมกันระหว่าง bot_engine และ flows/flow_config)
INITIAL_STATE = "start_game"

# ---------------------------------------------------------------------------
# ตั้งค่าความเสถียร (Phase 1)
# ---------------------------------------------------------------------------
WATCHDOG_TIMEOUT_SECONDS = 180  # ถ้าบอทติดอยู่สถานะเดิมเกิน 3 นาที (180 วินาที) จะทำการ reset state
ADB_MAX_RECONNECT_ATTEMPTS = 5   # จำนวนครั้งสูงสุดที่จะลอง reconnect ADB ใหม่ ก่อนส่งสัญญาณหยุดหรือเตือน LINE

DEFAULT_PORT_SETTINGS = {
    "ENABLE_BOOSTER_BUY": True,
    "ENABLE_FAST_START_BOOST": True,
    "ENABLE_USE_SECOND_COOKIE": True,
    "ENABLE_LINE_NOTIFY": True,
    "ENABLE_RANDOM_TAP_WHILE_WAIT": True,
    "DISCORD_REPORT_ENABLED": True,
    "OCR_SCORE_ENABLED": True,
    "SCHEDULE_ENABLED": False,
    "SELECTED_DISCORD_WEBHOOK": "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน",
    # ระบบส่งหัวใจอัตโนมัติ
    "HEART_AUTO_ENABLED": False,
    "HEART_INTERVAL_MINUTES": 30,
    # ระบบแลกเปลี่ยน Relic อัตโนมัติ
    "RELIC_EXCHANGE_ENABLED": False,
    "RELIC_EXCHANGE_EVERY_N_RUNS": 10,
}

def get_port_settings(pdata):
    settings = dict(DEFAULT_PORT_SETTINGS)
    if isinstance(pdata, dict):
        if "settings" in pdata and isinstance(pdata["settings"], dict):
            settings.update(pdata["settings"])
        else:
            for k in DEFAULT_PORT_SETTINGS:
                if k in pdata:
                    settings[k] = pdata[k]
    return settings

PORTS_FILE_PATH = os.path.join(DATA_DIR, "saved_ports.json")

import json

def load_saved_ports():
    if os.path.exists(PORTS_FILE_PATH):
        try:
            with open(PORTS_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"อ่านไฟล์ saved_ports.json ไม่สำเร็จ: {e}")
    return {}

def save_saved_ports(ports_dict):
    try:
        with open(PORTS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(ports_dict, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"บันทึกไฟล์ saved_ports.json ไม่สำเร็จ: {e}")
        return False

def get_stats_file_path(device_id=None):
    """ดึง path ของไฟล์สถิติ แยกตาม Device/Port เพื่อไม่ให้รันหลายโปรแกรมแล้วสถิติตีกันได้"""
    dev = device_id or globals().get("DEVICE_ID", "127.0.0.1:5559")
    dev_clean = str(dev).replace(":", "_").replace(".", "_")
    return os.path.join(DATA_DIR, f"bot_stats_{dev_clean}.json")

HEALTH_CHECK_WARNING_THRESHOLD = 0.50 # แจ้งเตือนในตอนเริ่มรันบอทหาก score ของ template ต่ำกว่า 50%

# ---------------------------------------------------------------------------
# ตั้งค่าการเลียนแบบมนุษย์ป้องกันแบน (Phase 3)
# ---------------------------------------------------------------------------
CLICK_JITTER_PIXELS = 8             # สุ่มเบี่ยงพิกัดกี่พิกเซลรอบจุดกึ่งกลางของปุ่ม (เช่น ±8 px)
AUTO_REST_INTERVAL_MINUTES = (75, 180) # สุ่มพักบอททุกๆกี่นาที (เช่น วิ่ง 75 ถึง 180 นาทีแล้วจะพัก)
AUTO_REST_DURATION_MINUTES = (1, 2)   # สุ่มระยะเวลาการพักแต่ละรอบกี่นาที (เช่น พัก 1 ถึง 2 นาที)

# ---------------------------------------------------------------------------
# ตั้งค่าระบบกู้คืนเมื่อเกมพากลับไปหน้าล็อกอิน
# ---------------------------------------------------------------------------
LOGIN_TAE_TIMEOUT_SECONDS = 30  # เวลารอปุ่ม login_tae.png หลังจากกด login.png
LOGIN_POLL_INTERVAL_SECONDS = 1  # ช่วงเวลาระหว่างการตรวจหน้าจอแต่ละรอบ

# ---------------------------------------------------------------------------
# ตั้งค่าระบบสวิตช์ควบคุมและความถี่การกด (Config & Toggle Settings)
# ---------------------------------------------------------------------------
ENABLE_BOOSTER_BUY = True           # True = ซื้อไอเทมเพิ่มพลัง, False = ข้ามไปเริ่มเกมทันที (กดเริ่มเกม 2 ครั้ง)
ENABLE_FAST_START_BOOST = True      # True = กด Fast Start Boost รัวๆ, False = ปิด
ENABLE_USE_SECOND_COOKIE = True     # True = ใช้คุกกี้ตัวที่ 2 เมื่อมีให้กด, False = ปิด
ENABLE_LINE_NOTIFY = True           # True = ส่งแจ้งเตือน LINE, False = ปิด
ENABLE_RANDOM_TAP_WHILE_WAIT = True # True = สุ่มกดหน้าจอขณะรอ over_game, False = ปิด (รอเฉยๆ)
BOOST_TAP_SPEED_MS = 50             # ความรัวกด Fast Start Boost (มิลลิวินาที เช่น 50ms)

# ---------------------------------------------------------------------------
# ตั้งค่าระบบ Fast Start Boost (กดรัวทันทีตอนเริ่มวิ่ง + สแกนหาภาพ)
# ---------------------------------------------------------------------------
FAST_START_ENTRY_BURST = True               # True = กดรัวทันทีเมื่อเริ่มวิ่ง (แก้ปัญหา ADB สแกนภาพช้าไม่ทันเกม)
FAST_START_BOOST_X = 650                    # พิกัด X ปุ่ม Fast Start Boost (อ้างอิงจอ 1280x720)
FAST_START_BOOST_Y = 340                    # พิกัด Y ปุ่ม Fast Start Boost (อ้างอิงจอ 1280x720)

FAST_START_BOOST_TEMPLATE = "fast_start.png" # ชื่อไฟล์ภาพ template ในโฟลเดอร์ templates/
FAST_START_BOOST_TAPS = 25                   # จำนวนครั้งที่กดรัว
FAST_START_BOOST_THRESHOLD = 0.65           # ความแม่นยำขั้นต่ำในการสแกนหาภาพ (0.0-1.0)

# ---------------------------------------------------------------------------
# ระบบ A: Human-like Curved Swiping (Bezier) — เลียนแบบลากนิ้วโค้งมนุษย์
# ---------------------------------------------------------------------------
SWIPE_CURVE_ENABLED = True        # True = เปิดระบบลากนิ้วโค้ง (Bezier Swipe)
SWIPE_CURVE_CHANCE = 0.30         # โอกาส (0.0-1.0) ที่แต่ละกดจะเป็น Curved Swipe แทน tap ปกติ
SWIPE_CURVE_STEPS = 8             # จำนวนจุดย่อยบนเส้นโค้ง (มากขึ้น = โค้งนุ่มขึ้น แต่ช้าขึ้น)
SWIPE_CURVE_STRENGTH = 40         # ความโค้งสูงสุด (px เบี่ยงออกจากเส้นตรง)
SWIPE_CURVE_DURATION_MS = 180     # ระยะเวลารวมของการลากทั้งหมด (ms)

# ---------------------------------------------------------------------------
# ระบบ B: Scheduled Play Hours — ตารางเวลาทำงานประจำวัน
# ---------------------------------------------------------------------------
SCHEDULE_ENABLED = False          # True = เปิดระบบตารางเวลา, False = รันตลอดเวลา (default)
ACTIVE_HOURS = [                  # ช่วงเวลาที่บอทได้รับอนุญาตให้ทำงาน (h_start, m_start, h_end, m_end)
    (8,  0, 12, 0),               # 08:00 - 12:00
    (14, 0, 18, 0),               # 14:00 - 18:00
]
SCHEDULE_CHECK_INTERVAL = 30      # ตรวจสอบตารางเวลาทุกกี่วินาทีขณะพัก

# ---------------------------------------------------------------------------
# ระบบ C: Discord Webhook Reports — รายงานสรุปผลเข้า Discord
# ---------------------------------------------------------------------------
DISCORD_REPORT_ENABLED = True     # True = ส่งรายงาน Discord, False = ปิด
DISCORD_REPORT_EVERY_N_RUNS = 10  # ส่งรายงานทุกกี่รอบที่เล่นสำเร็จ

# ---------------------------------------------------------------------------
# ระบบ D: OCR Score Reading — อ่านคะแนน/เหรียญตอนจบเกมด้วย Gemini
# ---------------------------------------------------------------------------
OCR_SCORE_ENABLED = True          # True = เปิดอ่านคะแนน (ใช้ Gemini API), False = ปิด
OCR_SCORE_DELAY = 1.5             # รอกี่วินาทีหลังจบเกมก่อนจับภาพเพื่ออ่านคะแนน
SELECTED_DISCORD_WEBHOOK = "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน"  # โปรไฟล์ Webhook ที่เลือกใช้งานเฉพาะสำหรับอินสแตนซ์นี้

# ---------------------------------------------------------------------------
# ระบบ E: Auto Heart Gifting — ส่ง/รับหัวใจเพื่อนอัตโนมัติ
# ---------------------------------------------------------------------------
HEART_AUTO_ENABLED = False        # True = เปิดระบบส่ง/รับหัวใจอัตโนมัติ, False = ปิด
HEART_INTERVAL_MINUTES = 30       # ส่งหัวใจทุกๆ กี่นาที (เช่น 30 นาที)

# ---------------------------------------------------------------------------
# ระบบ F: Auto Relic Exchange — แลกเปลี่ยน Relic อัตโนมัติทุกๆ N รอบ
# ---------------------------------------------------------------------------
RELIC_EXCHANGE_ENABLED = False    # True = เปิดระบบแลก Relic อัตโนมัติ, False = ปิด
RELIC_EXCHANGE_EVERY_N_RUNS = 10  # แลก Relic ทุกๆ กี่รอบที่เล่นผ่าน (เช่น 10 รอบ)