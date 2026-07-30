@echo off
chcp 65001 > nul
title Cookie Run Classic Bot — Multi-Instance Launcher

:: ============================================================================
:: Cookie Run Classic Auto Bot — Multi-Instance Launcher
:: สคริปต์เปิดบอทหลายหน้าต่างแยกตามพอร์ต ADB
:: ============================================================================

cd /d "%~dp0"

echo ============================================================================
echo  Cookie Run Classic Bot - Multi-Instance Launcher
echo ============================================================================
echo  [1] เปิด 2 จอ (Port 5559 + 7555)
echo  [2] เปิด 2 จอ (Port 5555 + 5557 - LDPlayer Default)
echo  [3] เปิด 3 จอ (Port 5559 + 7555 + 16384 - MuMu Player Multi)
echo  [4] กำหนดพอร์ตเอง (Custom Ports)
echo ============================================================================

set /p choice="กรุณาเลือกตัวเลือก (1-4) หรือกด Enter เพื่อรันข้อ 1: "

if "%choice%"=="2" goto opt2
if "%choice%"=="3" goto opt3
if "%choice%"=="4" goto custom
goto opt1

:opt1
echo [INFO] กำลังเปิด Window 1 (Port 5559)...
start "Bot Instance 1 (Port 5559)" python main.py --port 5559 --no-hotkey
timeout /t 2 > nul
echo [INFO] กำลังเปิด Window 2 (Port 7555)...
start "Bot Instance 2 (Port 7555)" python main.py --port 7555 --no-hotkey
goto end

:opt2
echo [INFO] กำลังเปิด Window 1 (Port 5555)...
start "Bot Instance 1 (Port 5555)" python main.py --port 5555 --no-hotkey
timeout /t 2 > nul
echo [INFO] กำลังเปิด Window 2 (Port 5557)...
start "Bot Instance 2 (Port 5557)" python main.py --port 5557 --no-hotkey
goto end

:opt3
echo [INFO] กำลังเปิด Window 1 (Port 5559)...
start "Bot Instance 1 (Port 5559)" python main.py --port 5559 --no-hotkey
timeout /t 2 > nul
echo [INFO] กำลังเปิด Window 2 (Port 7555)...
start "Bot Instance 2 (Port 7555)" python main.py --port 7555 --no-hotkey
timeout /t 2 > nul
echo [INFO] กำลังเปิด Window 3 (Port 16384)...
start "Bot Instance 3 (Port 16384)" python main.py --port 16384 --no-hotkey
goto end

:custom
set /p p1="ระบุ Port สำหรับจอที่ 1: "
set /p p2="ระบุ Port สำหรับจอที่ 2: "
if not "%p1%"=="" start "Bot Instance 1 (Port %p1%)" python main.py --port %p1% --no-hotkey
if not "%p2%"=="" (
    timeout /t 2 > nul
    start "Bot Instance 2 (Port %p2%)" python main.py --port %p2% --no-hotkey
)
goto end

:end
echo ============================================================================
echo [SUCCESS] เปิดหน้าต่าง Multi-Instance เรียบร้อยแล้ว!
echo หมายเหตุ: ใช้พารามิเตอร์ --no-hotkey แล้ว เพื่อไม่ให้ปุ่ม F6/F7 ตีกัน
echo ============================================================================
pause
