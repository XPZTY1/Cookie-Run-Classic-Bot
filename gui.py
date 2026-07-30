import os
import sys
import json
import ctypes
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

import config
from bot_engine import BotInstance
from adb_client import adb_connect
from secrets_loader import (
    save_secret, ADB_DEVICE_ID,
    get_discord_webhooks, save_discord_webhooks,
    LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID, GEMINI_API_KEY
)
from notifiers.line_notifier import send_line_message
from notifiers.discord_notifier import send_discord_test_to_url

# ---------------------------------------------------------------------------
# Constants & Helpers
# ---------------------------------------------------------------------------
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
PROFILES_FILE_PATH = os.path.join(config.DATA_DIR, "user_profiles.json")


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
        ICON_SMALL, ICON_BIG, IMAGE_ICON = 0, 1, 1
        LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x00000010, 0x00000040

        root.update()
        hwnd = user32.GetParent(root.winfo_id())
        h_big = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        h_sm = user32.LoadImageW(None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if h_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
        if h_sm:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_sm)
    except Exception as e:
        print(f"⚠️ ตั้งไอคอน taskbar ไม่สำเร็จ: {e}")


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------
class CookieBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🍪 Cookie Run Classic Auto Bot — Multi-Instance Manager")
        self.root.geometry("1050x800")
        self.root.minsize(900, 700)
        self.root.resizable(True, True)

        try:
            self.root.iconbitmap(ICON_PATH)
        except Exception:
            pass
        force_taskbar_icon(self.root, ICON_PATH)

        # State
        self.instances = {}        # device_id -> BotInstance
        self.saved_ports = config.load_saved_ports()
        self.pages = {}            # page_key -> Frame

        self._build_layout()
        self._load_existing_ports()
        self.show_page("home")
        self._update_loop()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self):
        # Top header (always visible)
        hdr = ttk.Frame(self.root, padding=(12, 8, 12, 6), bootstyle="dark")
        hdr.pack(fill=tk.X, side=tk.TOP)

        title_box = ttk.Frame(hdr)
        title_box.pack(side=tk.LEFT)
        ttk.Label(title_box, text="🍪 COOKIE RUN BOT", font=("Segoe UI", 15, "bold"),
                  bootstyle="warning").pack(side=tk.LEFT)
        ttk.Label(title_box, text=" PRO", font=("Segoe UI", 10, "bold"),
                  bootstyle="danger").pack(side=tk.LEFT, padx=(2, 0), pady=(4, 0))

        btn_box = ttk.Frame(hdr)
        btn_box.pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="⚡ Start All", bootstyle="success",
                   command=self._start_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_box, text="⛔ Stop All", bootstyle="danger",
                   command=self._stop_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_box, text="⚙️ ตั้งค่า", bootstyle="info-outline",
                   command=self._open_settings).pack(side=tk.LEFT, padx=4)

        # Page container
        self.container = ttk.Frame(self.root)
        self.container.pack(fill=tk.BOTH, expand=True)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

        # Build HOME page
        home = HomePage(self.container, self)
        home.grid(row=0, column=0, sticky="nsew")
        self.pages["home"] = home

    def _load_existing_ports(self):
        for key, pdata in self.saved_ports.items():
            self._create_port_page(pdata)

    def _update_loop(self):
        for p in self.pages.values():
            if hasattr(p, "update_stats"):
                try:
                    p.update_stats()
                except Exception:
                    pass
        self.root.after(1000, self._update_loop)

    # ------------------------------------------------------------------
    # Page Navigation
    # ------------------------------------------------------------------
    def get_port_key(self, device_id):
        return device_id.replace(":", "_").replace(".", "_")

    def show_page(self, page_key):
        page = self.pages.get(page_key)
        if page:
            page.tkraise()
            if page_key == "home":
                self.pages["home"].refresh()

    def _create_port_page(self, pdata):
        dev_id = pdata.get("device_id")
        if not dev_id:
            return
        key = self.get_port_key(dev_id)
        if key not in self.pages:
            page = PortWorkspacePage(self.container, self, pdata)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page

    # ------------------------------------------------------------------
    # Add / Remove Port
    # ------------------------------------------------------------------
    def add_port(self, raw_port, nickname=""):
        device_id = raw_port.strip()
        if not device_id:
            messagebox.showwarning("คำเตือน", "กรุณากรอกพอร์ตหรือ Device ID ก่อน")
            return False

        if ":" not in device_id and not device_id.startswith("emulator-"):
            device_id = f"127.0.0.1:{device_id}"

        key = self.get_port_key(device_id)
        if key in self.saved_ports:
            messagebox.showinfo("แจ้งเตือน", f"พอร์ต {device_id} มีอยู่แล้วในระบบ")
            self.show_page(key)
            return True

        # Test connection
        ok = adb_connect(device_id)
        if not ok:
            res = messagebox.askyesno(
                "เชื่อมต่อไม่สำเร็จ",
                f"เชื่อมต่อ ADB ไปที่ {device_id} ไม่สำเร็จ\n"
                "ตรวจสอบว่าเปิด MuMu Player แล้วหรือยัง\n\n"
                "ต้องการบันทึกพอร์ตนี้ไว้ก่อนหรือไม่?"
            )
            if not res:
                return False

        pdata = {"nickname": nickname or device_id, "device_id": device_id}
        self.saved_ports[key] = pdata
        config.save_saved_ports(self.saved_ports)
        self._create_port_page(pdata)
        self.show_page(key)
        return True

    def remove_port(self, device_id):
        if not messagebox.askyesno("ยืนยันการลบ", f"ลบพอร์ต {device_id} ออกจากระบบหรือไม่?"):
            return
        key = self.get_port_key(device_id)
        if key in self.saved_ports:
            del self.saved_ports[key]
            config.save_saved_ports(self.saved_ports)

        inst = self.instances.get(device_id)
        if inst:
            try:
                inst.stop_bot()
            except Exception:
                pass
            del self.instances[device_id]

        if key in self.pages:
            self.pages[key].destroy()
            del self.pages[key]

        self.show_page("home")

    # ------------------------------------------------------------------
    # Master Controls
    # ------------------------------------------------------------------
    def _start_all(self):
        for key, page in self.pages.items():
            if key != "home" and hasattr(page, "start_bot_action"):
                page.start_bot_action()

    def _stop_all(self):
        for dev_id, inst in self.instances.items():
            try:
                if inst.running:
                    inst.stop_bot()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Settings Window
    # ------------------------------------------------------------------
    def _open_settings(self):
        SettingsWindow(self.root)


