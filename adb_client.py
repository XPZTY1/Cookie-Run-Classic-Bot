import subprocess

import cv2
import numpy as np

from config import ADB_PATH, DEVICE_ID

# ---------------------------------------------------------------------------
# ฟังก์ชันพื้นฐานสำหรับคุย ADB กับ LDPlayer
# ---------------------------------------------------------------------------


import config


def adb_run(args, timeout=10, device_id=None):
    """
    รันคำสั่ง adb กับ device ที่กำหนดใน device_id หรือ config.DEVICE_ID
    args: list ของ argument ต่อจาก 'adb -s <device>' เช่น ["shell", "input", "tap", "500", "800"]
    คืนค่า CompletedProcess (มี .stdout เป็น bytes)
    """
    adb_path = getattr(config, "ADB_PATH", ADB_PATH)
    target_device = device_id or getattr(config, "DEVICE_ID", DEVICE_ID)
    cmd = [adb_path, "-s", target_device] + args
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
    _screen_size_cache.clear()

    if target_device:
        target_device = str(target_device).strip()
        if target_device:
            if ":" not in target_device and not target_device.startswith("emulator-"):
                target_device = f"127.0.0.1:{target_device}"
            config.DEVICE_ID = target_device

    device_id = (target_device or getattr(config, "DEVICE_ID", "")).strip()
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

    # 2. Disconnect แล้ว Connect ใหม่สด เพื่อล้าง offline state
    try:
        subprocess.run([adb_path, "disconnect", device_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except Exception:
        pass

    try:
        subprocess.run([adb_path, "connect", device_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
    except Exception:
        pass

    import time as _t
    _t.sleep(0.5)

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
    matched_device = None
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            dev = parts[0]
            if dev == device_id or device_id in dev:
                matched_device = dev
                break

    if not matched_device and ("5555" in device_id or "5554" in device_id):
        if "emulator-5554" in output:
            matched_device = "emulator-5554"
        elif "127.0.0.1:5555" in output:
            matched_device = "127.0.0.1:5555"

    if matched_device:
        config.DEVICE_ID = matched_device
        print(f"✅ เชื่อมต่อ ADB สำเร็จ: {matched_device}")
        return True

    # 5. Fallback: ทดสอบจับภาพหน้าจอจริง
    scr = grab_screen(device_id=device_id)
    if scr is not None:
        print(f"✅ เชื่อมต่อ ADB สำเร็จ (ยืนยันผ่านการจับภาพหน้าจอ): {device_id}")
        return True

    print(f"!! ไม่พบ device '{device_id}' ใน `adb devices` (ผลลัพธ์: {output.strip()})")
    print("!! ตรวจสอบว่าเปิด Emulator และเปิดตั้งค่า ADB Debugging ในจำลองหรือยัง:", adb_path)
    return False


_screen_size_cache = {}


def get_screen_size(device_id=None):
    """ดึงขนาดหน้าจอจริงของ LDPlayer/MuMu ผ่าน adb shell wm size (แยกตามพอร์ต)"""
    global _screen_size_cache
    target = device_id or getattr(config, "DEVICE_ID", "")
    if target in _screen_size_cache:
        return _screen_size_cache[target]

    result = adb_run(["shell", "wm", "size"], device_id=target)
    if result is None or result.returncode != 0:
        _screen_size_cache[target] = (1280, 720)
        return _screen_size_cache[target]

    output = result.stdout.decode(errors="ignore")
    try:
        import re
        matches = re.findall(r"(\d+)\s*x\s*(\d+)", output)
        if matches:
            w, h = map(int, matches[-1])
            # ปรับเป็นแนวนอนถ้าเกมเป็นแนวนอน
            if w < h:
                w, h = h, w
            _screen_size_cache[target] = (w, h)
        else:
            _screen_size_cache[target] = (1280, 720)
    except Exception:
        _screen_size_cache[target] = (1280, 720)

    return _screen_size_cache[target]


def grab_screen(device_id=None):
    """
    จับภาพหน้าจอของ Emulator ผ่าน adb exec-out screencap
    รองรับกรณีที่ MuMu Player ใส่ Warning text มาก่อน PNG header (เช่น multi-display)
    และรองรับการ auto-reconnect เมื่อ device offline
    คืนค่าเป็น numpy array (BGR สำหรับ OpenCV) หรือ None ถ้าจับไม่สำเร็จ
    """
    import subprocess as _sp
    import time as _t

    target = device_id or getattr(config, "DEVICE_ID", "")
    adb_path = getattr(config, "ADB_PATH", ADB_PATH)

    result = adb_run(["exec-out", "screencap", "-p"], timeout=10, device_id=target)

    # ถ้า device offline ให้ reconnect แล้วลองใหม่
    if result is None or not result.stdout or result.returncode != 0:
        try:
            _sp.run([adb_path, "connect", target], stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=8)
            _t.sleep(0.5)
        except Exception:
            pass
        result = adb_run(["exec-out", "screencap", "-p"], timeout=10, device_id=target)
        if result is None or not result.stdout:
            return None

    data = result.stdout

    # ค้นหา PNG Header (\x89PNG) และตัดข้อความ Warning ที่อาจติดมาก่อนหน้าออก
    idx = data.find(b"\x89PNG")
    if idx == -1:
        return None
    if idx > 0:
        data = data[idx:]

    img_array = np.frombuffer(data, dtype=np.uint8)
    screen = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    return screen


def adb_tap(x, y, device_id=None):
    """สั่งแตะจอ Emulator ที่พิกัด (x, y) ผ่าน adb shell input tap"""
    adb_run(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=5, device_id=device_id)


def adb_long_press(x, y, duration_ms=150, device_id=None):
    """
    สั่งกดค้างที่พิกัด (x, y) เป็นเวลา duration_ms มิลลิวินาที
    ใช้ adb shell input swipe จากจุดเดิมไปจุดเดิม พร้อม duration
    เพื่อจำลองการกดค้างแบบนิ้วมนุษย์
    """
    xi, yi = str(int(x)), str(int(y))
    adb_run(
        ["shell", "input", "swipe", xi, yi, xi, yi, str(int(duration_ms))],
        timeout=5,
        device_id=device_id,
    )


def adb_swipe_curve(x1, y1, x2, y2, curve_strength=40, steps=6, duration_ms=180, device_id=None):
    """
    ลากนิ้วจาก (x1, y1) ไปยัง (x2, y2) แบบเส้นโค้ง Bezier
    เพื่อเลียนแบบวิถีการลากนิ้วของมนุษย์จริงบนหน้าจอสัมผัสโดยไม่เกิดอาการกระตุก
    """
    import random
    import math

    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)

    if dist < 1.0:
        adb_tap(x1, y1, device_id=device_id)
        return

    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0

    side = random.choice([-1, 1])
    offset = random.uniform(curve_strength * 0.5, curve_strength)
    nx = -dy / dist * offset * side
    ny = dx / dist * offset * side

    cx = int(mx + nx)
    cy = int(my + ny)

    half_duration = max(20, int(duration_ms / 2))
    full_cmd = f"input swipe {int(x1)} {int(y1)} {cx} {cy} {half_duration} && input swipe {cx} {cy} {int(x2)} {int(y2)} {half_duration}"
    adb_run(["shell", full_cmd], timeout=5, device_id=device_id)



