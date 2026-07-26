import os

import cv2

from config import BASE_DIR, MATCH_THRESHOLD, TEMPLATE_DIR
from adb_client import grab_screen

# ---------------------------------------------------------------------------
# โหมดตรวจสอบค่า match ของ template ทั้งหมด (--debug)
# ---------------------------------------------------------------------------


def debug_mode(template_name=None):
    print("กำลังจับภาพหน้าจอจาก LDPlayer...")
    screen = grab_screen()
    if screen is None:
        print("!! จับภาพหน้าจอไม่สำเร็จ ตรวจสอบการเชื่อมต่อ ADB")
        return

    if template_name:
        names = [template_name]
    else:
        if not os.path.isdir(TEMPLATE_DIR):
            print("ยังไม่มีโฟลเดอร์ templates/")
            return
        names = [f for f in os.listdir(TEMPLATE_DIR) if f.endswith(".png")]

    if not names:
        print("ไม่พบไฟล์ template ให้ตรวจสอบ")
        return

    print(f"\nตั้งค่า MATCH_THRESHOLD ปัจจุบัน = {MATCH_THRESHOLD}\n")
    print(f"{'ไฟล์':<25} {'ค่าที่เจอ':<12} {'ผ่าน threshold?'}")
    print("-" * 55)

    for name in names:
        path = os.path.join(TEMPLATE_DIR, name)
        template = cv2.imread(path)
        if template is None:
            print(f"{name:<25} อ่านไฟล์ไม่ได้ (path ผิด หรือไฟล์เสีย)")
            continue

        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        passed = "ผ่าน ✅" if max_val >= MATCH_THRESHOLD else "ไม่ผ่าน ❌"
        print(f"{name:<25} {max_val:<12.4f} {passed}")

        h, w = template.shape[:2]
        debug_img = screen.copy()
        cv2.rectangle(debug_img, max_loc, (max_loc[0] + w, max_loc[1] + h), (0, 0, 255), 3)
        debug_path = os.path.join(BASE_DIR, f"debug_{name}")
        cv2.imwrite(debug_path, debug_img)
        print(f"   -> เซฟภาพจุดที่ match ดีที่สุดไว้ที่: {debug_path}")

    print("\nคำแนะนำ:")
    print("- ถ้าค่า 'ผ่าน threshold' ต่ำกว่ามาตั้งไว้ไม่มาก ลองลด MATCH_THRESHOLD ลง (เช่น 0.7)")
    print("- ถ้าค่าต่ำมากๆ (เช่น < 0.5) แปลว่า template หรือหน้าจอไม่ตรงกันเลย ต้อง capture ใหม่")
    print("- เปิดไฟล์ debug_xxx.png ดูว่ากรอบสีแดงชี้ไปตรงจุดที่ถูกต้องไหม")
