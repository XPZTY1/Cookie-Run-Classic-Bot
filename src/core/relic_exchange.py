import time
from src.core.adb_client import grab_screen, adb_run
from src.config.settings import MATCH_THRESHOLD


# ชื่อไฟล์ภาพ template ที่ใช้ในระบบแลกเปลี่ยน Relic
RELIC_TEMPLATES = {
    "menu_button": "relic_menu_button.png",  # ปุ่มเปิดหน้าแลก Relic (บนหน้าหลัก)
    "ready":       "relic_ready.png",        # ปุ่มแลกในหน้าแลก (ตอนที่พร้อมกดแลกได้)
    "confirm":     "confirm_relic.png",      # ปุ่มยืนยันรับของรางวัลหลังเปิดกล่อง Relic
    "close":       "close_relic.png",        # ปุ่ม X ปิดหน้าแลกเมื่อยังแลกไม่ได้
}

# ตั้งค่าเริ่มต้น
RELIC_STEP_TIMEOUT    = 3.0   # timeout สแกนปุ่มเปิดหน้าแลก / ปุ่มแลก / ปุ่มปิด (วินาที)
RELIC_CONFIRM_TIMEOUT = 15   # รอปุ่ม confirm (รับของรางวัล) สูงสุดกี่วินาที เผื่ออนิเมชันเปิดกล่อง
RELIC_UI_OPEN_DELAY   = 1.5   # รอ UI หน้าแลกเปิดขึ้นมาหลังกดปุ่มเปิด (วินาที)
RELIC_POLL_INTERVAL   = 0.4   # ช่วงเวลาระหว่างการสแกนซ้ำแต่ละครั้ง (วินาที)
RELIC_COOLDOWN_SECONDS = 30.0  # หลังเช็ก Relic แล้ว (ไม่ว่าจะสำเร็จหรือไม่) รออย่างน้อยกี่วินาทีก่อนเช็กใหม่ (ป้องกันลูปอนันต์)

# ขอบเขตค่าที่ผู้ใช้ตั้งได้ (mirror ของ UI Spinbox)
RELIC_EVERY_N_MIN = 1
RELIC_EVERY_N_MAX = 50
RELIC_EVERY_N_DEFAULT = 10


def _send_back_keyevent(bot):
    """Fallback: ส่งปุ่ม BACK ของ Android เพื่อปิดหน้าต่างปัจจุบัน"""
    try:
        adb_run(["shell", "input", "keyevent", "4"], device_id=bot.device_id)
    except Exception:
        pass


