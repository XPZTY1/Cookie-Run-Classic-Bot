# ---------------------------------------------------------------------------
# FLOW: บังคับลำดับขั้นตอนจริง (state machine)
# ---------------------------------------------------------------------------
FLOW = {
    "start_game": {
        "template": "start_button.png",
        "action": "click",
        "delay": 3,
        "entry_delay": 5,  # รอ 2 วินาทีก่อนเริ่มกดปุ่มเมื่อกลับมาหน้าแรก เพื่อให้เกมโหลด UI เสร็จ
        "next_state": "item_boots",
    },

    "item_boots": {
        "template": "boots_button.png",
        "action": "click",
        "delay": 2,
        "next_state": "click_multi",
    },

    "click_multi": {
        "template": "buy_button.png",
        "action": "click",
        "delay": 2,
        "next_state": "multi_buy",
    },

    "multi_buy": {
        "template": "multi_buy.png",
        "action": "click",
        "delay": 2,
        "next_state": "let_go",
    },

    "let_go": {
        "template": "start_button.png",
        "action": "click",
        "next_state": "over_game",
    },

    "over_game": {
        "template": "game_over.png",
        "action": "click",
        "delay": 15,
        "next_state": "start_game",
        "tap_while_wait": True,
        # หยุดกดรัวทันทีเมื่อเจอหน้าจบเกม เพื่อป้องกันไม่ให้เผลอกดปุ่ม OK
        "guard_templates": ["game_over.png"],
    },
}
