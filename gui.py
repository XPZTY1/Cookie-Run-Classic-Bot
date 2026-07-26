import os
import sys
import time
import json
import ctypes
import threading
import tkinter as tk
from tkinter import scrolledtext

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

import config
import bot_engine
from adb_client import adb_connect, grab_screen
from secrets_loader import save_secret, ADB_DEVICE_ID, get_discord_webhooks, save_discord_webhooks
from notifiers.line_notifier import send_line_message
from notifiers.discord_notifier import send_discord_embed, COLOR_INFO, send_discord_report, send_discord_test_to_url
from notifiers.gemini_vision import describe_screen_with_gemini, read_game_score_with_gemini

# path ของไอคอนแอป (วางไฟล์ icon.ico ไว้โฟลเดอร์ assets ข้างๆ ไฟล์นี้)
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
PROFILES_FILE_PATH = os.path.join(config.BASE_DIR, "user_profiles.json")


def load_custom_profiles():
    if os.path.exists(PROFILES_FILE_PATH):
        try:
            with open(PROFILES_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_custom_profiles_to_disk(profiles_dict):
    try:
        with open(PROFILES_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles_dict, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"บันทึกโปรไฟล์คัสทอมไม่สำเร็จ: {e}")
        return False


def force_taskbar_icon(root, icon_path):
    """
    แก้บั๊กที่ root.iconbitmap() เซ็ตไอคอน title bar ได้
    แต่ taskbar ยังโชว์ไอคอน python.exe เดิมอยู่ (เฉพาะ Windows)
    """
    if not sys.platform.startswith("win"):
        return
    try:
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p

        user32.LoadImageW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint
        ]
        user32.LoadImageW.restype = ctypes.c_void_p

        user32.SendMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p
        ]
        user32.SendMessageW.restype = ctypes.c_void_p

        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040

        root.update()
        hwnd = user32.GetParent(root.winfo_id())

        h_icon_big = user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
        )
        h_icon_small = user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
        )

        if h_icon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_icon_big)
        if h_icon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_icon_small)
    except Exception as e:
        print(f"⚠️ ตั้งไอคอน taskbar ไม่สำเร็จ: {e}")


