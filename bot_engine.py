import os
import sys
import random
import time
import threading
from datetime import datetime

import cv2
import re
import json
import config
from config import (
    INITIAL_STATE,
    MATCH_THRESHOLD,
    PAUSE_SCREENSHOT_DIR,
    RANDOM_TAP_X_RANGE,
    RANDOM_TAP_Y_RANGE,
    RANDOM_TAP_MAX_Y_PX,
    TAP_DELAY_RANGE,
    RANDOM_TAP_DELAY_RANGE,
    HOLD_DURATION_RANGE,
    HOLD_CHANCE,
    WATCHDOG_TIMEOUT_SECONDS,
    ADB_MAX_RECONNECT_ATTEMPTS,
    HEALTH_CHECK_WARNING_THRESHOLD,
    CLICK_JITTER_PIXELS,
    AUTO_REST_INTERVAL_MINUTES,
    AUTO_REST_DURATION_MINUTES,
    LOGIN_TAE_TIMEOUT_SECONDS,
    LOGIN_POLL_INTERVAL_SECONDS,
    FAST_START_ENTRY_BURST,
    FAST_START_BOOST_X,
    FAST_START_BOOST_Y,
    FAST_START_BOOST_TEMPLATE,
    FAST_START_BOOST_TAPS,
    FAST_START_BOOST_THRESHOLD,
    SWIPE_CURVE_ENABLED,
    SWIPE_CURVE_CHANCE,
    SWIPE_CURVE_STEPS,
    SWIPE_CURVE_STRENGTH,
    SWIPE_CURVE_DURATION_MS,
    SCHEDULE_ENABLED,
    ACTIVE_HOURS,
    SCHEDULE_CHECK_INTERVAL,
    DISCORD_REPORT_ENABLED,
    DISCORD_REPORT_EVERY_N_RUNS,
    OCR_SCORE_ENABLED,
    OCR_SCORE_DELAY,
)
from adb_client import adb_connect, adb_tap, adb_long_press, adb_swipe_curve, get_screen_size, grab_screen
from notifiers.line_notifier import send_line_message
from notifiers.gemini_vision import describe_image_with_gemini, read_game_score_with_gemini
from notifiers.discord_notifier import send_discord_report, send_discord_embed, COLOR_SUCCESS, COLOR_WARNING, COLOR_INFO
from flows.flow_config import FLOW
from flows.interrupts_config import INTERRUPTS
from flows.pause_events_config import PAUSE_EVENTS


def find_template(screen, template_name, threshold=MATCH_THRESHOLD):
    """
    หาตำแหน่ง template บนหน้าจอ
    คืนค่า (x, y, w, h) ของกึ่งกลางจุดที่เจอ หรือ None ถ้าไม่เจอ
    """
    if screen is None:
        return None
    template_path = os.path.join(config.TEMPLATE_DIR, template_name)
    if not os.path.exists(template_path):
        return None

    template = cv2.imread(template_path)
    if template is None:
        return None

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        h, w = template.shape[:2]
        center_x = max_loc[0] + w // 2
        center_y = max_loc[1] + h // 2
        return (center_x, center_y, w, h)

    return None

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

# previous state (ใช้เพื่อตรวจว่าเพิ่งมาจาก over_game หรือไม่)
previous_state = None

# Background interrupt watcher thread
_interrupt_thread = None
_interrupt_thread_stop = False

# ตัวแปรเก็บสถิติ session ปัจจุบัน
session_stats = {
    "total_runs": 0,
    "successful_runs": 0,
    "watchdog_resets": 0,
    "adb_disconnects": 0,
    "start_time": None,
    "elapsed_seconds": 0,
    "last_score": 0,
    "last_coins": 0,
    "last_boxes": 0,
    "scores_history": [],
    "coins_history": [],
    "boxes_history": []
}


def get_performance_metrics():
    """คำนวณอัตราการฟาร์ม Coins/Hr, Runs/Hr, Boxes/Hr และ Success Rate %"""
    if session_stats["start_time"] is None:
        return {"coins_per_hour": 0, "runs_per_hour": 0, "boxes_per_hour": 0.0, "boxes_per_run": 0.0, "total_boxes": 0, "success_rate_pct": 0.0}

    elapsed_sec = time.time() - session_stats["start_time"]
    elapsed_hours = elapsed_sec / 3600.0

    total_coins = sum(session_stats["coins_history"])
    total_boxes = sum(session_stats["boxes_history"])
    total_runs = session_stats["total_runs"]
    success_runs = session_stats["successful_runs"]

    coins_per_hr = int(total_coins / elapsed_hours) if elapsed_hours > 0.01 else 0
    runs_per_hr = int(total_runs / elapsed_hours) if elapsed_hours > 0.01 else 0
    boxes_per_hr = round(total_boxes / elapsed_hours, 1) if elapsed_hours > 0.01 else 0.0
    boxes_per_run = round(total_boxes / total_runs, 2) if total_runs > 0 else 0.0
    success_rate = round((success_runs / total_runs) * 100, 1) if total_runs > 0 else 0.0

    return {
        "coins_per_hour": coins_per_hr,
        "runs_per_hour": runs_per_hr,
        "boxes_per_hour": boxes_per_hr,
        "boxes_per_run": boxes_per_run,
        "total_boxes": total_boxes,
        "success_rate_pct": success_rate,
    }