class RelicExchangeManager:
    """
    จัดการ Flow การแลกเปลี่ยน Relic อัตโนมัติ

    หลักการทำงาน:
    1. นับรอบที่เล่นจบสะสม (increment_counter ถูกเรียกจาก bot_loop)
    2. เมื่อครบ N รอบและบอทอยู่สถานะ start_game จะเข้า flow (run_relic_flow)
    3. กดเข้าหน้าแลก → เช็กปุ่มแลกข้างใน:
       - ถ้าพร้อมแลก → กดแลก → รอรับของ → รีเซ็ตตัวนับ
       - ถ้ายังไม่พร้อม → กดปิดหน้าแลกออกมา (ไม่ reset ตัวนับ → ลองใหม่รอบถัดไป)
    4. ระหว่าง flow จะ lock สถานะ (relic_exchange_active = True) เพื่อหยุด INTERRUPTS
    """

    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.relic_exchange_active = False
        self._relic_counter = 0  # นับรอบสะสม — reset เฉพาะตอนแลกสำเร็จ
        self._last_relic_check_time = 0.0  # เวลาของการเช็ก Relic ครั้งล่าสุด — cooldown ป้องกันลูปอนันต์

    # ------------------------------------------------------------------
    # Properties / Helpers
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        return bool(self.bot.get_setting("RELIC_EXCHANGE_ENABLED", False))

    def _get_every_n(self) -> int:
        """ดึงค่ารอบการเช็ก (N) จาก settings พร้อม clamp เข้าขอบเขตที่กำหนด"""
        try:
            n = int(self.bot.get_setting("RELIC_EXCHANGE_EVERY_N_RUNS", RELIC_EVERY_N_DEFAULT) or RELIC_EVERY_N_DEFAULT)
        except (TypeError, ValueError):
            n = RELIC_EVERY_N_DEFAULT
        return max(RELIC_EVERY_N_MIN, min(RELIC_EVERY_N_MAX, n))

    def increment_counter(self):
        """เพิ่มตัวนับรอบ — ถูกเรียกทุกครั้งที่เล่นจบรอบสำเร็จ"""
        self._relic_counter += 1

    def check_due(self) -> bool:
        """คืนค่า True ถ้าครบรอบที่จะต้องเช็ก/แลก Relic แล้ว และผ่าน cooldown แล้ว"""
        if not self.is_enabled():
            return False
        if self.relic_exchange_active:
            return False
        if self._relic_counter < self._get_every_n():
            return False
        # cooldown: หลังเช็กครั้งล่าสุดต้องรอ RELIC_COOLDOWN_SECONDS วินาที ก่อนเช็กใหม่
        elapsed_since_last_check = time.time() - self._last_relic_check_time
        return elapsed_since_last_check >= RELIC_COOLDOWN_SECONDS

    # ------------------------------------------------------------------
    # Main Flow
    # ------------------------------------------------------------------

    def run_relic_flow(self) -> bool:
        """
        รันขั้นตอนแลก Relic ทั้งหมด
        คืนค่า True = แลกสำเร็จ, False = ยังไม่พร้อม/ล้มเหลว/หยุดบอท
        """
        self.relic_exchange_active = True
        self.bot.log_info(f"🏛️ [Relic] เริ่มเช็กการแลก Relic (ครบ {self._get_every_n()} รอบ) — ล็อค INTERRUPTS ชั่วคราว")

        try:
            # STEP 1: กดปุ่มเปิดหน้าแลก
            if not self._step_click("menu_button", "🏛️ [Relic] กดปุ่มเปิดหน้าแลก Relic...", RELIC_STEP_TIMEOUT):
                self.bot.log_info("⚠️ [Relic] ไม่พบปุ่มเปิดหน้าแลก — อาจไม่ได้อยู่หน้าหลัก ข้ามไปเริ่มเกมปกติ")
                return False
            time.sleep(RELIC_UI_OPEN_DELAY)  # รอ UI หน้าแลกเปิดขึ้นมา

            # STEP 2: สแกนปุ่มแลกในหน้าแลก (เช็กพร้อมแลกหรือยัง)
            ready_pos = self._find_with_timeout("ready", "🔍 [Relic] สแกนปุ่มแลกในหน้าแลก...", RELIC_STEP_TIMEOUT)
            if not ready_pos:
                # STEP 2b: ยังไม่พร้อมแลก → กดปิดหน้าแลกออกมา
                self.bot.log_info("⏳ [Relic] ยังไม่พร้อมแลก (ไม่พบปุ่มแลก) — กดปิดหน้าแลกแล้วฟาร์มต่อ")
                self._close_relic_panel()
                self.bot.log_info("🔁 [Relic] จะลองเช็กใหม่รอบถัดไปโดยอัตโนมัติ")
                return False  # ไม่ reset counter → ลองใหม่รอบถัดไป

            # พร้อมแลก → กดปุ่มแลก
            self.bot.do_click(ready_pos)
            self.bot.log_info(f"   ✓ กดปุ่มแลก 'ready' สำเร็จที่ตำแหน่ง {ready_pos[:2]}")

            # STEP 3: รอปุ่มยืนยันรับของรางวัล (เผื่ออนิเมชันเปิดกล่อง)
            confirm_pos = self._find_with_timeout(
                "confirm",
                "🎁 [Relic] รอหน้ารับของรางวัล (เผื่ออนิเมชันเปิดกล่อง)...",
                RELIC_CONFIRM_TIMEOUT,
            )
            if not confirm_pos:
                self.bot.log_info(f"⚠️ [Relic] ไม่พบปุ่มรับของภายใน {RELIC_CONFIRM_TIMEOUT:.0f} วิ — ส่ง BACK ออกแล้วฟาร์มต่อ")
                _send_back_keyevent(self.bot)
                time.sleep(0.8)
                return False

            # STEP 4: กดรับของรางวัล
            self.bot.do_click(confirm_pos)
            self.bot.log_info(f"   ✓ กดปุ่มรับของ 'confirm' สำเร็จที่ตำแหน่ง {confirm_pos[:2]}")
            time.sleep(1.0)

            # STEP 5: สำเร็จ — รีเซ็ตตัวนับ + นับสถิติ + แจ้งเตือน
            self._relic_counter = 0
            try:
                self.bot.session_stats["relic_exchanges"] = self.bot.session_stats.get("relic_exchanges", 0) + 1
            except Exception:
                pass
            self._notify_success()
            self.bot.log_info("✅ [Relic] แลก Relic สำเร็จ! รีเซ็ตตัวนับรอบเป็น 0 → กลับไปฟาร์มต่อ")
            return True

        except Exception as e:
            self.bot.log_info(f"🚨 [Relic] เกิดข้อผิดพลาดใน Relic Flow: {e}")
            return False

        finally:
            self.relic_exchange_active = False
            self._last_relic_check_time = time.time()  # ตั้ง cooldown ทุกครั้งที่ flow จบ ป้องกันลูปอนันต์
            self.bot.log_info("🔓 [Relic] ปลดล็อค INTERRUPTS — กลับสู่การทำงานปกติ")

    # ------------------------------------------------------------------
    # Internal Steps
    # ------------------------------------------------------------------

    def _find(self, key: str):
        """สแกนหน้าจอหาภาพ template แล้วคืนค่าตำแหน่ง หรือ None"""
        screen = grab_screen(device_id=self.bot.device_id)
        if screen is None:
            return None
        template_name = RELIC_TEMPLATES.get(key)
        if not template_name:
            return None
        return self.bot.find_template(screen, template_name, threshold=MATCH_THRESHOLD)

    def _step_click(self, key: str, log_msg: str, timeout: float) -> bool:
        """รอหาปุ่ม key แล้วกด — คืนค่า True ถ้าสำเร็จภายใน timeout วินาที"""
        self.bot.log_info(log_msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.bot.running:
                return False
            pos = self._find(key)
            if pos:
                self.bot.do_click(pos)
                self.bot.log_info(f"   ✓ กดปุ่ม '{key}' สำเร็จที่ตำแหน่ง {pos[:2]}")
                return True
            time.sleep(RELIC_POLL_INTERVAL)
        self.bot.log_info(f"⚠️ [Relic] หาปุ่ม '{key}' ไม่เจอภายใน {timeout:.0f} วิ")
        return False

    def _find_with_timeout(self, key: str, log_msg: str, timeout: float):
        """เหมือน _step_click แต่แค่สแกนหา (ไม่กด) — คืนค่าตำแหน่ง หรือ None"""
        self.bot.log_info(log_msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.bot.running:
                return None
            pos = self._find(key)
            if pos:
                return pos
            time.sleep(RELIC_POLL_INTERVAL)
        return None

    def _close_relic_panel(self):
        """ปิดหน้าแลก Relic — ลองสแกนปุ่มปิดก่อน ถ้าไม่เจอ fallback ส่ง BACK keyevent"""
        if self._step_click("close", "🔙 [Relic] กดปุ่มปิดหน้าแลก...", RELIC_STEP_TIMEOUT):
            return
        # fallback: ส่ง BACK keyevent
        self.bot.log_info("⚠️ [Relic] ไม่พบปุ่มปิด — ส่ง BACK keyevent เป็น fallback")
        _send_back_keyevent(self.bot)
        time.sleep(0.8)

    def _notify_success(self):
        """ส่งแจ้งเตือน Discord/LINE เมื่อแลก Relic สำเร็จ"""
        try:
            from src.notifiers.line_notifier import send_line_message
            send_line_message(f"[{self.bot.device_id}] 🏛️ แลก Relic สำเร็จ! (สะสม {self.bot.session_stats.get('relic_exchanges', 0)} ครั้ง)")
        except Exception:
            pass

        try:
            if self.bot.get_setting("DISCORD_REPORT_ENABLED", True):
                from src.notifiers.discord_notifier import send_discord_embed, COLOR_INFO
                target_wh = str(self.bot.get_setting("SELECTED_DISCORD_WEBHOOK", "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน") or "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน")
                send_discord_embed(
                    title=f"🏛️ แลก Relic สำเร็จ ({self.bot.device_id})",
                    fields=[
                        {"name": "✅ สถานะ", "value": "`แลกเรียบร้อย`", "inline": True},
                        {"name": "🔢 สะสม", "value": f"`{self.bot.session_stats.get('relic_exchanges', 0)} ครั้ง`", "inline": True},
                        {"name": "⏭️ รอบถัดไป", "value": f"`อีก {self._get_every_n()} รอบ`", "inline": True},
                    ],
                    color=COLOR_INFO,
                    target_webhook=target_wh,
                )
        except Exception:
            pass