# ---------------------------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------------------------
class HomePage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._content = None
        self.refresh()

    def refresh(self):
        if self._content:
            self._content.destroy()
        self._content = ttk.Frame(self, padding=20)
        self._content.pack(fill=tk.BOTH, expand=True)

        if not self.app.saved_ports:
            self._build_welcome()
        else:
            self._build_grid()

    def update_stats(self):
        pass  # Home page refreshes on show; stats live on port pages

    # -- Welcome (first run) --
    def _build_welcome(self):
        wrap = ttk.Frame(self._content)
        wrap.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        ttk.Label(wrap, text="🍪", font=("Segoe UI", 48)).pack(pady=(0, 10))
        ttk.Label(wrap, text="ยินดีต้อนรับสู่ Cookie Run Auto Bot!",
                  font=("Segoe UI", 20, "bold"), bootstyle="warning").pack()
        ttk.Label(wrap, text="เพิ่มพอร์ต ADB ของ MuMu Player เพื่อเริ่มต้นใช้งาน",
                  font=("Segoe UI", 11), bootstyle="secondary").pack(pady=(4, 30))

        row = ttk.Frame(wrap)
        row.pack()
        ttk.Label(row, text="Device/Port:", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self._entry_welcome = ttk.Entry(row, width=22, font=("Consolas", 11))
        self._entry_welcome.pack(side=tk.LEFT, padx=5)
        self._entry_welcome.bind("<Return>", lambda e: self._on_add_welcome())

        ttk.Button(wrap, text="➕ เพิ่มพอร์ตและเริ่มใช้งาน", bootstyle="primary",
                   command=self._on_add_welcome).pack(pady=18, ipady=6, ipadx=12)

        ttk.Label(wrap, text="ตัวอย่าง: 7555  หรือ  16384  หรือ  127.0.0.1:5559",
                  font=("Segoe UI", 9), bootstyle="secondary").pack()

    def _on_add_welcome(self):
        port = self._entry_welcome.get().strip()
        if port:
            self.app.add_port(port)

    # -- Port cards grid --
    def _build_grid(self):
        ttk.Label(self._content, text="📱 พอร์ตจำลองของคุณ",
                  font=("Segoe UI", 17, "bold"), bootstyle="info").pack(anchor=tk.W, pady=(0, 16))

        grid = ttk.Frame(self._content)
        grid.pack(fill=tk.BOTH, expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        col, row = 0, 0
        for key, pdata in self.app.saved_ports.items():
            self._build_card(grid, pdata, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1

        # Add-port card
        add_card = ttk.Labelframe(grid, text="➕ เพิ่มพอร์ตใหม่", bootstyle="info", padding=15)
        add_card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        ttk.Label(add_card, text="Port/Device (เช่น 7555, 16384):",
                  font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 4))
        entry = ttk.Entry(add_card, font=("Consolas", 10))
        entry.pack(fill=tk.X, pady=4)

        nick_row = ttk.Frame(add_card)
        nick_row.pack(fill=tk.X, pady=4)
        ttk.Label(nick_row, text="ชื่อกำกับ (ไม่บังคับ):", font=("Segoe UI", 9)).pack(anchor=tk.W)
        nick_entry = ttk.Entry(nick_row, font=("Segoe UI", 10))
        nick_entry.pack(fill=tk.X)

        ttk.Button(add_card, text="💾 บันทึกและเชื่อมต่อ", bootstyle="success",
                   command=lambda: self.app.add_port(
                       entry.get(), nick_entry.get()
                   )).pack(pady=10, fill=tk.X)

    def _build_card(self, parent, pdata, row, col):
        dev_id = pdata["device_id"]
        nick = pdata.get("nickname", dev_id)

        inst = self.app.instances.get(dev_id)
        is_running = getattr(inst, "running", False) if inst else False

        card = ttk.Labelframe(parent, text=nick, bootstyle="secondary", padding=14)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        # Status
        status_txt = "🟢 RUNNING" if is_running else "🔴 STOPPED"
        status_style = "success" if is_running else "danger"
        ttk.Label(card, text=status_txt, bootstyle=status_style,
                  font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 4))

        # Device ID
        ttk.Label(card, text=dev_id, font=("Consolas", 9),
                  bootstyle="secondary").pack(anchor=tk.W, pady=(0, 6))

        # Stats
        stats = "รอบสำเร็จ: 0 | อัตรา: 0%"
        if inst and hasattr(inst, "session_stats"):
            s = inst.session_stats
            tr = s.get("total_runs", 0)
            sr = round((s.get("successful_runs", 0) / tr) * 100, 1) if tr > 0 else 0
            stats = f"รอบสำเร็จ: {s.get('successful_runs', 0)} / {tr} | อัตรา: {sr}%"
        ttk.Label(card, text=stats, font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 10))

        # Buttons
        btn_row = ttk.Frame(card)
        btn_row.pack(fill=tk.X)
        key = self.app.get_port_key(dev_id)
        ttk.Button(btn_row, text="▶ รัน", bootstyle="success-outline", width=8,
                   command=lambda d=dev_id: self._quick_start(d)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="■ หยุด", bootstyle="danger-outline", width=8,
                   command=lambda d=dev_id: self._quick_stop(d)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="⚙️ เข้าสู่หน้าควบคุม", bootstyle="info",
                   command=lambda k=key: self.app.show_page(k)).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="🗑️", bootstyle="danger",
                   command=lambda d=dev_id: self.app.remove_port(d)).pack(side=tk.RIGHT)

    def _quick_start(self, dev_id):
        key = self.app.get_port_key(dev_id)
        if key in self.app.pages:
            self.app.pages[key].start_bot_action()
        self.refresh()

    def _quick_stop(self, dev_id):
        inst = self.app.instances.get(dev_id)
        if inst:
            try:
                inst.stop_bot()
            except Exception:
                pass
        self.refresh()