def run_gui():
    # ตรวจสอบการเชื่อมต่อ ADB เบื้องต้น
    adb_connect()

    if sys.platform.startswith("win"):
        try:
            myappid = "cookierunbot.gui.2.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # ttkbootstrap Window + Theme
    # ---------------------------------------------------------------------------
    root = ttk.Window(themename="darkly")
    root.title("Cookie Run Classic Auto Bot — Modern Dashboard v2.0")
    root.geometry("860x780")
    root.minsize(800, 700)
    root.resizable(True, True)

    try:
        root.iconbitmap(ICON_PATH)
    except Exception:
        pass

    force_taskbar_icon(root, ICON_PATH)

    LOG_BG = "#0f172a"
    LOG_FG = "#38bdf8"

    # เก็บประวัติ Log ทั้งหมดสำหรับระบบ Filter
    raw_logs = []

    # ---------------------------------------------------------------------------
    # 1. Layout ด้านบน: Header Bar & ADB Config Toolbar
    # ---------------------------------------------------------------------------
    header_frame = ttk.Frame(root, padding=(15, 12, 15, 8))
    header_frame.pack(fill=tk.X)

    title_box = ttk.Frame(header_frame)
    title_box.pack(side=tk.LEFT)

    ttk.Label(
        title_box,
        text="🍪 COOKIE RUN BOT",
        font=("Segoe UI", 16, "bold"),
        bootstyle="warning"
    ).pack(side=tk.LEFT)

    ttk.Label(
        title_box,
        text=" PRO",
        font=("Segoe UI", 10, "bold"),
        bootstyle="danger"
    ).pack(side=tk.LEFT, padx=(2, 0), pady=(4, 0))

    # ADB Connection Bar (ขวา)
    adb_frame = ttk.Frame(header_frame)
    adb_frame.pack(side=tk.RIGHT)

    ttk.Label(adb_frame, text="📱 Device/Port:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))

    preset_map = {
        "MuMu (5559)": "127.0.0.1:5559",
        "MuMu (7555)": "127.0.0.1:7555",
        "LDPlayer (5555)": "127.0.0.1:5555",
        "Nox (62001)": "127.0.0.1:62001",
        "BlueStacks": "127.0.0.1:5555"
    }

    adb_entry_var = tk.StringVar(value=getattr(config, "DEVICE_ID", ADB_DEVICE_ID))

    adb_entry = ttk.Entry(adb_frame, textvariable=adb_entry_var, width=16, font=("Consolas", 9))
    adb_entry.pack(side=tk.LEFT, padx=3)

    def on_preset_select(event=None):
        sel = preset_combo.get()
        if sel in preset_map:
            adb_entry_var.set(preset_map[sel])

    preset_combo = ttk.Combobox(
        adb_frame,
        values=list(preset_map.keys()),
        width=14,
        state="readonly",
        font=("Segoe UI", 8)
    )
    preset_combo.set("เลือกพอร์ต")
    preset_combo.pack(side=tk.LEFT, padx=3)
    preset_combo.bind("<<ComboboxSelected>>", on_preset_select)

    def connect_adb_action():
        target = adb_entry_var.get().strip()
        if not target:
            bot_engine.log_info("❌ กรุณากรอก Device IP:Port ก่อนกดเชื่อมต่อ")
            return

        bot_engine.log_info(f"🔌 กำลังพยายามเชื่อมต่อ ADB ไปที่ {target}...")
        success = adb_connect(target)
        if success:
            save_secret("adb_device_id", target)
            bot_engine.log_info(f"✅ บันทึกพอร์ต {target} ลง secrets.json เรียบร้อยแล้ว")
        else:
            bot_engine.log_info(f"❌ เชื่อมต่อ {target} ไม่สำเร็จ ตรวจสอบการเปิด Emulator")

    conn_btn = ttk.Button(
        adb_frame,
        text="🔌 Connect",
        bootstyle="info-outline",
        width=10,
        command=connect_adb_action
    )
    conn_btn.pack(side=tk.LEFT, padx=(3, 0))

    # ---------------------------------------------------------------------------
    # 2. Control Panel & Dashboard Metrics
    # ---------------------------------------------------------------------------
    dash_frame = ttk.Frame(root, padding=(15, 0, 15, 10))
    dash_frame.pack(fill=tk.X)

    # ปุ่มควบคุมหลัก (ซ้าย)
    btn_card = ttk.Labelframe(dash_frame, text="🎮  CONTROL", bootstyle="info", padding=12)
    btn_card.pack(side=tk.LEFT, fill=tk.Y)

    start_btn = ttk.Button(
        btn_card,
        text="▶  START BOT (F6)",
        bootstyle="success",
        width=18,
        command=bot_engine.start_bot
    )
    start_btn.pack(pady=4, ipady=5)

    stop_btn = ttk.Button(
        btn_card,
        text="■  STOP BOT (F7)",
        bootstyle="danger-outline",
        width=18,
        command=bot_engine.stop_bot
    )
    stop_btn.pack(pady=4, ipady=5)

    # การ์ดสถิติ แดชบอร์ดเรียลไทม์ (ขวา)
    stats_card = ttk.Labelframe(dash_frame, text="📊  LIVE PERFORMANCE DASHBOARD", bootstyle="dark", padding=12)
    stats_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

    for col in range(4):
        stats_card.columnconfigure(col, weight=1)

    # Row 0
    state_lbl = ttk.Label(stats_card, text="State: READY", font=("Segoe UI", 9, "bold"), bootstyle="warning")
    state_lbl.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=2)

    rest_lbl = ttk.Label(stats_card, text="Next Rest In: -", font=("Segoe UI", 9), bootstyle="secondary")
    rest_lbl.grid(row=0, column=2, columnspan=2, sticky=tk.W, pady=2)

    # Row 1
    runs_lbl = ttk.Label(stats_card, text="Total Runs: 0", font=("Segoe UI", 9))
    runs_lbl.grid(row=1, column=0, sticky=tk.W, pady=2)

    success_lbl = ttk.Label(stats_card, text="Success: 0", font=("Segoe UI", 9))
    success_lbl.grid(row=1, column=1, sticky=tk.W, pady=2)

    rate_lbl = ttk.Label(stats_card, text="Success Rate: 0.0%", font=("Segoe UI", 9, "bold"), bootstyle="success")
    rate_lbl.grid(row=1, column=2, columnspan=2, sticky=tk.W, pady=2)

    # Row 2
    score_lbl = ttk.Label(stats_card, text="Last Score: -", font=("Segoe UI", 9))
    score_lbl.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=2)

    coins_lbl = ttk.Label(stats_card, text="Last Coins: -", font=("Segoe UI", 9))
    coins_lbl.grid(row=2, column=2, columnspan=2, sticky=tk.W, pady=2)

    # Row 3 (Performance Rates)
    coins_hr_lbl = ttk.Label(stats_card, text="🪙 Coins/Hr: 0", font=("Segoe UI", 9, "bold"), bootstyle="warning")
    coins_hr_lbl.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=2)

    runs_hr_lbl = ttk.Label(stats_card, text="🔄 Runs/Hr: 0", font=("Segoe UI", 9, "bold"), bootstyle="info")
    runs_hr_lbl.grid(row=3, column=2, columnspan=2, sticky=tk.W, pady=2)

    # Row 4 (Mystery Boxes & Drop Rates)
    boxes_lbl = ttk.Label(stats_card, text="🎁 Boxes: 0 (0.0/Hr)", font=("Segoe UI", 9, "bold"), bootstyle="purple")
    boxes_lbl.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=2)

    # Row 5 (Resets & Disconnects)
    watchdog_lbl = ttk.Label(stats_card, text="Watchdog Resets: 0", font=("Segoe UI", 8), bootstyle="secondary")
    watchdog_lbl.grid(row=5, column=0, sticky=tk.W, pady=2)

    adb_lbl = ttk.Label(stats_card, text="ADB Disconnects: 0", font=("Segoe UI", 8), bootstyle="secondary")
    adb_lbl.grid(row=5, column=2, columnspan=2, sticky=tk.W, pady=2)

    # ---------------------------------------------------------------------------
    # 3. Settings Toggle Panel & Speed Control
    # ---------------------------------------------------------------------------
    settings_frame = ttk.Frame(root, padding=(15, 0, 15, 8))
    settings_frame.pack(fill=tk.X)

    settings_card = ttk.Labelframe(settings_frame, text="⚙️  CONFIG & FEATURE TOGGLES", bootstyle="dark", padding=12)
    settings_card.pack(fill=tk.X)

    for col in range(4):
        settings_card.columnconfigure(col, weight=1)

    # Toggles
    booster_var = tk.BooleanVar(value=getattr(config, "ENABLE_BOOSTER_BUY", True))
    def on_booster_toggle():
        config.ENABLE_BOOSTER_BUY = booster_var.get()
        bot_engine.log_info(f"⚙️ ซื้อไอเทมเพิ่มพลัง = {'เปิด' if config.ENABLE_BOOSTER_BUY else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="🛒 ซื้อไอเทมบูสเตอร์", variable=booster_var, command=on_booster_toggle, bootstyle="success-round-toggle").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)

    fast_start_var = tk.BooleanVar(value=getattr(config, "ENABLE_FAST_START_BOOST", True))
    def on_fast_start_toggle():
        config.ENABLE_FAST_START_BOOST = fast_start_var.get()
        bot_engine.log_info(f"⚙️ Fast Start Boost = {'เปิด' if config.ENABLE_FAST_START_BOOST else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="⚡ Fast Start Boost", variable=fast_start_var, command=on_fast_start_toggle, bootstyle="success-round-toggle").grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

    use_second_var = tk.BooleanVar(value=getattr(config, "ENABLE_USE_SECOND_COOKIE", True))
    def on_use_second_toggle():
        config.ENABLE_USE_SECOND_COOKIE = use_second_var.get()
        bot_engine.log_info(f"⚙️ ใช้คุกกี้ตัวที่ 2 = {'เปิด' if config.ENABLE_USE_SECOND_COOKIE else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="🔁 ใช้คุกกี้ตัวที่ 2", variable=use_second_var, command=on_use_second_toggle, bootstyle="success-round-toggle").grid(row=0, column=2, sticky=tk.W, padx=4, pady=4)

    line_var = tk.BooleanVar(value=getattr(config, "ENABLE_LINE_NOTIFY", True))
    def on_line_toggle():
        config.ENABLE_LINE_NOTIFY = line_var.get()
        bot_engine.log_info(f"⚙️ LINE Notify = {'เปิด' if config.ENABLE_LINE_NOTIFY else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="🔔 แจ้งเตือน LINE", variable=line_var, command=on_line_toggle, bootstyle="success-round-toggle").grid(row=0, column=3, sticky=tk.W, padx=4, pady=4)

    swipe_curve_var = tk.BooleanVar(value=getattr(config, "SWIPE_CURVE_ENABLED", True))
    def on_swipe_curve_toggle():
        config.SWIPE_CURVE_ENABLED = swipe_curve_var.get()
        bot_engine.log_info(f"⚙️ ลากนิ้วโค้ง Bezier = {'เปิด' if config.SWIPE_CURVE_ENABLED else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="〰️ ลากนิ้วโค้ง Bezier", variable=swipe_curve_var, command=on_swipe_curve_toggle, bootstyle="success-round-toggle").grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)

    schedule_var = tk.BooleanVar(value=getattr(config, "SCHEDULE_ENABLED", False))
    def on_schedule_toggle():
        config.SCHEDULE_ENABLED = schedule_var.get()
        bot_engine.log_info(f"⚙️ ตารางเวลาทำงาน = {'เปิด' if config.SCHEDULE_ENABLED else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="⏰ ตารางเวลาทำงาน", variable=schedule_var, command=on_schedule_toggle, bootstyle="success-round-toggle").grid(row=1, column=1, sticky=tk.W, padx=4, pady=4)

    discord_var = tk.BooleanVar(value=getattr(config, "DISCORD_REPORT_ENABLED", True))
    def on_discord_toggle():
        config.DISCORD_REPORT_ENABLED = discord_var.get()
        bot_engine.log_info(f"⚙️ รายงาน Discord Webhook = {'เปิด' if config.DISCORD_REPORT_ENABLED else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="💬 รายงาน Discord", variable=discord_var, command=on_discord_toggle, bootstyle="success-round-toggle").grid(row=1, column=2, sticky=tk.W, padx=4, pady=4)

    ocr_score_var = tk.BooleanVar(value=getattr(config, "OCR_SCORE_ENABLED", True))
    def on_ocr_score_toggle():
        config.OCR_SCORE_ENABLED = ocr_score_var.get()
        bot_engine.log_info(f"⚙️ อ่านคะแนน Gemini OCR = {'เปิด' if config.OCR_SCORE_ENABLED else 'ปิด'}")
    ttk.Checkbutton(settings_card, text="🔍 อ่านคะแนน OCR", variable=ocr_score_var, command=on_ocr_score_toggle, bootstyle="success-round-toggle").grid(row=1, column=3, sticky=tk.W, padx=4, pady=4)

    # Speed & Preset Profile Selector
    ttk.Label(settings_card, text="🚀 ความรัวการกด:", font=("Segoe UI", 9)).grid(row=2, column=0, sticky=tk.W, padx=4, pady=(6, 0))
    speed_map = {"100ms (ปกติ)": 100, "50ms (รัวเร็ว)": 50, "30ms (รัวมาก)": 30}
    speed_var = tk.StringVar(value="50ms (รัวเร็ว)")

    def on_speed_change(event=None):
        selected = speed_var.get()
        speed_ms = speed_map.get(selected, 50)
        config.BOOST_TAP_SPEED_MS = speed_ms
        bot_engine.log_info(f"⚙️ ความรัวการกด = {selected} ({speed_ms}ms)")

    speed_menu = ttk.Combobox(settings_card, textvariable=speed_var, values=list(speed_map.keys()), state="readonly", bootstyle="success", width=16)
    speed_menu.grid(row=2, column=1, sticky=tk.W, padx=4, pady=(6, 0))
    speed_menu.bind("<<ComboboxSelected>>", on_speed_change)

    # Preset Profiles System (100% Custom User Profiles)
    ttk.Label(settings_card, text="📋 โปรไฟล์ Preset:", font=("Segoe UI", 9, "bold"), bootstyle="info").grid(row=2, column=2, sticky=tk.W, padx=4, pady=(6, 0))

    custom_profiles = load_custom_profiles()

    default_placeholder = "เลือกโปรไฟล์ Preset" if custom_profiles else "ไม่มีโปรไฟล์ (กดบันทึกเพื่อสร้าง)"
    profile_var = tk.StringVar(value=default_placeholder)

    def on_profile_change(event=None):
        name = profile_var.get()
        p = custom_profiles.get(name)
        if not p:
            return

        booster_var.set(p.get("booster", True))
        on_booster_toggle()

        fast_start_var.set(p.get("fast_start", True))
        on_fast_start_toggle()

        use_second_var.set(p.get("use_second", True))
        on_use_second_toggle()

        line_var.set(p.get("line", True))
        on_line_toggle()

        swipe_curve_var.set(p.get("swipe_curve", True))
        on_swipe_curve_toggle()

        schedule_var.set(p.get("schedule", False))
        on_schedule_toggle()

        discord_var.set(p.get("discord", True))
        on_discord_toggle()

        ocr_score_var.set(p.get("ocr_score", True))
        on_ocr_score_toggle()

        speed_var.set(p.get("speed", "50ms (รัวเร็ว)"))
        on_speed_change()

        bot_engine.log_info(f"📋 โหลดและใช้โปรไฟล์เซ็ตติ้ง: {name} เรียบร้อย!")

    profile_menu = ttk.Combobox(settings_card, textvariable=profile_var, values=list(custom_profiles.keys()), state="readonly", bootstyle="info", width=22)
    profile_menu.grid(row=2, column=3, sticky=tk.W, padx=4, pady=(6, 0))
    profile_menu.bind("<<ComboboxSelected>>", on_profile_change)

    # ปุ่มจัดการ Custom Preset (Save / Delete)
    profile_btn_frame = ttk.Frame(settings_card)
    profile_btn_frame.grid(row=3, column=2, columnspan=2, sticky=tk.E, padx=4, pady=(6, 0))

    def save_custom_profile_action():
        from tkinter import simpledialog
        name = simpledialog.askstring("บันทึกโปรไฟล์ใหม่", "ตั้งชื่อโปรไฟล์การตั้งค่าของคุณ (เช่น 'สูตรคุกกี้ส้ม'):", parent=root)
        if not name or not name.strip():
            return

        name = name.strip()
        if not name.startswith("⭐"):
            name = f"⭐ {name}"

        profile_data = {
            "booster": booster_var.get(),
            "fast_start": fast_start_var.get(),
            "use_second": use_second_var.get(),
            "line": line_var.get(),
            "swipe_curve": swipe_curve_var.get(),
            "schedule": schedule_var.get(),
            "discord": discord_var.get(),
            "ocr_score": ocr_score_var.get(),
            "speed": speed_var.get()
        }

        custom_profiles[name] = profile_data
        save_custom_profiles_to_disk(custom_profiles)

        profile_menu.configure(values=list(custom_profiles.keys()))
        profile_var.set(name)
        bot_engine.log_info(f"💾 บันทึกโปรไฟล์คัสทอม '{name}' สำเร็จแล้ว!")

    def delete_custom_profile_action():
        current_name = profile_var.get()

        if current_name in custom_profiles:
            del custom_profiles[current_name]
            save_custom_profiles_to_disk(custom_profiles)

            profile_menu.configure(values=list(custom_profiles.keys()))
            profile_var.set("เลือกโปรไฟล์ Preset" if custom_profiles else "ไม่มีโปรไฟล์ (กดบันทึกเพื่อสร้าง)")
            bot_engine.log_info(f"🗑️ ลบโปรไฟล์คัสทอม '{current_name}' เรียบร้อยแล้ว!")
        else:
            bot_engine.log_info("⚠️ กรุณาเลือกโปรไฟล์คัสทอมที่ต้องการลบก่อน")

    ttk.Button(profile_btn_frame, text="💾 บันทึก Preset คัสทอม", bootstyle="success-outline", width=16, command=save_custom_profile_action).pack(side=tk.LEFT, padx=3)
    ttk.Button(profile_btn_frame, text="🗑️ ลบ Preset", bootstyle="danger-outline", width=10, command=delete_custom_profile_action).pack(side=tk.LEFT, padx=3)

    # ---------------------------------------------------------------------------
    # 4. Quick Test Tools Panel
    # ---------------------------------------------------------------------------
    tools_frame = ttk.Frame(root, padding=(15, 0, 15, 6))
    tools_frame.pack(fill=tk.X)

    tools_card = ttk.Labelframe(tools_frame, text="🛠️  QUICK TEST TOOLS", bootstyle="dark", padding=8)
    tools_card.pack(fill=tk.X)

    def test_line_action():
        bot_engine.log_info("🔔 กำลังทดสอบส่งข้อความเข้า LINE...")
        threading.Thread(target=lambda: send_line_message("🔔 ทดสอบการแจ้งเตือนจาก Cookie Run Classic Bot"), daemon=True).start()

    def test_discord_action():
        bot_engine.log_info("💬 กำลังทดสอบส่ง Discord Embed...")
        threading.Thread(target=lambda: send_discord_embed(
            title="🔔 ทดสอบระบบ Discord Webhook",
            fields=[{"name": "สถานะ", "value": "`ใช้งานได้ปกติ ✅`", "inline": True}],
            color=COLOR_INFO,
            description="ทดสอบการแจ้งเตือนรูปแบบ Embed จากหน้า GUI"
        ), daemon=True).start()

    def test_gemini_action():
        bot_engine.log_info("📸 กำลังทดสอบ Gemini OCR อ่านหน้าจอสด...")
        def run_test():
            scr = grab_screen()
            if scr is None:
                bot_engine.log_info("❌ จับภาพไม่สำเร็จ ตรวจสอบ ADB ก่อน")
                return
            res = read_game_score_with_gemini(scr)
            if res:
                bot_engine.log_info(f"✅ Gemini OCR สำเร็จ! Score: {res['score']:,} | Coins: {res['coins']:,}")
            else:
                bot_engine.log_info("⚠️ Gemini OCR อ่านไม่สำเร็จ หรือไม่พบหน้าสรุปคะแนน")
        threading.Thread(target=run_test, daemon=True).start()

    def open_webhook_manager_dialog(parent):
        dialog = tk.Toplevel(parent)
        dialog.title("🔔 จัดการโปรไฟล์ Discord Webhooks")
        dialog.geometry("750x550")
        dialog.minsize(650, 450)
        dialog.resizable(True, True)
        dialog.transient(parent)
        dialog.grab_set()

        header = ttk.Frame(dialog, padding=(15, 10))
        header.pack(fill=tk.X)
        ttk.Label(header, text="🔔 Discord Webhooks Manager (Multi-Profile)", font=("Segoe UI", 11, "bold"), bootstyle="info").pack(anchor=tk.W)
        ttk.Label(header, text="สร้างโปรไฟล์ Webhook ได้หลายตัว ตั้งชื่อ เลือกเปิด/ปิด หรือทดสอบส่งแยกโปรไฟล์ได้ (สามารถขยายหน้าต่างได้)", font=("Segoe UI", 8), bootstyle="secondary").pack(anchor=tk.W)

        list_frame = ttk.Frame(dialog, padding=(15, 5))
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("status", "name", "url")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8, selectmode="browse")
        tree.heading("status", text="สถานะ")
        tree.heading("name", text="ชื่อโปรไฟล์")
        tree.heading("url", text="Webhook URL")

        tree.column("status", width=80, anchor="center")
        tree.column("name", width=200, anchor="w")
        tree.column("url", width=420, anchor="w")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        webhooks_data = get_discord_webhooks()

        def refresh_tree():
            for item in tree.get_children():
                tree.delete(item)
            for i, w in enumerate(webhooks_data):
                st = "✅ เปิด" if w.get("enabled", True) else "❌ ปิด"
                tree.insert("", tk.END, iid=str(i), values=(st, w.get("name", "Unnamed"), w.get("url", "")))

        refresh_tree()

        form_frame = ttk.Labelframe(dialog, text="➕ เพิ่ม / แก้ไขโปรไฟล์ Webhook", padding=10)
        form_frame.pack(fill=tk.X, padx=15, pady=5)

        form_grid = ttk.Frame(form_frame)
        form_grid.pack(fill=tk.X, expand=True)
        form_grid.columnconfigure(1, weight=1)

        ttk.Label(form_grid, text="ชื่อโปรไฟล์:", font=("Segoe UI", 9)).grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(form_grid, textvariable=name_var, width=28)
        name_entry.grid(row=0, column=1, sticky=tk.W, padx=4, pady=2)

        ttk.Label(form_grid, text="Webhook URL:", font=("Segoe UI", 9)).grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
        url_var = tk.StringVar()
        url_entry = ttk.Entry(form_grid, textvariable=url_var)
        url_entry.grid(row=1, column=1, sticky=tk.EW, padx=4, pady=2)

        status_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form_grid, text="เปิดใช้งานโปรไฟล์นี้", variable=status_var, bootstyle="success-round-toggle").grid(row=0, column=1, sticky=tk.E, padx=4, pady=2)

        editing_index = [-1]

        def clear_inputs():
            name_var.set("")
            url_var.set("")
            status_var.set(True)
            editing_index[0] = -1
            save_btn.config(text="➕ เพิ่มโปรไฟล์", bootstyle="success")

        def on_select(event):
            sel = tree.selection()
            if sel:
                idx = int(sel[0])
                item = webhooks_data[idx]
                name_var.set(item.get("name", ""))
                url_var.set(item.get("url", ""))
                status_var.set(item.get("enabled", True))
                editing_index[0] = idx
                save_btn.config(text="💾 บันทึกแก้ไข", bootstyle="info")

        tree.bind("<<TreeviewSelect>>", on_select)

        def save_action():
            name = name_var.get().strip()
            url = url_var.get().strip()
            if not name or not url:
                bot_engine.log_info("⚠️ กรุณากรอกทั้งชื่อโปรไฟล์และ Webhook URL")
                return

            new_item = {"name": name, "url": url, "enabled": status_var.get()}
            if 0 <= editing_index[0] < len(webhooks_data):
                webhooks_data[editing_index[0]] = new_item
                bot_engine.log_info(f"✏️ อัปเดตโปรไฟล์ Webhook '{name}' สำเร็จ")
            else:
                webhooks_data.append(new_item)
                bot_engine.log_info(f"➕ เพิ่มโปรไฟล์ Webhook '{name}' สำเร็จ")

            save_discord_webhooks(webhooks_data)
            refresh_tree()
            clear_inputs()

        def toggle_action():
            sel = tree.selection()
            if not sel:
                bot_engine.log_info("⚠️ กรุณาเลือกโปรไฟล์ Webhook ในตารางก่อน")
                return
            idx = int(sel[0])
            webhooks_data[idx]["enabled"] = not webhooks_data[idx].get("enabled", True)
            save_discord_webhooks(webhooks_data)
            refresh_tree()
            bot_engine.log_info(f"🔘 สลับสถานะโปรไฟล์ '{webhooks_data[idx]['name']}' = {'เปิด' if webhooks_data[idx]['enabled'] else 'ปิด'}")

        def delete_action():
            sel = tree.selection()
            if not sel:
                bot_engine.log_info("⚠️ กรุณาเลือกโปรไฟล์ Webhook ที่ต้องการลบก่อน")
                return
            idx = int(sel[0])
            deleted_name = webhooks_data[idx].get("name", "")
            del webhooks_data[idx]
            save_discord_webhooks(webhooks_data)
            refresh_tree()
            clear_inputs()
            bot_engine.log_info(f"🗑️ ลบโปรไฟล์ Webhook '{deleted_name}' เรียบร้อยแล้ว")

        def test_action():
            url = url_var.get().strip()
            name = name_var.get().strip() or "Test Profile"
            if not url:
                sel = tree.selection()
                if sel:
                    idx = int(sel[0])
                    url = webhooks_data[idx].get("url", "")
                    name = webhooks_data[idx].get("name", "")
            if not url:
                bot_engine.log_info("⚠️ กรุณาเลือกโปรไฟล์หรือกรอก Webhook URL เพื่อทดสอบ")
                return

            bot_engine.log_info(f"🧪 กำลังทดสอบส่งข้อความไปยังโปรไฟล์ '{name}'...")
            def run_test():
                ok = send_discord_test_to_url(url, name)
                if ok:
                    bot_engine.log_info(f"✅ ทดสอบส่ง Webhook '{name}' สำเร็จ!")
                else:
                    bot_engine.log_info(f"❌ ทดสอบส่ง Webhook '{name}' ไม่สำเร็จ ตรวจสอบ URL อีกครั้ง")
            threading.Thread(target=run_test, daemon=True).start()

        btn_box = ttk.Frame(dialog, padding=(15, 5, 15, 10))
        btn_box.pack(fill=tk.X)

        save_btn = ttk.Button(btn_box, text="➕ เพิ่มโปรไฟล์", bootstyle="success", width=14, command=save_action)
        save_btn.pack(side=tk.LEFT, padx=3)

        ttk.Button(btn_box, text="🔘 สลับเปิด/ปิด", bootstyle="warning-outline", width=13, command=toggle_action).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="🧪 ทดสอบส่ง", bootstyle="info-outline", width=12, command=test_action).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="🗑️ ลบโปรไฟล์", bootstyle="danger-outline", width=12, command=delete_action).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_box, text="🧹 เคลียร์", bootstyle="secondary-link", command=clear_inputs).pack(side=tk.RIGHT, padx=3)

    # Webhook selector (per-window profile) - ช่วยให้แต่ละหน้าต่าง GUI เลือกโปรไฟล์ Webhook แยกกันได้
    def get_webhook_options_list():
        items = get_discord_webhooks()
        names = [w.get("name", "Unnamed") for w in items]
        opts = ["[ALL] ส่งทุก Webhook ที่เปิดใช้งาน"] + names
        return opts

    webhook_sel_var = tk.StringVar(value=getattr(config, "SELECTED_DISCORD_WEBHOOK", "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน"))
    webhook_combo = ttk.Combobox(tools_card, textvariable=webhook_sel_var, values=get_webhook_options_list(), state="readonly", width=36)
    webhook_combo.pack(side=tk.LEFT, padx=6)

    def refresh_webhook_options():
        try:
            vals = get_webhook_options_list()
            webhook_combo.configure(values=vals)
            cur = webhook_sel_var.get()
            if cur not in vals:
                webhook_sel_var.set(vals[0])
                config.SELECTED_DISCORD_WEBHOOK = vals[0]
        except Exception:
            pass

    def on_webhook_select(event=None):
        sel = webhook_sel_var.get()
        config.SELECTED_DISCORD_WEBHOOK = sel
        bot_engine.log_info(f"🔔 โปรไฟล์ Webhook ที่เลือก: {sel}")

    webhook_combo.bind("<<ComboboxSelected>>", on_webhook_select)

    def open_manager_and_refresh():
        open_webhook_manager_dialog(root)
        # หลังปิด dialog ให้รีเฟรชตัวเลือกใน combobox เผื่อผู้ใช้เพิ่ม/ลบโปรไฟล์
        refresh_webhook_options()

    ttk.Button(tools_card, text="🔔 Test LINE", bootstyle="secondary-outline", width=12, command=test_line_action).pack(side=tk.LEFT, padx=4)
    ttk.Button(tools_card, text="💬 Test Discord", bootstyle="info-outline", width=12, command=test_discord_action).pack(side=tk.LEFT, padx=4)
    ttk.Button(tools_card, text="📸 Test Gemini OCR", bootstyle="warning-outline", width=15, command=test_gemini_action).pack(side=tk.LEFT, padx=4)
    ttk.Button(tools_card, text="⚙️ จัดการ Webhooks", bootstyle="primary", width=16, command=open_manager_and_refresh).pack(side=tk.LEFT, padx=4)

    # ---------------------------------------------------------------------------
    # 5. Real-time Console Log & Filter
    # ---------------------------------------------------------------------------
    log_frame = ttk.Frame(root, padding=(15, 4, 15, 10))
    log_frame.pack(fill=tk.BOTH, expand=True)

    log_top_bar = ttk.Frame(log_frame)
    log_top_bar.pack(fill=tk.X, pady=(0, 4))

    ttk.Label(log_top_bar, text="💬 REAL-TIME CONSOLE LOG", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

    # Log Filter Combobox
    filter_var = tk.StringVar(value="[ALL] ทั้งหมด")
    filter_combo = ttk.Combobox(
        log_top_bar,
        textvariable=filter_var,
        values=["[ALL] ทั้งหมด", "[INFO] ทั่วไป", "[DEBUG] ดีบัก"],
        state="readonly",
        width=14,
        font=("Segoe UI", 8)
    )
    filter_combo.pack(side=tk.RIGHT, padx=5)

    def refresh_log_display(event=None):
        mode = filter_var.get()
        log_area.configure(state='normal')
        log_area.delete("1.0", tk.END)
        for msg in raw_logs:
            if mode == "[INFO] ทั่วไป" and "[DEBUG]" in msg:
                continue
            if mode == "[DEBUG] ดีบัก" and "[DEBUG]" not in msg:
                continue
            log_area.insert(tk.END, msg + "\n")
        log_area.see(tk.END)
        log_area.configure(state='disabled')

    filter_combo.bind("<<ComboboxSelected>>", refresh_log_display)

    def clear_log_action():
        raw_logs.clear()
        log_area.configure(state='normal')
        log_area.delete("1.0", tk.END)
        log_area.configure(state='disabled')

    ttk.Button(log_top_bar, text="🧹 Clear Log", bootstyle="danger-link", command=clear_log_action).pack(side=tk.RIGHT)

    log_area = scrolledtext.ScrolledText(
        log_frame,
        wrap=tk.WORD,
        bg=LOG_BG,
        fg=LOG_FG,
        insertbackground="white",
        borderwidth=0,
        font=("Consolas", 9),
        state='disabled'
    )
    log_area.pack(fill=tk.BOTH, expand=True)

    def write_to_log_area(formatted_msg):
        raw_logs.append(formatted_msg)
        if len(raw_logs) > 500:
            raw_logs.pop(0)

        def update_ui():
            mode = filter_var.get()
            if mode == "[INFO] ทั่วไป" and "[DEBUG]" in formatted_msg:
                return
            if mode == "[DEBUG] ดีบัก" and "[DEBUG]" not in formatted_msg:
                return

            log_area.configure(state='normal')
            log_area.insert(tk.END, formatted_msg + "\n")
            log_area.see(tk.END)
            log_area.configure(state='disabled')

        try:
            root.after(0, update_ui)
        except Exception:
            pass

    bot_engine.set_gui_log_callback(write_to_log_area)

    bot_thread = threading.Thread(target=bot_engine.bot_loop, daemon=True)
    bot_thread.start()

    # ลูปอัปเดตสถิติเรียลไทม์
    def update_stats_loop():
        try:
            state_lbl.config(text=f"State: {bot_engine.current_state}")
            runs_lbl.config(text=f"Total Runs: {bot_engine.session_stats['total_runs']}")
            success_lbl.config(text=f"Success: {bot_engine.session_stats['successful_runs']}")
            watchdog_lbl.config(text=f"Watchdog Resets: {bot_engine.session_stats['watchdog_resets']}")
            adb_lbl.config(text=f"ADB Disconnects: {bot_engine.session_stats['adb_disconnects']}")

            last_s = bot_engine.session_stats.get("last_score", 0)
            last_c = bot_engine.session_stats.get("last_coins", 0)
            score_lbl.config(text=f"Last Score: {last_s:,}" if last_s > 0 else "Last Score: -")
            coins_lbl.config(text=f"Last Coins: {last_c:,}" if last_c > 0 else "Last Coins: -")

            # Rates
            perf = bot_engine.get_performance_metrics()
            coins_hr_lbl.config(text=f"🪙 Coins/Hr: {perf['coins_per_hour']:,}")
            runs_hr_lbl.config(text=f"🔄 Runs/Hr: {perf['runs_per_hour']}")
            boxes_lbl.config(text=f"🎁 Boxes: {perf['total_boxes']} ({perf['boxes_per_hour']}/Hr)")
            rate_lbl.config(text=f"Success Rate: {perf['success_rate_pct']}%")

            if bot_engine.next_rest_time:
                remaining = int(bot_engine.next_rest_time - time.time())
                if remaining > 0:
                    rm_min = remaining // 60
                    rm_sec = remaining % 60
                    rest_lbl.config(text=f"Next Rest In: {rm_min:02d}:{rm_sec:02d}")
                else:
                    rest_lbl.config(text="Next Rest In: Resting...")
            else:
                rest_lbl.config(text="Next Rest In: -")

            if bot_engine.running:
                start_btn.config(text="●  RUNNING...", bootstyle="success-outline")
                stop_btn.config(text="■  STOP BOT (F7)", bootstyle="danger")
            else:
                start_btn.config(text="▶  START BOT (F6)", bootstyle="success")
                stop_btn.config(text="■  STOPPED", bootstyle="danger-outline")

        except Exception:
            pass
        root.after(500, update_stats_loop)

    root.after(500, update_stats_loop)

    def on_closing():
        bot_engine.save_global_stats(session_done=True)
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    run_gui()