# ตัวแปรระบบเลียนแบบมนุษย์ป้องกันแบน (Phase 3)
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

# ใช้ lambda แทน cache เพื่อให้ชี้ไปหา sys.stdout ตอนใช้งานจริงเสมอ
# หลีกปัญหาที่ main.py reconfigure stdout เป็น UTF-8 แล้ว bot_engine ยังใช้ stdout เก่า (cp1252)
sys_stdout_write = lambda s: sys.stdout.write(s)

_interrupt_last_click = {}


# ---------------------------------------------------------------------------
# ฟังก์ชันระบบจัดการสถิติ (Stats Tracker)
# ---------------------------------------------------------------------------

def load_global_stats():
    """โหลดสถิติรวมทั้งหมดจากไฟล์ json (แยกตามพอร์ตของอินสแตนซ์)"""
    stats_path = config.get_stats_file_path()
    if os.path.exists(stats_path):
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "all_time_runs": 0,
        "all_time_success": 0,
        "all_time_watchdog_resets": 0,
        "all_time_boxes": 0,
        "history": []
    }

def save_global_stats(session_done=False):
    """บันทึกสถิติรวมและข้อมูลประวัติประจุลงไฟล์ json (แยกตามพอร์ตของอินสแตนซ์)"""
    stats_path = config.get_stats_file_path()
    global_stats = load_global_stats()
    
    # อัปเดตข้อมูล Session ล่าสุด
    if session_done and session_stats["start_time"] is not None:
        elapsed = int(time.time() - session_stats["start_time"])
        session_stats["elapsed_seconds"] = elapsed
        
        global_stats["all_time_runs"] += session_stats["total_runs"]
        global_stats["all_time_success"] += session_stats["successful_runs"]
        global_stats["all_time_watchdog_resets"] += session_stats["watchdog_resets"]
        global_stats["all_time_boxes"] = global_stats.get("all_time_boxes", 0) + sum(session_stats["boxes_history"])
        
        # บันทึกลงประวัติ history
        history_entry = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "runs": session_stats["total_runs"],
            "success": session_stats["successful_runs"],
            "boxes": sum(session_stats["boxes_history"]),
            "watchdog_resets": session_stats["watchdog_resets"],
            "adb_disconnects": session_stats["adb_disconnects"],
            "duration_seconds": elapsed
        }
        global_stats["history"].append(history_entry)
        # เก็บประวัติย้อนหลังแค่ 50 รายการล่าสุด
        if len(global_stats["history"]) > 50:
            global_stats["history"].pop(0)

    try:
        with open(stats_path, "w", encoding="utf-8") as f:
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
        print("❌ ตรวจสอบไม่สำเร็จ: ไม่สามารถดึงหน้าจอ MuMu Player ได้ กรุณาเชื่อมต่อ ADB ก่อน")
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
# ฟังก์ชันระบบตารางเวลาทำงานประจำวัน (Scheduled Play Hours)
# ---------------------------------------------------------------------------

def is_within_schedule():
    """ตรวจสอบว่าเวลาปัจจุบันอยู่ในช่วงเวลาที่อนุญาตให้บอทรันหรือไม่"""
    if not getattr(config, "SCHEDULE_ENABLED", False):
        return True

    now = datetime.now()
    curr_min = now.hour * 60 + now.minute

    active_hours = getattr(config, "ACTIVE_HOURS", [])
    if not active_hours:
        return True

    for h_start, m_start, h_end, m_end in active_hours:
        start_min = h_start * 60 + m_start
        end_min = h_end * 60 + m_end
        if start_min <= curr_min < end_min:
            return True
    return False


def check_and_trigger_schedule():
    """ตรวจสอบตารางเวลาทำงาน หากอยู่นอกช่วงเวลา บอทจะหยุดพักสลีปและรอจนกว่าจะเข้าช่วงเวลาถัดไป"""
    global running
    if not running or not getattr(config, "SCHEDULE_ENABLED", False):
        return False

    if not is_within_schedule():
        msg = "⏰ [Schedule] อยู่นอกช่วงเวลาทำงานที่อนุญาต! บอทจะหยุดพักสลีปชั่วคราว..."
        log_info(msg)
        send_line_message(msg)

        while running and not is_within_schedule():
            time.sleep(getattr(config, "SCHEDULE_CHECK_INTERVAL", 30))

        if not running:
            return False

        msg_resume = "⏰ [Schedule] เข้าสู่ช่วงเวลาทำงานแล้ว! บอทเริ่มรันต่อ..."
        log_info(msg_resume)
        send_line_message(msg_resume)
        return True
    return False


# ---------------------------------------------------------------------------
# ฟังก์ชันส่งรายงานสรุปผลเข้า Discord Webhook
# ---------------------------------------------------------------------------

