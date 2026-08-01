import os

import cv2

from src.config.settings import TEMPLATE_DIR
from src.core.adb_client import grab_screen

# ---------------------------------------------------------------------------
# โหมดช่วยครอปรูป template (--capture)
# ---------------------------------------------------------------------------


def capture_mode():
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    print("กำลังจับภาพหน้าจอจาก LDPlayer...")

    screen = grab_screen()
    if screen is None:
        print("!! จับภาพหน้าจอไม่สำเร็จ ตรวจสอบว่าเปิด LDPlayer และเชื่อมต่อ ADB อยู่")
        return

    print("ลากกรอบเลือกบริเวณปุ่ม แล้วกด ENTER หรือ SPACE เพื่อยืนยัน, กด c เพื่อยกเลิก")

    roi = cv2.selectROI("เลือกบริเวณปุ่ม (ลากแล้วกด Enter)", screen, showCrosshair=True)
    cv2.destroyAllWindows()

    x, y, w, h = roi
    if w == 0 or h == 0:
        print("ไม่ได้เลือกพื้นที่ ยกเลิกการบันทึก")
        return

    cropped = screen[y:y + h, x:x + w]
    filename = input("ตั้งชื่อไฟล์ template (เช่น start_button.png): ").strip()
    if not filename.endswith(".png"):
        filename += ".png"

    save_path = os.path.join(TEMPLATE_DIR, filename)
    cv2.imwrite(save_path, cropped)
    print(f"บันทึกแล้วที่: {save_path}")
