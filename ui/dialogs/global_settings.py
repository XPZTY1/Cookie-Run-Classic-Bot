from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext

import ttkbootstrap as ttk

import config
from secrets_loader import (
    GEMINI_API_KEY,
    LINE_CHANNEL_ACCESS_TOKEN,
    LINE_USER_ID,
    get_discord_webhooks,
    save_discord_webhooks,
    save_secret,
)
from notifiers.discord_notifier import send_discord_test_to_url
from notifiers.line_notifier import send_line_message
from ui import theme


class SettingsWindow(tk.Toplevel):
    """Application settings grouped into purposeful, low-noise sections."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("ตั้งค่าแอปพลิเคชัน — Cookie Run")
        self.geometry("920x730")
        self.minsize(780, 620)
        self.resizable(True, True)
        self.grab_set()
        theme.apply_window_chrome(self)
        theme.enable_acrylic(self)
        self._build_ui()

    def _build_ui(self):
        shell = ttk.Frame(self, padding=theme.PAD)
        shell.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(shell)
        header.pack(fill=tk.X, pady=(0, 18))
        copy = ttk.Frame(header)
        copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        theme.make_eyebrow(copy, "การกำหนดค่า", color=theme.ACCENT_GOLD).pack(anchor=tk.W)
        ttk.Label(copy, text="ตั้งค่าแอปพลิเคชัน", font=theme.FONT_H1).pack(anchor=tk.W, pady=(4, 3))
        ttk.Label(
            copy,
            text="จัดการข้อมูลเชื่อมต่อ การแจ้งเตือน และพฤติกรรมเริ่มต้นของบอท",
            font=theme.FONT_SUBTITLE,
            bootstyle="secondary",
        ).pack(anchor=tk.W)
        tk.Label(
            header,
            text="การตั้งค่าแบบรวม",
            bg=theme.PRIMARY_SOFT,
            fg="#D9D3FF",
            font=theme.FONT_SMALL,
            padx=11,
            pady=6,
        ).pack(side=tk.RIGHT, anchor="n", pady=(15, 0))

        notebook = ttk.Notebook(shell, bootstyle="primary")
        notebook.pack(fill=tk.BOTH, expand=True)

        tab_api = ttk.Frame(notebook, padding=22)
        tab_discord = ttk.Frame(notebook, padding=22)
        tab_test = ttk.Frame(notebook, padding=22)
        notebook.add(tab_api, text="ข้อมูลเชื่อมต่อ")
        notebook.add(tab_discord, text="Discord")
        notebook.add(tab_test, text="ทดสอบการแจ้งเตือน")

        self._build_api_tab(tab_api)
        self._build_discord_tab(tab_discord)
        self._build_test_tab(tab_test)

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------
    def _build_api_tab(self, parent):
        scroller = theme.ScrollableFrame(parent, bootstyle="dark", bg=theme.APP_BG)
        scroller.pack(fill=tk.BOTH, expand=True)
        content = scroller.body

        theme.make_eyebrow(content, "ข้อมูลเชื่อมต่อ", color=theme.ACCENT_CYAN).pack(anchor=tk.W)
        ttk.Label(content, text="API Keys และ Tokens", font=theme.FONT_H2).pack(anchor=tk.W, pady=(4, 3))
        ttk.Label(
            content,
            text="ข้อมูลจะถูกบันทึกลงในไฟล์ .env บนเครื่องนี้โดยตรง",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(0, 16))

        fields = [
            ("LINE Channel Access Token", LINE_CHANNEL_ACCESS_TOKEN, "line_channel_access_token", "Token สำหรับส่งข้อความ LINE"),
            ("LINE User ID", LINE_USER_ID, "line_user_id", "ผู้รับการแจ้งเตือน LINE"),
            ("Gemini API Key", GEMINI_API_KEY, "gemini_api_key", "ใช้สำหรับอ่านคะแนนด้วย OCR"),
        ]
        for label, value, key, hint in fields:
            self._credential_card(content, label, value, key, hint)

        note = tk.Label(
            content,
            text="เคล็ดลับ: เก็บคีย์ไว้เป็นความลับ และสร้างคีย์ใหม่ทันทีหากสงสัยว่ารั่วไหล",
            bg=theme.SURFACE_MUTED,
            fg=theme.TEXT_MUTED,
            font=theme.FONT_SMALL,
            anchor="w",
            padx=12,
            pady=10,
        )
        note.pack(fill=tk.X, pady=(16, 0))

    def _credential_card(self, parent, label, value, key, hint):
        card = theme.GlassCard(parent, accent=theme.BORDER, padding=16)
        card.pack(fill=tk.X, pady=5)
        body = card.body
        heading = ttk.Frame(body)
        heading.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(heading, text=label, font=theme.FONT_H3).pack(side=tk.LEFT)
        ttk.Label(heading, text=hint, font=theme.FONT_SMALL, bootstyle="secondary").pack(side=tk.RIGHT)

        row = ttk.Frame(body)
        row.pack(fill=tk.X)
        var = tk.StringVar(value=value or "")
        entry = ttk.Entry(row, textvariable=var, show="•", font=theme.FONT_MONO)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        visible = tk.BooleanVar(value=False)

        def toggle_visibility():
            entry.configure(show="" if visible.get() else "•")

        ttk.Checkbutton(
            row,
            text="แสดง",
            variable=visible,
            bootstyle="secondary-round-toggle",
            command=toggle_visibility,
        ).pack(side=tk.LEFT, padx=(10, 6))
        ttk.Button(
            row,
            text="บันทึก",
            bootstyle="success-outline",
            command=lambda setting=key, field=var: self._save_key(setting, field.get()),
        ).pack(side=tk.LEFT)

    def _save_key(self, key, value):
        save_secret(key, value)
        messagebox.showinfo("บันทึกสำเร็จ", "บันทึกข้อมูลเชื่อมต่อเรียบร้อยแล้ว")

    # ------------------------------------------------------------------
    # Discord profiles
    # ------------------------------------------------------------------
    def _build_discord_tab(self, parent):
        scroller = theme.ScrollableFrame(parent, bootstyle="dark", bg=theme.APP_BG)
        scroller.pack(fill=tk.BOTH, expand=True)
        content = scroller.body

        theme.make_eyebrow(content, "การแจ้งเตือน", color=theme.ACCENT_CYAN).pack(anchor=tk.W)
        ttk.Label(content, text="Discord Webhook Profiles", font=theme.FONT_H2).pack(anchor=tk.W, pady=(4, 3))
        ttk.Label(
            content,
            text="กำหนดปลายทางสำหรับรายงานของแต่ละอุปกรณ์ แล้วเลือกใช้งานในหน้าตั้งค่าพอร์ต",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(0, 14))

        self._webhooks = get_discord_webhooks()
        self._wh_rows_frame = ttk.Frame(content)
        self._wh_rows_frame.pack(fill=tk.BOTH, expand=True)
        self._render_webhook_rows()

        add_card = theme.GlassCard(content, accent=theme.PRIMARY, padding=16)
        add_card.pack(fill=tk.X, pady=(14, 0))
        body = add_card.body
        ttk.Label(body, text="เพิ่ม Webhook ใหม่", font=theme.FONT_H3).pack(anchor=tk.W, pady=(0, 10))
        self._wh_name_var = tk.StringVar()
        self._wh_url_var = tk.StringVar()

        name_row = ttk.Frame(body)
        name_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(name_row, text="ชื่อโปรไฟล์", font=theme.FONT_SMALL, width=14).pack(side=tk.LEFT)
        ttk.Entry(name_row, textvariable=self._wh_name_var, font=theme.FONT_BODY).pack(side=tk.LEFT, fill=tk.X, expand=True)
        url_row = ttk.Frame(body)
        url_row.pack(fill=tk.X)
        ttk.Label(url_row, text="Webhook URL", font=theme.FONT_SMALL, width=14).pack(side=tk.LEFT)
        ttk.Entry(url_row, textvariable=self._wh_url_var, font=theme.FONT_MONO).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(url_row, text="เพิ่มโปรไฟล์", bootstyle="success", command=self._add_webhook).pack(side=tk.LEFT, padx=(10, 0))

    def _render_webhook_rows(self):
        for child in self._wh_rows_frame.winfo_children():
            child.destroy()
        if not self._webhooks:
            empty = theme.GlassCard(self._wh_rows_frame, accent=theme.BORDER, padding=18)
            empty.pack(fill=tk.X, pady=(0, 4))
            ttk.Label(empty.body, text="ยังไม่มี Webhook Profile", font=theme.FONT_H3).pack(anchor=tk.W)
            ttk.Label(
                empty.body,
                text="เพิ่มโปรไฟล์ด้านล่างเพื่อเริ่มต้นรับรายงานผ่าน Discord",
                font=theme.FONT_SMALL,
                bootstyle="secondary",
            ).pack(anchor=tk.W, pady=(3, 0))
            return

        for index, webhook in enumerate(self._webhooks):
            card = theme.GlassCard(self._wh_rows_frame, accent=theme.ACCENT_CYAN, padding=(14, 11))
            card.pack(fill=tk.X, pady=4)
            body = card.body
            enabled = tk.BooleanVar(value=webhook.get("enabled", True))
            ttk.Checkbutton(
                body,
                variable=enabled,
                bootstyle="success-round-toggle",
                command=lambda var=enabled, item=index: self._toggle_webhook(item, var.get()),
            ).pack(side=tk.LEFT, padx=(0, 10))

            copy = ttk.Frame(body)
            copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Label(copy, text=webhook.get("name", "ไม่มีชื่อ"), font=theme.FONT_H3).pack(anchor=tk.W)
            url = webhook.get("url", "")
            display_url = url if len(url) <= 70 else f"{url[:67]}…"
            ttk.Label(copy, text=display_url, font=theme.FONT_SMALL, bootstyle="secondary").pack(anchor=tk.W, pady=(2, 0))
            ttk.Button(
                body,
                text="ทดสอบ",
                bootstyle="info-outline",
                command=lambda url=webhook.get("url", ""), name=webhook.get("name", "Discord"): self._test_webhook(url, name),
            ).pack(side=tk.LEFT, padx=6)
            ttk.Button(
                body,
                text="ลบ",
                bootstyle="danger-outline",
                command=lambda item=index: self._del_webhook(item),
            ).pack(side=tk.LEFT)

    def _add_webhook(self):
        name = self._wh_name_var.get().strip()
        url = self._wh_url_var.get().strip()
        if not name or not url:
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกชื่อโปรไฟล์และ Webhook URL")
            return
        self._webhooks.append({"name": name, "url": url, "enabled": True})
        save_discord_webhooks(self._webhooks)
        self._wh_name_var.set("")
        self._wh_url_var.set("")
        self._render_webhook_rows()

    def _toggle_webhook(self, index, value):
        self._webhooks[index]["enabled"] = value
        save_discord_webhooks(self._webhooks)

    def _del_webhook(self, index):
        del self._webhooks[index]
        save_discord_webhooks(self._webhooks)
        self._render_webhook_rows()

    def _test_webhook(self, url, name="Discord"):
        if not url:
            return
        try:
            send_discord_test_to_url(url, name)
            messagebox.showinfo("ทดสอบสำเร็จ", f"ส่งข้อความทดสอบไปยัง “{name}” เรียบร้อยแล้ว")
        except Exception as exc:
            messagebox.showerror("ทดสอบไม่สำเร็จ", f"เกิดข้อผิดพลาด: {exc}")

    # ------------------------------------------------------------------
    # Notification tests
    # ------------------------------------------------------------------
    def _build_test_tab(self, parent):
        theme.make_eyebrow(parent, "ตรวจสอบการเชื่อมต่อ", color=theme.ACCENT_CYAN).pack(anchor=tk.W)
        ttk.Label(parent, text="ทดสอบการแจ้งเตือน", font=theme.FONT_H2).pack(anchor=tk.W, pady=(4, 3))
        ttk.Label(
            parent,
            text="ผลลัพธ์จะปรากฏด้านล่าง ตรวจสอบข้อมูลเชื่อมต่อก่อนหากการทดสอบล้มเหลว",
            font=theme.FONT_SMALL,
            bootstyle="secondary",
        ).pack(anchor=tk.W, pady=(0, 14))

        log_card = theme.GlassCard(parent, accent=theme.BORDER, padding=2)
        log_card.pack(fill=tk.BOTH, expand=True, pady=(0, 14))
        self._test_log = scrolledtext.ScrolledText(
            log_card.body,
            height=12,
            bg=theme.LOG_BG,
            fg=theme.LOG_FG,
            insertbackground=theme.LOG_FG,
            borderwidth=0,
            relief="flat",
            font=theme.FONT_MONO,
            state="disabled",
            padx=14,
            pady=12,
        )
        self._test_log.pack(fill=tk.BOTH, expand=True)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="ทดสอบ LINE", bootstyle="info", command=self._test_line).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(actions, text="ทดสอบ Discord", bootstyle="primary", command=self._test_discord).pack(side=tk.LEFT)

    def _log_test(self, message):
        self._test_log.configure(state="normal")
        self._test_log.insert(tk.END, message + "\n")
        self._test_log.see(tk.END)
        self._test_log.configure(state="disabled")

    def _test_line(self):
        self._log_test("กำลังส่งข้อความทดสอบ LINE …")
        try:
            send_line_message("ทดสอบการแจ้งเตือนจาก Cookie Run Auto Bot")
            self._log_test("สำเร็จ: ส่งข้อความ LINE แล้ว")
        except Exception as exc:
            self._log_test(f"ไม่สำเร็จ: {exc}")

    def _test_discord(self):
        webhooks = get_discord_webhooks()
        enabled = [webhook for webhook in webhooks if webhook.get("enabled")]
        if not enabled:
            self._log_test("ไม่พบ Discord Webhook ที่เปิดใช้งาน")
            return
        self._log_test(f"กำลังทดสอบ {len(enabled)} Discord Webhook …")
        for webhook in enabled:
            try:
                send_discord_test_to_url(webhook["url"], webhook.get("name", "Discord"))
                self._log_test(f"สำเร็จ: {webhook.get('name', 'Discord')}")
            except Exception as exc:
                self._log_test(f"ไม่สำเร็จ: {webhook.get('name', 'Discord')} — {exc}")