def send_discord_run_report():
    """สร้างและส่งรายงานสรุปผลเข้า Discord Webhook แบบ Embed"""
    if not getattr(config, "DISCORD_REPORT_ENABLED", True):
        return

    elapsed = int(time.time() - (session_stats["start_time"] or time.time()))
    m, s = divmod(elapsed, 60)
    h, m = divmod(m, 60)

    avg_score = int(sum(session_stats["scores_history"]) / len(session_stats["scores_history"])) if session_stats["scores_history"] else 0
    avg_coins = int(sum(session_stats["coins_history"]) / len(session_stats["coins_history"])) if session_stats["coins_history"] else 0

    fields = [
        {"name": "⏱️ เวลาที่เปิดบอท",      "value": f"`{h:02d}:{m:02d}:{s:02d}`",                                                    "inline": True},
        {"name": "🔄 รอบสำเร็จ / รวม",     "value": f"`{session_stats['successful_runs']} / {session_stats['total_runs']} รอบ`",     "inline": True},
        {"name": "⚠️ Watchdog Resets",     "value": f"`{session_stats['watchdog_resets']} ครั้ง`",                                    "inline": True},
        {"name": "📡 ADB หลุดสะสม",        "value": f"`{session_stats['adb_disconnects']} ครั้ง`",                                    "inline": True},
        {"name": "🏆 คะแนนล่าสุด",         "value": f"`{session_stats['last_score']:,}` *(เฉลี่ย: {avg_score:,})*",                   "inline": True},
        {"name": "🪙 เหรียญล่าสุด",         "value": f"`{session_stats['last_coins']:,}` *(เฉลี่ย: {avg_coins:,})*",                   "inline": True},
    ]
    send_discord_embed(
        title="📊 Cookie Run Bot — รายงานสรุปผลการฟาร์ม",
        fields=fields,
        color=COLOR_SUCCESS,
    )


# ---------------------------------------------------------------------------
# ระบบ Fast Start Boost (กดรัวทันทีตอนเริ่มวิ่ง + สแกนหาภาพ)
# ---------------------------------------------------------------------------

def do_fast_start_boost_fixed(count=FAST_START_BOOST_TAPS):
    """
    กดรัวที่พิกัดประจำ (FAST_START_BOOST_X, FAST_START_BOOST_Y) ทันทีเมื่อเพิ่งเริ่มวิ่ง
    เพื่อแก้ปัญหา ADB exec-out screencap ช้า (300-500ms) ทำให้สแกนภาพไม่ทันปุ่มที่หายเร็ว
    """
    if not getattr(config, "ENABLE_FAST_START_BOOST", True):
        return
    target_x = FAST_START_BOOST_X
    target_y = FAST_START_BOOST_Y
    log_info(f"⚡ Fast Start Burst {count} ครั้ง ทันทีที่เข้าด่าน! (พิกัด {target_x},{target_y} px)")
    delay_sec = getattr(config, "BOOST_TAP_SPEED_MS", 50) / 1000.0
    for i in range(count):
        if not running:
            break
        x = target_x + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        y = target_y + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        log_debug(f"[fast_start_fixed] กดรัวครั้งที่ {i+1}/{count} ที่พิกัด ({x},{y})")
        adb_tap(x, y)
        time.sleep(delay_sec)


def do_fast_start_boost(pos, count=FAST_START_BOOST_TAPS):
    """
    กดรัวที่พิกัด pos (x, y) ของปุ่ม Fast Start Boost เมื่อสแกนเจอภาพบนจอ
    """
    if not getattr(config, "ENABLE_FAST_START_BOOST", True):
        return
    log_info(f"⚡ ตรวจพบภาพ Fast Start Boost บนจอ! กำลังกดรัว {count} ครั้งทันที...")
    delay_sec = getattr(config, "BOOST_TAP_SPEED_MS", 50) / 1000.0
    for i in range(count):
        if not running:
            break
        x = pos[0] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        y = pos[1] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        log_debug(f"[fast_start_image] กดรัวครั้งที่ {i+1}/{count} ที่พิกัด ({x},{y})")
        adb_tap(x, y)
        time.sleep(delay_sec)


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


