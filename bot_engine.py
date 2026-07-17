import os
import sys
import random
import time
from datetime import datetime

import cv2
import re
import json
from config import (
    INITIAL_STATE,
    MATCH_THRESHOLD,
    PAUSE_SCREENSHOT_DIR,
    RANDOM_TAP_X_RANGE,
    RANDOM_TAP_Y_RANGE,
    TAP_DELAY_RANGE,
    HOLD_DURATION_RANGE,
    HOLD_CHANCE,
    WATCHDOG_TIMEOUT_SECONDS,
    ADB_MAX_RECONNECT_ATTEMPTS,
    STATS_FILE_PATH,
    HEALTH_CHECK_WARNING_THRESHOLD,
    CLICK_JITTER_PIXELS,
    AUTO_REST_INTERVAL_MINUTES,
    AUTO_REST_DURATION_MINUTES,
    LOGIN_TAE_TIMEOUT_SECONDS,
    LOGIN_POLL_INTERVAL_SECONDS,
)
from adb_client import adb_connect, adb_tap, adb_long_press, get_screen_size, grab_screen
from template_matcher import find_template
from notifiers.line_notifier import send_line_message
from notifiers.gemini_vision import describe_image_with_gemini
from flows.flow_config import FLOW
from flows.interrupts_config import INTERRUPTS
from flows.pause_events_config import PAUSE_EVENTS

# ---------------------------------------------------------------------------
# state ของบอท (module-level, เหมือนตอนเป็นไฟล์เดียว)
# ---------------------------------------------------------------------------
running = False
current_state = INITIAL_STATE
paused_event_active = None

# ตัวแปรระบบเสถียรภาพ
state_start_time = time.time()
last_state_check = INITIAL_STATE
adb_fail_count = 0
_last_reconnect_line_time = 0   # cooldown กันส่ง LINE ซ้ำตอน ADB reconnect

# ตัวแปรเก็บสถิติ session ปัจจุบัน
session_stats = {
    "total_runs": 0,
    "successful_runs": 0,
    "watchdog_resets": 0,
    "adb_disconnects": 0,
    "start_time": None,
    "elapsed_seconds": 0
}

# ตัวแปรระบบเลียนแบบมนุษย์ป้องกันแบน (Phase 3)
session_run_start_time = None
next_rest_time = None
is_resting = False

# สถานะระบบกู้คืนหน้า Login
# เมื่อเริ่มขั้นตอนนี้ บอทจะไม่ทำงานตาม FLOW หรือกด Interrupt อื่นจนกว่าจะกด login_tae สำเร็จ
login_recovery_active = False
login_recovery_started_at = None

# ฟังก์ชัน Callback สำหรับส่ง Log ไปแสดงที่ GUI
_gui_log_callback = None

def set_gui_log_callback(callback):
    global _gui_log_callback
    _gui_log_callback = callback

def log_info(msg):
    """ส่งข้อมูลที่เป็นภาษาไทยสวยงามอ่านง่ายไปที่ GUI และแสดงที่ Terminal ด้วย"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    
    # ส่งไปแสดงที่ Terminal (stdout จริง)
    sys_stdout_write(formatted_msg + "\n")
    
    # ส่งไปแสดงที่ GUI
    if _gui_log_callback:
        _gui_log_callback(formatted_msg)

def log_debug(msg):
    """พิมพ์ข้อมูล debug เชิงลึกและทางเทคนิคเฉพาะที่ Terminal (PowerShell) เท่านั้น"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    sys_stdout_write(f"[{timestamp}] [DEBUG] {msg}\n")

# เซฟตัวเขียน stdout เดิมของระบบเพื่อใช้งานตอนสั่ง log
sys_stdout_write = sys.__stdout__.write

_interrupt_last_click = {}


# ---------------------------------------------------------------------------
# ฟังก์ชันระบบจัดการสถิติ (Stats Tracker)
# ---------------------------------------------------------------------------

def load_global_stats():
    """โหลดสถิติรวมทั้งหมดจากไฟล์ json"""
    if os.path.exists(STATS_FILE_PATH):
        try:
            with open(STATS_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "all_time_runs": 0,
        "all_time_success": 0,
        "all_time_watchdog_resets": 0,
        "history": []
    }

