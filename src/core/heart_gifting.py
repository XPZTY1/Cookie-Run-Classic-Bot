import time
from src.core.adb_client import grab_screen
from src.config.settings import MATCH_THRESHOLD


# ชื่อไฟล์ภาพ template ที่ใช้ในระบบส่งหัวใจ
HEART_TEMPLATES = {
    "mailbox":        "mail_icon.png",        # ปุ่มซองจดหมาย (หน้าหลัก)
    "claim_send_all": "claim_send_all.png",   # ปุ่มรับและส่งให้ทั้งหมด
    "confirm":        "confirm2_green.png",   # ปุ่มยืนยัน (กดรัวจนหาย)
    "close":          "close_mailbox.png",    # ปุ่มปิด/กลับหน้าหลัก
}

# ตั้งค่าเริ่มต้น
HEART_CONFIRM_LOOP_INTERVAL = 0.5   # ช่วงเวลา (วินาที) ระหว่างการกด confirm แต่ละครั้ง
HEART_CONFIRM_MAX_WAIT    = 60.0   # รอปุ่ม confirm สูงสุดกี่วินาที ก่อนถือว่าเสร็จหรือมีปัญหา
HEART_STEP_TIMEOUT        = 15.0   # timeout ของแต่ละสเต็ป (ปุ่มต้องปรากฏภายในกี่วินาที)


