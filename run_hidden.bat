@echo off
cd /d "%~dp0"

REM ================================================================
REM  Cookie Run Classic Auto Bot — Launcher
REM ================================================================
REM
REM  เปิด 1 หน้าต่าง (default port 5559 จาก .env):
REM    python main.py
REM
REM  เปิด Multi-Instance (หลายหน้าต่างพร้อมกัน):
REM    python main.py --port 5559 --no-hotkey
REM    python main.py --port 7555 --no-hotkey
REM    python main.py --port 16384 --no-hotkey
REM
REM  โปรดใช้ --no-hotkey เสมอเมื่อเปิดหลายหน้าต่าง
REM  เพื่อป้องกัน F6/F7/F9 ตีกันระหว่าง instance
REM ================================================================

python.exe main.py %*