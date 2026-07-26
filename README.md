# Cookie Run Classic Auto Bot — โครงสร้างและฟีเจอร์

## วิธีติดตั้งและรัน
1. ติดตั้งไลบรารีที่จำเป็น:
```bash
pip install -r requirements.txt
```

2. ตั้งค่าไฟล์ `secrets.json` (คัดลอกมาจาก `secrets.example.json` แล้วกรอกค่า):
```json
{
  "line_channel_access_token": "...",
  "line_user_id": "...",
  "gemini_api_key": "...",
  "discord_webhook_url": "..."
}
```

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

## โครงสร้างไฟล์
```
cookierun_bot/
├── main.py                      # entry point: parse args, hotkeys (F6/F7/F9), GUI launcher
├── config.py                    # ค่าคงที่: ADB_PATH, DEVICE_ID, threshold, path ต่างๆ, 4 ระบบใหม่
├── secrets_loader.py            # โหลด LINE token / Gemini API key / Discord Webhook จาก secrets.json
├── secrets.example.json         # แม่แบบไฟล์ secrets.json สำหรับผู้ใช้ใหม่
├── secrets.json                 # ไฟล์เก็บ API key และ Token ส่วนตัว (ห้ามแชร์)
├── adb_client.py                # คุยกับ MuMu/LDPlayer ผ่าน ADB (screenshot, tap, swipe_curve)
├── template_matcher.py          # find_template()
├── requirements.txt             # รายชื่อ Python Packages ที่จำเป็น
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
