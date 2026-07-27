import os
import sys

# ---------------------------------------------------------------------------
# ตั้งค่าการเชื่อมต่อ MuMu Player (ADB)
# ---------------------------------------------------------------------------

def get_base_dir():
    """
    หาโฟลเดอร์ฐานสำหรับอ้างอิงไฟล์ template/debug/.env
    - ถ้ารันเป็น .exe (PyInstaller): ใช้โฟลเดอร์ที่ตัว .exe วางอยู่จริง
    - ถ้ารันเป็น .py ปกติ: ใช้โฟลเดอร์ที่ไฟล์ main.py วางอยู่ (โฟลเดอร์นี้เอง เพราะ
      config.py อยู่ข้างๆ main.py เสมอ)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# BASE_DIR ต้องถูกกำหนดก่อน import secrets_loader เสมอ เพราะ secrets_loader
# ต้องใช้ BASE_DIR เพื่อหาไฟล์ .env (ไม่งั้นจะเจอ ImportError แบบเงียบๆ จาก circular import)
BASE_DIR = get_base_dir()

try:
    from secrets_loader import ADB_DEVICE_ID, ADB_PATH as SECRET_ADB_PATH
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
    3. fallback: path เดิมของผู้พัฒนา (อาจไม่ตรงกับเครื่องคุณ)
    """
    if SECRET_ADB_PATH and os.path.exists(SECRET_ADB_PATH):
        return SECRET_ADB_PATH

    from shutil import which
    found = which("adb") or which("adb.exe")
    if found:
        return found

    return r"D:\MUMU\MuMuPlayerGlobal\nx_main\adb.exe"


ADB_PATH = find_adb_path()

TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
PAUSE_SCREENSHOT_DIR = os.path.join(BASE_DIR, "pause_screenshots")  # โฟลเดอร์เก็บภาพตอนหยุดทำงาน

MATCH_THRESHOLD = 0.8         # ความมั่นใจขั้นต่ำ (0-1) ที่จะถือว่า "เจอ" ปุ่ม/ภาพ
TAP_DELAY_RANGE = (0.3, 0.6)  # หน่วงเวลาสุ่มระหว่างแต่ละครั้งที่แตะ ใน tap_loop ขณะวิ่งเกม (วินาที)
RANDOM_TAP_DELAY_RANGE = (0.03, 0.15)  # หน่วงเวลาสุ่มระหว่างการสุ่มแตะขณะรอ over_game (วินาที)
HOLD_DURATION_RANGE = (150, 300)     # ระยะเวลากดค้างแบบสุ่ม (มิลลิวินาที) เพื่อเลียนแบบมนุษย์
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

# ---------------------------------------------------------------------------
# ตั้งค่าระบบสถิติและตรวจสอบ (Phase 2)
# ---------------------------------------------------------------------------
def get_stats_file_path():
    """ดึง path ของไฟล์สถิติ แยกตาม Device/Port เพื่อไม่ให้รันหลายโปรแกรมแล้วสถิติตีกัน"""
    dev = getattr(sys.modules.get("config"), "DEVICE_ID", DEVICE_ID)
    dev_clean = dev.replace(":", "_").replace(".", "_")
    return os.path.join(BASE_DIR, f"bot_stats_{dev_clean}.json")

STATS_FILE_PATH = os.path.join(BASE_DIR, "bot_stats.json")
HEALTH_CHECK_WARNING_THRESHOLD = 0.50 # แจ้งเตือนในตอนเริ่มรันบอทหาก score ของ template ต่ำกว่า 50%

# ---------------------------------------------------------------------------
# ตั้งค่าการเลียนแบบมนุษย์ป้องกันแบน (Phase 3)
# ---------------------------------------------------------------------------
CLICK_JITTER_PIXELS = 8             # สุ่มเบี่ยงพิกัดกี่พิกเซลรอบจุดกึ่งกลางของปุ่ม (เช่น ±8 px)
AUTO_REST_INTERVAL_MINUTES = (45, 75) # สุ่มพักบอททุกๆกี่นาที (เช่น วิ่ง 45 ถึง 75 นาทีแล้วจะพัก)
AUTO_REST_DURATION_MINUTES = (3, 8)   # สุ่มระยะเวลาการพักแต่ละรอบกี่นาที (เช่น พัก 3 ถึง 8 นาที)

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
BOOST_TAP_SPEED_MS = 50             # ความรัวกด Fast Start Boost (มิลลิวินาที เช่น 50ms)

# ---------------------------------------------------------------------------
# ตั้งค่าระบบ Fast Start Boost (กดรัวทันทีตอนเริ่มวิ่ง + สแกนหาภาพ)
# ---------------------------------------------------------------------------
FAST_START_ENTRY_BURST = True               # True = กดรัวทันทีเมื่อเริ่มวิ่ง (แก้ปัญหา ADB สแกนภาพช้าไม่ทันเกม)
FAST_START_BOOST_X = 652                    # พิกัด X ปุ่ม Fast Start Boost (อ้างอิงจอ 1280x720)
FAST_START_BOOST_Y = 345                    # พิกัด Y ปุ่ม Fast Start Boost (อ้างอิงจอ 1280x720)

FAST_START_BOOST_TEMPLATE = "fast1_start.png" # ชื่อไฟล์ภาพ template ในโฟลเดอร์ templates/
FAST_START_BOOST_TAPS = 20                   # จำนวนครั้งที่กดรัว
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