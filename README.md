# Cookie Run Classic Auto Bot — โครงสร้างและฟีเจอร์

## วิธีติดตั้งและรัน

1. ติดตั้งไลบรารีที่จำเป็น:
```bash
pip install -r requirements.txt
```

2. ตั้งค่าไฟล์ `.env` (คัดลอกมาจาก `.env.example` แล้วกรอกค่า):
```env
LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_CHANNEL_ACCESS_TOKEN
LINE_USER_ID=YOUR_LINE_USER_ID
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```
*(หมายเหตุ: ยังคงรองรับไฟล์ `secrets.json` สำหรับผู้ใช้งานรุ่นเดิม)*

3. คำสั่งทดสอบและรันโปรแกรม:
```bash
python main.py --capture       # โหมดครอปสร้างรูปภาพ Template ปุ่มใหม่
python main.py --debug         # โหมดตรวจสอบค่า Match Score ของ Template ทั้งหมด
python main.py --test-line     # ทดสอบส่งข้อความเข้า LINE
python main.py --test-discord  # ทดสอบส่งข้อความเข้า Discord Webhook
python main.py --test-gemini   # ทดสอบบรรยายหน้าจอด้วย Gemini Vision
python main.py --no-gui        # รันโหมด Console (ไม่เปิด GUI)
python main.py                 # รันโหมด GUI (Default)
```

---

## ⚡ การใช้งาน Multi-Instance (เปิดหลายจอพร้อมกัน)

หากต้องการเปิดบอทหลายหน้าต่างพร้อมกัน (เช่น MuMu Player Multi-instance):

### วิธีที่ 1: รันผ่าน `run_multi_instance.bat` (แนะนำ)
ดับเบิ้ลคลิกไฟล์ `run_multi_instance.bat` ระบบจะเปิด 2 หน้าต่างอัตโนมัติ โดยแยกพอร์ตและแยกไฟล์สถิติจำลองของแต่ละจอ

### วิธีที่ 2: รันแยก Command Line
เปิด Terminal แยกแต่ละหน้าต่าง แล้วระบุพอร์ตและพารามิเตอร์ `--no-hotkey`:

```bash
# หน้าต่างที่ 1 (Port 5559)
python main.py --port 5559 --no-hotkey

# หน้าต่างที่ 2 (Port 7555)
python main.py --port 7555 --no-hotkey
```

> ⚠️ **ข้อสำคัญ:** ต้องใส่ `--no-hotkey` เสมอเมื่อเปิดหลายหน้าต่าง เพื่อป้องกันไม่ให้ปุ่ม F6/F7/F9 ควบคุมซ้ำซ้อนกันระหว่างหน้าต่าง

---

## โครงสร้างไฟล์
```
cookierun_bot/
├── main.py                      # entry point: parse args, hotkeys (F6/F7/F9), GUI launcher
├── config.py                    # ค่าคงที่: ADB_PATH, DEVICE_ID, threshold, path ต่างๆ
├── secrets_loader.py            # โหลด LINE token / Gemini API key / Discord Webhook จาก .env หรือ secrets.json
├── .env.example                 # แม่แบบไฟล์ .env
├── .env                         # ไฟล์เก็บ API key และ Token ส่วนตัว (ห้ามแชร์)
├── adb_client.py                # คุยกับ MuMu/LDPlayer ผ่าน ADB (screenshot, tap, swipe_curve)
├── requirements.txt             # รายชื่อ Python Packages ที่จำเป็น
├── run_hidden.bat               # Launcher สคริปต์แบบเดี่ยว
├── run_multi_instance.bat       # Launcher สคริปต์สำหรับเปิดหลายจอ (Multi-Instance)
│
├── data/                        # โฟลเดอร์เก็บข้อมูลระบบ (แยกตาม Device/Port)
│   ├── bot_stats_*.json         # ไฟล์สถิติการรันแยกตาม Device
│   ├── user_profiles.json       # โปรไฟล์ Preset ที่ผู้ใช้บันทึก
│   └── pause_screenshots/       # โฟลเดอร์เก็บภาพแคปหน้าจอเมื่อเกิด Pause Event
│
├── notifiers/
│   ├── line_notifier.py         # send_line_message()
│   ├── discord_notifier.py      # send_discord_report()
│   └── gemini_vision.py         # describe_screen_with_gemini() / read_game_score_with_gemini()
│
├── flows/
│   ├── flow_config.py           # FLOW (state machine หลัก)
│   ├── interrupts_config.py     # INTERRUPTS (popup ที่กดได้ทันที)
│   └── pause_events_config.py   # PAUSE_EVENTS (เหตุการณ์ที่ต้องหยุดรอ+แจ้งเตือน)
│
├── bot_engine.py                # state machine loop, action funcs, schedule check, OCR, stats
├── gui.py                       # หน้าต่าง GUI Dashboard Control Panel
│
└── tools/
    ├── capture_mode.py          # --capture
    └── debug_mode.py            # --debug
```

## หมายเหตุและข้อแนะนำ
- ไฟล์รูปภาพ Template ใน `templates/`: หากมีป๊อปอัปใหม่ที่บอทยังไม่รู้จัก สามารถใช้คำสั่ง `python main.py --capture` ครอปภาพเพิ่มได้ตลอดเวลา
