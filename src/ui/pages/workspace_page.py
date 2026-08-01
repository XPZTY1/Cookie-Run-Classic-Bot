from __future__ import annotations

import threading
import time as _time
import tkinter as tk
from tkinter import scrolledtext

import ttkbootstrap as ttk

import src.config.settings as config
from src.core.bot_instance import BotInstance
from src.ui import theme
from src.ui.theme import StatTile
from src.ui.dialogs.port_settings import PortSettingsDialog


TILE_MIN_WIDTH = 178
MAX_TILE_COLUMNS = 4


class PortWorkspacePage(ttk.Frame):
    """Dedicated operations dashboard for a single emulator instance."""

    def __init__(self, parent, app, pdata):
        super().__init__(parent)
        self.app = app
        self.device_id = pdata["device_id"]
        self.nickname = pdata.get("nickname", self.device_id)
        self._tiles = {}
        self._tile_defs = []
        self._stats_frame = None
        self._current_tile_columns = None
        self._is_running = False
        self._setup_ui()

        self._reflow_debounced = theme.debounce(self, theme.RESIZE_DEBOUNCE_MS, self._reflow_tiles)
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        if event.widget is self:
            self._reflow_debounced()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _setup_ui(self):
        content = ttk.Frame(self, padding=theme.PAD)
        content.pack(fill=tk.BOTH, expand=True)

        self._build_header(content)
        self._build_action_bar(content)
        self._build_stats_section(content)
        self._build_log_section(content)

    def _build_header(self, parent):
        header = ttk.Frame(parent)
        header.pack(fill=tk.X)
        title = ttk.Frame(header)
        title.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.make_eyebrow(title, "พื้นที่ทำงานอุปกรณ์", color=theme.ACCENT_GOLD).pack(anchor=tk.W)
        title_row = ttk.Frame(title)
        title_row.pack(fill=tk.X, pady=(4, 5))
        ttk.Label(title_row, text=self.nickname, font=theme.FONT_H1).pack(side=tk.LEFT)
        theme.device_chip(title_row, self.device_id).pack(side=tk.LEFT, padx=(12, 0), pady=(3, 0))
        ttk.Label(
            title,
            text="ควบคุมการทำงาน ดูสถิติสด และตรวจสอบเหตุการณ์ของอินสแตนซ์นี้",
            font=theme.FONT_SUBTITLE,
            bootstyle="secondary",
        ).pack(anchor=tk.W)

        self._status_container = ttk.Frame(header)
        self._status_container.pack(side=tk.RIGHT, anchor="n", pady=(15, 0))
        self._status_lbl = theme.status_badge(self._status_container, False)
        self._status_lbl.pack()

    def _build_action_bar(self, parent):
        bar = theme.GlassCard(parent, accent=theme.PRIMARY, padding=(18, 14))
        bar.pack(fill=tk.X, pady=(22, 16))
        body = bar.body
        body.columnconfigure(0, weight=1)

        copy = ttk.Frame(body)
        copy.grid(row=0, column=0, sticky="w")
        ttk.Label(copy, text="การควบคุม", font=theme.FONT_H3).pack(anchor=tk.W)
        ttk.Label(
            copy,
            text="เริ่มหรือหยุดบอทได้ทันที การตั้งค่าไม่กระทบอินสแตนซ์อื่น",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(2, 0))

        actions = ttk.Frame(body)
        actions.grid(row=0, column=1, sticky="e")
        self._start_btn = ttk.Button(
            actions,
            text="เริ่มบอท",
            bootstyle="success",
            command=self.start_bot_action,
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._stop_btn = ttk.Button(
            actions,
            text="หยุดบอท",
            bootstyle="danger-outline",
            command=self.stop_bot_action,
        )
        self._stop_btn.pack(side=tk.LEFT, padx=6)
        ttk.Button(
            actions,
            text="ตั้งค่า",
            bootstyle="secondary-outline",
            command=self._open_port_settings,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(
            actions,
            text="ลบ",
            bootstyle="danger-outline",
            command=lambda: self.app.remove_port(self.device_id),
        ).pack(side=tk.LEFT, padx=(6, 0))

    def _build_stats_section(self, parent):
        heading = ttk.Frame(parent)
        heading.pack(fill=tk.X, pady=(0, 8))
        copy = ttk.Frame(heading)
        copy.pack(side=tk.LEFT)
        theme.make_eyebrow(copy, "ประสิทธิภาพ", color=theme.ACCENT_CYAN).pack(anchor=tk.W)
        ttk.Label(copy, text="ข้อมูลการทำงานแบบเรียลไทม์", font=theme.FONT_H2).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(
            heading,
            text="อัปเดตอัตโนมัติทุกวินาที",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(side=tk.RIGHT, pady=(14, 0))

        self._stats_frame = ttk.Frame(parent)
        self._stats_frame.pack(fill=tk.X, pady=(0, 22))
        self._tile_defs = [
            ("state", "◎", "สถานะปัจจุบัน", "—", "secondary"),
            ("runs", "↻", "รอบทั้งหมด", "0", "primary"),
            ("success", "✓", "รอบสำเร็จ", "0", "success"),
            ("rate", "↗", "อัตราสำเร็จ", "0.0%", "info"),
            ("coins", "◈", "เหรียญต่อชั่วโมง", "0", "warning"),
            ("boxes", "□", "กล่องที่ได้รับ", "0", "warning"),
            ("score", "★", "คะแนนล่าสุด", "0", "primary"),
            ("rest", "◷", "พักครั้งถัดไป", "—", "secondary"),
        ]
        self._reflow_tiles(force=True)

    def _build_log_section(self, parent):
        heading = ttk.Frame(parent)
        heading.pack(fill=tk.X, pady=(0, 8))
        copy = ttk.Frame(heading)
        copy.pack(side=tk.LEFT)
        theme.make_eyebrow(copy, "กิจกรรม", color=theme.ACCENT_GOLD).pack(anchor=tk.W)
        ttk.Label(copy, text="บันทึกการทำงาน", font=theme.FONT_H2).pack(anchor=tk.W, pady=(2, 0))
        ttk.Button(
            heading,
            text="ล้างบันทึก",
            bootstyle="secondary-outline",
            command=self._clear_log,
        ).pack(side=tk.RIGHT, pady=(8, 0))

        log_card = theme.GlassCard(parent, accent=theme.BORDER, padding=2)
        log_card.pack(fill=tk.BOTH, expand=True)
        self._log_box = scrolledtext.ScrolledText(
            log_card.body,
            height=12,
            bg=theme.LOG_BG,
            fg=theme.LOG_FG,
            insertbackground=theme.LOG_FG,
            selectbackground=theme.PRIMARY_SOFT,
            selectforeground=theme.TEXT,
            borderwidth=0,
            relief="flat",
            font=theme.FONT_MONO,
            state="disabled",
            padx=14,
            pady=12,
        )
        self._log_box.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Responsive stat grid
    # ------------------------------------------------------------------
    def _reflow_tiles(self, force=False):
        if self._stats_frame is None or not self._stats_frame.winfo_exists():
            return
        width = self._stats_frame.winfo_width() or self.winfo_width()
        columns = theme.columns_for_width(width, TILE_MIN_WIDTH, minimum=2, maximum=MAX_TILE_COLUMNS)
        if not force and columns == self._current_tile_columns:
            return
        self._current_tile_columns = columns

        old_values = {
            key: tile.get_value()
            for key, tile in self._tiles.items()
            if hasattr(tile, "get_value")
        }
        for child in self._stats_frame.winfo_children():
            child.destroy()
        for column in range(columns):
            self._stats_frame.columnconfigure(column, weight=1, uniform="stat-tile")
        self._tiles = {}

        for index, (key, icon, label, default, style) in enumerate(self._tile_defs):
            value = old_values.get(key, default)
            tile = StatTile(self._stats_frame, icon, label, value, bootstyle=style)
            tile.grid(
                row=index // columns,
                column=index % columns,
                padx=(0 if index % columns == 0 else 5, 0 if index % columns == columns - 1 else 5),
                pady=5,
                sticky="nsew",
            )
            self._tiles[key] = tile

    # ------------------------------------------------------------------
    # Actions and logs
    # ------------------------------------------------------------------
    def _open_port_settings(self):
        PortSettingsDialog(self, self.app, self.device_id)

    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", tk.END)
        self._log_box.configure(state="disabled")

    def append_log(self, message):
        def _write():
            try:
                self._log_box.configure(state="normal")
                self._log_box.insert(tk.END, message + "\n")
                self._log_box.see(tk.END)
                self._log_box.configure(state="disabled")
            except Exception:
                pass

        try:
            self.after(0, _write)
        except Exception:
            pass

    def start_bot_action(self):
        key = self.app.get_port_key(self.device_id)
        pdata = self.app.saved_ports.get(key, {})
        port_settings = config.get_port_settings(pdata)

        if self.device_id not in self.app.instances:
            self.app.instances[self.device_id] = BotInstance(
                device_id=self.device_id,
                log_callback=self.append_log,
                settings=port_settings,
            )
        else:
            instance = self.app.instances[self.device_id]
            instance.update_settings(port_settings)
            instance.set_log_callback(self.append_log)

        instance = self.app.instances[self.device_id]
        if instance.running or getattr(instance, "_thread_active", False):
            self.append_log("บอทกำลังทำงานอยู่แล้ว")
            return

        instance._thread_active = True
        self.append_log(f"กำลังเริ่มบอทบนพอร์ต {self.device_id} …")

        def _run():
            try:
                instance.start_bot()
            finally:
                instance._thread_active = False

        threading.Thread(target=_run, daemon=True).start()
        self._set_status(True)

    def stop_bot_action(self):
        instance = self.app.instances.get(self.device_id)
        if instance:
            self.append_log("ส่งสัญญาณหยุดบอท …")
            instance.stop_bot()
            instance._thread_active = False
            instance.running = False
        self._set_status(False)

    def _set_status(self, running):
        self._status_lbl.destroy()
        self._status_lbl = theme.status_badge(self._status_container, running)
        self._status_lbl.pack()
        self._is_running = bool(running)
        if running:
            self._start_btn.configure(text="กำลังทำงาน", bootstyle="success-outline")
            self._stop_btn.configure(bootstyle="danger")
        else:
            self._start_btn.configure(text="เริ่มบอท", bootstyle="success")
            self._stop_btn.configure(bootstyle="danger-outline")

    def update_stats(self):
        instance = self.app.instances.get(self.device_id)
        if not instance:
            return
        try:
            running = bool(instance.running)
            if self._is_running != running:
                self._set_status(running)

            if running:
                session = instance.session_stats
                performance = instance.get_performance_metrics()
                state = getattr(instance, "current_state", "—")
                self._tiles["state"].set_value(state)
                self._tiles["runs"].set_value(session.get("total_runs", 0))
                self._tiles["success"].set_value(session.get("successful_runs", 0))
                self._tiles["rate"].set_value(f'{performance.get("success_rate_pct", 0.0)}%')
                self._tiles["coins"].set_value(f'{performance.get("coins_per_hour", 0):,}')
                self._tiles["boxes"].set_value(performance.get("total_boxes", 0))
                self._tiles["score"].set_value(f'{session.get("last_score", 0):,}')

                next_rest = getattr(instance, "next_rest_time", None)
                if next_rest:
                    seconds_left = max(0, int(next_rest - _time.time()))
                    minutes, seconds = divmod(seconds_left, 60)
                    self._tiles["rest"].set_value(f"{minutes:02d}:{seconds:02d}")
        except Exception:
            pass
