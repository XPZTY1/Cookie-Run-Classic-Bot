import os
import sys
import io

# บังคับ stdout/stderr ให้ใช้ UTF-8 เสมอ ป้องกัน UnicodeEncodeError บน Windows Terminal
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import keyboard

from config import DEVICE_ID, TEMPLATE_DIR
from adb_client import adb_connect, grab_screen
from notifiers.line_notifier import send_line_message
from notifiers.gemini_vision import describe_screen_with_gemini
from tools.capture_mode import capture_mode
from tools.debug_mode import debug_mode
from bot_engine import bot_loop, start_bot, stop_bot, quit_program

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if not adb_connect():
        print("!! ไม่สามารถเชื่อมต่อ LDPlayer ผ่าน ADB ได้ กรุณาตรวจสอบก่อนใช้งานต่อ")
        return

    if "--capture" in sys.argv:
        capture_mode()
        return

    if "--debug" in sys.argv:
        idx = sys.argv.index("--debug")
        template_arg = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else None
        debug_mode(template_arg)
        return

    if "--test-line" in sys.argv:
        send_line_message("🔔 ทดสอบการแจ้งเตือนจาก Cookie Run Auto Bot")
        return

    if "--test-discord" in sys.argv:
        from notifiers.discord_notifier import send_discord_report
        print("[Discord] กำลังทดสอบส่งข้อความแจ้งเตือน...")
        send_discord_report("🔔 **ทดสอบการแจ้งเตือนจาก Cookie Run Auto Bot ผ่าน Discord Webhook** ✅")
        return


    if "--test-gemini" in sys.argv:
        print("[Gemini] กำลังทดสอบ... จับภาพหน้าจอจาก LDPlayer แล้วส่งให้ Gemini บรรยาย")
        screen = grab_screen()
        if screen is None:
            print("!! จับภาพหน้าจอไม่สำเร็จ ตรวจสอบการเชื่อมต่อ ADB ก่อน")
            return

        result = describe_screen_with_gemini(screen)
        if result:
            print("[Gemini] เชื่อมต่อสำเร็จ ✅")
            print("[Gemini] คำตอบที่ได้:")
            print(result)
        else:
            print("[Gemini] เชื่อมต่อไม่สำเร็จ ❌ ดู error ด้านบน (เช่น key ผิด, โควตาหมด, network)")
        return

    if not os.path.isdir(TEMPLATE_DIR) or not os.listdir(TEMPLATE_DIR):
        print("!! ยังไม่มีไฟล์ template ใน templates/")
        print("!! รันโหมด --capture ก่อนเพื่อสร้างรูป template ของปุ่มต่างๆ")
        print("   ตัวอย่าง: python main.py --capture")
        return

    # ลงทะเบียน Hotkeys เผื่อผู้ใช้ต้องการกดผ่านแป้นพิมพ์ขณะหน้าต่าง GUI เปิดอยู่
    keyboard.add_hotkey("F6", start_bot)
    keyboard.add_hotkey("F7", stop_bot)
    keyboard.add_hotkey("F9", quit_program)

    # หากผู้ใช้ระบุ --no-gui จะรันบน console แบบเดิม
    if "--no-gui" in sys.argv:
        print("=" * 50)
        print("Cookie Run Classic Auto Bot (Console Mode)")
        print("Device:", DEVICE_ID)
        print("F6 = เริ่มออโต้ | F7 = หยุดออโต้ | F9 = ออกจากโปรแกรม")
        print("=" * 50)
        bot_loop()
    else:
        # เปิดรัน GUI Mode เป็น Default
        import gui
        gui.run_gui()


if __name__ == "__main__":
    main()
