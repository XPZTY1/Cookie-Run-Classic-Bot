import subprocess

import cv2
import numpy as np

from config import ADB_PATH, DEVICE_ID

# ---------------------------------------------------------------------------
# ฟังก์ชันพื้นฐานสำหรับคุย ADB กับ LDPlayer
# ---------------------------------------------------------------------------


import config


def adb_run(args, timeout=10):
    """
    รันคำสั่ง adb กับ device ที่กำหนดใน config.DEVICE_ID
    args: list ของ argument ต่อจาก 'adb -s <device>' เช่น ["shell", "input", "tap", "500", "800"]
    คืนค่า CompletedProcess (มี .stdout เป็น bytes)
    """
    # อ่าน ADB_PATH และ DEVICE_ID จาก config ทุกครั้ง เพื่อให้ตอบสนองการเปลี่ยนค่า Multi-Instance
    adb_path = getattr(config, "ADB_PATH", ADB_PATH)
    device_id = getattr(config, "DEVICE_ID", DEVICE_ID)
    cmd = [adb_path, "-s", device_id] + args
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
        print(f"[ADB] ไม่พบไฟล์ adb.exe ที่ path: {adb_path}")
        return None


def adb_connect(target_device=None):
    """
    เชื่อมต่อ ADB กับ Emulator ตาม target_device หรือ config.DEVICE_ID
    รองรับทั้งพอร์ต 5555, 5559, 7555, 16384 และ serial 'emulator-5554'
    """
    global _screen_size_cache
    _screen_size_cache = None

    if target_device:
        target_device = str(target_device).strip()
        if target_device:
            if ":" not in target_device and not target_device.startswith("emulator-"):
                target_device = f"127.0.0.1:{target_device}"
            config.DEVICE_ID = target_device

    device_id = getattr(config, "DEVICE_ID", "").strip()
    if not device_id:
        print("[ADB] ❌ ยังไม่ได้ระบุพอร์ต/Device IP:Port กรุณากรอกพอร์ตก่อนกดเชื่อมต่อ")
        return False

    if ":" not in device_id and not device_id.startswith("emulator-"):
        device_id = f"127.0.0.1:{device_id}"
        config.DEVICE_ID = device_id
    adb_path = getattr(config, "ADB_PATH", ADB_PATH)

    # 1. เริ่ม ADB Server
    try:
        subprocess.run([adb_path, "start-server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except Exception:
        pass

    # 2. พยายามเรียก adb connect <device_id>
    try:
        subprocess.run([adb_path, "connect", device_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
    except Exception:
        pass

    # พิเศษ: หากผู้ใช้พิมพ์พอร์ต 5555 หรือ 5554 ให้ลอง connect ทั้ง 127.0.0.1:5555 และ 127.0.0.1:5554
    if "5555" in device_id or "5554" in device_id:
        try:
            subprocess.run([adb_path, "connect", "127.0.0.1:5555"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            subprocess.run([adb_path, "connect", "127.0.0.1:5554"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        except Exception:
            pass

    # 3. เช็ครายการอุปกรณ์ใน adb devices
    result = subprocess.run([adb_path, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    output = result.stdout.decode(errors="ignore")
    print("[ADB] อุปกรณ์ที่เจอ:")
    print(output)

    # 4. ตรวจหาความสอดคล้อง (Smart Device Identifier Matching)
    # Windows ADB มักแสดงพอร์ต 5555 ในชื่อ 'emulator-5554' หรือ '127.0.0.1:5555'
    matched_device = None
    if device_id in output:
        matched_device = device_id
    elif "5555" in device_id or "5554" in device_id:
        if "emulator-5554" in output:
            matched_device = "emulator-5554"
        elif "127.0.0.1:5555" in output:
            matched_device = "127.0.0.1:5555"

    if matched_device:
        config.DEVICE_ID = matched_device
        print(f"✅ เชื่อมต่อ ADB สำเร็จ: {matched_device}")
        return True

    # 5. Fallback Check: ทดสอบสแกนจับภาพหน้าจอจริง หากได้ภาพแสดงว่าพอร์ตเชื่อมต่อได้จริง
    scr = grab_screen()
    if scr is not None:
        print(f"✅ เชื่อมต่อ ADB สำเร็จ (ยืนยันผ่านการจับภาพหน้าจอ): {device_id}")
        return True

    # 6. หากมี Emulator ติดอยู่อย่างน้อย 1 ตัว ให้สลับไปใช้อุปกรณ์ตัวแรกที่ออนไลน์
    lines = [line.strip() for line in output.splitlines() if line.strip() and not line.startswith("List of")]
    active_devs = [l.split()[0] for l in lines if "device" in l and "offline" not in l]
    if active_devs:
        fallback_dev = active_devs[0]
        config.DEVICE_ID = fallback_dev
        if grab_screen() is not None:
            print(f"✅ สลับไปใช้อุปกรณ์ที่พบบน ADB อัตโนมัติ: {fallback_dev}")
            return True

    print(f"!! ไม่พบ device '{device_id}' ใน `adb devices` (ผลลัพธ์: {output.strip()})")
    print("!! ตรวจสอบว่าเปิด Emulator และเปิดตั้งค่า ADB Debugging ในจำลองหรือยัง:", adb_path)
    return False


_screen_size_cache = None


def get_screen_size():
    """ดึงขนาดหน้าจอจริงของ LDPlayer/MuMu ผ่าน adb shell wm size"""
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
    จับภาพหน้าจอของ Emulator ผ่าน adb exec-out screencap
    คืนค่าเป็น numpy array (BGR สำหรับ OpenCV) หรือ None ถ้าจับไม่สำเร็จ
    """
    result = adb_run(["exec-out", "screencap", "-p"], timeout=10)
    if result is None or not result.stdout:
        return None

    img_array = np.frombuffer(result.stdout, dtype=np.uint8)
    screen = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    return screen


def adb_tap(x, y):
    """สั่งแตะจอ Emulator ที่พิกัด (x, y) ผ่าน adb shell input tap"""
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


def adb_swipe_curve(x1, y1, x2, y2, curve_strength=40, steps=6, duration_ms=180):
    """
    ลากนิ้วจาก (x1, y1) ไปยัง (x2, y2) แบบเส้นโค้ง Bezier (Quadratic Bezier Curve)
    เพื่อเลียนแบบวิถีการลากนิ้วของมนุษย์จริงบนหน้าจอสัมผัส
    """
    import random
    import math

    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0

    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)

    if dist < 1.0:
        adb_tap(x1, y1)
        return

    side = random.choice([-1, 1])
    offset = random.uniform(curve_strength * 0.5, curve_strength)
    nx = -dy / dist * offset * side
    ny = dx / dist * offset * side

    cx = mx + nx
    cy = my + ny

    points = []
    for i in range(steps + 1):
        t = i / float(steps)
        one_minus_t = 1.0 - t
        px = (one_minus_t ** 2) * x1 + 2 * one_minus_t * t * cx + (t ** 2) * x2
        py = (one_minus_t ** 2) * y1 + 2 * one_minus_t * t * cy + (t ** 2) * y2
        points.append((int(px), int(py)))

    step_duration = max(10, int(duration_ms / max(1, steps)))
    swipe_cmds = []
    for i in range(len(points) - 1):
        p_start = points[i]
        p_end = points[i + 1]
        swipe_cmds.append(f"input swipe {p_start[0]} {p_start[1]} {p_end[0]} {p_end[1]} {step_duration}")

    full_cmd = " && ".join(swipe_cmds)
    adb_run(["shell", full_cmd], timeout=5)

