import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

import bot_engine
from config import DEVICE_ID
from adb_client import adb_connect

class TextRedirector:
    """ redirect print() stdout ไปที่ Tkinter Text Widget """
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, str_val):
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, str_val)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')

    def flush(self):
        pass

def run_gui():
    # ตรวจสอบการเชื่อมต่อ ADB
    adb_connect()

    root = tk.Tk()
    root.title("Cookie Run Classic Auto Bot")
    root.geometry("680x560")
    root.resizable(True, True)
    
    # ธีมสีสไตล์โมเดิร์น
    bg_color = "#1e1e24"
    card_color = "#2a2a35"
    text_color = "#ffffff"
    accent_green = "#4caf50"
    accent_red = "#f44336"
    
    root.configure(bg=bg_color)
    
    # กำหนดสไตล์ปุ่ม
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("TFrame", background=bg_color)
    style.configure("Card.TFrame", background=card_color)
    style.configure("TLabel", background=bg_color, foreground=text_color, font=("Consolas", 10))
    style.configure("CardLabel.TLabel", background=card_color, foreground=text_color, font=("Consolas", 10))
    style.configure("Title.TLabel", background=bg_color, foreground="#e0e0e0", font=("Consolas", 14, "bold"))
    
    # Layout ด้านบน: ชื่อรุ่น & อุปกรณ์
    top_frame = ttk.Frame(root, padding=10)
    top_frame.pack(fill=tk.X)
    
    title_lbl = ttk.Label(top_frame, text="🍪 COOKIE RUN CLASSIC BOT", style="Title.TLabel")
    title_lbl.pack(side=tk.LEFT)
    
    device_lbl = ttk.Label(top_frame, text=f"Device: {DEVICE_ID}", foreground="#aaa")
    device_lbl.pack(side=tk.RIGHT, padx=10)
    
    # Layout กลาง: แผงควบคุมและสถิติ
    control_frame = ttk.Frame(root, padding=10)
    control_frame.pack(fill=tk.X)
    
    # กลุ่มปุ่มควบคุม (ซ้าย)
    btn_frame = ttk.Frame(control_frame, padding=5)
    btn_frame.pack(side=tk.LEFT, fill=tk.Y)
    
    start_btn = tk.Button(
        btn_frame, 
        text="Start Bot (F6)", 
        bg=accent_green, 
        fg="white", 
        font=("Consolas", 11, "bold"),
        width=18, 
        height=2,
        bd=0,
        command=bot_engine.start_bot
    )
    start_btn.pack(pady=5)
    
    stop_btn = tk.Button(
        btn_frame, 
        text="Stop Bot (F7)", 
        bg=accent_red, 
        fg="white", 
        font=("Consolas", 11, "bold"),
        width=18, 
        height=2,
        bd=0,
        command=bot_engine.stop_bot
    )
    stop_btn.pack(pady=5)
    
    # การ์ดสถิติ (ขวา)
    stats_card = ttk.Frame(control_frame, style="Card.TFrame", padding=10)
    stats_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
    
    ttk.Label(stats_card, text="📊 LIVE SESSION STATS", style="CardLabel.TLabel", font=("Consolas", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0,5))
    
    state_lbl = ttk.Label(stats_card, text="Current State: -", style="CardLabel.TLabel")
    state_lbl.grid(row=1, column=0, sticky=tk.W, pady=2)
    
    runs_lbl = ttk.Label(stats_card, text="Total Runs: 0", style="CardLabel.TLabel")
    runs_lbl.grid(row=1, column=1, sticky=tk.W, pady=2)
    
    success_lbl = ttk.Label(stats_card, text="Successful Runs: 0", style="CardLabel.TLabel")
    success_lbl.grid(row=2, column=0, sticky=tk.W, pady=2)
    
    watchdog_lbl = ttk.Label(stats_card, text="Watchdog Resets: 0", style="CardLabel.TLabel")
    watchdog_lbl.grid(row=2, column=1, sticky=tk.W, pady=2)

    adb_lbl = ttk.Label(stats_card, text="ADB Disconnects: 0", style="CardLabel.TLabel")
    adb_lbl.grid(row=3, column=0, sticky=tk.W, pady=2)
    
    rest_lbl = ttk.Label(stats_card, text="Next Rest In: -", style="CardLabel.TLabel")
    rest_lbl.grid(row=3, column=1, sticky=tk.W, pady=2)

    # Layout ล่างสุด: หน้าต่าง Log
    log_frame = ttk.Frame(root, padding=10)
    log_frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(log_frame, text="💬 Real-time Log Console:").pack(anchor=tk.W, pady=3)
    
    log_area = scrolledtext.ScrolledText(
        log_frame, 
        wrap=tk.WORD, 
        bg="#121214", 
        fg="#22c55e", # สีเขียวสไตล์ terminal
        insertbackground="white", 
        font=("Consolas", 9),
        state='disabled'
    )
    log_area.pack(fill=tk.BOTH, expand=True)
    
    # ฟังก์ชันเขียน Log ลงช่อง Text Widget (Thread-safe ด้วยการใช้ root.after)
    def write_to_log_area(formatted_msg):
        try:
            def update_ui():
                log_area.configure(state='normal')
                log_area.insert(tk.END, formatted_msg + "\n")
                log_area.see(tk.END)
                log_area.configure(state='disabled')
            root.after(0, update_ui)
        except Exception:
            pass

    # ลงทะเบียน callback log ไปที่ bot_engine
    bot_engine.set_gui_log_callback(write_to_log_area)
    
    # รัน Bot loop ใน Background Thread เพื่อป้องกันไม่ให้ GUI ค้าง
    bot_thread = threading.Thread(target=bot_engine.bot_loop, daemon=True)
    bot_thread.start()
    
    # ฟังก์ชันลูปอัปเดตแผงสถิติบน UI แบบเรียลไทม์
    def update_stats_loop():
        try:
            # ดึงข้อมูลตัวแปรหลักจาก bot_engine
            state_lbl.config(text=f"Current State: {bot_engine.current_state}")
            runs_lbl.config(text=f"Total Runs: {bot_engine.session_stats['total_runs']}")
            success_lbl.config(text=f"Success Runs: {bot_engine.session_stats['successful_runs']}")
            watchdog_lbl.config(text=f"Watchdog Resets: {bot_engine.session_stats['watchdog_resets']}")
            adb_lbl.config(text=f"ADB Disconnects: {bot_engine.session_stats['adb_disconnects']}")
            
            # คำนวณเวลาก่อนพักสายตาบอท
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
                
            # เปลี่ยนสีปุ่มสถานะบอท
            if bot_engine.running:
                start_btn.config(relief=tk.SUNKEN, bg="#1b5e20", text="Running...")
                stop_btn.config(relief=tk.RAISED, bg=accent_red, text="Stop Bot (F7)")
            else:
                start_btn.config(relief=tk.RAISED, bg=accent_green, text="Start Bot (F6)")
                stop_btn.config(relief=tk.SUNKEN, bg="#b71c1c", text="Stopped")
                
        except Exception:
            pass
        root.after(500, update_stats_loop) # วนรอบทำงานอัปเดตข้อมูลทุกๆ 0.5 วินาที
        
    root.after(500, update_stats_loop)
    
    # บังคับบันทึกประวัติก่อนปิดหน้าต่าง
    def on_closing():
        bot_engine.save_global_stats(session_done=True)
        root.destroy()
        os._exit(0)
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    run_gui()