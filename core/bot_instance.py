import os
import sys
import random
import time
import threading
from datetime import datetime

import cv2
import re
import config
from config import (
    INITIAL_STATE,
    MATCH_THRESHOLD,
    RANDOM_TAP_X_RANGE,
    RANDOM_TAP_Y_RANGE,
    RANDOM_TAP_MAX_Y_PX,
    TAP_DELAY_RANGE,
    RANDOM_TAP_DELAY_RANGE,
    HOLD_DURATION_RANGE,
    HOLD_CHANCE,
    WATCHDOG_TIMEOUT_SECONDS,
    ADB_MAX_RECONNECT_ATTEMPTS,
    CLICK_JITTER_PIXELS,
    FAST_START_ENTRY_BURST,
    FAST_START_BOOST_X,
    FAST_START_BOOST_Y,
    FAST_START_BOOST_TEMPLATE,
    FAST_START_BOOST_TAPS,
    FAST_START_BOOST_THRESHOLD,
)
from adb_client import (
    adb_connect, adb_tap, adb_long_press, adb_swipe_curve,
    get_screen_size, grab_screen
)
from notifiers.line_notifier import send_line_message
from notifiers.gemini_vision import describe_image_with_gemini, read_game_score_with_gemini
from notifiers.discord_notifier import send_discord_embed, COLOR_INFO
from flows.flow_config import FLOW
from flows.interrupts_config import INTERRUPTS
from flows.pause_events_config import PAUSE_EVENTS

from core.stats_manager import StatsManager
from core.scheduler import SchedulerManager
from core.recovery import RecoveryManager

sys_stdout_write = lambda s: sys.stdout.write(s)


