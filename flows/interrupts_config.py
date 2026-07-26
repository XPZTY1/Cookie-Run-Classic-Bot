# ---------------------------------------------------------------------------
# INTERRUPTS: ปรากฏการณ์ที่ไม่บังคับลำดับ (เจอเมื่อไหร่ก็กดได้ทันที)
# ---------------------------------------------------------------------------
INTERRUPTS = {
    "open_box": {
        "template": "open_all.png",
        "action": "click",
        "cooldown": 5.0,
    },
    "confirm_blue_popup": {
        "template": "confirm_blue.png",
        "action": "click",
        "cooldown": 5.0,
    },
    "confirm_green_popup": {
        "template": "confirm_green.png",
        "action": "click",
        "cooldown": 5.0,
    },
    "cancel_popup": {
        "template": "cancel_button.png",
        "action": "click",
        "cooldown": 5.0,
    },
    "live_two": {
        "template": "live_two.png",
        "action": "click",
        "cooldown": 0.05,
    },
    "confirm2_green_popup": {
        "template": "confirm2_green.png",
        "action": "click",
        "cooldown": 5.0,
    },
    # Popup "You've been inactive" — เกมเตือนว่าบอทไม่ได้กดนานเกิน
    # ให้ใช้ template เดิมก่อน ถ้า score ยังต่ำให้ capture ใหม่ชื่อ confirm_inactive.png
    "confirm_inactive": {
        "template": "confirm_inactive.png",
        "action": "click",
        "cooldown": 10.0,
        "threshold": 0.70,   # ลด threshold เพราะ popup นี้อาจมีพื้นหลังต่างกัน
    },
}