def do_random_tap_loop(duration, guard_templates=None, state=None):
    """
    สุ่มแตะตำแหน่งต่างๆ บนหน้าจอไปเรื่อยๆ เป็นเวลา `duration` วินาที
    แต่ละครั้งจะสุ่มว่าจะเป็น tap ธรรมดา หรือ กดค้าง (hold) ตาม HOLD_CHANCE
    พร้อมระยะเวลา hold แบบสุ่ม เพื่อเลียนแบบการกดของมนุษย์ให้มากที่สุด
    ใช้ระหว่าง "รอ" template ของ state ที่ตั้งค่า tap_while_wait=True

    guard_templates: list ของชื่อ template ที่ถ้าเจอบนจอให้หยุดกดรัวทันที
    (เช่น ["game_over.png"] เพื่อป้องกันการเผลอกดปุ่ม OK บนหน้าจบเกม)
    state: ชื่อสถานะปัจจุบัน เพื่อปรับขอบเขตการกดให้ปลอดภัยเมื่ออยู่ใน over_game
    """
    screen_w, screen_h = get_screen_size()
    x_min = int(screen_w * RANDOM_TAP_X_RANGE[0])
    x_max = int(screen_w * RANDOM_TAP_X_RANGE[1])
    y_min = int(screen_h * RANDOM_TAP_Y_RANGE[0])
    # บังคับขอบเขต Y ไม่ให้เกิน RANDOM_TAP_MAX_Y_PX (400 px สเกลตามความสูงจริงของจอ)
    max_y_allowed = int((RANDOM_TAP_MAX_Y_PX / 720.0) * screen_h)
    y_max = min(int(screen_h * RANDOM_TAP_Y_RANGE[1]), max_y_allowed)

    safe_over_game_mode = state == "over_game" or (guard_templates and "game_over.png" in guard_templates)
    if safe_over_game_mode:
        # ลดพื้นที่การกดให้อยู่เฉพาะส่วนบนของหน้าจอมากขึ้น
        # เพื่อหลีกเลี่ยงปุ่ม OK / Show Off ที่อยู่ด้านล่าง
        y_min = int(screen_h * 0.05)
        y_max = min(y_max, int(screen_h * 0.22))
        hold_chance = min(HOLD_CHANCE, 0.1)
    else:
        hold_chance = HOLD_CHANCE

    end_time = time.time() + duration
    while time.time() < end_time:
        if not running:
            break

        # จับภาพหน้าจอเพียง 1 ครั้งต่อรอบเพื่อประสิทธิภาพสูงสุด
        current_screen = grab_screen()

        # 1) ตรวจสอบภาพ Fast Start Boost บนจอ
        if config.ENABLE_FAST_START_BOOST and current_screen is not None:
            boost_match = find_template(current_screen, FAST_START_BOOST_TEMPLATE, threshold=FAST_START_BOOST_THRESHOLD)
            if boost_match:
                do_fast_start_boost(boost_match)

        # 2) ตรวจสอบ guard templates (เช่น game_over.png)
        if guard_templates and current_screen is not None:
            for gtpl in guard_templates:
                if find_template(current_screen, gtpl):
                    log_debug(f"[random_tap] เจอ guard template '{gtpl}' -> หยุดกดรัว รอให้บอทจัดการ")
                    return

        # 4) ตรวจสอบ interrupt ระหว่างรอ เพื่อจับปุ่มสำคัญที่อาจปรากฏและหายเร็ว
        if current_screen is not None and INTERRUPTS:
            intr_handled = check_interrupts(current_screen)
            if intr_handled:
                return

        # 5) สุ่มกดตามปกติ (รองรับ Curved Swiping เลียนแบบลากนิ้วโค้งมนุษย์)
        x = random.randint(x_min, x_max)
        y = random.randint(y_min, y_max)
        
        if getattr(config, "SWIPE_CURVE_ENABLED", True) and random.random() < getattr(config, "SWIPE_CURVE_CHANCE", 0.3):
            # สุ่มจุดสิ้นสุดใกล้ๆ เพื่อทำ Bezier curved swipe เลียนแบบการลากนิ้ว
            x2 = min(max(x + random.randint(-40, 40), x_min), x_max)
            y2 = min(max(y + random.randint(-40, 40), y_min), y_max)
            log_debug(f"[random_tap] curved_swipe ({x},{y}) -> ({x2},{y2})")
            adb_swipe_curve(x, y, x2, y2, 
                            curve_strength=getattr(config, "SWIPE_CURVE_STRENGTH", 40),
                            steps=getattr(config, "SWIPE_CURVE_STEPS", 8),
                            duration_ms=getattr(config, "SWIPE_CURVE_DURATION_MS", 180))
        elif random.random() < hold_chance:
            hold_ms = random.randint(*HOLD_DURATION_RANGE)
            log_debug(f"[random_tap] hold ({x},{y}) {hold_ms}ms")
            adb_long_press(x, y, hold_ms)
        else:
            log_debug(f"[random_tap] tap  ({x},{y})")
            adb_tap(x, y)

        # หน่วงเวลาแบบซอยย่อยเพื่อตอบสนองต่อคำสั่ง F7 ได้ทันที
        wait_target = random.uniform(*RANDOM_TAP_DELAY_RANGE)
        wait_until = time.time() + wait_target
        while time.time() < wait_until:
            if not running:
                break
            time.sleep(0.1)


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
    ถ้าเจอตัวใดตัวหนึ่ง (และพ้น cooldown แล้ว) จะกดทันทีแล้วคืนค่าชื่อ interrupt (str)
    ถ้าไม่เจอเลย คืนค่า None
    """
    now = time.time()
    for name, cfg in INTERRUPTS.items():
        # ข้าม live_two ถ้าผู้ใช้ปิดการตั้งค่า
        if name == "live_two" and not getattr(config, "ENABLE_USE_SECOND_COOKIE", True):
            continue

        last_click = _interrupt_last_click.get(name, 0)
        cooldown = cfg.get("cooldown", 1.0)
        if now - last_click < cooldown:
            continue

        threshold = cfg.get("threshold", MATCH_THRESHOLD)
        match = find_template(screen, cfg["template"], threshold=threshold)
        if match:
            # พบ interrupt -> ทำการกดทันที
            log_info(f"⚡ แก้ไขป๊อปอัปขัดจังหวะ: {name}")
            log_debug(f"[interrupt] เจอ {name} ({cfg['template']}) -> กดตำแหน่ง {match}")
            try:
                do_click(match)
            except Exception as e:
                log_debug(f"[interrupt] กดไม่สำเร็จ: {e}")
            _interrupt_last_click[name] = time.time()
            return name

    return None


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
    วนคลิกทุกคู่พิกัดที่ Gemini ส่งมา (รองรับ 2 จุดตาม prompt)
    """
    pairs = gemini_text_to_int(description)
    if not pairs:
        print("[click_gemini] ไม่พบพิกัดใน description")
        return

    # ดึงขนาดหน้าจอจริงของ LDPlayer เพื่อนำมาสเกลพิกัดอย่างถูกต้อง (คำนวณจากจอฐาน 1280x720)
    screen_w, screen_h = get_screen_size()

    for x, y in pairs:
        # [Bug fix] เพิ่ม return เมื่อค่าพิกัดอยู่นอกช่วงที่รองรับ
        # เพื่อป้องกัน UnboundLocalError จาก real_x / real_y ที่ไม่ถูก assign
        if x == 1:
            base_x = 450
        elif x == 2:
            base_x = 650
        elif x == 3:
            base_x = 850
        else:
            print(f"[click_gemini] ค่า x={x} ไม่รองรับ (รองรับแค่ 1,2,3) -> ข้ามพิกัดนี้")
            continue

        if y == 1:
            base_y = 300
        elif y == 2:
            base_y = 600
        else:
            print(f"[click_gemini] ค่า y={y} ไม่รองรับ (รองรับแค่ 1,2) -> ข้ามพิกัดนี้")
            continue

        # สเกลพิกัดตามขนาดหน้าจอจริงเทียบกับหน้าจอฐาน 1280x720
        real_x = int((base_x / 1280.0) * screen_w)
        real_y = int((base_y / 720.0) * screen_h)

        log_debug(f"[click_gemini] คลิกพิกัด ({x},{y}) -> หน้าจอ ({real_x},{real_y})")
        do_click((real_x, real_y))
        time.sleep(0.5)  # หน่วงเล็กน้อยระหว่างการคลิกแต่ละจุด