class BotInstance:
    def __init__(self, device_id, log_callback=None, settings=None):
        self.device_id = device_id
        self._gui_log_callback = log_callback
        self.settings = config.get_port_settings(settings)

        self.running = False
        self.current_state = INITIAL_STATE
        self.paused_event_active = None

        self.state_start_time = time.time()
        self.last_state_check = INITIAL_STATE
        self.adb_fail_count = 0
        self._last_reconnect_line_time = 0

        self.previous_state = None

        self._interrupt_thread = None
        self._interrupt_thread_stop = False

        self.stats_mgr = StatsManager(self.device_id)
        self.sched_mgr = SchedulerManager(self)
        self.recov_mgr = RecoveryManager(self)

        self._interrupt_last_click = {}
        self.adb_lock = threading.Lock()
        self._template_cache = {}
        self._in_bot_loop = False

        self.ACTION_FUNCS = {
            "click": self.do_click,
            "tap_loop": self.do_tap_loop,
        }

    # -- Delegated Properties for Backward Compatibility --
    @property
    def session_stats(self):
        return self.stats_mgr.session_stats

    @property
    def next_rest_time(self):
        return self.sched_mgr.next_rest_time

    @next_rest_time.setter
    def next_rest_time(self, val):
        self.sched_mgr.next_rest_time = val

    @property
    def is_resting(self):
        return self.sched_mgr.is_resting

    @is_resting.setter
    def is_resting(self, val):
        self.sched_mgr.is_resting = val

    @property
    def login_recovery_active(self):
        return self.recov_mgr.login_recovery_active

    @login_recovery_active.setter
    def login_recovery_active(self, val):
        self.recov_mgr.login_recovery_active = val

    @property
    def login_recovery_started_at(self):
        return self.recov_mgr.login_recovery_started_at

    @login_recovery_started_at.setter
    def login_recovery_started_at(self, val):
        self.recov_mgr.login_recovery_started_at = val

    def get_setting(self, key, default=None):
        val = None
        if hasattr(self, "settings") and isinstance(self.settings, dict) and key in self.settings:
            val = self.settings[key]
        if val is None:
            val = getattr(config, key, default)
        return val if val is not None else default

    def update_settings(self, new_settings):
        if not hasattr(self, "settings") or not isinstance(self.settings, dict):
            self.settings = config.get_port_settings({})
        self.settings.update(new_settings)

    def set_log_callback(self, callback):
        """เปลี่ยน GUI log callback — ใช้แทนการเข้าถึง _gui_log_callback โดยตรง"""
        self._gui_log_callback = callback

    def log_info(self, msg):
        """ส่งข้อมูลที่เป็นภาษาไทยสวยงามอ่านง่ายไปที่ GUI และแสดงที่ Terminal ด้วย"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{self.device_id}] " if self.device_id else ""
        formatted_msg = f"[{timestamp}] {prefix}{msg}"
        sys_stdout_write(formatted_msg + "\n")
        if self._gui_log_callback:
            self._gui_log_callback(formatted_msg)

    def log_debug(self, msg):
        """พิมพ์ข้อมูล debug เชิงลึกและทางเทคนิคเฉพาะที่ Terminal เท่านั้น"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{self.device_id}] " if self.device_id else ""
        sys_stdout_write(f"[{timestamp}] [DEBUG] {prefix}{msg}\n")

    def find_template(self, screen, template_name, threshold=MATCH_THRESHOLD):
        if screen is None or not template_name:
            return None

        if template_name in self._template_cache:
            template = self._template_cache[template_name]
        else:
            template_path = os.path.join(config.TEMPLATE_DIR, template_name)
            if not os.path.exists(template_path):
                return None
            template = cv2.imread(template_path)
            if template is None:
                return None
            self._template_cache[template_name] = template

        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = template.shape[:2]
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return (center_x, center_y, w, h)

        return None

    # -- Delegated Stats Methods --
    def get_performance_metrics(self):
        return self.stats_mgr.get_performance_metrics()

    def load_global_stats(self):
        return self.stats_mgr.load_global_stats()

    def save_global_stats(self, session_done=False):
        self.stats_mgr.save_global_stats(session_done=session_done)

    def print_session_report(self):
        self.stats_mgr.print_session_report()

    # -- Delegated Recovery & Health Check Methods --
    def run_templates_health_check(self):
        self.recov_mgr.run_templates_health_check()

    def save_pause_screenshot(self, screen, event_name):
        return self.recov_mgr.save_pause_screenshot(screen, event_name)

    def handle_login_recovery(self, screen):
        return self.recov_mgr.handle_login_recovery(screen)

    # -- Delegated Scheduler Methods --
    def calculate_next_rest(self):
        self.sched_mgr.calculate_next_rest()

    def check_and_trigger_rest(self):
        return self.sched_mgr.check_and_trigger_rest()

    def is_within_schedule(self):
        return self.sched_mgr.is_within_schedule()

    def check_and_trigger_schedule(self):
        return self.sched_mgr.check_and_trigger_schedule()

    def send_discord_run_report(self):
        if not self.get_setting("DISCORD_REPORT_ENABLED", True):
            return

        elapsed = int(time.time() - (self.session_stats["start_time"] or time.time()))
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)

        avg_score = int(sum(self.session_stats["scores_history"]) / len(self.session_stats["scores_history"])) if self.session_stats["scores_history"] else 0
        avg_coins = int(sum(self.session_stats["coins_history"]) / len(self.session_stats["coins_history"])) if self.session_stats["coins_history"] else 0

        fields = [
            {"name": "⏱️ เวลาที่เปิดบอท",      "value": f"`{h:02d}:{m:02d}:{s:02d}`",                                                    "inline": True},
            {"name": "🔄 รอบสำเร็จ / รวม",     "value": f"`{self.session_stats['successful_runs']} / {self.session_stats['total_runs']} รอบ`",     "inline": True},
            {"name": "⚠️ Watchdog Resets",     "value": f"`{self.session_stats['watchdog_resets']} ครั้ง`",                                    "inline": True},
            {"name": "📡 ADB หลุดสะสม",        "value": f"`{self.session_stats['adb_disconnects']} ครั้ง`",                                    "inline": True},
            {"name": "🏆 คะแนนล่าสุด",         "value": f"`{self.session_stats['last_score']:,}` *(เฉลี่ย: {avg_score:,})*",                   "inline": True},
            {"name": "🪙 เหรียญล่าสุด",         "value": f"`{self.session_stats['last_coins']:,}` *(เฉลี่ย: {avg_coins:,})*",                   "inline": True},
        ]
        target_wh = str(self.get_setting("SELECTED_DISCORD_WEBHOOK", "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน") or "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน")
        send_discord_embed(
            title=f"📊 Cookie Run Bot ({self.device_id}) — รายงานสรุปผลการฟาร์ม",
            fields=fields,
            color=COLOR_INFO,
            target_webhook=target_wh
        )

    def do_fast_start_boost_fixed(self, count=FAST_START_BOOST_TAPS):
        if not self.get_setting("ENABLE_FAST_START_BOOST", True):
            return
        target_x = FAST_START_BOOST_X
        target_y = FAST_START_BOOST_Y
        self.log_info(f"⚡ Fast Start Burst {count} ครั้ง ทันทีที่เข้าด่าน! (พิกัด {target_x},{target_y} px)")
        delay_sec = float(self.get_setting("BOOST_TAP_SPEED_MS", 50) or 50) / 1000.0
        for i in range(count):
            if not self.running:
                break
            x = target_x + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
            y = target_y + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
            self.log_debug(f"[fast_start_fixed] กดรัวครั้งที่ {i + 1}/{count} ที่พิกัด ({x},{y})")
            adb_tap(x, y, device_id=self.device_id)
            time.sleep(delay_sec)

    def do_fast_start_boost(self, pos, count=FAST_START_BOOST_TAPS):
        if not self.get_setting("ENABLE_FAST_START_BOOST", True):
            return
        self.log_info(f"⚡ ตรวจพบภาพ Fast Start Boost บนจอ! กำลังกดรัว {count} ครั้งทันที...")
        delay_sec = float(self.get_setting("BOOST_TAP_SPEED_MS", 50) or 50) / 1000.0
        for i in range(count):
            if not self.running:
                break
            x = pos[0] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
            y = pos[1] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
            self.log_debug(f"[fast_start_image] กดรัวครั้งที่ {i + 1}/{count} ที่พิกัด ({x},{y})")
            adb_tap(x, y, device_id=self.device_id)
            time.sleep(delay_sec)

    def do_click(self, pos):
        x = pos[0] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        y = pos[1] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
        adb_tap(x, y, device_id=self.device_id)
        time.sleep(random.uniform(0.3, 0.6))

    def do_tap_loop(self, pos, duration=0.6):
        end_time = time.time() + duration
        while time.time() < end_time:
            if not self.running:
                break
            x = pos[0] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
            y = pos[1] + random.randint(-CLICK_JITTER_PIXELS, CLICK_JITTER_PIXELS)
            adb_tap(x, y, device_id=self.device_id)
            time.sleep(random.uniform(*TAP_DELAY_RANGE))

    def do_random_tap_loop(self, duration, guard_templates=None, state=None):
        screen_w, screen_h = get_screen_size(device_id=self.device_id)
        x_min = int(screen_w * RANDOM_TAP_X_RANGE[0])
        x_max = int(screen_w * RANDOM_TAP_X_RANGE[1])
        y_min = int(screen_h * RANDOM_TAP_Y_RANGE[0])
        max_y_allowed = int((RANDOM_TAP_MAX_Y_PX / 720.0) * screen_h)
        y_max = min(int(screen_h * RANDOM_TAP_Y_RANGE[1]), max_y_allowed)

        safe_over_game_mode = state == "over_game" or (guard_templates and "game_over.png" in guard_templates)
        if safe_over_game_mode:
            y_min = int(screen_h * 0.05)
            y_max = min(y_max, int(screen_h * 0.22))
            hold_chance = min(HOLD_CHANCE, 0.1)
        else:
            hold_chance = HOLD_CHANCE

        end_time = time.time() + duration
        while time.time() < end_time:
            if not self.running:
                break

            current_screen = grab_screen(device_id=self.device_id)

            if self.get_setting("ENABLE_FAST_START_BOOST", True) and current_screen is not None:
                boost_match = self.find_template(current_screen, FAST_START_BOOST_TEMPLATE, threshold=FAST_START_BOOST_THRESHOLD)
                if boost_match:
                    self.do_fast_start_boost(boost_match)

            if guard_templates and current_screen is not None:
                for gtpl in guard_templates:
                    if self.find_template(current_screen, gtpl):
                        self.log_debug(f"[random_tap] เจอ guard template '{gtpl}' -> หยุดกดรัว รอให้บอทจัดการ")
                        return

            if current_screen is not None and INTERRUPTS:
                intr_handled = self.check_interrupts(current_screen)
                if intr_handled:
                    return

            x = random.randint(x_min, x_max)
            y = random.randint(y_min, y_max)

            swipe_chance = float(self.get_setting("SWIPE_CURVE_CHANCE", 0.3) or 0.3)
            if self.get_setting("SWIPE_CURVE_ENABLED", True) and random.random() < swipe_chance:
                x2 = min(max(x + random.randint(-40, 40), x_min), x_max)
                y2 = min(max(y + random.randint(-40, 40), y_min), y_max)
                self.log_debug(f"[random_tap] curved_swipe ({x},{y}) -> ({x2},{y2})")
                adb_swipe_curve(
                    x, y, x2, y2,
                    curve_strength=int(self.get_setting("SWIPE_CURVE_STRENGTH", 40) or 40),
                    steps=int(self.get_setting("SWIPE_CURVE_STEPS", 8) or 8),
                    duration_ms=int(self.get_setting("SWIPE_CURVE_DURATION_MS", 180) or 180),
                    device_id=self.device_id
                )
            elif random.random() < hold_chance:
                hold_ms = random.randint(*HOLD_DURATION_RANGE)
                self.log_debug(f"[random_tap] hold ({x},{y}) {hold_ms}ms")
                adb_long_press(x, y, hold_ms, device_id=self.device_id)
            else:
                self.log_debug(f"[random_tap] tap  ({x},{y})")
                adb_tap(x, y, device_id=self.device_id)

            wait_target = random.uniform(*RANDOM_TAP_DELAY_RANGE)
            wait_until = time.time() + wait_target
            while time.time() < wait_until:
                if not self.running:
                    break
                time.sleep(0.1)

    def check_interrupts(self, screen):
        now = time.time()
        for name, cfg in INTERRUPTS.items():
            if name == "live_two" and not self.get_setting("ENABLE_USE_SECOND_COOKIE", True):
                continue

            last_click = self._interrupt_last_click.get(name, 0)
            cooldown = cfg.get("cooldown", 1.0)
            if now - last_click < cooldown:
                continue

            threshold = cfg.get("threshold", MATCH_THRESHOLD)
            match = self.find_template(screen, cfg["template"], threshold=threshold)
            if match:
                self.log_info(f"⚡ แก้ไขป๊อปอัปขัดจังหวะ: {name}")
                self.log_debug(f"[interrupt] เจอ {name} ({cfg['template']}) -> กดตำแหน่ง {match}")
                try:
                    self.do_click(match)
                except Exception as e:
                    self.log_debug(f"[interrupt] กดไม่สำเร็จ: {e}")
                self._interrupt_last_click[name] = time.time()
                return name

        return None

    def check_pause_events(self, screen):
        for name, cfg in PAUSE_EVENTS.items():
            threshold = cfg.get("threshold", MATCH_THRESHOLD)
            match = self.find_template(screen, cfg["template"], threshold=threshold)
            if match:
                return name
        return None

    def handle_pause_start(self, pause_name, screen):
        cfg = PAUSE_EVENTS[pause_name]
        self.log_info(f"⚠️ หยุดชั่วคราว: {cfg['message'].split(':')[-1].strip()}")
        self.log_debug(f"[pause] เจอ {pause_name} ({cfg['template']}) -> หยุดทำงานรอผู้ใช้")

        screenshot_path = self.save_pause_screenshot(screen, pause_name)
        description = describe_image_with_gemini(screenshot_path)

        message_parts = [f"[{self.device_id}] " + cfg["message"]]
        if description:
            message_parts.append(f"\nรายละเอียดจาก Gemini: {description}")
        if screenshot_path:
            message_parts.append(f"\nภาพถูกเก็บไว้ที่เครื่อง: {os.path.basename(screenshot_path)}")

        send_line_message("\n".join(message_parts))
        return description

    def interrupt_watcher(self):
        self.log_debug("[interrupt_watcher] เริ่มทำงาน (background)")
        while self.running and not self._interrupt_thread_stop:
            try:
                screen = grab_screen(device_id=self.device_id)
                if screen is None:
                    time.sleep(0.1)
                    continue

                now = time.time()
                handled_any = False
                for name, cfg in INTERRUPTS.items():
                    if name == "live_two" and not self.get_setting("ENABLE_USE_SECOND_COOKIE", True):
                        continue
                    last_click = self._interrupt_last_click.get(name, 0)
                    cooldown = cfg.get("cooldown", 1.0)
                    if now - last_click < cooldown:
                        continue

                    threshold = cfg.get("threshold", MATCH_THRESHOLD)
                    match = self.find_template(screen, cfg["template"], threshold=threshold)
                    if match:
                        self.log_info(f"🔔 [watcher] เจอ interrupt: {name} -> กดทันที")
                        self.log_debug(f"[watcher] เจอ {name} ({cfg['template']}) -> กดตำแหน่ง {match}")
                        try:
                            self.do_click(match)
                        except Exception as e:
                            self.log_debug(f"[watcher] กดไม่สำเร็จ: {e}")
                        self._interrupt_last_click[name] = time.time()
                        handled_any = True
                        intr_delay = cfg.get("cooldown", 0.5)
                        time.sleep(intr_delay)
                        break

                if not handled_any:
                    time.sleep(0.08)
            except Exception as e:
                self.log_debug(f"[interrupt_watcher] เกิดข้อผิดพลาด: {e}")
                time.sleep(0.2)

        self.log_debug("[interrupt_watcher] หยุดทำงาน (background)")

    def bot_loop(self):
        self._in_bot_loop = True
        self.log_info("🤖 บอทเตรียมตัวรันระบบออโต้...")
        self.log_debug("บอทเริ่มทำงาน... (กด F7 เพื่อหยุด)")
        self.state_start_time = time.time()
        self.last_state_check = self.current_state
        self.adb_fail_count = 0
        self._last_reconnect_line_time = 0

        try:
            while self.running:
                try:
                    if not self.running:
                        break

                    if self.check_and_trigger_schedule():
                        self.state_start_time = time.time()
                        continue

                    if self.check_and_trigger_rest():
                        self.state_start_time = time.time()
                        continue

                    current_step = FLOW.get(self.current_state, {})
                    is_tap_while_wait_state = current_step.get("tap_while_wait", False)

                    if self.current_state != self.last_state_check:
                        self.state_start_time = time.time()

                        if self.current_state == "over_game" and self.get_setting("ENABLE_FAST_START_BOOST", True) and FAST_START_ENTRY_BURST:
                            self.do_fast_start_boost_fixed()

                        self.last_state_check = self.current_state
                    elif not self.paused_event_active and not is_tap_while_wait_state:
                        elapsed_time = time.time() - self.state_start_time
                        if elapsed_time > WATCHDOG_TIMEOUT_SECONDS:
                            msg = f"[{self.device_id}] ⚠️ [Watchdog] บอทติดอยู่สถานะ '{self.current_state}' นานเกิน {WATCHDOG_TIMEOUT_SECONDS} วินาที! จะทำการรีเซ็ตกลับไปสถานะเริ่มต้น"
                            self.log_info("🔄 ตรวจพบสถานะนิ่งเกินกำหนด: กำลัง Reset บอทไปเริ่มต้นใหม่")
                            self.log_debug(msg)
                            send_line_message(msg)

                            self.current_state = INITIAL_STATE
                            self.state_start_time = time.time()
                            self.paused_event_active = None
                            self.login_recovery_active = False
                            self.login_recovery_started_at = None

                            self.session_stats["watchdog_resets"] += 1
                            self.save_global_stats()
                            time.sleep(1)
                            continue

                    screen = grab_screen(device_id=self.device_id)
                    if screen is None:
                        self.adb_fail_count += 1
                        self.log_debug(f"[ADB Error] จับภาพหน้าจอไม่สำเร็จ ({self.adb_fail_count}/{ADB_MAX_RECONNECT_ATTEMPTS})")

                        if self.adb_fail_count >= ADB_MAX_RECONNECT_ATTEMPTS:
                            now = time.time()
                            if now - self._last_reconnect_line_time > 60:
                                msg = f"[{self.device_id}] 🚨 [ADB Error] การเชื่อมต่อ MuMu Player ({self.device_id}) ขัดข้องสะสม! กำลังพยายามบังคับ Reconnect ใหม่..."
                                self.log_info(f"🔌 กำลัง Reconnect สัญญาณ ADB ({self.device_id})...")
                                self.log_debug(msg)
                                send_line_message(msg)
                                self._last_reconnect_line_time = now
                            else:
                                self.log_debug(f"🚨 [ADB Error] ครบขีดจำกัด กำลัง Reconnect {self.device_id}... (ไม่ส่ง LINE ซ้ำ)")

                            if adb_connect(self.device_id):
                                self.log_info(f"🔌 เชื่อมต่อ MuMu Player ({self.device_id}) สำเร็จ!")
                                self.log_debug("✅ [ADB Reconnect] เชื่อมต่อสำเร็จแล้ว ทำงานต่อ...")
                            else:
                                self.log_info(f"❌ เชื่อมต่อ MuMu Player ({self.device_id}) ไม่สำเร็จ! รอ 2 วิเพื่อลองใหม่")
                                self.log_debug("❌ [ADB Reconnect] เชื่อมต่อไม่สำเร็จ รอสักครู่แล้วจะลองใหม่")

                            self.session_stats["adb_disconnects"] += 1
                            self.save_global_stats()
                            self.adb_fail_count = 0

                        time.sleep(2)
                        continue
                    else:
                        self.adb_fail_count = 0

                    if self.handle_login_recovery(screen):
                        continue

                    if PAUSE_EVENTS:
                        pause_name = self.check_pause_events(screen)

                        if pause_name:
                            cfg = PAUSE_EVENTS[pause_name]
                            if self.paused_event_active != pause_name:
                                self.handle_pause_start(pause_name, screen)
                                self.paused_event_active = pause_name
                            else:
                                print(f"[{self.device_id}] [pause] ยังอยู่ในสถานะหยุด ({pause_name}) — รอต่อ...")

                            time.sleep(cfg.get("check_interval", 2))
                            continue

                        elif self.paused_event_active is not None:
                            resumed_cfg = PAUSE_EVENTS.get(self.paused_event_active, {})
                            self.log_info("✅ กลับมาทำงานต่อตามปกติ")
                            self.log_debug(f"[pause] {self.paused_event_active} หายไปแล้ว -> กลับมาทำงานต่อจาก state: {self.current_state}")
                            resume_message = resumed_cfg.get("resume_message")
                            if resume_message:
                                send_line_message(f"[{self.device_id}] " + resume_message)
                            self.paused_event_active = None

                    if INTERRUPTS:
                        intr_name = self.check_interrupts(screen)
                        if intr_name:
                            continue

                    step = FLOW[self.current_state]
                    template_name = step["template"]
                    action_name = step["action"]
                    next_state = step["next_state"]
                    delay = step.get("delay", 1)
                    tap_while_wait = step.get("tap_while_wait", False)

                    match = self.find_template(screen, template_name)

                    if match:
                        action_func = self.ACTION_FUNCS[action_name]

                        if self.current_state == "start_game":
                            self.log_info("🍪 คลิกเริ่มรันรอบใหม่...")
                        elif self.current_state == "item_boots":
                            self.log_info("⚡ คลิกเลือกบูสเตอร์เพิ่มพลัง...")
                        elif self.current_state == "click_multi":
                            self.log_info("🛍️ คลิกเลือกซื้อไอเทม...")
                        elif self.current_state == "multi_buy":
                            self.log_info("🛒 กดยืนยันการซื้อไอเทมสำรอง...")
                        elif self.current_state == "let_go":
                            self.log_info("🚀 คุกกี้กระโดดเริ่มออกวิ่งแล้ว! ปล่อยบอททำงานอัตโนมัติ...")
                        elif self.current_state == "over_game":
                            self.log_info("🏁 คุกกี้ชน/หมดพลัง: ตรวจพบหน้าจบเกม (over_game)")

                            if self.get_setting("OCR_SCORE_ENABLED", True):
                                ocr_delay = float(self.get_setting("OCR_SCORE_DELAY", 1.5) or 1.5)
                                self.log_info(f"🔍 [OCR] ตรวจพบหน้าจบเกม: รอนิ่ง {ocr_delay} วินาทีเพื่อให้คะแนนเสถียรก่อนอ่าน...")
                                wait_start = time.time()
                                while time.time() - wait_start < ocr_delay:
                                    if not self.running:
                                        break
                                    time.sleep(0.1)

                                self.log_info("⏳ [OCR] กำลังประมวลผลอ่านคะแนนและเหรียญด้วย Gemini...")

                                score_data = None
                                max_ocr_attempts = 2
                                for attempt in range(1, max_ocr_attempts + 1):
                                    fresh_screen = grab_screen(device_id=self.device_id)
                                    if fresh_screen is None:
                                        fresh_screen = screen

                                    score_data = read_game_score_with_gemini(fresh_screen)
                                    if score_data and (score_data.get("score", 0) > 0 or score_data.get("coins", 0) > 0 or score_data.get("boxes", 0) > 0):
                                        break

                                    if attempt < max_ocr_attempts:
                                        self.log_info(f"🔄 [OCR] ผลลัพธ์ยังไม่สมบูรณ์ ลองอ่านซ้ำครั้งที่ {attempt + 1}/{max_ocr_attempts}...")
                                        time.sleep(1.5)

                                if score_data:
                                    boxes_cnt = score_data.get("boxes", 0)
                                    self.session_stats["last_score"] = score_data["score"]
                                    self.session_stats["last_coins"] = score_data["coins"]
                                    self.session_stats["last_boxes"] = boxes_cnt
                                    self.session_stats["scores_history"].append(score_data["score"])
                                    self.session_stats["coins_history"].append(score_data["coins"])
                                    self.session_stats["boxes_history"].append(boxes_cnt)

                                    metrics = self.get_performance_metrics()
                                    round_num = self.session_stats['successful_runs'] + 1
                                    score_line_msg = (
                                        f"[{self.device_id}] 🏁 สรุปผลคะแนนรอบที่ {round_num}\n"
                                        f"🏆 คะแนน: {score_data['score']:,}\n"
                                        f"🪙 เหรียญ: {score_data['coins']:,}\n"
                                        f"🎁 กล่องสมบัติ: {boxes_cnt} กล่อง (เฉลี่ย {metrics['boxes_per_hour']} กล่อง/ชม.)"
                                    )
                                    self.log_info(f"📊 อ่านคะแนนสำเร็จ: {score_data['score']:,} | เหรียญ: {score_data['coins']:,} | 🎁 กล่อง: {boxes_cnt} (เฉลี่ย {metrics['boxes_per_hour']}/ชม.)")
                                    send_line_message(score_line_msg)
                                    if self.get_setting("DISCORD_REPORT_ENABLED", True):
                                        target_wh = str(self.get_setting("SELECTED_DISCORD_WEBHOOK", "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน") or "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน")
                                        send_discord_embed(
                                            title=f"🏁 สรุปผลคะแนน ({self.device_id}) — รอบที่ {round_num}",
                                            fields=[
                                                {"name": "🏆 คะแนน", "value": f"`{score_data['score']:,}`", "inline": True},
                                                {"name": "🪙 เหรียญ", "value": f"`{score_data['coins']:,}`", "inline": True},
                                                {"name": "🎁 กล่องสมบัติ", "value": f"`{boxes_cnt}` (`{metrics['boxes_per_hour']}/ชม.`)", "inline": True},
                                            ],
                                            color=COLOR_INFO,
                                            target_webhook=target_wh
                                        )
                                    self.log_info("✅ ส่งข้อความสรุปผลคะแนนและสถิติกล่องสมบัติเข้า LINE / Discord เรียบร้อยแล้ว")
                                else:
                                    self.log_info("⚠️ ไม่สามารถอ่านคะแนนจากหน้าจอได้ (Gemini OCR อ่านไม่สำเร็จ หรือ API key ไม่ถูกต้อง)")

                            self.log_info("🔘 กระบวนการ OCR และส่งข้อความเสร็จสิ้น -> กำลังกดปุ่ม OK เพื่อผ่านหน้าจบเกม...")

                        self.log_debug(f"[match] เจอ template: {template_name} -> ทำ action: {action_name} ที่พิกัด {match}")

                        if self.current_state == "start_game" and self.previous_state == "over_game":
                            self.log_info("⏳ พบปุ่มเริ่มเกมเมื่อกลับมาจาก over_game: รอ 5 วินาทีแล้วกด")
                            wait_start = time.time()
                            while time.time() - wait_start < 5:
                                if not self.running:
                                    break
                                time.sleep(0.1)

                            refreshed_screen = grab_screen(device_id=self.device_id)
                            if refreshed_screen is not None:
                                re_match = self.find_template(refreshed_screen, template_name)
                                if re_match:
                                    action_func(re_match)
                                else:
                                    self.log_debug("[start_game] ปุ่มเริ่มหายไปหลังรอ 5 วินาที -> ข้ามการกด")
                            else:
                                self.log_debug("[start_game] ไม่สามารถจับภาพเพื่อยืนยันปุ่มได้หลังรอ 5 วินาที -> ข้ามการกด")

                        elif self.current_state == "over_game":
                            refreshed_screen = grab_screen(device_id=self.device_id)
                            if refreshed_screen is not None:
                                re_match = self.find_template(refreshed_screen, template_name)
                                if re_match:
                                    action_func(re_match)
                                else:
                                    action_func(match)
                            else:
                                action_func(match)

                        else:
                            action_func(match)

                        if self.current_state == "start_game" and not self.get_setting("ENABLE_BOOSTER_BUY", True):
                            self.log_info("⏩ ข้ามการซื้อไอเทมเพิ่มพลัง -> ไปหน้าเริ่มเล่นเกมโดยตรง...")
                            next_state = "let_go"

                        if next_state != self.current_state:
                            self.log_debug(f"   -> เปลี่ยน state: {self.current_state} -> {next_state}")

                            if self.current_state == "over_game" and next_state == INITIAL_STATE:
                                self.stats_mgr.session_stats["successful_runs"] += 1
                                self.stats_mgr.session_stats["total_runs"] += 1
                                self.log_info(f"🏆 เล่นผ่านสำเร็จแล้วรอบที่ {self.session_stats['successful_runs']}!")

                                report_every = self.get_setting("DISCORD_REPORT_EVERY_N_RUNS", 10)
                                if self.get_setting("DISCORD_REPORT_ENABLED", True) and (self.session_stats["successful_runs"] % report_every == 0):
                                    self.send_discord_run_report()

                                self.save_global_stats()
                            elif self.current_state == INITIAL_STATE:
                                if self.session_stats["total_runs"] == 0:
                                    self.session_stats["total_runs"] = 1
                                    self.save_global_stats()

                            self.previous_state = self.current_state
                            self.current_state = next_state

                            new_step = FLOW.get(self.current_state, {})
                            entry_delay = new_step.get("entry_delay", 0)
                            if entry_delay:
                                self.log_info(f"⏳ รอ {entry_delay} วินาที ให้ UI โหลดเต็มก่อนเริ่ม state: {self.current_state}")
                                wait_until = time.time() + float(entry_delay)
                                while time.time() < wait_until:
                                    if not self.running:
                                        break
                                    time.sleep(0.1)

                        start_wait = time.time()
                        waited = 0.0
                        poll_interval = 0.15
                        while waited < delay:
                            if not self.running:
                                break
                            try:
                                screen_during_wait = grab_screen(device_id=self.device_id)
                                if screen_during_wait is not None and INTERRUPTS:
                                    intr_handled = self.check_interrupts(screen_during_wait)
                                    if intr_handled:
                                        intr_cfg = INTERRUPTS.get(intr_handled, {})
                                        intr_delay = intr_cfg.get("cooldown", 1.0)
                                        self.log_info(f"⏳ หลังจัดการ interrupt '{intr_handled}' จะรอ {intr_delay} วินาที ตามคอนฟิก")
                                        wait_until_intr = time.time() + float(intr_delay)
                                        while time.time() < wait_until_intr:
                                            if not self.running:
                                                break
                                            time.sleep(0.1)
                                        break
                            except Exception:
                                pass

                            time.sleep(poll_interval)
                            waited = time.time() - start_wait
                    else:
                        self.log_debug(f"[{self.current_state}] ยังไม่เจอ {template_name}... กำลังสแกนหา")
                        if tap_while_wait:
                            if self.get_setting("ENABLE_RANDOM_TAP_WHILE_WAIT", True):
                                self.log_debug(f"[{self.current_state}] สุ่มกดปุ่มกระโดดต่อเนื่อง...")
                                guard_tpls = step.get("guard_templates", None)
                                self.do_random_tap_loop(delay, guard_templates=guard_tpls, state=self.current_state)
                            else:
                                self.log_debug(f"[{self.current_state}] ENABLE_RANDOM_TAP_WHILE_WAIT=False -> รอเฉยๆ (ไม่กดสุ่ม)")
                                start_wait = time.time()
                                waited = 0.0
                                poll_interval = 0.15
                                while waited < delay:
                                    if not self.running:
                                        break
                                    try:
                                        screen_during_wait = grab_screen(device_id=self.device_id)
                                        if screen_during_wait is not None and INTERRUPTS:
                                            intr_handled = self.check_interrupts(screen_during_wait)
                                            if intr_handled:
                                                intr_cfg = INTERRUPTS.get(intr_handled, {})
                                                intr_delay = intr_cfg.get("cooldown", 1.0)
                                                self.log_info(f"⏳ หลังจัดการ interrupt '{intr_handled}' จะรอ {intr_delay} วินาที ตามคอนฟิก")
                                                wait_until_intr = time.time() + float(intr_delay)
                                                while time.time() < wait_until_intr:
                                                    if not self.running:
                                                        break
                                                    time.sleep(0.1)
                                                break
                                    except Exception:
                                        pass
                                    time.sleep(poll_interval)
                                    waited = time.time() - start_wait
                        else:
                            start_wait = time.time()
                            waited = 0.0
                            poll_interval = 0.15
                            while waited < delay:
                                if not self.running:
                                    break
                                try:
                                    screen_during_wait = grab_screen(device_id=self.device_id)
                                    if screen_during_wait is not None and INTERRUPTS:
                                        intr_handled = self.check_interrupts(screen_during_wait)
                                        if intr_handled:
                                            intr_cfg = INTERRUPTS.get(intr_handled, {})
                                            intr_delay = intr_cfg.get("cooldown", 1.0)
                                            self.log_info(f"⏳ หลังจัดการ interrupt '{intr_handled}' จะรอ {intr_delay} วินาที ตามคอนฟิก")
                                            wait_until_intr = time.time() + float(intr_delay)
                                            while time.time() < wait_until_intr:
                                                if not self.running:
                                                    break
                                                time.sleep(0.1)
                                            break
                                except Exception:
                                    pass

                                time.sleep(poll_interval)
                                waited = time.time() - start_wait

                except Exception as crash_err:
                    msg = f"[{self.device_id}] 🚨 [Crash Recovery] เกิด Error ใน Bot Loop: {crash_err}\nบอทจะรอ 5 วินาทีก่อนเริ่มการรันในลูปใหม่อัตโนมัติ"
                    self.log_info("🚨 บอทเกิดข้อผิดพลาดขัดข้อง! กำลังเปิดระบบกู้คืนใน 5 วิ...")
                    self.log_debug(msg)
                    try:
                        send_line_message(msg)
                    except Exception:
                        pass
                    time.sleep(5)
        finally:
            self._in_bot_loop = False

    def start_bot(self):
        if not self.device_id:
            self.log_info("❌ ยังไม่ได้กรอกพอร์ต! กรุณากรอกพอร์ต (เช่น 5559) ในช่อง Device/Port แล้วกด Connect ก่อนเริ่มบอท")
            return

        screen_test = grab_screen(device_id=self.device_id)
        if screen_test is None:
            self.log_info(f"🔌 กำลังพยายามเชื่อมต่อ ADB ไปที่ {self.device_id}...")
            if not adb_connect(self.device_id):
                self.log_info(f"❌ เชื่อมต่อ ADB ไปที่ {self.device_id} ไม่สำเร็จ กรุณาตรวจสอบว่าเปิด Emulator และพอร์ตถูกต้องแล้วกด Connect อีกครั้ง")
                return

        self.running = True
        self.current_state = INITIAL_STATE
        self.state_start_time = time.time()
        self.last_state_check = INITIAL_STATE
        self.login_recovery_active = False
        self.login_recovery_started_at = None

        self.stats_mgr.reset_session()
        self.calculate_next_rest()

        self.log_info("▶️ สั่งเริ่มบอททำงานอัตโนมัติ...")
        self.log_debug(">> เริ่มออโต้ (F6) — เริ่มจาก state: " + self.current_state)

        try:
            self.run_templates_health_check()
        except Exception as e:
            print(f"[{self.device_id}] [Health Check] เกิดข้อผิดพลาดขณะรัน: {e}")

        try:
            self._interrupt_thread_stop = False
            self._interrupt_thread = threading.Thread(target=self.interrupt_watcher, daemon=True)
            self._interrupt_thread.start()
        except Exception as e:
            self.log_debug(f"[start_bot] ไม่สามารถเริ่ม interrupt watcher: {e}")

        if not getattr(self, "_in_bot_loop", False):
            self.log_debug("[start_bot] สปอว์น Thread สำหรับ bot_loop อัตโนมัติ...")
            threading.Thread(target=self.bot_loop, daemon=True).start()

    def stop_bot(self):
        self.running = False
        self.current_state = INITIAL_STATE
        self.login_recovery_active = False
        self.login_recovery_started_at = None
        self._interrupt_thread_stop = True
        self.log_info("⏸️ สั่งหยุดการทำงานบอทชั่วคราว")
        self.log_debug(">> หยุดออโต้ (F7)")
        self.save_global_stats(session_done=True)
        self.print_session_report()