def save_global_stats(session_done=False):
    """บันทึกสถิติรวมและข้อมูลประวัติประจุลงไฟล์ json"""
    global_stats = load_global_stats()
    
    # อัปเดตข้อมูล Session ล่าสุด
    if session_done and session_stats["start_time"] is not None:
        elapsed = int(time.time() - session_stats["start_time"])
        session_stats["elapsed_seconds"] = elapsed
        
        global_stats["all_time_runs"] += session_stats["total_runs"]
        global_stats["all_time_success"] += session_stats["successful_runs"]
        global_stats["all_time_watchdog_resets"] += session_stats["watchdog_resets"]
        
        # บันทึกลงประวัติ history
        history_entry = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "runs": session_stats["total_runs"],
            "success": session_stats["successful_runs"],
            "watchdog_resets": session_stats["watchdog_resets"],
            "adb_disconnects": session_stats["adb_disconnects"],
            "duration_seconds": elapsed
        }
        global_stats["history"].append(history_entry)
        # เก็บประวัติย้อนหลังแค่ 50 รายการล่าสุด
        if len(global_stats["history"]) > 50:
            global_stats["history"].pop(0)

    try:
        with open(STATS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(global_stats, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Stats] ไม่สามารถเขียนไฟล์สถิติได้: {e}")

def print_session_report():
    """แสดงรายงานสถิติประจุใน Console"""
    if session_stats["start_time"] is None:
        return
    elapsed = int(time.time() - session_stats["start_time"])
    m, s = divmod(elapsed, 60)
    h, m = divmod(m, 60)
    print("\n" + "="*40)
    print("📊 สรุปสถิติการทำงานในเซสชันนี้")
    print(f"⏱️ เวลาที่เปิดบอท: {h:02d}:{m:02d}:{s:02d}")
    print(f"🔄 เล่นเกมทั้งหมด: {session_stats['total_runs']} รอบ")
    print(f"🏆 เล่นผ่านสมบูรณ์: {session_stats['successful_runs']} รอบ")
    print(f"⚠️ โดนรีเซ็ตจากบอทค้าง: {session_stats['watchdog_resets']} ครั้ง")
    print(f"📡 ADB หลุดสะสม: {session_stats['adb_disconnects']} ครั้ง")
    print("="*40 + "\n")


# ---------------------------------------------------------------------------
# ฟังก์ชันระบบวิเคราะห์ความพร้อมก่อนรันบอท (Template Health Check)
# ---------------------------------------------------------------------------

def run_templates_health_check():
    """
    ตรวจสอบคะแนน Template Matching เบื้องต้นก่อนรัน
    เพื่อประเมินว่าตัวบอทจะระบุภาพและปุ่มได้ดีเพียงใด
    """
    print("\n🔍 กำลังสแกนตรวจสอบความพร้อมของภาพ Template ในโฟลเดอร์...")
    screen = grab_screen()
    if screen is None:
        print("❌ ตรวจสอบไม่สำเร็จ: ไม่สามารถดึงหน้าจอ LDPlayer ได้ กรุณาเชื่อมต่อ ADB ก่อน")
        return
        
    from config import TEMPLATE_DIR
    if not os.path.exists(TEMPLATE_DIR):
        print("❌ ไม่พบโฟลเดอร์เก็บไฟล์ภาพ templates/!")
        return
        
    all_files = [f for f in os.listdir(TEMPLATE_DIR) if f.endswith(".png")]
    if not all_files:
        print("❌ ไม่มีไฟล์ template ใดๆ ในระบบ")
        return
        
    low_scores = []
    print(f"{'ชื่อไฟล์ภาพ':<30} {'ความพร้อมประเมิน':<15}")
    print("-" * 50)
    
    for f in all_files:
        path = os.path.join(TEMPLATE_DIR, f)
        tmpl = cv2.imread(path)
        if tmpl is None:
            continue
        try:
            res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            
            # ถ้า score ต่ำกว่าที่ใช้จริง
            status = "✅ พร้อมใช้งาน"
            if max_val < MATCH_THRESHOLD:
                if max_val < HEALTH_CHECK_WARNING_THRESHOLD:
                    status = "❌ ควรตรวจใหม่ (ต่ำมาก)"
                    low_scores.append((f, max_val))
                else:
                    status = "⚠️ พอใช้ได้ (เสี่ยง)"
                    
            print(f"{f:<30} {max_val:<6.2f} ({status})")
        except Exception:
            pass
            
    if low_scores:
        print("\n⚠️ ข้อแนะนำสำหรับการรันบอท:")
        for name, score in low_scores:
            print(f"  - ภาพ '{name}' มีการตอบรับต่ำ ({score:.2f}) แนะนำให้ใช้โหมด --capture ใหม่เพื่อความแม่นยำ")
    else:
        print("\n🚀 ภาพ Template สำคัญส่วนใหญ่พร้อมใช้งานแล้ว!")
    print("-" * 50 + "\n")


# ---------------------------------------------------------------------------
# บันทึกภาพหน้าจอตอนเกิด pause event
# ---------------------------------------------------------------------------

def save_pause_screenshot(screen, event_name):
    """
    เซฟภาพหน้าจอตอนที่เกิด pause event ไว้ในโฟลเดอร์ pause_screenshots/
    ตั้งชื่อไฟล์ตาม event + timestamp เพื่อไม่ให้ทับกัน
    คืนค่า path ของไฟล์ที่เซฟ หรือ None ถ้าเซฟไม่สำเร็จ
    """
    try:
        os.makedirs(PAUSE_SCREENSHOT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{event_name}_{timestamp}.png"
        save_path = os.path.join(PAUSE_SCREENSHOT_DIR, filename)
        cv2.imwrite(save_path, screen)
        print(f"[pause] เซฟภาพหน้าจอไว้ที่: {save_path}")
        return save_path
    except Exception as e:
        print(f"[pause] เซฟภาพไม่สำเร็จ: {e}")
        return None


# ---------------------------------------------------------------------------
# ฟังก์ชันจัดการการพักสายตาบอทป้องกันแบน (Auto Rest Scheduler)
# ---------------------------------------------------------------------------

def calculate_next_rest():
    """คำนวณสุ่มเวลาพักบอทรอบถัดไป"""
    global next_rest_time
    interval = random.randint(*AUTO_REST_INTERVAL_MINUTES) * 60
    next_rest_time = time.time() + interval
    print(f"🕒 [Scheduler] กำหนดการหยุดพักบอทรอบถัดไปในอีก {interval//60} นาที")


def check_and_trigger_rest():
    """ตรวจสอบว่าถึงกำหนดเวลาพักสายตาของบอทหรือยัง ถ้าถึงจะเข้าสู่โหมดพักนอน"""
    global is_resting, next_rest_time, running
    if not running or next_rest_time is None:
        return False
        
    if time.time() >= next_rest_time:
        is_resting = True
        rest_duration_min = random.randint(*AUTO_REST_DURATION_MINUTES)
        rest_duration_sec = rest_duration_min * 60
        
        msg = f"😴 [Scheduler] บอทเริ่มหยุดพักสายตาจำลองมนุษย์เป็นเวลา {rest_duration_min} นาที เพื่อความปลอดภัย..."
        print(msg)
        send_line_message(msg)
        
        # วนรอบนอนหลับพักเหนื่อย
        rest_end = time.time() + rest_duration_sec
        while time.time() < rest_end:
            if not running: # ถ้าสั่งกด F7 ระหว่างพัก ก็ให้ออกจากลูป
                is_resting = False
                return False
            time.sleep(1)
            
        is_resting = False
        msg_resume = "🚀 [Scheduler] พักสายตาเสร็จแล้ว! บอทเริ่มวิ่งต่อ..."
        print(msg_resume)
        send_line_message(msg_resume)
        
        # สุ่มช่วงรันรอบถัดไปต่อ
        calculate_next_rest()
        return True
        
    return False


# ---------------------------------------------------------------------------
# Action ที่บอทจะทำเมื่อเจอสถานะต่างๆ
# ---------------------------------------------------------------------------

def do_click(pos):
    """
    คลิกที่พิกัด (x, y) 
    [Phase 3 Jitter] สุ่มเบี่ยงเบนตำแหน่งกดรอบๆ จุดศูนย์กลางเพื่อป้องกันการแบน
    """
    x = pos[0] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
    y = pos[1] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
    adb_tap(x, y)
    time.sleep(random.uniform(0.3, 0.6))


def do_tap_loop(pos, duration=0.6):
    """
    แตะจอรัวๆ บริเวณที่เจอ 'running_screen'
    ใช้ระหว่างวิ่งเพื่อเก็บของ/กระโดดต่อเนื่อง
    [Phase 3 Jitter] สุ่มเบี่ยงเบนตำแหน่งในทุกลูปที่กดซ้ำ
    """
    end_time = time.time() + duration
    while time.time() < end_time:
        if not running:
            break
        # สุ่มเบี่ยงตำแหน่งกดเล็กน้อยเพื่อไม่ให้กดพิกัดเป๊ะทุกครั้ง
        x = pos[0] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        y = pos[1] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        adb_tap(x, y)
        time.sleep(random.uniform(*TAP_DELAY_RANGE))


def do_random_tap_loop(duration):
    """
    สุ่มแตะตำแหน่งต่างๆ บนหน้าจอไปเรื่อยๆ เป็นเวลา `duration` วินาที
    แต่ละครั้งจะสุ่มว่าจะเป็น tap ธรรมดา หรือ กดค้าง (hold) ตาม HOLD_CHANCE
    พร้อมระยะเวลา hold แบบสุ่ม เพื่อเลียนแบบการกดของมนุษย์ให้มากที่สุด
    ใช้ระหว่าง "รอ" template ของ state ที่ตั้งค่า tap_while_wait=True
    """
    screen_w, screen_h = get_screen_size()
    x_min = int(screen_w * RANDOM_TAP_X_RANGE[0])
    x_max = int(screen_w * RANDOM_TAP_X_RANGE[1])
    y_min = int(screen_h * RANDOM_TAP_Y_RANGE[0])
    y_max = int(screen_h * RANDOM_TAP_Y_RANGE[1])

    end_time = time.time() + duration
    while time.time() < end_time:
        if not running:
            break
        x = random.randint(x_min, x_max)
        y = random.randint(y_min, y_max)

        if random.random() < HOLD_CHANCE:
            # กดค้าง: สุ่มระยะเวลาภายใน HOLD_DURATION_RANGE (ms)
            hold_ms = random.randint(*HOLD_DURATION_RANGE)
            print(f"[random_tap] hold ({x},{y}) {hold_ms}ms")
            adb_long_press(x, y, hold_ms)
        else:
            # tap ธรรมดา
            print(f"[random_tap] tap  ({x},{y})")
            adb_tap(x, y)

        # หน่วงเพิ่มระหว่างการกดแต่ละครั้ง เพื่อเลียนแบบช่วงเว้นของมนุษย์
        time.sleep(random.uniform(*TAP_DELAY_RANGE))


ACTION_FUNCS = {
    "click": do_click,
    "tap_loop": do_tap_loop,
}


# ---------------------------------------------------------------------------
# ตรวจจับ interrupts / pause events
# ---------------------------------------------------------------------------

def check_interrupts(screen):
    """
    เช็ค template ใน INTERRUPTS ทุกตัวจากภาพ screen ที่ให้มา
    ถ้าเจอตัวใดตัวหนึ่ง (และพ้น cooldown แล้ว) จะกดทันทีแล้วคืนค่า True
    ถ้าไม่เจอเลย คืนค่า False
    """
    now = time.time()
    for name, cfg in INTERRUPTS.items():
        last_click = _interrupt_last_click.get(name, 0)
        cooldown = cfg.get("cooldown", 1.0)
        if now - last_click < cooldown:
            continue

        threshold = cfg.get("threshold", MATCH_THRESHOLD)
        match = find_template(screen, cfg["template"], threshold=threshold)
        if match:
            log_info(f"⚡ แก้ไขป๊อปอัปขัดจังหวะ: {name}")
            log_debug(f"[interrupt] เจอ {name} ({cfg['template']}) -> กดตำแหน่ง {match}")
            do_click(match)
            _interrupt_last_click[name] = now
            return True

    return False


def check_pause_events(screen):
    """
    เช็ค template ใน PAUSE_EVENTS ทุกตัวจากภาพ screen ที่ให้มา
    คืนค่าชื่อ event แรกที่เจอ (str) หรือ None ถ้าไม่เจอเลย
    """
    for name, cfg in PAUSE_EVENTS.items():
        threshold = cfg.get("threshold", MATCH_THRESHOLD)
        match = find_template(screen, cfg["template"], threshold=threshold)
        if match:
            return name
    return None


def handle_login_recovery(screen):
    """
    จัดการกรณีเกมเด้งกลับไปหน้าล็อกอินตามลำดับที่กำหนด:

    1. เจอ login.png -> กด login.png เพียงครั้งเดียว
    2. รอและตรวจหา login_tae.png -> เมื่อเจอจึงกด
    3. รีเซ็ต state กลับไป INITIAL_STATE เหมือนเริ่มเกมรอบใหม่

    คืนค่า True เมื่อระบบ Login กำลังทำงานหรือเพิ่งทำงานเสร็จ
    เพื่อให้ bot_loop ข้าม Pause Events, Interrupts และ FLOW ในรอบนั้น
    """
    global login_recovery_active, login_recovery_started_at
    global current_state, paused_event_active, state_start_time, last_state_check
    global adb_fail_count

    # ถ้ายังไม่ได้เริ่มกู้คืน ให้ตรวจหา login.png ก่อน
    if not login_recovery_active:
        login_match = find_template(screen, "login.png")
        if not login_match:
            return False

        login_recovery_active = True
        login_recovery_started_at = time.time()
        log_info("🔐 ตรวจพบหน้าล็อกอิน: หยุด Flow ชั่วคราวและกำลังกด login.png")
        log_debug(f"[login] เจอ login.png -> กดตำแหน่ง {login_match}")
        do_click(login_match)
        return True

    # ระหว่างกู้คืน Login ห้ามปล่อยให้ระบบไปทำงานตาม FLOW เดิม
    # ใช้ภาพหน้าจอที่ bot_loop จับมาแล้ว เพื่อไม่ต้องเรียก ADB ซ้ำในรอบเดียวกัน
    login_tae_match = find_template(screen, "login_tae.png")
    if login_tae_match:
        log_info("👤 พบปุ่ม login_tae.png: กำลังกดเลือกบัญชี")
        log_debug(f"[login] เจอ login_tae.png -> กดตำแหน่ง {login_tae_match}")
        do_click(login_tae_match)

        # รีเซ็ตเฉพาะการทำงานของ Flow ไม่รีเซ็ตสถิติของ Session ปัจจุบัน
        current_state = INITIAL_STATE
        paused_event_active = None
        state_start_time = time.time()
        last_state_check = INITIAL_STATE
        adb_fail_count = 0
        login_recovery_active = False
        login_recovery_started_at = None

        log_info("✅ ล็อกอินสำเร็จ: รีเซ็ต Flow กลับไปเริ่มเกมใหม่แล้ว")
        return True

    # ถ้ารอนานเกินกำหนด ให้แจ้งเตือนแต่ยังคงอยู่ใน Login Recovery
    # เพื่อป้องกันไม่ให้บอทกลับไปกดปุ่มของเกมผิดหน้า
    elapsed = time.time() - (login_recovery_started_at or time.time())
    if elapsed >= LOGIN_TAE_TIMEOUT_SECONDS:
        log_info(
            f"⚠️ ยังไม่พบ login_tae.png หลังรอ {LOGIN_TAE_TIMEOUT_SECONDS} วินาที "
            "บอทยังคงหยุดรออยู่"
        )
        login_recovery_started_at = time.time()

    time.sleep(LOGIN_POLL_INTERVAL_SECONDS)
    return True


def handle_pause_start(pause_name, screen):
    """
    ทำงานตอนเพิ่งตรวจเจอ pause event ครั้งแรก:
    เซฟภาพ -> ให้ Gemini บรรยาย -> ส่งเข้า LINE
    """
    cfg = PAUSE_EVENTS[pause_name]
    log_info(f"⚠️ หยุดชั่วคราว: {cfg['message'].split(':')[-1].strip()}")
    log_debug(f"[pause] เจอ {pause_name} ({cfg['template']}) -> หยุดทำงานรอผู้ใช้")

    # เซฟภาพหน้าจอลงไฟล์ก่อน แล้วให้ Gemini "อ่านจากไฟล์ที่บันทึกไว้จริงๆ"
    # (ไม่ใช้ภาพสดในหน่วยความจำ) เพื่อให้คำอธิบายตรงกับภาพที่แนบไปกับ LINE เป๊ะๆ
    screenshot_path = save_pause_screenshot(screen, pause_name)
    description = describe_image_with_gemini(screenshot_path)

    message_parts = [cfg["message"]]
    if description:
        message_parts.append(f"\nรายละเอียดจาก Gemini: {description}")
    if screenshot_path:
        message_parts.append(f"\nภาพถูกเก็บไว้ที่เครื่อง: {os.path.basename(screenshot_path)}")

    send_line_message("\n".join(message_parts))

    if description:
        click_gemini_position(description, screen)

    return description


def gemini_text_to_int(description):
    text = description
    pattern = r'\((-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\)'
    matches = re.findall(pattern, text)
    
    # แปลง string เป็นตัวเลข (int หรือ float)
    def to_number(s):
        return float(s) if '.' in s else int(s)
    
    pairs = [(to_number(x), to_number(y)) for x, y in matches]
    return pairs


def click_gemini_position(description, screen):
    """
    แปลงข้อความจาก Gemini เป็นพิกัด แล้วสั่งคลิกที่ตำแหน่งนั้น
    โดยสเกลพิกัดให้ตรงกับขนาดหน้าจอจริงของ LDPlayer
    """
    pairs = gemini_text_to_int(description)
    if not pairs:
        print("[click_gemini] ไม่พบพิกัดใน description")
        return

    x, y = pairs[0]  # เอาคู่แรกที่เจอ

    # ดึงขนาดหน้าจอจริงของ LDPlayer เพื่อนำมาสเกลพิกัดอย่างถูกต้อง (คำนวณจากจอฐาน 1280x720)
    screen_w, screen_h = get_screen_size()

    # [Bug fix] เพิ่ม return เมื่อค่าพิกัดอยู่นอกช่วงที่รองรับ
    # เพื่อป้องกัน UnboundLocalError จาก real_x / real_y ที่ไม่ถูก assign
    if x == 1:
        base_x = 450
    elif x == 2:
        base_x = 650
    elif x == 3:
        base_x = 850
    else:
        print(f"[click_gemini] ค่า x={x} ไม่รองรับ (รองรับแค่ 1,2,3)")
        return

    if y == 1:
        base_y = 300
    elif y == 2:
        base_y = 600
    else:
        print(f"[click_gemini] ค่า y={y} ไม่รองรับ (รองรับแค่ 1,2)")
        return

    # สเกลพิกัดตามขนาดหน้าจอจริงเทียบกับหน้าจอฐาน 1280x720
    real_x = int((base_x / 1280.0) * screen_w)
    real_y = int((base_y / 720.0) * screen_h)

    do_click((real_x, real_y))


# ---------------------------------------------------------------------------
# Loop หลักของบอท
# ---------------------------------------------------------------------------

def bot_loop():
    global running, current_state, paused_event_active
    global state_start_time, last_state_check, adb_fail_count, _last_reconnect_line_time
    
    log_info("🤖 บอทเตรียมตัวรันระบบออโต้...")
    log_debug("บอทเริ่มทำงาน... (กด F7 เพื่อหยุด)")
    state_start_time = time.time()
    last_state_check = current_state
    adb_fail_count = 0
    _last_reconnect_line_time = 0

    while True:
        try:
            if not running:
                time.sleep(0.2)
                continue

            # -------------------------------------------------------------
            # [Phase 3] ระบบตรวจสอบและทำงานโหมดพักสายตาบอท
            # -------------------------------------------------------------
            if check_and_trigger_rest():
                # ถ้าพึ่งพักสายตาเสร็จ ให้เริ่มตั้งค่าการนับ watchdog และข้ามไปตรวจจอใหม่ทันที
                state_start_time = time.time()
                continue

            # -------------------------------------------------------------
            # ตรวจจับ Watchdog (ถ้าติดอยู่ State เดิมนานเกินไป)
            # [Bug fix] ข้ามการเช็ค Watchdog ระหว่าง:
            #   - paused_event_active: บอทหยุดรอผู้ใช้อยู่ ไม่ควร reset
            #   - tap_while_wait state: กำลังวิ่งเกมอยู่ตามปกติ Watchdog ไม่ควร fire
            # -------------------------------------------------------------
            current_step = FLOW.get(current_state, {})
            is_tap_while_wait_state = current_step.get("tap_while_wait", False)
            
            if current_state != last_state_check:
                # เปลี่ยน State แล้ว -> รีเซ็ตตัวนับเวลาของ Watchdog
                state_start_time = time.time()
                last_state_check = current_state
            elif not paused_event_active and not is_tap_while_wait_state:
                # เช็ค Watchdog เฉพาะตอน: ไม่ได้ pause และไม่ได้อยู่ใน state ที่ต้องรอนาน
                elapsed_time = time.time() - state_start_time
                if elapsed_time > WATCHDOG_TIMEOUT_SECONDS:
                    msg = f"⚠️ [Watchdog] บอทติดอยู่สถานะ '{current_state}' นานเกิน {WATCHDOG_TIMEOUT_SECONDS} วินาที! จะทำการรีเซ็ตกลับไปสถานะเริ่มต้น"
                    log_info(f"🔄 ตรวจพบสถานะนิ่งเกินกำหนด: กำลัง Reset บอทไปเริ่มต้นใหม่")
                    log_debug(msg)
                    send_line_message(msg)
                    
                    # รีเซ็ตสถานะกลับไปเป็นค่าเริ่มต้น
                    current_state = INITIAL_STATE
                    state_start_time = time.time()
                    
                    # อัปเดตสถิติ
                    session_stats["watchdog_resets"] += 1
                    save_global_stats()
                    time.sleep(1)
                    continue

            # -------------------------------------------------------------
            # ดึงภาพหน้าจอพร้อมตัวดักจับความล้มเหลวของ ADB (Auto-Reconnect)
            # -------------------------------------------------------------
            screen = grab_screen()
            if screen is None:
                adb_fail_count += 1
                log_debug(f"[ADB Error] จับภาพหน้าจอไม่สำเร็จ ({adb_fail_count}/{ADB_MAX_RECONNECT_ATTEMPTS})")
                
                if adb_fail_count >= ADB_MAX_RECONNECT_ATTEMPTS:
                    # [Bug fix] ส่ง LINE เฉพาะทุกๆ 60 วินาที ป้องกัน spam
                    now = time.time()
                    if now - _last_reconnect_line_time > 60:
                        msg = "🚨 [ADB Error] การเชื่อมต่อ LDPlayer ขัดข้องสะสม! กำลังพยายามบังคับ Reconnect ใหม่..."
                        log_info("🔌 กำลัง Reconnect สัญญาณ ADB...")
                        log_debug(msg)
                        send_line_message(msg)
                        _last_reconnect_line_time = now
                    else:
                        log_debug("🚨 [ADB Error] ครบขีดจำกัด กำลัง Reconnect... (ไม่ส่ง LINE ซ้ำ)")
                    
                    # พยายาม reconnect ใหม่ และรีเซ็ต adb_fail_count เสมอ
                    # เพื่อไม่ให้ trigger reconnect ทุก loop ซ้ำโดยไม่มี backoff
                    if adb_connect():
                        log_info("🔌 เชื่อมต่อ LDPlayer สำเร็จ!")
                        log_debug("✅ [ADB Reconnect] เชื่อมต่อสำเร็จแล้ว ทำงานต่อ...")
                    else:
                        log_info("❌ เชื่อมต่อ LDPlayer ไม่สำเร็จ! รอ 2 วิเพื่อลองใหม่")
                        log_debug("❌ [ADB Reconnect] เชื่อมต่อไม่สำเร็จ รอสักครู่แล้วจะลองใหม่")
                    
                    # อัปเดตสถิติ
                    session_stats["adb_disconnects"] += 1
                    save_global_stats()
                    adb_fail_count = 0  # รีเซ็ตเสมอ เพื่อให้มี backoff ก่อน trigger ซ้ำ
                        
                time.sleep(2)
                continue
            else:
                # แกรบผ่านแล้ว เคลียร์ประวัติตัวนับหลุด
                adb_fail_count = 0

            # -------------------------------------------------------------
            # 1) เช็คระบบกู้คืนหน้า Login ก่อนทุกระบบ
            #    เพื่อไม่ให้ Pause Events / Interrupts / FLOW มากดปุ่มผิดหน้า
            # -------------------------------------------------------------
            if handle_login_recovery(screen):
                continue

            # -------------------------------------------------------------
            # 2) เช็ค PAUSE_EVENTS — ถ้าเจอให้หยุดทุกอย่างและรอ
            # -------------------------------------------------------------
            if PAUSE_EVENTS:
                pause_name = check_pause_events(screen)

                if pause_name:
                    cfg = PAUSE_EVENTS[pause_name]
                    if paused_event_active != pause_name:
                        handle_pause_start(pause_name, screen)
                        paused_event_active = pause_name
                    else:
                        print(f"[pause] ยังอยู่ในสถานะหยุด ({pause_name}) — รอต่อ...")
                        save_pause_screenshot(screen, pause_name)

                    time.sleep(cfg.get("check_interval", 2))
                    continue

                elif paused_event_active is not None:
                    resumed_cfg = PAUSE_EVENTS.get(paused_event_active, {})
                    log_info("✅ กลับมาทำงานต่อตามปกติ")
                    log_debug(f"[pause] {paused_event_active} หายไปแล้ว -> กลับมาทำงานต่อจาก state: {current_state}")
                    resume_message = resumed_cfg.get("resume_message")
                    if resume_message:
                        send_line_message(resume_message)
                    paused_event_active = None

            # -------------------------------------------------------------
            # 3) เช็ค interrupt — ถ้าเจอให้กดแล้ววนรอบใหม่ทันที
            # -------------------------------------------------------------
            if INTERRUPTS and check_interrupts(screen):
                continue

            # -------------------------------------------------------------
            # 4) ทำงานตาม FLOW ปกติ
            # -------------------------------------------------------------
            step = FLOW[current_state]
            template_name = step["template"]
            action_name = step["action"]
            next_state = step["next_state"]
            delay = step.get("delay", 1)
            tap_while_wait = step.get("tap_while_wait", False)

            match = find_template(screen, template_name)

            if match:
                action_func = ACTION_FUNCS[action_name]
                
                # แสดงข้อมูลแบบเป็นมิตรบน GUI
                if current_state == "start_game":
                    log_info("🍪 คลิกเริ่มรันรอบใหม่...")
                elif current_state == "item_boots":
                    log_info("⚡ คลิกเลือกบูสเตอร์เพิ่มพลัง...")
                elif current_state == "click_multi":
                    log_info("🛍️ คลิกเลือกซื้อไอเทม...")
                elif current_state == "multi_buy":
                    log_info("🛒 กดยืนยันการซื้อไอเทมสำรอง...")
                elif current_state == "let_go":
                    log_info("🚀 คุกกี้กระโดดเริ่มออกวิ่งแล้ว! ปล่อยบอททำงานอัตโนมัติ...")
                elif current_state == "over_game":
                    log_info("🏁 คุกกี้ชน/หมดพลัง: กดยืนยันสิ้นสุดเกม...")
                    
                log_debug(f"[match] เจอ template: {template_name} -> ทำ action: {action_name} ที่พิกัด {match}")
                
                action_func(match)

                if next_state != current_state:
                    log_debug(f"   -> เปลี่ยน state: {current_state} -> {next_state}")
                    
                    # ตรวจสอบการนับรอบการทำงาน (Cycle Complete)
                    # เมื่อเปลี่ยนจาก over_game ไป start_game (หรือเริ่มรอบใหม่)
                    if current_state == "over_game" and next_state == INITIAL_STATE:
                        session_stats["successful_runs"] += 1
                        session_stats["total_runs"] += 1
                        log_info(f"🏆 เล่นผ่านสำเร็จแล้วรอบที่ {session_stats['successful_runs']}!")
                        save_global_stats()
                    elif current_state == INITIAL_STATE:
                        # เริ่มนับรอบใหม่ (กรณีบอทพึ่งเริ่มรัน)
                        if session_stats["total_runs"] == 0:
                            session_stats["total_runs"] = 1
                            save_global_stats()
                            
                    current_state = next_state

                time.sleep(delay)
            else:
                log_debug(f"[{current_state}] ยังไม่เจอ {template_name}... กำลังสแกนหา")
                if tap_while_wait:
                    # ปรับเป็น log_debug แทนเพื่อไม่ให้ terminal GUI รก
                    log_debug(f"[over_game] สุ่มกดปุ่มกระโดดต่อเนื่อง...")
                    do_random_tap_loop(delay)
                else:
                    time.sleep(delay)
                    
        except Exception as crash_err:
            msg = f"🚨 [Crash Recovery] เกิด Error ใน Bot Loop: {crash_err}\nบอทจะรอ 5 วินาทีก่อนเริ่มการรันในลูปใหม่อัตโนมัติ"
            log_info("🚨 บอทเกิดข้อผิดพลาดขัดข้อง! กำลังเปิดระบบกู้คืนใน 5 วิ...")
            log_debug(msg)
            try:
                send_line_message(msg)
            except Exception:
                pass
            time.sleep(5)


# ---------------------------------------------------------------------------
# Hotkey handlers
# ---------------------------------------------------------------------------

def start_bot():
    global running, current_state, state_start_time, last_state_check
    global login_recovery_active, login_recovery_started_at
    if not running:
        running = True
        current_state = INITIAL_STATE
        state_start_time = time.time()
        last_state_check = INITIAL_STATE
        login_recovery_active = False
        login_recovery_started_at = None
        
        # เริ่มนับสถิติ session ใหม่
        session_stats["start_time"] = time.time()
        session_stats["total_runs"] = 0
        session_stats["successful_runs"] = 0
        session_stats["watchdog_resets"] = 0
        session_stats["adb_disconnects"] = 0
        
        # [Phase 3] กำหนดเวลาพักสายตารอบถัดไป
        calculate_next_rest()
        
        log_info("▶️ สั่งเริ่มบอททำงานอัตโนมัติ...")
        log_debug(">> เริ่มออโต้ (F6) — เริ่มจาก state: " + current_state)
        
        # รันการตรวจวิเคราะห์ภาพ Template
        try:
            run_templates_health_check()
        except Exception as e:
            print(f"[Health Check] เกิดข้อผิดพลาดขณะรัน: {e}")


def stop_bot():
    global running, login_recovery_active, login_recovery_started_at
    if running:
        running = False
        login_recovery_active = False
        login_recovery_started_at = None
        log_info("⏸️ สั่งหยุดการทำงานบอทชั่วคราว")
        log_debug(">> หยุดออโต้ (F7)")
        # เซฟประวัติและรายงานสถิติ
        save_global_stats(session_done=True)
        print_session_report()


def quit_program():
    print(">> ออกจากโปรแกรม (F9)")
    if running:
        save_global_stats(session_done=True)
        print_session_report()
    os._exit(0)