# ---------------------------------------------------------------------------
# Loop หลักของบอท
# ---------------------------------------------------------------------------

def interrupt_watcher():
    """Background thread that continuously checks for interrupts and handles them immediately.
    This ensures interrupts are detected and clicked even if main bot loop is in a wait.
    """
    global _interrupt_thread_stop
    log_debug("[interrupt_watcher] เริ่มทำงาน (background)")
    while running and not _interrupt_thread_stop:
        try:
            screen = grab_screen()
            if screen is None:
                time.sleep(0.1)
                continue

            now = time.time()
            handled_any = False
            for name, cfg in INTERRUPTS.items():
                if name == "live_two" and not getattr(config, "ENABLE_USE_SECOND_COOKIE", True):
                    continue
                last_click = _interrupt_last_click.get(name, 0)
                cooldown = cfg.get("cooldown", 1.0)
                if now - last_click < cooldown:
                    continue

                threshold = cfg.get("threshold", MATCH_THRESHOLD)
                match = find_template(screen, cfg["template"], threshold=threshold)
                if match:
                    log_info(f"🔔 [watcher] เจอ interrupt: {name} -> กดทันที")
                    log_debug(f"[watcher] เจอ {name} ({cfg['template']}) -> กดตำแหน่ง {match}")
                    try:
                        do_click(match)
                    except Exception as e:
                        log_debug(f"[watcher] กดไม่สำเร็จ: {e}")
                    _interrupt_last_click[name] = time.time()
                    handled_any = True
                    # หลังจัดการ interrupt ตัวนี้ ให้หน่วงตาม cooldown ของมันเพื่อลด spam
                    intr_delay = cfg.get("cooldown", 0.5)
                    time.sleep(intr_delay)
                    break

            if not handled_any:
                # ถ้าไม่มีอะไรเกิดขึ้น ให้รอสั้นๆ ก่อนสแกนอีกครั้ง
                time.sleep(0.08)
        except Exception as e:
            log_debug(f"[interrupt_watcher] เกิดข้อผิดพลาด: {e}")
            time.sleep(0.2)

    log_debug("[interrupt_watcher] หยุดทำงาน (background)")