# ---------------------------------------------------------------------------
# PORT WORKSPACE PAGE
# ---------------------------------------------------------------------------
class PortWorkspacePage(ttk.Frame):
    def __init__(self, parent, app, pdata):
        super().__init__(parent)
        self.app = app
        self.device_id = pdata["device_id"]
        self.nickname = pdata.get("nickname", self.device_id)
        self._setup_ui()

    def _setup_ui(self):
        content = ttk.Frame(self, padding=(20, 15, 20, 15))
        content.pack(fill=tk.BOTH, expand=True)

        # Header
        hdr = ttk.Frame(content)
        hdr.pack(fill=tk.X, pady=(0, 12))

        ttk.Button(hdr, text="← กลับหน้าหลัก", bootstyle="secondary-outline",
                   command=lambda: self.app.show_page("home")).pack(side=tk.LEFT)
        ttk.Label(hdr, text=f"  📱 {self.nickname}",
                  font=("Segoe UI", 15, "bold"), bootstyle="info").pack(side=tk.LEFT)
        self._status_lbl = ttk.Label(hdr, text="🔴 STOPPED",
                                     font=("Segoe UI", 11, "bold"), bootstyle="danger")
        self._status_lbl.pack(side=tk.RIGHT)

        # ADB port row
        adb_row = ttk.Frame(content)
        adb_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(adb_row, text="📡 Device:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        ttk.Label(adb_row, text=self.device_id, font=("Consolas", 9),
                  bootstyle="secondary").pack(side=tk.LEFT, padx=6)

        # Control buttons
        ctrl = ttk.Frame(content)
        ctrl.pack(fill=tk.X, pady=6)
        ttk.Button(ctrl, text="▶  START BOT", bootstyle="success", width=16,
                   command=self.start_bot_action).pack(side=tk.LEFT, padx=4, ipady=4)
        ttk.Button(ctrl, text="■  STOP BOT", bootstyle="danger-outline", width=16,
                   command=self.stop_bot_action).pack(side=tk.LEFT, padx=4, ipady=4)
        ttk.Button(ctrl, text="⚙️ ตั้งค่าพอร์ทนี้", bootstyle="info-outline", width=16,
                   command=self._open_port_settings).pack(side=tk.LEFT, padx=4, ipady=4)
        ttk.Button(ctrl, text="🗑️ ลบพอร์ตนี้", bootstyle="danger",
                   command=lambda: self.app.remove_port(self.device_id)).pack(side=tk.RIGHT, padx=4)

        # Stats Overview
        stats_frame = ttk.Labelframe(content, text="📊 สถิติการทำงานแบบ Real-time", bootstyle="primary", padding=12)
        stats_frame.pack(fill=tk.X, pady=10)

        r1 = ttk.Frame(stats_frame)
        r1.pack(fill=tk.X, pady=3)
        self._lbl_state = ttk.Label(r1, text="State: -", font=("Segoe UI", 9, "bold"), bootstyle="warning", width=22)
        self._lbl_state.pack(side=tk.LEFT, padx=5)
        self._lbl_runs = ttk.Label(r1, text="Total Runs: 0", font=("Segoe UI", 9), width=22)
        self._lbl_runs.pack(side=tk.LEFT, padx=5)
        self._lbl_success = ttk.Label(r1, text="Success: 0", font=("Segoe UI", 9), width=22)
        self._lbl_success.pack(side=tk.LEFT, padx=5)
        self._lbl_rate = ttk.Label(r1, text="Rate: 0.0%", font=("Segoe UI", 9), width=22)
        self._lbl_rate.pack(side=tk.LEFT, padx=5)

        r2 = ttk.Frame(stats_frame)
        r2.pack(fill=tk.X, pady=3)
        self._lbl_coins = ttk.Label(r2, text="🪙 Coins/Hr: 0", font=("Segoe UI", 9), width=22)
        self._lbl_coins.pack(side=tk.LEFT, padx=5)
        self._lbl_boxes = ttk.Label(r2, text="🎁 Boxes: 0", font=("Segoe UI", 9), width=22)
        self._lbl_boxes.pack(side=tk.LEFT, padx=5)
        self._lbl_score = ttk.Label(r2, text="🏆 Last Score: 0", font=("Segoe UI", 9), width=22)
        self._lbl_score.pack(side=tk.LEFT, padx=5)
        self._lbl_rest = ttk.Label(r2, text="Next Rest: --:--", font=("Segoe UI", 9), width=22)
        self._lbl_rest.pack(side=tk.LEFT, padx=5)

        # Log Section
        log_hdr = ttk.Frame(content)
        log_hdr.pack(fill=tk.X, pady=(10, 4))
        ttk.Label(log_hdr, text="📜 บันทึกการทำงาน (Log)", font=("Segoe UI", 11, "bold"), bootstyle="secondary").pack(side=tk.LEFT)
        ttk.Button(log_hdr, text="🧹 ล้าง Log", bootstyle="secondary-outline", command=self._clear_log).pack(side=tk.RIGHT)

        self._log_box = scrolledtext.ScrolledText(
            content, height=16, bg="#0f172a", fg="#38bdf8",
            font=("Consolas", 10), state="disabled"
        )
        self._log_box.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

    def _open_port_settings(self):
        PortSettingsDialog(self, self.app, self.device_id)

    # ------------------------------------------------------------------
    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", tk.END)
        self._log_box.configure(state="disabled")

    def append_log(self, msg):
        def _do():
            try:
                self._log_box.configure(state="normal")
                self._log_box.insert(tk.END, msg + "\n")
                self._log_box.see(tk.END)
                self._log_box.configure(state="disabled")
            except Exception:
                pass
        try:
            self.after(0, _do)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def start_bot_action(self):
        key = self.app.get_port_key(self.device_id)
        pdata = self.app.saved_ports.get(key, {})
        port_settings = config.get_port_settings(pdata)

        if self.device_id not in self.app.instances:
            self.app.instances[self.device_id] = BotInstance(
                device_id=self.device_id,
                log_callback=self.append_log,
                settings=port_settings
            )
        else:
            inst = self.app.instances[self.device_id]
            inst.update_settings(port_settings)
            inst._gui_log_callback = self.append_log

        inst = self.app.instances[self.device_id]
        if inst.running or getattr(inst, "_thread_active", False):
            self.append_log("⚠️ บอทกำลังทำงานอยู่แล้ว")
            return

        inst._thread_active = True

        self.append_log(f"🚀 กำลังเริ่มบอทบนพอร์ต {self.device_id}...")
        
        def _run():
            try:
                inst.start_bot()
                inst.bot_loop()
            finally:
                inst._thread_active = False
                inst.running = False
                try:
                    self.after(0, lambda: self._status_lbl.config(text="🔴 STOPPED", bootstyle="danger"))
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()
        self._status_lbl.config(text="🟢 RUNNING", bootstyle="success")

    def stop_bot_action(self):
        inst = self.app.instances.get(self.device_id)
        if inst:
            self.append_log("🛑 ส่งสัญญาณหยุดบอท...")
            inst.stop_bot()
            inst._thread_active = False
            inst.running = False
        self._status_lbl.config(text="🔴 STOPPED", bootstyle="danger")

    # ------------------------------------------------------------------
    def update_stats(self):
        inst = self.app.instances.get(self.device_id)
        if not inst:
            return
        try:
            is_running = inst.running
            self._status_lbl.config(
                text="🟢 RUNNING" if is_running else "🔴 STOPPED",
                bootstyle="success" if is_running else "danger"
            )
            if is_running:
                s = inst.session_stats
                perf = inst.get_performance_metrics()
                state = getattr(inst, "current_state", "-")
                self._lbl_state.config(text=f"State: {state}")
                self._lbl_runs.config(text=f"Total Runs: {s.get('total_runs', 0)}")
                self._lbl_success.config(text=f"Success: {s.get('successful_runs', 0)}")
                rate = perf.get("success_rate_pct", 0.0)
                self._lbl_rate.config(text=f"Rate: {rate}%")
                self._lbl_coins.config(text=f"🪙 Coins/Hr: {perf.get('coins_per_hour', 0):,}")
                self._lbl_boxes.config(text=f"🎁 Boxes: {perf.get('total_boxes', 0)}")
                self._lbl_score.config(text=f"🏆 Last Score: {s.get('last_score', 0):,}")

                nr = getattr(inst, "next_rest_time", None)
                if nr:
                    import time as _t
                    secs_left = max(0, int(nr - _t.time()))
                    m, s2 = divmod(secs_left, 60)
                    self._lbl_rest.config(text=f"Next Rest: {m:02d}:{s2:02d}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# PORT SETTINGS DIALOG (Toplevel)
# ---------------------------------------------------------------------------
class PortSettingsDialog(tk.Toplevel):
    def __init__(self, parent, app, device_id):
        super().__init__(parent)
        self.app = app
        self.device_id = device_id
        self.key = self.app.get_port_key(device_id)
        self.pdata = self.app.saved_ports.get(self.key, {})
        self.nickname = self.pdata.get("nickname", self.device_id)

        self.title(f"⚙️ ตั้งค่าพอร์ต — {self.nickname} ({self.device_id})")
        self.geometry("620x680")
        self.resizable(True, True)
        self.grab_set()

        self.port_settings = config.get_port_settings(self.pdata)

        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text=f"📱 ตั้งค่าพอร์ต: {self.nickname}",
                  font=("Segoe UI", 14, "bold"), bootstyle="info").pack(anchor=tk.W, pady=(0, 2))
        ttk.Label(container, text=f"Device ID: {self.device_id}",
                  font=("Consolas", 9), bootstyle="secondary").pack(anchor=tk.W, pady=(0, 14))

        sf = ttk.Frame(container)
        sf.pack(fill=tk.BOTH, expand=True)

        # Toggles section
        self.vars = {}
        toggles = [
            ("ENABLE_BOOSTER_BUY",          "ซื้อไอเทมเพิ่มพลัง (Booster)"),
            ("ENABLE_FAST_START_BOOST",      "Fast Start Boost (กดรัวตอนเริ่มวิ่ง)"),
            ("ENABLE_USE_SECOND_COOKIE",     "ใช้คุกกี้ตัวที่ 2 เมื่อมีให้กด"),
            ("ENABLE_LINE_NOTIFY",           "ส่งแจ้งเตือน LINE"),
            ("ENABLE_RANDOM_TAP_WHILE_WAIT", "สุ่มกดระหว่างรอ (over_game)"),
            ("DISCORD_REPORT_ENABLED",       "ส่งรายงาน Discord"),
            ("OCR_SCORE_ENABLED",            "อ่านคะแนนด้วย Gemini OCR"),
            ("SCHEDULE_ENABLED",             "ระบบตารางเวลาทำงาน"),
        ]

        toggles_frame = ttk.Labelframe(sf, text="🎮 สวิตช์ควบคุมระบบบอทเฉพาะพอร์ตนี้", bootstyle="primary", padding=15)
        toggles_frame.pack(fill=tk.X, pady=(0, 15))

        for attr, label in toggles:
            row = ttk.Frame(toggles_frame)
            row.pack(fill=tk.X, pady=4)
            cur_val = self.port_settings.get(attr, True)
            var = tk.BooleanVar(value=bool(cur_val))
            self.vars[attr] = var
            ttk.Checkbutton(row, variable=var, bootstyle="success-round-toggle").pack(side=tk.LEFT)
            ttk.Label(row, text=f"  {label}", font=("Segoe UI", 10)).pack(side=tk.LEFT)

        # Discord Webhook selection
        wh_frame = ttk.Labelframe(sf, text="💬 Discord Webhook สำหรับพอร์ตนี้", bootstyle="info", padding=15)
        wh_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(wh_frame, text="เลือกโปรไฟล์ Webhook ที่ต้องการให้พอร์ตนี้ใช้ส่งรายงาน:",
                  font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 6))

        webhooks = get_discord_webhooks()
        wh_options = ["[ALL] ส่งทุก Webhook ที่เปิดใช้งาน", "[NONE] ปิดใช้งาน"]
        for wh in webhooks:
            if isinstance(wh, dict) and wh.get("name"):
                wh_options.append(wh["name"])

        selected_wh = self.port_settings.get("SELECTED_DISCORD_WEBHOOK", "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน")
        if selected_wh not in wh_options:
            selected_wh = "[ALL] ส่งทุก Webhook ที่เปิดใช้งาน"

        self.wh_var = tk.StringVar(value=selected_wh)
        combobox = ttk.Combobox(wh_frame, textvariable=self.wh_var, values=wh_options, state="readonly", font=("Segoe UI", 10))
        combobox.pack(fill=tk.X, pady=4)

        # Action Buttons
        btn_box = ttk.Frame(container)
        btn_box.pack(fill=tk.X, pady=(15, 0))

        ttk.Button(btn_box, text="💾 บันทึกการตั้งค่าพอร์ต", bootstyle="success",
                   command=self._save_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="ยกเลิก", bootstyle="secondary-outline",
                   command=self.destroy).pack(side=tk.RIGHT, padx=5)

    def _save_settings(self):
        new_settings = {}
        for attr, var in self.vars.items():
            new_settings[attr] = var.get()
        new_settings["SELECTED_DISCORD_WEBHOOK"] = self.wh_var.get()

        # Update saved_ports dict
        if self.key in self.app.saved_ports:
            self.app.saved_ports[self.key]["settings"] = new_settings
            config.save_saved_ports(self.app.saved_ports)

        # Update running instance if any
        inst = self.app.instances.get(self.device_id)
        if inst:
            inst.update_settings(new_settings)

        messagebox.showinfo("บันทึกสำเร็จ", f"บันทึกการตั้งค่าสำหรับพอร์ต {self.nickname} เรียบร้อยแล้ว!")
        self.destroy()


