import os
import time
from datetime import datetime
import cv2
import config
from config import (
    INITIAL_STATE,
    MATCH_THRESHOLD,
    HEALTH_CHECK_WARNING_THRESHOLD,
    PAUSE_SCREENSHOT_DIR,
    LOGIN_TAE_TIMEOUT_SECONDS,
    LOGIN_POLL_INTERVAL_SECONDS,
)
from adb_client import grab_screen
from notifiers.line_notifier import send_line_message
from notifiers.gemini_vision import describe_image_with_gemini


class RecoveryManager:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.login_recovery_active = False
        self.login_recovery_started_at = None

    def run_templates_health_check(self):
        """
        ตรวจสอบคะแนน Template Matching เบื้องต้นก่อนรัน
        เพื่อประเมินว่าตัวบอทจะระบุภาพและปุ่มได้ดีเพียงใด
        """
        print(f"\n[{self.bot.device_id}] 🔍 กำลังสแกนตรวจสอบความพร้อมของภาพ Template ในโฟลเดอร์...")
        screen = grab_screen(device_id=self.bot.device_id)
        if screen is None:
            print(f"[{self.bot.device_id}] ❌ ตรวจสอบไม่สำเร็จ: ไม่สามารถดึงหน้าจอ MuMu Player ได้ กรุณาเชื่อมต่อ ADB ก่อน")
            return

        if not os.path.exists(config.TEMPLATE_DIR):
            print(f"[{self.bot.device_id}] ❌ ไม่พบโฟลเดอร์เก็บไฟล์ภาพ templates/!")
            return

        all_files = [f for f in os.listdir(config.TEMPLATE_DIR) if f.endswith(".png")]
        if not all_files:
            print(f"[{self.bot.device_id}] ❌ ไม่มีไฟล์ template ใดๆ ในระบบ")
            return

        low_scores = []
        print(f"{'ชื่อไฟล์ภาพ':<30} {'ความพร้อมประเมิน':<15}")
        print("-" * 50)

        for f in all_files:
            path = os.path.join(config.TEMPLATE_DIR, f)
            tmpl = cv2.imread(path)
            if tmpl is None:
                continue
            try:
                res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)

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
            print(f"\n[{self.bot.device_id}] ⚠️ ข้อแนะนำสำหรับการรันบอท:")
            for name, score in low_scores:
                print(f"  - ภาพ '{name}' มีการตอบรับต่ำ ({score:.2f}) แนะนำให้ใช้โหมด --capture ใหม่เพื่อความแม่นยำ")
        else:
            print(f"\n[{self.bot.device_id}] 🚀 ภาพ Template สำคัญส่วนใหญ่พร้อมใช้งานแล้ว!")
        print("-" * 50 + "\n")

    def save_pause_screenshot(self, screen, event_name):
        """
        เซฟภาพหน้าจอตอนที่เกิด pause event ไว้ในโฟลเดอร์ pause_screenshots/
        """
        try:
            os.makedirs(PAUSE_SCREENSHOT_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.bot.device_id}_{event_name}_{timestamp}.png"
            save_path = os.path.join(PAUSE_SCREENSHOT_DIR, filename)
            cv2.imwrite(save_path, screen)
            print(f"[{self.bot.device_id}] [pause] เซฟภาพหน้าจอไว้ที่: {save_path}")
            return save_path
        except Exception as e:
            print(f"[{self.bot.device_id}] [pause] เซฟภาพไม่สำเร็จ: {e}")
            return None

    def handle_login_recovery(self, screen):
        if not self.login_recovery_active:
            login_match = self.bot.find_template(screen, "login.png")
            if not login_match:
                return False

            self.login_recovery_active = True
            self.login_recovery_started_at = time.time()
            self.bot.log_info("🔐 ตรวจพบหน้าล็อกอิน: หยุด Flow ชั่วคราวและกำลังกด login.png")
            self.bot.log_debug(f"[login] เจอ login.png -> กดตำแหน่ง {login_match}")
            self.bot.do_click(login_match)
            return True

        login_tae_match = self.bot.find_template(screen, "login_tae.png")
        if login_tae_match:
            self.bot.log_info("👤 พบปุ่ม login_tae.png: กำลังกดเลือกบัญชี")
            self.bot.log_debug(f"[login] เจอ login_tae.png -> กดตำแหน่ง {login_tae_match}")
            self.bot.do_click(login_tae_match)

            self.bot.current_state = INITIAL_STATE
            self.bot.paused_event_active = None
            self.bot.state_start_time = time.time()
            self.bot.last_state_check = INITIAL_STATE
            self.bot.adb_fail_count = 0
            self.login_recovery_active = False
            self.login_recovery_started_at = None

            self.bot.log_info("✅ ล็อกอินสำเร็จ: รีเซ็ต Flow กลับไปเริ่มเกมใหม่แล้ว")
            return True

        elapsed = time.time() - (self.login_recovery_started_at or time.time())
        if elapsed >= LOGIN_TAE_TIMEOUT_SECONDS:
            self.bot.log_info(
                f"⚠️ ยังไม่พบ login_tae.png หลังรอ {LOGIN_TAE_TIMEOUT_SECONDS} วินาที "
                "บอทยังคงหยุดรออยู่"
            )
            self.login_recovery_started_at = time.time()

        time.sleep(LOGIN_POLL_INTERVAL_SECONDS)
        return True
