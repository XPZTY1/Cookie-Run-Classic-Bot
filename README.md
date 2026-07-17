# Cookie Run Classic Auto Bot — โครงสร้างแยกไฟล์

## วิธีรัน
รันจากภายในโฟลเดอร์นี้เหมือนเดิมทุกอย่าง แค่เปลี่ยนชื่อไฟล์ entry point:

```
python main.py --capture
python main.py --debug
python main.py --test-line
python main.py --test-gemini
python main.py
```

## โครงสร้างไฟล์
```
cookierun_bot/
├── main.py                      # entry point: parse args, hotkeys (F6/F7/F9), เรียก bot_loop
├── config.py                    # ค่าคงที่: ADB_PATH, DEVICE_ID, threshold, path ต่างๆ
├── secrets_loader.py            # โหลด LINE token / Gemini API key จาก secrets.json
├── adb_client.py                # คุยกับ LDPlayer ผ่าน ADB (screenshot, tap, connect)
├── template_matcher.py          # find_template()
│
├── notifiers/
│   ├── line_notifier.py         # send_line_message()
│   └── gemini_vision.py         # describe_screen_with_gemini() / describe_image_with_gemini()
│
├── flows/
│   ├── flow_config.py           # FLOW (state machine หลัก)
│   ├── interrupts_config.py     # INTERRUPTS (popup ที่กดได้ทันที)
│   └── pause_events_config.py   # PAUSE_EVENTS (เหตุการณ์ที่ต้องหยุดรอ+แจ้งเตือน)
│
├── bot_engine.py                # state machine loop, action funcs, hotkey handlers
│
└── tools/
    ├── capture_mode.py          # --capture
    └── debug_mode.py            # --debug
```

## หมายเหตุ
- `secrets.json` ยังคงวางไว้ข้างๆ `main.py` (หรือข้างๆ .exe ถ้า build ด้วย PyInstaller) เหมือนเดิม
- `templates/` และ `pause_screenshots/` path เหมือนเดิม ไม่กระทบ
- ถ้า build เป็น .exe ต้องรัน PyInstaller จาก `main.py` แทน (เช่น `pyinstaller main.py`)
- ทดสอบ import ครบทุกไฟล์แล้ว ไม่มี circular import
