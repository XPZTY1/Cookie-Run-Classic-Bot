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
    device_id = getattr(config, "DEVICE_ID", DEVICE_ID)
    cmd = [ADB_PATH, "-s", device_id] + args
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


def adb_connect(target_device=None):
    """เชื่อมต่อ ADB กับ Emulator ตาม target_device หรือ config.DEVICE_ID"""
    global _screen_size_cache
    _screen_size_cache = None

    if target_device:
        config.DEVICE_ID = target_device

    device_id = getattr(config, "DEVICE_ID", DEVICE_ID)

    try:
        subprocess.run([ADB_PATH, "start-server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except Exception:
        pass

    # พยายามเรียก adb connect <device_id> ก่อน
    try:
        subprocess.run([ADB_PATH, "connect", device_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
    except Exception:
        pass

    result = subprocess.run([ADB_PATH, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    output = result.stdout.decode(errors="ignore")
    print("[ADB] อุปกรณ์ที่เจอ:")
    print(output)

    if device_id not in output:
        print(f"!! ไม่พบ device '{device_id}' ใน `adb devices`")
        print("!! ตรวจสอบว่าเปิด Emulator และพอร์ตถูกต้องแล้ว:", ADB_PATH)
        return False
    print(f"✅ เชื่อมต่อ ADB สำเร็จ: {device_id}")
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


def adb_swipe_curve(x1, y1, x2, y2, curve_strength=40, steps=6, duration_ms=180):
    """
    ลากนิ้วจาก (x1, y1) ไปยัง (x2, y2) แบบเส้นโค้ง Bezier (Quadratic Bezier Curve)
    เพื่อเลียนแบบวิถีการลากนิ้วของมนุษย์จริงบนหน้าจอสัมผัส
    """
    import random
    import math
    import time

    # คำนวณจุดกึ่งกลาง (Midpoint)
    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0

    # คำนวณ Vector ตั้งฉาก (Perpendicular Vector)
    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)

    if dist < 1.0:
        adb_tap(x1, y1)
        return

    # Normal vector ตั้งฉาก สุ่มทิศทาง (+1 หรือ -1)
    side = random.choice([-1, 1])
    offset = random.uniform(curve_strength * 0.5, curve_strength)
    nx = -dy / dist * offset * side
    ny = dx / dist * offset * side

    # Control Point (P1) สำหรับ Quadratic Bezier
    cx = mx + nx
    cy = my + ny

    # สร้างจุดบนเส้นโค้ง Bezier B(t) = (1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2
    points = []
    for i in range(steps + 1):
        t = i / float(steps)
        one_minus_t = 1.0 - t
        px = (one_minus_t ** 2) * x1 + 2 * one_minus_t * t * cx + (t ** 2) * x2
        py = (one_minus_t ** 2) * y1 + 2 * one_minus_t * t * cy + (t ** 2) * y2
        points.append((int(px), int(py)))

    # ลากนิ้วตามช่วงจุดย่อยๆ โดยรวมคำสั่งส่งให้ adb shell รันลวดเดียวเพื่อลด overhead ของ subprocess
    step_duration = max(10, int(duration_ms / max(1, steps)))
    swipe_cmds = []
    for i in range(len(points) - 1):
        p_start = points[i]
        p_end = points[i + 1]
        swipe_cmds.append(f"input swipe {p_start[0]} {p_start[1]} {p_end[0]} {p_end[1]} {step_duration}")

    # เชื่อมต่อคำสั่งด้วย && เพื่อรันต่อเนื่องใน adb shell
    full_cmd = " && ".join(swipe_cmds)
    adb_run(["shell", full_cmd], timeout=5)


def find_mumu_ports():
    """
    ค้นหาพอร์ต ADB ของ MuMu Player ที่กำลังเปิดอยู่อัตโนมัติ
    รองรับทั้ง MuMu Player 6, MuMu Player 9 และ MuMu Player 12 (Multi-instance)
    """
    import socket

    # พอร์ตมาตรฐานยอดนิยมของ MuMu Player (5559, 7555 และ 16384+N*32 สำหรับ MuMu 12)
    candidate_ports = [5559, 7555, 5555] + [16384 + i * 32 for i in range(16)]
    active_ports = []

    for port in candidate_ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            res = s.connect_ex(("127.0.0.1", port))
            s.close()
            if res == 0:
                dev = f"127.0.0.1:{port}"
                if dev not in active_ports:
                    active_ports.append(dev)
        except Exception:
            pass

    # พยายามเรียก adb connect สั้นๆ กับพอร์ตที่พบ เพื่อลงทะเบียนกับ ADB server
    connected_ports = []
    for dev in active_ports:
        try:
            subprocess.run([ADB_PATH, "connect", dev], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            connected_ports.append(dev)
        except Exception:
            pass

    return connected_ports if connected_ports else active_ports