def bot_loop():
    global running, current_state, paused_event_active
    global state_start_time, last_state_check, adb_fail_count, _last_reconnect_line_time
    global previous_state, _interrupt_thread, _interrupt_thread_stop
    
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
            # [Phase 3] ระบบตรวจสอบและทำงานโหมดพักสายตาบอท / ตารางเวลา
            # -------------------------------------------------------------
            if check_and_trigger_schedule():
                state_start_time = time.time()
                continue

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

                # ถ้าเข้าสู่ over_game state (เริ่มออกวิ่งด่านใหม่) -> กด Fast Start Entry Burst ทันที
                if current_state == "over_game" and config.ENABLE_FAST_START_BOOST and FAST_START_ENTRY_BURST:
                    do_fast_start_boost_fixed()

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
                    paused_event_active = None
                    login_recovery_active = False
                    login_recovery_started_at = None
                    
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
                    dev_id = getattr(config, "DEVICE_ID", "")
                    now = time.time()
                    if now - _last_reconnect_line_time > 60:
                        msg = f"🚨 [ADB Error] การเชื่อมต่อ MuMu Player ({dev_id}) ขัดข้องสะสม! กำลังพยายามบังคับ Reconnect ใหม่..."
                        log_info(f"🔌 กำลัง Reconnect สัญญาณ ADB ({dev_id})...")
                        log_debug(msg)
                        send_line_message(msg)
                        _last_reconnect_line_time = now
                    else:
                        log_debug(f"🚨 [ADB Error] ครบขีดจำกัด กำลัง Reconnect {dev_id}... (ไม่ส่ง LINE ซ้ำ)")
                    
                    # พยายาม reconnect ใหม่กับ device_id ปัจจุบัน
                    if adb_connect(dev_id):
                        log_info(f"🔌 เชื่อมต่อ MuMu Player ({dev_id}) สำเร็จ!")
                        log_debug("✅ [ADB Reconnect] เชื่อมต่อสำเร็จแล้ว ทำงานต่อ...")
                    else:
                        log_info(f"❌ เชื่อมต่อ MuMu Player ({dev_id}) ไม่สำเร็จ! รอ 2 วิเพื่อลองใหม่")
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
            if INTERRUPTS:
                intr_name = check_interrupts(screen)
                if intr_name:
                    # ถ้าเจอ interrupt ให้วนลูปรอบใหม่ทันที
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
                    log_info("🏁 คุกกี้ชน/หมดพลัง: ตรวจพบหน้าจบเกม (over_game)")

                    # -------------------------------------------------------------
                    # อ่านคะแนนและเหรียญด้วย Gemini Vision OCR ก่อนกดปุ่ม OK !
                    # -------------------------------------------------------------
                    if getattr(config, "OCR_SCORE_ENABLED", True):
                        ocr_delay = getattr(config, "OCR_SCORE_DELAY", 1.5)
                        log_info(f"🔍 [OCR] ตรวจพบหน้าจบเกม: รอนิ่ง {ocr_delay} วินาทีเพื่อให้คะแนนเสถียรก่อนอ่าน...")
                        wait_start = time.time()
                        while time.time() - wait_start < ocr_delay:
                            if not running:
                                break
                            time.sleep(0.1)

                        log_info("⏳ [OCR] กำลังประมวลผลอ่านคะแนนและเหรียญด้วย Gemini...")
                        
                        score_data = None
                        max_ocr_attempts = 2
                        for attempt in range(1, max_ocr_attempts + 1):
                            fresh_screen = grab_screen()
                            if fresh_screen is None:
                                fresh_screen = screen

                            score_data = read_game_score_with_gemini(fresh_screen)
                            if score_data and (score_data.get("score", 0) > 0 or score_data.get("coins", 0) > 0 or score_data.get("boxes", 0) > 0):
                                break
                            
                            if attempt < max_ocr_attempts:
                                log_info(f"🔄 [OCR] ผลลัพธ์ยังไม่สมบูรณ์ ลองอ่านซ้ำครั้งที่ {attempt + 1}/{max_ocr_attempts}...")
                                time.sleep(1.5)

                        if score_data:
                            boxes_cnt = score_data.get("boxes", 0)
                            session_stats["last_score"] = score_data["score"]
                            session_stats["last_coins"] = score_data["coins"]
                            session_stats["last_boxes"] = boxes_cnt
                            session_stats["scores_history"].append(score_data["score"])
                            session_stats["coins_history"].append(score_data["coins"])
                            session_stats["boxes_history"].append(boxes_cnt)

                            metrics = get_performance_metrics()
                            round_num = session_stats['successful_runs'] + 1
                            score_line_msg = (
                                f"🏁 สรุปผลคะแนนรอบที่ {round_num}\n"
                                f"🏆 คะแนน: {score_data['score']:,}\n"
                                f"🪙 เหรียญ: {score_data['coins']:,}\n"
                                f"🎁 กล่องสมบัติ: {boxes_cnt} กล่อง (เฉลี่ย {metrics['boxes_per_hour']} กล่อง/ชม.)"
                            )
                            log_info(f"📊 อ่านคะแนนสำเร็จ: {score_data['score']:,} | เหรียญ: {score_data['coins']:,} | 🎁 กล่อง: {boxes_cnt} (เฉลี่ย {metrics['boxes_per_hour']}/ชม.)")
                            send_line_message(score_line_msg)
                            if getattr(config, "DISCORD_REPORT_ENABLED", True):
                                send_discord_embed(
                                    title=f"🏁 สรุปผลคะแนน — รอบที่ {round_num}",
                                    fields=[
                                        {"name": "🏆 คะแนน", "value": f"`{score_data['score']:,}`", "inline": True},
                                        {"name": "🪙 เหรียญ", "value": f"`{score_data['coins']:,}`", "inline": True},
                                        {"name": "🎁 กล่องสมบัติ", "value": f"`{boxes_cnt}` (`{metrics['boxes_per_hour']}/ชม.`)", "inline": True},
                                    ],
                                    color=COLOR_INFO,
                                )
                            log_info("✅ ส่งข้อความสรุปผลคะแนนและสถิติกล่องสมบัติเข้า LINE / Discord เรียบร้อยแล้ว")
                        else:
                            log_info("⚠️ ไม่สามารถอ่านคะแนนจากหน้าจอได้ (Gemini OCR อ่านไม่สำเร็จ หรือ API key ไม่ถูกต้อง)")

                    log_info("🔘 กระบวนการ OCR และส่งข้อความเสร็จสิ้น -> กำลังกดปุ่ม OK เพื่อผ่านหน้าจบเกม...")

                log_debug(f"[match] เจอ template: {template_name} -> ทำ action: {action_name} ที่พิกัด {match}")

                # พิเศษ: ถ้าเป็น start_game และเพิ่งกลับมาจาก over_game ให้รอ 5 วินาทีก่อนกด
                if current_state == "start_game" and previous_state == "over_game":
                    log_info("⏳ พบปุ่มเริ่มเกมเมื่อกลับมาจาก over_game: รอ 5 วินาทีแล้วกด")
                    # รอ 5 วินาที โดยตอบสนองต่อคำสั่งหยุด และตรวจว่าปุ่มยังอยู่ก่อนจะกด
                    wait_start = time.time()
                    while time.time() - wait_start < 5:
                        if not running:
                            break
                        time.sleep(0.1)

                    # ตรวจสอบอีกครั้งว่าปุ่มยังอยู่ก่อนกดจริง
                    refreshed_screen = grab_screen()
                    if refreshed_screen is not None:
                        re_match = find_template(refreshed_screen, template_name)
                        if re_match:
                            action_func(re_match)
                        else:
                            log_debug("[start_game] ปุ่มเริ่มหายไปหลังรอ 5 วินาที -> ข้ามการกด")
                    else:
                        log_debug("[start_game] ไม่สามารถจับภาพเพื่อยืนยันปุ่มได้หลังรอ 5 วินาที -> ข้ามการกด")

                elif current_state == "over_game":
                    # ตรวจสอบพิกัดปุ่ม OK บนหน้าจอล่าสุดอีกครั้งหลังอ่านคะแนนเสร็จ
                    refreshed_screen = grab_screen()
                    if refreshed_screen is not None:
                        re_match = find_template(refreshed_screen, template_name)
                        if re_match:
                            action_func(re_match)
                        else:
                            action_func(match)
                    else:
                        action_func(match)

                else:
                    action_func(match)

                # ถ้าปิดระบบซื้อไอเทม (ENABLE_BOOSTER_BUY = False) ให้ข้ามไปยังหน้ากดเริ่มเกมรอบ 2 (let_go) ทันที
                if current_state == "start_game" and not getattr(config, "ENABLE_BOOSTER_BUY", True):
                    log_info("⏩ ข้ามการซื้อไอเทมเพิ่มพลัง -> ไปหน้าเริ่มเล่นเกมโดยตรง...")
                    next_state = "let_go"

                if next_state != current_state:
                    log_debug(f"   -> เปลี่ยน state: {current_state} -> {next_state}")
                    
                    # ตรวจสอบการนับรอบการทำงาน (Cycle Complete)
                    # เมื่อเปลี่ยนจาก over_game ไป start_game (หรือเริ่มรอบใหม่)
                    if current_state == "over_game" and next_state == INITIAL_STATE:
                        session_stats["successful_runs"] += 1
                        session_stats["total_runs"] += 1
                        log_info(f"🏆 เล่นผ่านสำเร็จแล้วรอบที่ {session_stats['successful_runs']}!")

                        # -------------------------------------------------
                        # ส่งรายงาน Discord Webhook สรุปผลภาพรวม ทุก N รอบ (ถ้าเปิด)
                        # -------------------------------------------------
                        report_every = getattr(config, "DISCORD_REPORT_EVERY_N_RUNS", 10)
                        if getattr(config, "DISCORD_REPORT_ENABLED", True) and (session_stats["successful_runs"] % report_every == 0):
                            send_discord_run_report()

                        save_global_stats()
                    elif current_state == INITIAL_STATE:
                        # เริ่มนับรอบใหม่ (กรณีบอทพึ่งเริ่มรัน)
                        if session_stats["total_runs"] == 0:
                            session_stats["total_runs"] = 1
                            save_global_stats()
                            
                    # เปลี่ยน state จริงที่นี่ (เก็บ previous_state ก่อนเปลี่ยน)
                    previous_state = current_state
                    current_state = next_state

                    # ถ้ามี entry_delay กำหนดใน FLOW ของ state ใหม่ ให้รอก่อนเริ่มสแกน/กด
                    new_step = FLOW.get(current_state, {})
                    entry_delay = new_step.get("entry_delay", 0)
                    if entry_delay:
                        log_info(f"⏳ รอ {entry_delay} วินาที ให้ UI โหลดเต็มก่อนเริ่ม state: {current_state}")
                        # รอแบบสั้นๆ เพื่อตอบสนองต่อการสั่งหยุด (F7) ได้ทันที
                        wait_until = time.time() + float(entry_delay)
                        while time.time() < wait_until:
                            if not running:
                                break
                            time.sleep(0.1)

                # แทนการ sleep แบบ blocking ให้เป็น wait loop ที่ poll หา interrupts ระหว่างรอ
                start_wait = time.time()
                waited = 0.0
                poll_interval = 0.15
                while waited < delay:
                    if not running:
                        break
                    try:
                        screen_during_wait = grab_screen()
                        if screen_during_wait is not None and INTERRUPTS:
                            intr_handled = check_interrupts(screen_during_wait)
                            if intr_handled:
                                # ถ้า interrupt ถูกจัดการ ใช้ cooldown ของ interrupt นั้นเป็นดีเลย์แทน
                                intr_cfg = INTERRUPTS.get(intr_handled, {})
                                intr_delay = intr_cfg.get("cooldown", 1.0)
                                log_info(f"⏳ หลังจัดการ interrupt '{intr_handled}' จะรอ {intr_delay} วินาที ตามคอนฟิก")
                                # รอในช่วงสั้นๆ เพื่อให้สามารถตอบสนองการหยุดได้ทัน
                                wait_until_intr = time.time() + float(intr_delay)
                                while time.time() < wait_until_intr:
                                    if not running:
                                        break
                                    time.sleep(0.1)
                                break
                    except Exception:
                        pass

                    time.sleep(poll_interval)
                    waited = time.time() - start_wait
            else:
                log_debug(f"[{current_state}] ยังไม่เจอ {template_name}... กำลังสแกนหา")
                if tap_while_wait:
                    if getattr(config, "ENABLE_RANDOM_TAP_WHILE_WAIT", True):
                        log_debug(f"[{current_state}] สุ่มกดปุ่มกระโดดต่อเนื่อง...")
                        # ส่ง guard_templates เพื่อหยุดกดรัวทันทีที่เจอ game_over.png บนจอ
                        # ป้องกันการเผลอไปกดปุ่ม OK ที่หน้าจบเกมก่อนที่บอทจะ detect ได้
                        guard_tpls = step.get("guard_templates", None)
                        do_random_tap_loop(delay, guard_templates=guard_tpls, state=current_state)
                    else:
                        # ระบบสุ่มกดถูกปิด: รอด้วย polling loop เหมือน state ทั่วไป
                        log_debug(f"[{current_state}] ENABLE_RANDOM_TAP_WHILE_WAIT=False -> รอเฉยๆ (ไม่กดสุ่ม)")
                        start_wait = time.time()
                        waited = 0.0
                        poll_interval = 0.15
                        while waited < delay:
                            if not running:
                                break
                            try:
                                screen_during_wait = grab_screen()
                                if screen_during_wait is not None and INTERRUPTS:
                                    intr_handled = check_interrupts(screen_during_wait)
                                    if intr_handled:
                                        intr_cfg = INTERRUPTS.get(intr_handled, {})
                                        intr_delay = intr_cfg.get("cooldown", 1.0)
                                        log_info(f"⏳ หลังจัดการ interrupt '{intr_handled}' จะรอ {intr_delay} วินาที ตามคอนฟิก")
                                        wait_until_intr = time.time() + float(intr_delay)
                                        while time.time() < wait_until_intr:
                                            if not running:
                                                break
                                            time.sleep(0.1)
                                        break
                            except Exception:
                                pass
                            time.sleep(poll_interval)
                            waited = time.time() - start_wait
                else:
                    # ถ้า state นี้ไม่มี tap_while_wait ให้รอแบบ poll หา interrupts แทนการ sleep ปกติ
                    start_wait = time.time()
                    waited = 0.0
                    poll_interval = 0.15
                    while waited < delay:
                        if not running:
                            break
                        try:
                            screen_during_wait = grab_screen()
                            if screen_during_wait is not None and INTERRUPTS:
                                intr_handled = check_interrupts(screen_during_wait)
                                if intr_handled:
                                    intr_cfg = INTERRUPTS.get(intr_handled, {})
                                    intr_delay = intr_cfg.get("cooldown", 1.0)
                                    log_info(f"⏳ หลังจัดการ interrupt '{intr_handled}' จะรอ {intr_delay} วินาที ตามคอนฟิก")
                                    wait_until_intr = time.time() + float(intr_delay)
                                    while time.time() < wait_until_intr:
                                        if not running:
                                            break
                                        time.sleep(0.1)
                                    break
                        except Exception:
                            pass

                        time.sleep(poll_interval)
                        waited = time.time() - start_wait
                    
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
    global login_recovery_active, login_recovery_started_at, _interrupt_thread, _interrupt_thread_stop
    if not running:
        dev_id = getattr(config, "DEVICE_ID", "").strip()
        if not dev_id:
            log_info("❌ ยังไม่ได้กรอกพอร์ต! กรุณากรอกพอร์ต (เช่น 5559) ในช่อง Device/Port แล้วกด Connect ก่อนเริ่มบอท")
            return

        screen_test = grab_screen()
        if screen_test is None:
            log_info(f"🔌 กำลังพยายามเชื่อมต่อ ADB ไปที่ {dev_id}...")
            if not adb_connect(dev_id):
                log_info(f"❌ เชื่อมต่อ ADB ไปที่ {dev_id} ไม่สำเร็จ กรุณาตรวจสอบว่าเปิด Emulator และพอร์ตถูกต้องแล้วกด Connect อีกครั้ง")
                return

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

        # เริ่ม background interrupt watcher
        try:
            _interrupt_thread_stop = False
            _interrupt_thread = threading.Thread(target=interrupt_watcher, daemon=True)
            _interrupt_thread.start()
        except Exception as e:
            log_debug(f"[start_bot] ไม่สามารถเริ่ม interrupt watcher: {e}")


def stop_bot():
    global running, login_recovery_active, login_recovery_started_at, _interrupt_thread_stop, _interrupt_thread
    if running:
        running = False
        login_recovery_active = False
        login_recovery_started_at = None
        # สั่งให้ watcher หยุด
        _interrupt_thread_stop = True
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