# ---------------------------------------------------------------------------
# SETTINGS WINDOW (Toplevel)
# ---------------------------------------------------------------------------
class SettingsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("⚙️ ตั้งค่า — Cookie Run Auto Bot")
        self.geometry("820x680")
        self.resizable(True, True)
        self.grab_set()

        notebook = ttk.Notebook(self, bootstyle="dark")
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: LINE & Gemini
        tab_api = ttk.Frame(notebook, padding=20)
        notebook.add(tab_api, text="🔑 API Keys")
        self._build_api_tab(tab_api)

        # Tab 2: Discord
        tab_discord = ttk.Frame(notebook, padding=20)
        notebook.add(tab_discord, text="💬 Discord")
        self._build_discord_tab(tab_discord)

        # Tab 3: Bot Toggles
        tab_toggle = ttk.Frame(notebook, padding=20)
        notebook.add(tab_toggle, text="🎮 การตั้งค่าบอท")
        self._build_toggles_tab(tab_toggle)

        # Tab 4: Test
        tab_test = ttk.Frame(notebook, padding=20)
        notebook.add(tab_test, text="🧪 ทดสอบ")
        self._build_test_tab(tab_test)

    # -- API Keys Tab --
    def _build_api_tab(self, parent):
        def _field(label, value, key):
            row = ttk.Frame(parent)
            row.pack(fill=tk.X, pady=6)
            ttk.Label(row, text=label, font=("Segoe UI", 9, "bold"), width=28).pack(side=tk.LEFT)
            var = tk.StringVar(value=value or "")
            entry = ttk.Entry(row, textvariable=var, font=("Consolas", 9), width=50)
            entry.pack(side=tk.LEFT, padx=6)
            ttk.Button(row, text="💾 บันทึก", bootstyle="success-outline",
                       command=lambda k=key, v=var: self._save_key(k, v.get())).pack(side=tk.LEFT)

        ttk.Label(parent, text="🔑 ตั้งค่า API Keys และ Tokens",
                  font=("Segoe UI", 13, "bold"), bootstyle="warning").pack(anchor=tk.W, pady=(0, 16))

        _field("LINE Channel Access Token:", LINE_CHANNEL_ACCESS_TOKEN, "line_channel_access_token")
        _field("LINE User ID:", LINE_USER_ID, "line_user_id")
        _field("Gemini API Key:", GEMINI_API_KEY, "gemini_api_key")

        ttk.Separator(parent).pack(fill=tk.X, pady=14)
        ttk.Label(parent, text="ค่าที่บันทึกจะถูกเขียนลงในไฟล์ .env ทันที",
                  font=("Segoe UI", 9), bootstyle="secondary").pack(anchor=tk.W)

    def _save_key(self, key, value):
        save_secret(key, value)
        messagebox.showinfo("บันทึกสำเร็จ", f"บันทึกค่า {key.upper()} เรียบร้อยแล้ว")

    # -- Discord Tab --
    def _build_discord_tab(self, parent):
        ttk.Label(parent, text="💬 จัดการ Discord Webhook Profiles",
                  font=("Segoe UI", 13, "bold"), bootstyle="warning").pack(anchor=tk.W, pady=(0, 12))

        self._webhooks = get_discord_webhooks()

        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self._wh_rows_frame = ttk.Frame(list_frame)
        self._wh_rows_frame.pack(fill=tk.BOTH, expand=True)
        self._render_webhook_rows()

        add_frame = ttk.Frame(parent)
        add_frame.pack(fill=tk.X, pady=10)
        ttk.Label(add_frame, text="ชื่อ:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._wh_name_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self._wh_name_var, width=15,
                  font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=4)
        ttk.Label(add_frame, text="URL:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._wh_url_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self._wh_url_var, width=45,
                  font=("Consolas", 9)).pack(side=tk.LEFT, padx=4)
        ttk.Button(add_frame, text="➕ เพิ่ม", bootstyle="success",
                   command=self._add_webhook).pack(side=tk.LEFT, padx=4)

    def _render_webhook_rows(self):
        for w in self._wh_rows_frame.winfo_children():
            w.destroy()
        for i, wh in enumerate(self._webhooks):
            row = ttk.Frame(self._wh_rows_frame)
            row.pack(fill=tk.X, pady=3)
            en_var = tk.BooleanVar(value=wh.get("enabled", True))
            ttk.Checkbutton(row, variable=en_var, bootstyle="success",
                            command=lambda v=en_var, idx=i: self._toggle_webhook(idx, v.get())
                            ).pack(side=tk.LEFT)
            ttk.Label(row, text=f"[{wh.get('name', '')}]",
                      font=("Segoe UI", 9, "bold"), width=20).pack(side=tk.LEFT)
            ttk.Label(row, text=wh.get("url", "")[:55] + "...",
                      font=("Consolas", 8), bootstyle="secondary").pack(side=tk.LEFT, padx=6)
            ttk.Button(row, text="🧪 ทดสอบ", bootstyle="info-outline",
                       command=lambda u=wh.get("url", ""): self._test_webhook(u)).pack(side=tk.LEFT, padx=4)
            ttk.Button(row, text="🗑️", bootstyle="danger",
                       command=lambda idx=i: self._del_webhook(idx)).pack(side=tk.RIGHT)

    def _add_webhook(self):
        name = self._wh_name_var.get().strip()
        url = self._wh_url_var.get().strip()
        if not name or not url:
            messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อและ URL")
            return
        self._webhooks.append({"name": name, "url": url, "enabled": True})
        save_discord_webhooks(self._webhooks)
        self._render_webhook_rows()
        self._wh_name_var.set("")
        self._wh_url_var.set("")

    def _toggle_webhook(self, idx, val):
        self._webhooks[idx]["enabled"] = val
        save_discord_webhooks(self._webhooks)

    def _del_webhook(self, idx):
        del self._webhooks[idx]
        save_discord_webhooks(self._webhooks)
        self._render_webhook_rows()

    def _test_webhook(self, url):
        if url:
            try:
                send_discord_test_to_url(url, "🔔 ทดสอบการแจ้งเตือนจาก Cookie Run Auto Bot ✅")
                messagebox.showinfo("ทดสอบ Discord", "ส่งข้อความทดสอบเรียบร้อยแล้ว!")
            except Exception as e:
                messagebox.showerror("ทดสอบ Discord", f"เกิดข้อผิดพลาด: {e}")

    # -- Bot Toggles Tab --
    def _build_toggles_tab(self, parent):
        ttk.Label(parent, text="🎮 ตั้งค่าสวิตช์ควบคุมบอท",
                  font=("Segoe UI", 13, "bold"), bootstyle="warning").pack(anchor=tk.W, pady=(0, 16))

        toggles = [
            ("ENABLE_BOOSTER_BUY",         "ซื้อไอเทมเพิ่มพลัง (Booster)"),
            ("ENABLE_FAST_START_BOOST",     "Fast Start Boost (กดรัวตอนเริ่มวิ่ง)"),
            ("ENABLE_USE_SECOND_COOKIE",    "ใช้คุกกี้ตัวที่ 2 เมื่อมีให้กด"),
            ("ENABLE_LINE_NOTIFY",          "ส่งแจ้งเตือน LINE"),
            ("ENABLE_RANDOM_TAP_WHILE_WAIT","สุ่มกดระหว่างรอ (over_game)"),
            ("DISCORD_REPORT_ENABLED",      "ส่งรายงาน Discord"),
            ("OCR_SCORE_ENABLED",           "อ่านคะแนนด้วย Gemini OCR"),
            ("SCHEDULE_ENABLED",            "ระบบตารางเวลาทำงาน"),
        ]

        for attr, label in toggles:
            row = ttk.Frame(parent)
            row.pack(fill=tk.X, pady=5)
            cur = getattr(config, attr, False)
            var = tk.BooleanVar(value=bool(cur))
            ttk.Checkbutton(row, variable=var, bootstyle="success-round-toggle",
                            command=lambda a=attr, v=var: setattr(config, a, v.get())
                            ).pack(side=tk.LEFT)
            ttk.Label(row, text=f"  {label}", font=("Segoe UI", 10)).pack(side=tk.LEFT)

    # -- Test Tab --
    def _build_test_tab(self, parent):
        ttk.Label(parent, text="🧪 ทดสอบการเชื่อมต่อ",
                  font=("Segoe UI", 13, "bold"), bootstyle="warning").pack(anchor=tk.W, pady=(0, 16))

        self._test_log = scrolledtext.ScrolledText(
            parent, height=12, bg="#0f172a", fg="#38bdf8",
            font=("Consolas", 9), state="disabled"
        )
        self._test_log.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="📨 ทดสอบ LINE", bootstyle="info",
                   command=self._test_line).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="💬 ทดสอบ Discord", bootstyle="primary",
                   command=self._test_discord).pack(side=tk.LEFT, padx=5)

    def _log_test(self, msg):
        self._test_log.configure(state="normal")
        self._test_log.insert(tk.END, msg + "\n")
        self._test_log.see(tk.END)
        self._test_log.configure(state="disabled")

    def _test_line(self):
        self._log_test("📨 กำลังส่งข้อความทดสอบ LINE...")
        try:
            send_line_message("🔔 ทดสอบการแจ้งเตือนจาก Cookie Run Auto Bot")
            self._log_test("✅ ส่ง LINE สำเร็จ!")
        except Exception as e:
            self._log_test(f"❌ ล้มเหลว: {e}")

    def _test_discord(self):
        whs = get_discord_webhooks()
        enabled = [w for w in whs if w.get("enabled")]
        if not enabled:
            self._log_test("❌ ไม่มี Discord Webhook ที่เปิดใช้งาน")
            return
        self._log_test(f"💬 กำลังทดสอบ {len(enabled)} Webhook...")
        for wh in enabled:
            try:
                send_discord_test_to_url(wh["url"], "🔔 ทดสอบ Discord Webhook จาก Cookie Run Auto Bot ✅")
                self._log_test(f"  ✅ [{wh['name']}] สำเร็จ")
            except Exception as e:
                self._log_test(f"  ❌ [{wh['name']}] ล้มเหลว: {e}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def run_gui():
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "cookierunbot.gui.multiinstance.v3"
            )
        except Exception:
            pass

    root = ttk.Window(themename="darkly")
    CookieBotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()