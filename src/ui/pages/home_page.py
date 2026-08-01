from __future__ import annotations

from typing import Optional
import tkinter as tk

import ttkbootstrap as ttk

from src.ui import theme


CARD_MIN_WIDTH = 240
MAX_GRID_COLUMNS = 4


class HomePage(ttk.Frame):
    """Overview dashboard for all emulator instances."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._content: Optional[ttk.Frame] = None
        self._welcome_entry: Optional[ttk.Entry] = None
        self._scroller: Optional[ttk.Frame] = None
        self._grid: Optional[ttk.Frame] = None
        self._current_columns = None
        # refs ของ widget แต่ละ card สำหรับอัปเดต in-place
        self._card_widgets: dict = {}
        self._header_chip: Optional[tk.Label] = None
        self._summary_tiles: list = []
        self.refresh()
        self._reflow_debounced = theme.debounce(self, theme.RESIZE_DEBOUNCE_MS, self._reflow_grid)
        self.bind("<Configure>", self._on_configure)

    def refresh(self):
        if self._content:
            self._content.destroy()
        self._content = ttk.Frame(self, padding=theme.PAD)
        self._content.pack(fill=tk.BOTH, expand=True)
        self._scroller = None
        self._grid = None
        self._current_columns = None
        self._card_widgets = {}
        self._header_chip = None
        self._summary_tiles = []

        if not self.app.saved_ports:
            self._build_welcome()
        else:
            self._build_dashboard()

    def update_stats(self):
        """อัปเดต UI ทั้งหน้า dashboard แบบ in-place ทุก 1 วินาที ไม่ rebuild widgets"""
        # อัปเดต header chip
        if self._header_chip:
            try:
                total, running, _r, _s = self._stats()
                self._header_chip.configure(
                    text=f"{running} กำลังทำงาน  /  {total} อุปกรณ์",
                    bg=theme.SUCCESS_SOFT if running else "#282D46",
                    fg="#A4F4CE" if running else "#CCD3EA",
                )
            except Exception:
                pass

        # อัปเดต summary strip tiles
        if self._summary_tiles:
            try:
                total, running, runs, success = self._stats()
                rate = round((success / runs) * 100, 1) if runs else 0.0
                values = [str(total), str(running), f"{rate}%"]
                for tile, val in zip(self._summary_tiles, values):
                    tile.set_value(val)
            except Exception:
                pass

        # อัปเดต device card แต่ละใบ in-place
        for device_id, refs in list(self._card_widgets.items()):
            try:
                if not refs["card"].winfo_exists():
                    continue
                instance = self.app.instances.get(device_id)
                running = bool(getattr(instance, "running", False)) if instance else False

                # อัปเดต status badge ทุก tick
                if running:
                    refs["status_badge"].configure(
                        text="\u25cf  กำลังทำงาน", bg=theme.SUCCESS_SOFT, fg="#A4F4CE"
                    )
                else:
                    refs["status_badge"].configure(
                        text="\u25cb  หยุดทำงาน", bg="#282D46", fg="#CCD3EA"
                    )

                # อัปเดต card accent และปุ่มเมื่อ running state เปลี่ยน
                if running != refs["_was_running"]:
                    refs["_was_running"] = running
                    refs["card"]._accent = theme.SUCCESS if running else theme.PRIMARY
                    refs["card"]._draw()
                    if running:
                        refs["action_btn"].configure(
                            text="หยุดบอท", bootstyle="danger-outline",
                            command=lambda d=device_id: self._quick_stop(d),
                        )
                    else:
                        refs["action_btn"].configure(
                            text="เริ่มบอท", bootstyle="success",
                            command=lambda d=device_id: self._quick_start(d),
                        )

                # อัปเดต metrics ทุก tick
                session = getattr(instance, "session_stats", {}) if instance else {}
                total_runs = session.get("total_runs", 0)
                successful = session.get("successful_runs", 0)
                rate = round((successful / total_runs) * 100, 1) if total_runs else 0
                refs["runs_lbl"].configure(text=f"{total_runs:,}")
                refs["rate_lbl"].configure(text=f"{rate}%")
            except Exception:
                pass

    def _on_configure(self, event):
        if event.widget is self:
            self._reflow_debounced()

    # ------------------------------------------------------------------
    # First-run view
    # ------------------------------------------------------------------
    def _build_welcome(self):
        shell = ttk.Frame(self._content)
        shell.place(relx=0.5, rely=0.46, anchor=tk.CENTER)

        icon = tk.Label(
            shell,
            text="🍪",
            bg=theme.APP_BG,
            fg=theme.ACCENT_GOLD,
            font=("Segoe UI Emoji", 54),
        )
        icon.pack(pady=(0, 4))
        ttk.Label(shell, text="ยินดีต้อนรับสู่ Cookie Run Bot", font=theme.FONT_H1).pack()
        ttk.Label(
            shell,
            text="เพิ่มพอร์ต ADB ของ MuMu Player เพื่อเริ่มต้นใช้งาน",
            font=theme.FONT_SUBTITLE,
            bootstyle="secondary",
        ).pack(pady=(6, 24))

        card = theme.GlassCard(shell, accent=theme.ACCENT_CYAN, padding=20)
        card.pack()
        body = card.body

        ttk.Label(body, text="เพิ่มอุปกรณ์แรกของคุณ", font=theme.FONT_H2).pack(anchor=tk.W, pady=(0, 10))
        row = ttk.Frame(body)
        row.pack(pady=(0, 4))
        ttk.Label(row, text="Device / Port:", font=theme.FONT_BODY_BOLD).pack(side=tk.LEFT, padx=(0, 8))
        self._welcome_entry = ttk.Entry(row, width=20, font=theme.FONT_MONO)
        self._welcome_entry.pack(side=tk.LEFT)
        self._welcome_entry.bind("<Return>", lambda _event: self._on_add_welcome())
        self._welcome_entry.focus_set()

        ttk.Button(
            body,
            text="เพิ่มอุปกรณ์และเริ่มใช้งาน",
            bootstyle="primary",
            command=self._on_add_welcome,
        ).pack(pady=(16, 8), fill=tk.X)
        ttk.Label(
            body,
            text="ตัวอย่าง: 7555  ·  16384  ·  127.0.0.1:5559",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack()

    def focus_add_input(self):
        if self._welcome_entry:
            self._welcome_entry.focus_set()

    def _on_add_welcome(self):
        if self._welcome_entry is None:
            return
        port = self._welcome_entry.get().strip()
        if port:
            self.app.add_port(port)

    # ------------------------------------------------------------------
    # Populated dashboard
    # ------------------------------------------------------------------
    def _build_dashboard(self):
        self._build_header()
        self._build_summary_strip()
        section = ttk.Frame(self._content)
        section.pack(fill=tk.X, pady=(24, 10))
        copy = ttk.Frame(section)
        copy.pack(side=tk.LEFT)
        theme.make_eyebrow(copy, "อินสแตนซ์", color=theme.ACCENT_CYAN).pack(anchor=tk.W)
        ttk.Label(copy, text="อุปกรณ์ของคุณ", font=theme.FONT_H2).pack(anchor=tk.W, pady=(2, 0))
        ttk.Button(
            section,
            text="+ เพิ่มอุปกรณ์",
            bootstyle="primary-outline",
            command=self._focus_add_card,
        ).pack(side=tk.RIGHT, pady=(8, 0))

        # Keep the add-device card reachable when a compact window pushes it
        # onto a second row.  The custom scroll frame only shows a scrollbar
        # when content actually exceeds the available vertical space.
        self._scroller = theme.ScrollableFrame(self._content, bootstyle="dark", bg=theme.APP_BG)
        self._scroller.pack(fill=tk.BOTH, expand=True)
        self._grid = self._scroller.body
        self._reflow_grid(force=True)

    def _build_header(self):
        header = ttk.Frame(self._content)
        header.pack(fill=tk.X)
        copy = ttk.Frame(header)
        copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.make_eyebrow(copy, "ศูนย์ควบคุม", color=theme.ACCENT_GOLD).pack(anchor=tk.W)
        ttk.Label(copy, text="ภาพรวมการทำงาน", font=theme.FONT_H1).pack(anchor=tk.W, pady=(4, 3))
        ttk.Label(
            copy,
            text="ติดตามสถานะและจัดการทุกอินสแตนซ์จากพื้นที่ทำงานเดียว",
            font=theme.FONT_SUBTITLE,
            bootstyle="secondary",
        ).pack(anchor=tk.W)

        total, running, _runs, _success = self._stats()
        chip = tk.Label(
            header,
            text=f"{running} กำลังทำงาน  /  {total} อุปกรณ์",
            bg=theme.SUCCESS_SOFT if running else "#282D46",
            fg="#A4F4CE" if running else "#CCD3EA",
            font=theme.FONT_BODY_BOLD,
            padx=13,
            pady=7,
        )
        chip.pack(side=tk.RIGHT, anchor="n", pady=(12, 0))
        self._header_chip = chip  # เก็บ ref สำหรับ update_stats()

    def _build_summary_strip(self):
        total, running, runs, success = self._stats()
        success_rate = round((success / runs) * 100, 1) if runs else 0.0
        strip = ttk.Frame(self._content)
        strip.pack(fill=tk.X, pady=(22, 0))
        for index in range(3):
            strip.columnconfigure(index, weight=1, uniform="overview")

        values = [
            ("\u25a3", str(total), "อุปกรณ์ที่บันทึก", "primary"),
            ("\u25cf", str(running), "กำลังทำงาน", "success"),
            ("\u2197", f"{success_rate}%", "อัตราสำเร็จรวม", "info"),
        ]
        self._summary_tiles = []
        for index, (icon, value, label, style) in enumerate(values):
            tile = theme.StatTile(strip, icon, label, value, bootstyle=style)
            tile.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 0 if index == 2 else 5))
            self._summary_tiles.append(tile)  # เก็บ ref สำหรับ update_stats()

    def _stats(self):
        total = len(self.app.saved_ports)
        running = 0
        total_runs = 0
        successful_runs = 0
        for pdata in self.app.saved_ports.values():
            instance = self.app.instances.get(pdata["device_id"])
            if not instance:
                continue
            running += int(bool(getattr(instance, "running", False)))
            session = getattr(instance, "session_stats", {}) or {}
            total_runs += session.get("total_runs", 0)
            successful_runs += session.get("successful_runs", 0)
        return total, running, total_runs, successful_runs

    def _reflow_grid(self, force=False):
        if self._grid is None or not self._grid.winfo_exists():
            return
        # คำนวณ columns จากความกว้างจริง ไม่ hardcode
        available_width = self._scroller.winfo_width() or self.winfo_width()
        columns = theme.columns_for_width(
            available_width, CARD_MIN_WIDTH, minimum=2, maximum=2
        )
        if not force and columns == self._current_columns:
            return
        self._current_columns = columns

        for index in range(columns):
            self._grid.columnconfigure(index, weight=1, uniform="device-card")
        # ล้าง column config เก่าที่เกิน
        for index in range(columns, MAX_GRID_COLUMNS + 1):
            self._grid.columnconfigure(index, weight=0)

        children = self._grid.winfo_children()
        # If the number of widgets doesn't match total ports + 1 (add card), rebuild once
        expected_count = len(self.app.saved_ports) + 1
        if force or len(children) != expected_count:
            for child in children:
                child.destroy()
            row = 0
            col = 0
            for _key, pdata in self.app.saved_ports.items():
                self._build_device_card(self._grid, pdata, row, col)
                col += 1
                if col >= columns:
                    col = 0
                    row += 1
            self._build_add_card(self._grid, row, col)
        else:
            # Re-position existing card widgets without destroying/recreating
            row = 0
            col = 0
            for child in children:
                child.grid_configure(row=row, column=col, padx=6, pady=6, sticky="nsew")
                col += 1
                if col >= columns:
                    col = 0
                    row += 1

    def _build_device_card(self, parent, pdata, row, col):
        device_id = pdata["device_id"]
        nickname = pdata.get("nickname", device_id)
        instance = self.app.instances.get(device_id)
        running = bool(getattr(instance, "running", False)) if instance else False
        accent = theme.SUCCESS if running else theme.PRIMARY

        card = theme.GlassCard(parent, accent=accent, padding=18)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        body = card.body

        top = ttk.Frame(body)
        top.pack(fill=tk.X)
        title = ttk.Frame(top)
        title.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title, text=nickname, font=theme.FONT_H2).pack(anchor=tk.W)
        theme.device_chip(title, device_id).pack(anchor=tk.W, pady=(7, 0))
        # เก็บ ref ของ status_badge เพื่อ configure() ใน update_stats()
        status_badge = theme.status_badge(top, running)
        status_badge.pack(side=tk.RIGHT, anchor="n")

        tk.Frame(body, bg=theme.BORDER_SOFT, height=1).pack(fill=tk.X, pady=16)

        session = getattr(instance, "session_stats", {}) if instance else {}
        total_runs = session.get("total_runs", 0)
        successful = session.get("successful_runs", 0)
        rate = round((successful / total_runs) * 100, 1) if total_runs else 0
        metrics = ttk.Frame(body)
        metrics.pack(fill=tk.X)
        metrics.columnconfigure(0, weight=1)
        metrics.columnconfigure(1, weight=1)
        runs_lbl = self._mini_metric(metrics, "รอบทั้งหมด", f"{total_runs:,}", 0)
        rate_lbl = self._mini_metric(metrics, "สำเร็จ", f"{rate}%", 1)

        actions = ttk.Frame(body)
        actions.pack(fill=tk.X, pady=(18, 0))
        key = self.app.get_port_key(device_id)
        # สร้างปุ่มเดียวและเก็บ ref ไว้ เพื่อ configure() แทนการ rebuild
        if running:
            action_btn = ttk.Button(
                actions, text="หยุดบอท", bootstyle="danger-outline",
                command=lambda device=device_id: self._quick_stop(device),
            )
        else:
            action_btn = ttk.Button(
                actions, text="เริ่มบอท", bootstyle="success",
                command=lambda device=device_id: self._quick_start(device),
            )
        action_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(
            actions, text="จัดการ", bootstyle="secondary-outline",
            command=lambda page_key=key: self.app.show_page(page_key),
        ).pack(side=tk.LEFT, padx=(4, 0))

        # บันทึก refs ทั้งหมดสำหรับ in-place update
        self._card_widgets[device_id] = {
            "card": card,
            "status_badge": status_badge,
            "action_btn": action_btn,
            "runs_lbl": runs_lbl,
            "rate_lbl": rate_lbl,
            "_was_running": running,
        }

    def _mini_metric(self, parent, label, value, column) -> ttk.Label:
        """สร้าง metric box และคืน value label สำหรับ in-place update"""
        box = ttk.Frame(parent)
        box.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 7, 7 if column == 0 else 0))
        value_lbl = ttk.Label(box, text=value, font=theme.FONT_H3)
        value_lbl.pack(anchor=tk.W)
        ttk.Label(box, text=label.upper(), font=theme.FONT_STAT_LABEL, bootstyle="secondary").pack(anchor=tk.W, pady=(1, 0))
        return value_lbl

    def _build_add_card(self, parent, row, col):
        card = theme.GlassCard(parent, accent=theme.ACCENT_GOLD, padding=18)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        body = card.body
        theme.make_eyebrow(body, "ใหม่", color=theme.ACCENT_GOLD).pack(anchor=tk.W)
        ttk.Label(body, text="เพิ่มอุปกรณ์", font=theme.FONT_H2).pack(anchor=tk.W, pady=(5, 3))
        ttk.Label(
            body,
            text="เชื่อมต่อ MuMu Player อีกหนึ่งอินสแตนซ์",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(0, 13))

        entry = ttk.Entry(body, font=theme.FONT_MONO)
        entry.pack(fill=tk.X)
        entry.insert(0, "Port / Device ID")
        entry.bind("<FocusIn>", lambda _event: self._clear_placeholder(entry, "Port / Device ID"))
        nickname = ttk.Entry(body, font=theme.FONT_BODY)
        nickname.pack(fill=tk.X, pady=(8, 0))
        nickname.insert(0, "ชื่อเรียก (ไม่บังคับ)")
        nickname.bind("<FocusIn>", lambda _event: self._clear_placeholder(nickname, "ชื่อเรียก (ไม่บังคับ)"))

        ttk.Button(
            body,
            text="เชื่อมต่ออุปกรณ์",
            bootstyle="primary-outline",
            command=lambda: self._add_from_card(entry, nickname),
        ).pack(fill=tk.X, pady=(12, 0))
        entry.bind("<Return>", lambda _event: self._add_from_card(entry, nickname))
        entry._add_field = True

    def _clear_placeholder(self, entry, placeholder):
        if entry.get() == placeholder:
            entry.delete(0, tk.END)

    def _add_from_card(self, port_entry, nickname_entry):
        port = port_entry.get().strip()
        nickname = nickname_entry.get().strip()
        if port == "Port / Device ID":
            port = ""
        if nickname == "ชื่อเรียก (ไม่บังคับ)":
            nickname = ""
        if self.app.add_port(port, nickname):
            self.refresh()

    def _focus_add_card(self):
        if self._grid:
            for child in self._grid.winfo_children():
                # The add card is the only card that contains this private marker.
                for descendant in self._descendants(child):
                    if getattr(descendant, "_add_field", False):
                        descendant.focus_set()
                        return

    def _descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._descendants(child)

    def _quick_start(self, device_id):
        key = self.app.get_port_key(device_id)
        if key in self.app.pages:
            self.app.pages[key].start_bot_action()
        # ไม่เรียก refresh() — update_stats() จะอัปเดต UI ให้อัตโนมัติทุก 1 วินาที

    def _quick_stop(self, device_id):
        instance = self.app.instances.get(device_id)
        if instance:
            try:
                instance.stop_bot()
            except Exception:
                pass
        # ไม่เรียก refresh() — update_stats() จะอัปเดต UI ให้อัตโนมัติทุก 1 วินาที
