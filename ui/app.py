import os
import sys
import ctypes
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as ttk

import config
from adb_client import adb_connect
from ui import theme
from ui.theme import NavButton, ScrollableFrame
from ui.pages.home_page import HomePage
from ui.pages.workspace_page import PortWorkspacePage
from ui.dialogs.global_settings import SettingsWindow


ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")


def force_taskbar_icon(root, icon_path):
    """Use the application icon in the Windows taskbar when possible."""
    if not sys.platform.startswith("win"):
        return
    try:
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
        ]
        user32.SendMessageW.restype = ctypes.c_void_p

        root.update()
        hwnd = user32.GetParent(root.winfo_id())
        load_flags = 0x00000010 | 0x00000040
        h_big = user32.LoadImageW(None, icon_path, 1, 0, 0, load_flags)
        h_small = user32.LoadImageW(None, icon_path, 1, 16, 16, 0x00000010)
        if h_big:
            user32.SendMessageW(hwnd, 0x0080, 1, h_big)
        if h_small:
            user32.SendMessageW(hwnd, 0x0080, 0, h_small)
    except Exception:
        pass


class CookieBotGUI:
    """Application shell: navigation, multi-device lifecycle and global actions."""

    def __init__(self, root):
        self.root = root
        self.root.title("Cookie Run Classic — Multi-Instance Bot")
        self.root.geometry("1360x820")
        self.root.minsize(1024, 700)
        self.root.resizable(True, True)
        theme.apply_window_chrome(self.root)

        try:
            self.root.iconbitmap(ICON_PATH)
        except Exception:
            pass
        force_taskbar_icon(self.root, ICON_PATH)
        theme.enable_acrylic(self.root)

        self.instances = {}
        self.saved_ports = config.load_saved_ports()
        self.pages = {}
        self.nav_buttons = {}
        self.current_page = None
        self._sidebar_collapsed = False

        self._build_layout()
        self._load_existing_ports()
        self.show_page("home")
        self._update_loop()

        self._on_resize_debounced = theme.debounce(
            self.root, theme.RESIZE_DEBOUNCE_MS, self._on_sidebar_resize
        )
        self.sidebar.bind("<Configure>", self._handle_sidebar_configure)

    # ------------------------------------------------------------------
    # Shell layout
    # ------------------------------------------------------------------
    def _build_layout(self):
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        self.paned = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            bd=0,
            bg=theme.APP_BG,
            sashwidth=theme.SASH_WIDTH,
            sashrelief=tk.FLAT,
            sashpad=0,
            opaqueresize=True,
        )
        self.paned.grid(row=0, column=0, sticky="nsew")

        self._build_sidebar()
        self.paned.add(
            self.sidebar,
            width=theme.SIDEBAR_WIDTH,
            minsize=theme.SIDEBAR_MIN_DRAG_WIDTH,
            stretch="never",
        )

        self.container = ttk.Frame(self.paned)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)
        self.paned.add(self.container, minsize=520, stretch="always")

        home = HomePage(self.container, self)
        home.grid(row=0, column=0, sticky="nsew")
        self.pages["home"] = home

        self.paned.bind("<B1-Motion>", self._clamp_sash)
        self.paned.bind("<ButtonRelease-1>", self._clamp_sash)

    def _clamp_sash(self, _event=None):
        try:
            position = self.paned.sash_coord(0)[0]
        except Exception:
            return
        if position > theme.SIDEBAR_MAX_DRAG_WIDTH:
            self.paned.sash_place(0, theme.SIDEBAR_MAX_DRAG_WIDTH, 0)

    def _build_sidebar(self):
        self.sidebar = tk.Frame(self.paned, bg=theme.SIDEBAR_BG, highlightthickness=0)
        self.sidebar.rowconfigure(3, weight=1)
        self.sidebar.columnconfigure(0, weight=1)

        # Brand
        brand = tk.Frame(self.sidebar, bg=theme.SIDEBAR_BG)
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 14))
        self.brand_frame = brand

        mark = tk.Label(
            brand, text="CR", bg=theme.PRIMARY, fg="#FFFFFF",
            font=("Segoe UI", 10, "bold"), width=3, pady=5,
        )
        mark.pack(side=tk.LEFT, anchor="n", padx=(0, 10))
        self.brand_mark = mark
        brand_copy = tk.Frame(brand, bg=theme.SIDEBAR_BG)
        brand_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.brand_title = tk.Label(
            brand_copy, text="COOKIE RUN", bg=theme.SIDEBAR_BG, fg=theme.TEXT,
            font=theme.FONT_BRAND, anchor="w",
        )
        self.brand_title.pack(anchor="w")
        self.brand_subtitle = tk.Label(
            brand_copy, text="MULTI-INSTANCE CONTROL", bg=theme.SIDEBAR_BG,
            fg=theme.TEXT_MUTED, font=theme.FONT_EYEBROW, anchor="w",
        )
        self.brand_subtitle.pack(anchor="w", pady=(1, 0))

        tk.Frame(self.sidebar, bg=theme.BORDER_SOFT, height=1).grid(
            row=1, column=0, sticky="ew", padx=16
        )

        # Primary navigation
        nav_top = tk.Frame(self.sidebar, bg=theme.SIDEBAR_BG)
        nav_top.grid(row=2, column=0, sticky="ew", padx=10, pady=(14, 8))
        self.nav_top = nav_top
        self.nav_section_label = tk.Label(
            nav_top, text="WORKSPACE", bg=theme.SIDEBAR_BG, fg=theme.TEXT_DIM,
            font=theme.FONT_EYEBROW, anchor="w",
        )
        self.nav_section_label.pack(fill=tk.X, padx=8, pady=(0, 6))

        home_btn = NavButton(nav_top, "ภาพรวม", "⌂", command=lambda: self.show_page("home"))
        home_btn.pack(fill=tk.X)
        self.nav_buttons["home"] = home_btn

        self.ports_label = tk.Label(
            nav_top, text="อุปกรณ์ที่เชื่อมต่อ", bg=theme.SIDEBAR_BG, fg=theme.TEXT_DIM,
            font=theme.FONT_EYEBROW, anchor="w",
        )
        self.ports_label.pack(fill=tk.X, padx=8, pady=(18, 6))

        # This row expands so device navigation remains available on small screens.
        self._port_list = ScrollableFrame(self.sidebar, bootstyle="dark", bg=theme.SIDEBAR_BG)
        self._port_list.grid(row=3, column=0, sticky="nsew", padx=(10, 6), pady=(0, 8))
        self.nav_body = self._port_list.body

        # Global controls
        bottom_outer = tk.Frame(self.sidebar, bg=theme.SIDEBAR_ELEVATED, highlightthickness=0)
        bottom_outer.grid(row=4, column=0, sticky="ew")
        self.bottom_bar = bottom_outer
        bottom = tk.Frame(bottom_outer, bg=theme.SIDEBAR_ELEVATED)
        bottom.pack(fill=tk.X, padx=14, pady=(12, 16))
        self.bottom_content = bottom

        self.bottom_caption = tk.Label(
            bottom, text="คำสั่งด่วน", bg=theme.SIDEBAR_ELEVATED, fg=theme.TEXT_DIM,
            font=theme.FONT_EYEBROW, anchor="w",
        )
        self.bottom_caption.pack(fill=tk.X, pady=(0, 7))

        self.bottom_row1 = ttk.Frame(bottom)
        self.bottom_row1.pack(fill=tk.X, pady=(0, 7))
        self.bottom_row1.columnconfigure(0, weight=1, uniform="master-action")
        self.bottom_row1.columnconfigure(1, weight=1, uniform="master-action")
        self.start_all_btn = ttk.Button(
            self.bottom_row1, text="เริ่มทั้งหมด", bootstyle="success",
            command=self._start_all,
        )
        self.start_all_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4), ipady=2)
        self.stop_all_btn = ttk.Button(
            self.bottom_row1, text="หยุดทั้งหมด", bootstyle="danger-outline",
            command=self._stop_all,
        )
        self.stop_all_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0), ipady=2)
        self.settings_btn = ttk.Button(
            bottom, text="ตั้งค่าแอปพลิเคชัน", bootstyle="secondary-outline",
            command=self._open_settings,
        )
        self.settings_btn.pack(fill=tk.X, ipady=1)

    def _load_existing_ports(self):
        for _key, pdata in self.saved_ports.items():
            self._create_port_page(pdata)

    def _update_loop(self):
        for key, page in list(self.pages.items()):
            if hasattr(page, "update_stats"):
                try:
                    page.update_stats()
                except Exception:
                    pass
            if key != "home" and key in self.nav_buttons:
                instance = self.instances.get(page.device_id) if hasattr(page, "device_id") else None
                self.nav_buttons[key].set_status(getattr(instance, "running", False))
        self.root.after(1000, self._update_loop)

    # ------------------------------------------------------------------
    # Responsive sidebar
    # ------------------------------------------------------------------
    def _handle_sidebar_configure(self, event):
        if event.widget is self.sidebar:
            self._on_resize_debounced()

    def _on_sidebar_resize(self):
        collapsed = self.sidebar.winfo_width() < theme.SIDEBAR_COLLAPSE_AT
        if collapsed != self._sidebar_collapsed:
            self._sidebar_collapsed = collapsed
            self._apply_sidebar_collapsed(collapsed)

    def _apply_sidebar_collapsed(self, collapsed):
        if collapsed:
            self.brand_mark.pack_forget()
            self.brand_title.configure(text="CR", font=("Segoe UI", 12, "bold"))
            self.brand_title.pack(anchor="center")
            self.brand_subtitle.pack_forget()
            self.nav_section_label.pack_forget()
            self.ports_label.pack_forget()
            self.bottom_caption.pack_forget()
            self.start_all_btn.configure(text="▶")
            self.stop_all_btn.configure(text="■")
            self.settings_btn.configure(text="⚙")
            self.start_all_btn.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=(0, 4), ipady=2)
            self.stop_all_btn.grid(row=1, column=0, columnspan=2, sticky="ew", padx=0, pady=0, ipady=2)
        else:
            # ทำความสะอาดก่อน repack เสมอเพื่อป้องกัน duplicate pack
            self.brand_title.pack_forget()
            self.brand_mark.pack_forget()
            self.brand_subtitle.pack_forget()
            # เรียงลำดับให้ถูก: mark (ซ้าย) → brand_copy (text+subtitle)
            self.brand_mark.pack(side=tk.LEFT, anchor="n", padx=(0, 10))
            self.brand_title.configure(text="COOKIE RUN", font=theme.FONT_BRAND)
            self.brand_title.pack(anchor="w")
            self.brand_subtitle.pack(anchor="w", pady=(1, 0))
            self.nav_section_label.pack(fill=tk.X, padx=8, pady=(0, 6), before=self.nav_buttons["home"])
            self.ports_label.pack(fill=tk.X, padx=8, pady=(18, 6))
            self.bottom_caption.pack(fill=tk.X, pady=(0, 7), before=self.bottom_row1)
            self.start_all_btn.configure(text="เริ่มทั้งหมด")
            self.stop_all_btn.configure(text="หยุดทั้งหมด")
            self.settings_btn.configure(text="ตั้งค่าแอปพลิเคชัน")
            self.start_all_btn.grid(row=0, column=0, columnspan=1, sticky="ew", padx=(0, 4), pady=0, ipady=2)
            self.stop_all_btn.grid(row=0, column=1, columnspan=1, sticky="ew", padx=(4, 0), pady=0, ipady=2)

        for button in self.nav_buttons.values():
            button.set_collapsed(collapsed)

    # ------------------------------------------------------------------
    # Navigation and port lifecycle
    # ------------------------------------------------------------------
    def get_port_key(self, device_id):
        return device_id.replace(":", "_").replace(".", "_")

    def show_page(self, page_key):
        page = self.pages.get(page_key)
        if not page:
            return
        page.tkraise()
        self.current_page = page_key
        for key, button in self.nav_buttons.items():
            button.set_selected(key == page_key)

    def _create_port_page(self, pdata):
        device_id = pdata.get("device_id")
        if not device_id:
            return
        key = self.get_port_key(device_id)
        if key in self.pages:
            return
        page = PortWorkspacePage(self.container, self, pdata)
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = page

        name = pdata.get("nickname", device_id)
        nav_btn = NavButton(
            self.nav_body, name, "▣", command=lambda item=key: self.show_page(item),
            on_remove=lambda device=device_id: self.remove_port(device),
        )
        nav_btn.pack(fill=tk.X, pady=2)
        self.nav_buttons[key] = nav_btn

    def add_port(self, raw_port, nickname=""):
        device_id = raw_port.strip()
        if not device_id:
            messagebox.showwarning("ต้องระบุพอร์ต", "กรุณากรอกพอร์ตหรือ Device ID ก่อน")
            return False

        if ":" not in device_id and not device_id.startswith("emulator-"):
            device_id = f"127.0.0.1:{device_id}"

        key = self.get_port_key(device_id)
        if key in self.saved_ports:
            messagebox.showinfo("มีอุปกรณ์นี้แล้ว", f"พอร์ต {device_id} ถูกเพิ่มไว้แล้ว")
            self.show_page(key)
            return True

        connected = adb_connect(device_id)
        if not connected:
            save_anyway = messagebox.askyesno(
                "เชื่อมต่อไม่สำเร็จ",
                f"เชื่อมต่อ ADB ไปที่ {device_id} ไม่สำเร็จ\n"
                "ตรวจสอบว่าเปิด MuMu Player แล้วหรือยัง\n\n"
                "ต้องการบันทึกพอร์ตนี้ไว้ก่อนหรือไม่?",
            )
            if not save_anyway:
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

        instance = self.instances.get(device_id)
        if instance:
            try:
                instance.stop_bot()
            except Exception:
                pass
            del self.instances[device_id]

        if key in self.pages:
            self.pages[key].destroy()
            del self.pages[key]
        if key in self.nav_buttons:
            self.nav_buttons[key].destroy()
            del self.nav_buttons[key]
        self.show_page("home")

    # ------------------------------------------------------------------
    # Global actions
    # ------------------------------------------------------------------
    def _start_all(self):
        for key, page in list(self.pages.items()):
            if key != "home" and hasattr(page, "start_bot_action"):
                page.start_bot_action()

    def _stop_all(self):
        for _device_id, instance in list(self.instances.items()):
            try:
                if instance.running:
                    instance.stop_bot()
            except Exception:
                pass

    def _open_settings(self):
        SettingsWindow(self.root)


def run_gui():
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "cookierunbot.gui.multiinstance.v4"
            )
        except Exception:
            pass
    root = ttk.Window(themename=theme.THEME_NAME)
    CookieBotGUI(root)
    root.mainloop()
