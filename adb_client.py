import subprocess

import cv2
import numpy as np

from config import ADB_PATH, DEVICE_ID

# ---------------------------------------------------------------------------
# ฟังก์ชันพื้นฐานสำหรับคุย ADB กับ LDPlayer
# ---------------------------------------------------------------------------


def adb_run(args, timeout=10):
    """
    รันคำสั่ง adb กับ device ที่กำหนด
    args: list ของ argument ต่อจาก 'adb -s <device>' เช่น ["shell", "input", "tap", "500", "800"]
    คืนค่า CompletedProcess (มี .stdout เป็น bytes)
    """
    cmd = [ADB_PATH, "-s", DEVICE_ID] + args
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"[ADB] คำสั่งหมดเวลา: {' '.join(args)}")
        return None
    except FileNotFoundError:
        print(f"[ADB] ไม่พบไฟล์ adb.exe ที่ path: {ADB_PATH}")
        return None


def adb_connect():
    """เชื่อมต่อ ADB กับ LDPlayer ก่อนเริ่มทำงาน (เผื่อยังไม่ได้ connect)"""
    try:
        subprocess.run([ADB_PATH, "start-server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except Exception:
        pass

    result = subprocess.run([ADB_PATH, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    output = result.stdout.decode(errors="ignore")
    print("[ADB] อุปกรณ์ที่เจอ:")
    print(output)

    if DEVICE_ID not in output:
        print(f"!! ไม่พบ device '{DEVICE_ID}' ใน `adb devices`")
        print("!! ตรวจสอบว่า:")
        print("   1) เปิด LDPlayer ทิ้งไว้แล้ว")
        print("   2) path ของ adb.exe ถูกต้อง:", ADB_PATH)
        print("   3) ลองรัน `adb devices` เองใน cmd เพื่อดู device id ที่ถูกต้อง")
        return False
    return True


_screen_size_cache = None


def get_screen_size():
    """ดึงขนาดหน้าจอจริงของ LDPlayer ผ่าน adb shell wm size"""
    global _screen_size_cache
    if _screen_size_cache:
        return _screen_size_cache

    result = adb_run(["shell", "wm", "size"])
    if result is None or result.returncode != 0:
        _screen_size_cache = (960, 540)
        return _screen_size_cache

    output = result.stdout.decode(errors="ignore")
    try:
        size_str = output.strip().split(":")[-1].strip()
        w, h = size_str.split("x")
        _screen_size_cache = (int(w), int(h))
    except Exception:
        _screen_size_cache = (960, 540)

    return _screen_size_cache


def grab_screen():
    """
    จับภาพหน้าจอของ LDPlayer ผ่าน adb exec-out screencap
    คืนค่าเป็น numpy array (BGR สำหรับ OpenCV) หรือ None ถ้าจับไม่สำเร็จ
    """
    result = adb_run(["exec-out", "screencap", "-p"], timeout=10)
    if result is None or not result.stdout:
        return None

    img_array = np.frombuffer(result.stdout, dtype=np.uint8)
    screen = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    return screen


def adb_tap(x, y):
    """สั่งแตะจอ LDPlayer ที่พิกัด (x, y) ผ่าน adb shell input tap"""
    adb_run(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=5)


def adb_long_press(x, y, duration_ms=150):
    """
    สั่งกดค้างที่พิกัด (x, y) เป็นเวลา duration_ms มิลลิวินาที
    ใช้ adb shell input swipe จากจุดเดิมไปจุดเดิม พร้อม duration
    เพื่อจำลองการกดค้างแบบนิ้วมนุษย์
    """
    xi, yi = str(int(x)), str(int(y))
    adb_run(
        ["shell", "input", "swipe", xi, yi, xi, yi, str(int(duration_ms))],
        timeout=5,
    )
