from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as ttk

import src.config.settings as config
from src.config.secrets import get_discord_webhooks
from src.ui import theme


class PortSettingsDialog(tk.Toplevel):
    """Per-instance preferences with a clearly separated save action."""

    def __init__(self, parent, app, device_id):
        super().__init__(parent)
        self.app = app
        self.device_id = device_id
        self.key = self.app.get_port_key(device_id)
        self.pdata = self.app.saved_ports.get(self.key, {})
        self.nickname = self.pdata.get("nickname", self.device_id)

        self.title(f"ตั้งค่าอุปกรณ์ — {self.nickname}")
        self.geometry("700x730")
        self.minsize(600, 620)
        self.resizable(True, True)
        self.grab_set()
        theme.apply_window_chrome(self)
        theme.enable_acrylic(self)

        self.port_settings = config.get_port_settings(self.pdata)
        self.vars = {}
        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self, padding=theme.PAD)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=tk.X, pady=(0, 18))
        copy = ttk.Frame(header)
        copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.make_eyebrow(copy, "การตั้งค่ารายอุปกรณ์", color=theme.ACCENT_GOLD).pack(anchor=tk.W)
        title_row = ttk.Frame(copy)
        title_row.pack(fill=tk.X, pady=(4, 4))
        ttk.Label(title_row, text=self.nickname, font=theme.FONT_H1).pack(side=tk.LEFT)
        theme.device_chip(title_row, self.device_id).pack(side=tk.LEFT, padx=(10, 0), pady=(3, 0))
        ttk.Label(
            copy,
            text="การเปลี่ยนแปลงชุดนี้ใช้กับอินสแตนซ์ปัจจุบันเท่านั้น",
            font=theme.FONT_SUBTITLE,
            bootstyle="secondary",
        ).pack(anchor=tk.W)

        notebook = ttk.Notebook(container, bootstyle="primary")
        notebook.pack(fill=tk.BOTH, expand=True)
        tab_behavior = ttk.Frame(notebook, padding=20)
        tab_report = ttk.Frame(notebook, padding=20)
        notebook.add(tab_behavior, text="พฤติกรรมบอท")
        notebook.add(tab_report, text="รายงาน Discord")
        self._build_behavior_tab(tab_behavior)
        self._build_report_tab(tab_report)

        footer = tk.Frame(container, bg=theme.APP_BG)
        footer.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(footer, text="ยกเลิก", bootstyle="secondary-outline", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(
            footer,
            text="บันทึกการตั้งค่า",
            bootstyle="success",
            command=self._save_settings,
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def _build_behavior_tab(self, parent):
        # A single device can expose many controls.  Keep the notebook footer
        # fixed while letting this content area scroll on compact displays.
        scroller = theme.ScrollableFrame(parent, bootstyle="dark", bg=theme.APP_BG)
        scroller.pack(fill=tk.BOTH, expand=True)
        content = scroller.body
        theme.make_eyebrow(content, "เฉพาะอินสแตนซ์นี้", color=theme.ACCENT_CYAN).pack(anchor=tk.W)
        ttk.Label(content, text="สวิตช์ควบคุมระบบบอท", font=theme.FONT_H2).pack(anchor=tk.W, pady=(4, 3))
        ttk.Label(
            content,
            text="เลือกความสามารถที่ควรเปิดใช้สำหรับอุปกรณ์นี้ โดยไม่กระทบอุปกรณ์อื่น",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(0, 14))

        groups = [
            (
                "การเล่นเกม",
                [
                    ("ENABLE_BOOSTER_BUY", "ซื้อไอเทมเพิ่มพลัง", "เลือกซื้อ Booster เมื่อเงื่อนไขเหมาะสม"),
                    ("ENABLE_FAST_START_BOOST", "เร่งเริ่มต้น", "กดเร็วขึ้นในช่วงเริ่มรอบ"),
                    ("ENABLE_USE_SECOND_COOKIE", "ใช้คุกกี้ตัวที่สอง", "เปิดใช้ความสามารถเสริมเมื่อพร้อม"),
                    ("ENABLE_RANDOM_TAP_WHILE_WAIT", "สุ่มกดระหว่างรอ", "ช่วยจัดการช่วง over_game"),
                ],
            ),
            (
                "แจ้งเตือนและอัตโนมัติ",
                [
                    ("ENABLE_LINE_NOTIFY", "แจ้งเตือน LINE", "ส่งข้อความเมื่อเกิดเหตุการณ์สำคัญ"),
                    ("DISCORD_REPORT_ENABLED", "รายงาน Discord", "ส่งผลลัพธ์ผ่าน Webhook ที่เลือก"),
                    ("OCR_SCORE_ENABLED", "อ่านคะแนนด้วย OCR", "ใช้ Gemini OCR เพื่ออ่านคะแนน"),
                    ("SCHEDULE_ENABLED", "ตารางเวลาทำงาน", "เปิดพฤติกรรมตามกำหนดการ"),
                ],
            ),
        ]
        for title, controls in groups:
            card = theme.GlassCard(content, accent=theme.BORDER, padding=14)
            card.pack(fill=tk.X, pady=5)
            ttk.Label(card.body, text=title, font=theme.FONT_H3).pack(anchor=tk.W, pady=(0, 6))
            for attr, label, hint in controls:
                self._build_toggle(card.body, attr, label, hint)
        # --- ส่ง/รับหัวใจอัตโนมัติประจำพอร์ต ---
        heart_card = theme.GlassCard(content, accent="#FF6B9D", padding=14)
        heart_card.pack(fill=tk.X, pady=5)
        body_h = heart_card.body
        ttk.Label(body_h, text="💌 ส่ง/รับหัวใจอัตโนมัติประจำพอร์ต", font=theme.FONT_H3).pack(anchor=tk.W, pady=(0, 8))
        self._build_toggle(body_h, "HEART_AUTO_ENABLED", "เปิดระบบส่งหัวใจ", "ส่ง/รับหัวใจให้อัตโนมัติสำหรับพอร์ตนี้เฉพาะ")

        interval_row = ttk.Frame(body_h, padding=(0, 7))
        interval_row.pack(fill=tk.X)
        copy_h = ttk.Frame(interval_row)
        copy_h.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(copy_h, text="รอบเวลาส่งหัวใจ (นาที)", font=theme.FONT_BODY_BOLD).pack(anchor=tk.W)
        ttk.Label(copy_h, text="ส่งหัวใจทุกๆ N นาที (เฉพาะพอร์ตนี้)", font=theme.FONT_SMALL, bootstyle="secondary").pack(anchor=tk.W, pady=(1, 0))
        self.heart_interval_var = tk.IntVar(value=int(self.port_settings.get("HEART_INTERVAL_MINUTES", 30)))
        spin = ttk.Spinbox(
            interval_row,
            from_=5, to=240, increment=5,
            textvariable=self.heart_interval_var,
            width=6,
        )
        spin.pack(side=tk.RIGHT, padx=(8, 0))

        btn_row = ttk.Frame(body_h, padding=(0, 7))
        btn_row.pack(fill=tk.X)
        ttk.Button(
            btn_row,
            text="🧪 บังคับส่งหัวใจในรอบถัดไปทันที",
            bootstyle="pink-outline",
            command=self._trigger_test_heart,
        ).pack(anchor=tk.W)

        # --- แลกเปลี่ยน Relic อัตโนมัติประจำพอร์ต ---
        relic_card = theme.GlassCard(content, accent="#C9A227", padding=14)
        relic_card.pack(fill=tk.X, pady=5)
        body_r = relic_card.body
        ttk.Label(body_r, text="🏛️ แลกเปลี่ยน Relic อัตโนมัติประจำพอร์ต", font=theme.FONT_H3).pack(anchor=tk.W, pady=(0, 8))
        self._build_toggle(body_r, "RELIC_EXCHANGE_ENABLED", "เปิดระบบแลก Relic", "ครบ N รอบจะเข้าไปเช็กและแลก Relic ให้อัตโนมัติ")

        relic_interval_row = ttk.Frame(body_r, padding=(0, 7))
        relic_interval_row.pack(fill=tk.X)
        copy_r = ttk.Frame(relic_interval_row)
        copy_r.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(copy_r, text="รอบการเช็ก Relic (รอบ)", font=theme.FONT_BODY_BOLD).pack(anchor=tk.W)
        ttk.Label(copy_r, text="แลก Relic ทุกๆ N รอบที่เล่นผ่าน (เฉพาะพอร์ตนี้)", font=theme.FONT_SMALL, bootstyle="secondary").pack(anchor=tk.W, pady=(1, 0))
        self.relic_interval_var = tk.IntVar(value=int(self.port_settings.get("RELIC_EXCHANGE_EVERY_N_RUNS", 10)))
        relic_spin = ttk.Spinbox(
            relic_interval_row,
            from_=1, to=50, increment=1,
            textvariable=self.relic_interval_var,
            width=6,
        )
        relic_spin.pack(side=tk.RIGHT, padx=(8, 0))

        relic_btn_row = ttk.Frame(body_r, padding=(0, 7))
        relic_btn_row.pack(fill=tk.X)
        ttk.Button(
            relic_btn_row,
            text="🧪 บังคับเช็ก Relic ในรอบถัดไปทันที",
            bootstyle="warning-outline",
            command=self._trigger_test_relic,
        ).pack(anchor=tk.W)


    def _build_toggle(self, parent, attr, label, hint):
        row = ttk.Frame(parent, padding=(0, 7))
        row.pack(fill=tk.X)
        current = self.port_settings.get(attr, True)
        variable = tk.BooleanVar(value=bool(current))
        self.vars[attr] = variable
        ttk.Checkbutton(row, variable=variable, bootstyle="success-round-toggle").pack(side=tk.LEFT, padx=(0, 9))
        copy = ttk.Frame(row)
        copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(copy, text=label, font=theme.FONT_BODY_BOLD).pack(anchor=tk.W)
        ttk.Label(copy, text=hint, font=theme.FONT_SMALL, bootstyle="secondary").pack(anchor=tk.W, pady=(1, 0))

    def _build_report_tab(self, parent):
        theme.make_eyebrow(parent, "การแจ้งเตือน", color=theme.ACCENT_CYAN).pack(anchor=tk.W)
        ttk.Label(parent, text="Discord Webhook", font=theme.FONT_H2).pack(anchor=tk.W, pady=(4, 3))
        ttk.Label(
            parent,
            text="เลือกปลายทางสำหรับรายงานของอินสแตนซ์นี้",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(0, 16))

        card = theme.GlassCard(parent, accent=theme.ACCENT_CYAN, padding=18)
        card.pack(fill=tk.X)
        body = card.body
        ttk.Label(body, text="โปรไฟล์ Webhook", font=theme.FONT_H3).pack(anchor=tk.W)
        ttk.Label(
            body,
            text="เลือก [ทั้งหมด] เพื่อส่งไปยังทุกโปรไฟล์ที่เปิดใช้งาน หรือ [ปิด] เพื่อไม่ส่งรายงาน",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(3, 12))

        webhooks = get_discord_webhooks()
        options = ["[ALL] ส่งทุก Webhook ที่เปิดใช้งาน", "[NONE] ปิดใช้งาน"]
        options.extend(webhook["name"] for webhook in webhooks if isinstance(webhook, dict) and webhook.get("name"))
        selected = self.port_settings.get("SELECTED_DISCORD_WEBHOOK", options[0])
        if selected not in options:
            selected = options[0]
        self.wh_var = tk.StringVar(value=selected)
        ttk.Combobox(
            body,
            textvariable=self.wh_var,
            values=options,
            state="readonly",
            font=theme.FONT_BODY,
            bootstyle="info",
        ).pack(fill=tk.X)

        note = tk.Label(
            parent,
            text="ต้องการเพิ่มหรือแก้ไข Webhook Profile ให้ไปที่ ตั้งค่าแอปพลิเคชัน › Discord",
            bg=theme.SURFACE_MUTED,
            fg=theme.TEXT_MUTED,
            font=theme.FONT_SMALL,
            anchor="w",
            padx=12,
            pady=10,
        )
        note.pack(fill=tk.X, pady=(14, 0))

    def _trigger_test_heart(self):
        instance = self.app.instances.get(self.device_id)
        if not instance or not instance.running:
            messagebox.showwarning("บอทไม่ได้เปิดรัน", "กรุณากดเปิดทำงานบอทของพอร์ตนี้ก่อนกดทดสอบ")
            return
        instance.heart_mgr._last_heart_time = 0
        instance.log_info("🧪 [Test] ตั้งค่าบังคับส่งหัวใจเรียบร้อย! บอทจะเริ่มส่งหัวใจทันทีที่กลับมาหน้าหลัก (start_game)")
        messagebox.showinfo("ตั้งค่าสำเร็จ", "ตั้งค่าสำเร็จแล้ว! บอทพอร์ตนี้จะสลับไปส่งหัวใจทันทีเมื่อพบบอทอยู่หน้าหลัก")

    def _trigger_test_relic(self):
        instance = self.app.instances.get(self.device_id)
        if not instance or not instance.running:
            messagebox.showwarning("บอทไม่ได้เปิดรัน", "กรุณากดเปิดทำงานบอทของพอร์ตนี้ก่อนกดทดสอบ")
            return
        instance.relic_mgr._relic_counter = 999
        instance.log_info("🧪 [Test] ตั้งค่าบังคับเช็ก Relic เรียบร้อย! บอทจะเช็กแลก Relic ทันทีที่กลับมาหน้าหลัก (start_game)")
        messagebox.showinfo("ตั้งค่าสำเร็จ", "ตั้งค่าสำเร็จแล้ว! บอทพอร์ตนี้จะสลับไปเช็กแลก Relic ทันทีเมื่อพบบอทอยู่หน้าหลัก")

    def _save_settings(self):
        new_settings = {attr: var.get() for attr, var in self.vars.items()}
        new_settings["SELECTED_DISCORD_WEBHOOK"] = self.wh_var.get()
        new_settings["HEART_INTERVAL_MINUTES"] = self.heart_interval_var.get()
        new_settings["RELIC_EXCHANGE_EVERY_N_RUNS"] = self.relic_interval_var.get()
        if self.key in self.app.saved_ports:
            self.app.saved_ports[self.key]["settings"] = new_settings
            config.save_saved_ports(self.app.saved_ports)

        instance = self.app.instances.get(self.device_id)
        if instance:
            instance.update_settings(new_settings)

        messagebox.showinfo("บันทึกสำเร็จ", f"บันทึกการตั้งค่าสำหรับ “{self.nickname}” เรียบร้อยแล้ว")
        self.destroy()