class HeartGiftingManager:
    """
    จัดการ Flow การรับและส่งหัวใจให้เพื่อนอัตโนมัติ

    หลักการทำงาน:
    1. ตรวจสอบว่าถึงเวลาส่งหัวใจหรือยัง (check_due)
    2. ถ้าถึงเวลาและบอทอยู่สถานะ start_game ให้เข้า flow (run_heart_flow)
    3. ระหว่าง flow จะ lock สถานะ (heart_gifting_active = True) เพื่อหยุด INTERRUPTS
    4. เมื่อเสร็จแล้วให้ปลดล็อคและรีเซ็ตตัวนับเวลา
    """

    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.heart_gifting_active = False
        self._last_heart_time = 0.0  # เวลา Unix ของการส่งหัวใจครั้งล่าสุด

    # ------------------------------------------------------------------
    # Properties / Helpers
    # ------------------------------------------------------------------

    def _get_interval_seconds(self) -> float:
        """ดึงค่า interval จาก settings (หน่วยเป็นวินาที)"""
        minutes = float(self.bot.get_setting("HEART_INTERVAL_MINUTES", 30) or 30)
        return minutes * 60.0

    def is_enabled(self) -> bool:
        return bool(self.bot.get_setting("HEART_AUTO_ENABLED", False))

    def check_due(self) -> bool:
        """คืนค่า True ถ้าถึงเวลาส่งหัวใจแล้ว"""
        if not self.is_enabled():
            return False
        if self.heart_gifting_active:
            return False
        elapsed = time.time() - self._last_heart_time
        return elapsed >= self._get_interval_seconds()

    def time_until_next(self) -> float:
        """คืนค่าจำนวนวินาทีที่เหลือก่อนถึงรอบส่งหัวใจถัดไป (0 = ถึงเวลาแล้ว)"""
        if not self.is_enabled():
            return -1
        remaining = self._get_interval_seconds() - (time.time() - self._last_heart_time)
        return max(0.0, remaining)

    # ------------------------------------------------------------------
    # Main Flow
    # ------------------------------------------------------------------

    def run_heart_flow(self) -> bool:
        """
        รันขั้นตอนการส่งหัวใจทั้งหมด
        คืนค่า True = เสร็จปกติ, False = ล้มเหลว/หยุดบอท
        """
        self.heart_gifting_active = True
        self.bot.log_info("💌 [Heart] เริ่มส่ง/รับหัวใจให้เพื่อนอัตโนมัติ (ล็อค INTERRUPTS ชั่วคราว)")

        try:
            # สเต็ป 1: กดปุ่มซองจดหมาย
            if self._step_click("mailbox", "💌 [Heart] กดปุ่มซองจดหมาย..."):
                time.sleep(1.5)  # รอ UI เปิดขึ้นมา

                # สเต็ป 2: กดปุ่มรับและส่งให้ทั้งหมด (หากล้มเหลวก็ยังต้องกดปุ่มปิดออกไป)
                if self._step_click("claim_send_all", "💝 [Heart] กดปุ่มรับและส่งให้ทั้งหมด..."):
                    time.sleep(1.0)
                    # สเต็ป 3: ลูปกด confirm2_green จนกว่าปุ่มจะหายไป
                    self._confirm_loop()

                # สเต็ป 4: กดปุ่มออกกลับหน้าหลัก (รันเสมอถ้าเปิดซองจดหมายสำเร็จ)
                if not self._step_click("close", "🔙 [Heart] กดปุ่มออกกลับหน้าหลัก..."):
                    self.bot.log_info("⚠️ [Heart] หาปุ่มปิดหน้าต่างไม่เจอ — อาจหลุดออกมาเองแล้ว")
                time.sleep(1.0)

            # รีเซ็ตตัวนับเวลา
            self._last_heart_time = time.time()
            interval_min = self._get_interval_seconds() / 60
            self.bot.log_info(f"✅ [Heart] ดำเนินการขั้นตอนส่ง/รับหัวใจเรียบร้อย! รอบถัดไปในอีก {interval_min:.0f} นาที")
            return True

        except Exception as e:
            self.bot.log_info(f"🚨 [Heart] เกิดข้อผิดพลาดใน Heart Flow: {e}")
            return False

        finally:
            self.heart_gifting_active = False
            self.bot.log_info("🔓 [Heart] ปลดล็อค INTERRUPTS — กลับสู่การทำงานปกติ")

    # ------------------------------------------------------------------
    # Internal Steps
    # ------------------------------------------------------------------

    def _find(self, key: str):
        """สแกนหน้าจอหาภาพ template และคืนค่าตำแหน่ง หรือ None"""
        screen = grab_screen(device_id=self.bot.device_id)
        if screen is None:
            return None
        template_name = HEART_TEMPLATES.get(key)
        if not template_name:
            return None
        return self.bot.find_template(screen, template_name, threshold=MATCH_THRESHOLD)

    def _step_click(self, key: str, log_msg: str) -> bool:
        """
        รอหาปุ่ม key แล้วกด — คืนค่า True ถ้าสำเร็จ
        Timeout ตาม HEART_STEP_TIMEOUT วินาที
        """
        self.bot.log_info(log_msg)
        deadline = time.time() + HEART_STEP_TIMEOUT
        while time.time() < deadline:
            if not self.bot.running:
                return False
            pos = self._find(key)
            if pos:
                self.bot.do_click(pos)
                self.bot.log_info(f"   ✓ กดปุ่ม '{key}' สำเร็จที่ตำแหน่ง {pos[:2]}")
                return True
            time.sleep(0.4)

        self.bot.log_info(f"⚠️ [Heart] หาปุ่ม '{key}' ไม่เจอภายใน {HEART_STEP_TIMEOUT:.0f} วิ")
        return False

    def _confirm_loop(self):
        """
        กดปุ่ม confirm2_green รัวๆ จนกว่ามันจะหายไปจากหน้าจอ
        (หมายความว่าส่งหัวใจครบทุกคนแล้ว)
        """
        self.bot.log_info("🔁 [Heart] เริ่มกด Confirm รัวจนครบทุกคน...")
        deadline = time.time() + HEART_CONFIRM_MAX_WAIT
        confirmed_count = 0

        while time.time() < deadline:
            if not self.bot.running:
                break
            pos = self._find("confirm")
            if pos:
                self.bot.do_click(pos)
                confirmed_count += 1
                self.bot.log_info(f"   💚 กด Confirm ครั้งที่ {confirmed_count}")
                time.sleep(HEART_CONFIRM_LOOP_INTERVAL)
            else:
                # ปุ่มหายไปแล้ว = ส่งครบทุกคน
                self.bot.log_info(f"   ✅ ปุ่ม Confirm หายไปแล้ว (กดทั้งหมด {confirmed_count} ครั้ง) — ส่งหัวใจครบทุกคนแล้ว!")
                break
