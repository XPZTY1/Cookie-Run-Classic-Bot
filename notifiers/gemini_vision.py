import os
import sys
import time

import cv2
from google import genai  # pip install google-genai  (ใช้สำหรับ Gemini แทนการยิง REST ตรงๆ)

from config import GEMINI_MODEL
from secrets_loader import GEMINI_API_KEY


def _safe_print(msg):
    """
    พิมพ์ข้อความอย่างปลอดภัย ป้องกัน UnicodeEncodeError จากอิโมจิ/อักขระพิเศษบนคอนโซล Windows (cp1252)
    """
    try:
        print(msg)
    except Exception:
        try:
            if hasattr(sys, "stdout") and hasattr(sys.stdout, "buffer"):
                sys.stdout.buffer.write((str(msg) + "\n").encode("utf-8", errors="replace"))
            else:
                clean_msg = str(msg).encode("ascii", errors="replace").decode("ascii")
                print(clean_msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Gemini Vision: บรรยายภาพหน้าจอเป็นข้อความ (ใช้ตอนหยุดทำงานเพื่อแจ้งเตือน)
# ---------------------------------------------------------------------------

# Prompt สำหรับบรรยายหน้าจอ Error/ขัดจังหวะ เพื่อแจ้งเตือนเข้า LINE
GEMINI_DESCRIBE_PROMPT = (
    "นี่คือภาพหน้าจอเกมมือถือ ช่วยบรรยายสั้นๆ (ไม่เกิน 2-3 ประโยค) "
    "ว่าตอนนี้หน้าจอกำลังแสดงอะไรอยู่ เช่น ข้อความ error, หน้าต่างแจ้งเตือน, "
    "หรือสถานการณ์ทั่วไปที่เห็นในภาพ ตอบเป็นภาษาไทยเท่านั้น"
)

# Prompt สำหรับถอดพิกัดการ์ดมินิเกม (ใช้แยกต่างหากจาก Prompt บรรยายหน้าจอ)
GEMINI_MINIGAME_PROMPT = (
    "วิเคราะห์ภาพในรูปให้หน่อย แล้วหาตำแหน่งการ์ดที่มันมีรูปภาพต่างจากการ์ดอื่น "
    "โดยบอกเป็นพิกัด x และ y โดย x จะมี 3 และ y มี 2 โดยมันจะมีให้กด 2 รูป "
    "บอกมาเป็นแบบนี้ เช่น (1,2),(2,1)"
)

_gemini_client = None


def get_gemini_client():
    """
    สร้าง (หรือคืนค่า) genai.Client() แบบ lazy-load
    ใช้ SDK ทางการแทนการยิง REST เอง เพราะ SDK จัดการรูปแบบ API key ให้อัตโนมัติ
    """
    global _gemini_client
    if _gemini_client is None and GEMINI_API_KEY:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


def _describe_image_bytes_with_gemini(image_bytes, prompt=GEMINI_DESCRIBE_PROMPT):
    """
    ฟังก์ชันกลาง: ส่ง image bytes (PNG) ให้ Gemini บรรยาย พร้อม retry ตอนเจอ 503
    คืนค่าเป็น string คำอธิบาย หรือ None ถ้าเรียกไม่สำเร็จ
    """
    if not GEMINI_API_KEY:
        _safe_print("[Gemini] ยังไม่ได้ตั้งค่า gemini_api_key ใน secrets.json — ข้ามการบรรยายภาพ")
        return None

    client = get_gemini_client()
    if client is None:
        _safe_print("[Gemini] สร้าง client ไม่สำเร็จ ตรวจสอบ gemini_api_key ใน secrets.json")
        return None

    try:
        response = None
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[
                        genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                        prompt,
                    ],
                )
                break  # สำเร็จ ออกจาก loop
            except Exception as retry_err:
                is_last_attempt = attempt == max_retries
                err_str = str(retry_err)
                # 503 = โมเดลโหลดสูงชั่วคราว, ลองใหม่ได้
                if "503" in err_str and not is_last_attempt:
                    wait_seconds = attempt * 2
                    _safe_print(f"[Gemini] โมเดลโหลดสูง (503) กำลังลองใหม่ครั้งที่ {attempt + 1}/{max_retries} ใน {wait_seconds} วิ...")
                    time.sleep(wait_seconds)
                    continue
                # Model ไม่รองรับภาพ
                if "does not support image" in err_str.lower():
                    _safe_print(f"[Gemini] ❌ รุ่น '{GEMINI_MODEL}' ไม่รองรับภาพ! ลองเปลี่ยนเป็น 'gemini-flash-latest'")
                    return None
                # Model ไม่พบใน API
                if "not found" in err_str.lower() and "v1beta" in err_str.lower():
                    _safe_print(f"[Gemini] ❌ รุ่น '{GEMINI_MODEL}' ไม่พบใน API v1beta!")
                    return None
                # Quota หมด
                if "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                    _safe_print(f"[Gemini] ❌ Quota API หมดหรือเกินจำกัด! ({err_str[:120]})")
                    return None
                # Authentication failed
                if "unauthenticated" in err_str.lower() or "invalid authentication credentials" in err_str.lower() or "access_token_type_unsupported" in err_str.lower():
                    _safe_print("[Gemini] ❌ ไม่สามารถยืนยันตัวตนได้ด้วยคีย์ที่ตั้งไว้ ตรวจสอบ gemini_api_key ใน secrets.json")
                    return None
                # error อื่น → ให้ลองครั้งถัดไป ถ้าครบแล้วค่อยยกเลิก
                if is_last_attempt:
                    raise
                wait_seconds = attempt * 2
                _safe_print(f"[Gemini] error ({err_str[:80]}...) ลองใหม่ครั้งที่ {attempt + 1}/{max_retries} ใน {wait_seconds} วิ...")
                time.sleep(wait_seconds)
                continue
        return response.text.strip() if response and response.text else None
    except Exception as e:
        _safe_print(f"[Gemini] เกิดข้อผิดพลาดตอนบรรยายภาพ: {e}")
        return None


def describe_screen_with_gemini(screen):
    """
    ส่งภาพหน้าจอ (numpy array ที่จับสดจาก LDPlayer) ให้ Gemini อธิบายสั้นๆ
    """
    success, buffer = cv2.imencode(".png", screen)
    if not success:
        _safe_print("[Gemini] เข้ารหัสภาพไม่สำเร็จ")
        return None
    return _describe_image_bytes_with_gemini(buffer.tobytes())


def describe_image_with_gemini(image_path):
    """
    อ่านไฟล์ภาพที่เซฟไว้บนดิสก์แล้วส่งให้ Gemini บรรยาย
    """
    if not image_path or not os.path.exists(image_path):
        _safe_print(f"[Gemini] ไม่พบไฟล์ภาพที่จะอ่าน: {image_path}")
        return None

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
    except Exception as e:
        _safe_print(f"[Gemini] อ่านไฟล์ภาพไม่สำเร็จ: {e}")
        return None

    return _describe_image_bytes_with_gemini(image_bytes)


# Prompt สำหรับอ่านคะแนนและเหรียญตอนจบเกม (OCR Score Reading)
GEMINI_OCR_SCORE_PROMPT = (
    "นี่คือภาพหน้าจอสรุปผลเกม Cookie Run เมื่อจบเกม ช่วยอ่านและสกัดค่าตัวเลข 2 ค่าออกจากภาพนี้:\n"
    "1. คะแนนรวม (Score)\n"
    "2. จำนวนเหรียญที่ได้ (Coins)\n"
    "ตอบเป็นรูปแบบ JSON สั้นๆ เท่านั้น เช่น: {\"score\": 1250000, \"coins\": 3450}\n"
    "ห้ามมีข้อความอื่นใด นอกเหนือจาก JSON นี้เด็ดขาด"
)


def _parse_int_safe(val):
    """
    แปลงค่าจาก Gemini (เช่น 1250000, "1,250,000", "3,450 coins") ให้เป็น int อย่างปลอดภัย
    """
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    import re
    val_str = str(val)
    digits = re.sub(r"[^\d]", "", val_str)
    return int(digits) if digits else 0


def read_game_score_with_gemini(screen):
    """
    อ่านคะแนนและเหรียญจากภาพหน้าจอจบเกม (game_over) ด้วย Gemini Vision OCR
    คืนค่าเป็น dict {"score": int, "coins": int} หรือ None ถ้าอ่านไม่สำเร็จ
    """
    import json
    import re

    success, buffer = cv2.imencode(".png", screen)
    if not success:
        _safe_print("[Gemini OCR] เข้ารหัสภาพไม่สำเร็จ")
        return None

    res_text = _describe_image_bytes_with_gemini(buffer.tobytes(), prompt=GEMINI_OCR_SCORE_PROMPT)
    if not res_text:
        return None

    try:
        # ดึงเฉพาะส่วนที่เป็น JSON ลบ markdown ```json ... ``` ออกถ้ามี
        clean_json = re.sub(r"```(?:json)?", "", res_text).strip("` \n\r")
        json_match = re.search(r"\{.*\}", clean_json, re.DOTALL)
        if json_match:
            clean_json = json_match.group(0)

        data = json.loads(clean_json)
        score = _parse_int_safe(data.get("score"))
        coins = _parse_int_safe(data.get("coins"))
        _safe_print(f"[Gemini OCR] อ่านคะแนนสำเร็จ! 🏆 คะแนน: {score:,} | 🪙 เหรียญ: {coins:,}")
        return {"score": score, "coins": coins}
    except Exception as e:
        _safe_print(f"[Gemini OCR] แปลงข้อมูล JSON ตรงๆ ไม่สำเร็จ ({e}) -> ลองใช้ Regex สำรอง...")
        # Fallback using regex to find numbers associated with score/coins or listed numbers
        try:
            score = 0
            coins = 0
            # หาแพทเทิร์น "score": 1234 หรือ "coins": 5678
            score_match = re.search(r'"score"\s*:\s*"?([\d,\.]+)"?', res_text, re.IGNORECASE)
            coins_match = re.search(r'"coins"\s*:\s*"?([\d,\.]+)"?', res_text, re.IGNORECASE)

            if score_match:
                score = _parse_int_safe(score_match.group(1))
            if coins_match:
                coins = _parse_int_safe(coins_match.group(1))

            if score > 0 or coins > 0:
                _safe_print(f"[Gemini OCR Fallback] อ่านคะแนนสำเร็จ! 🏆 คะแนน: {score:,} | 🪙 เหรียญ: {coins:,}")
                return {"score": score, "coins": coins}
        except Exception as fb_err:
            _safe_print(f"[Gemini OCR Fallback] ล้มเหลว: {fb_err}")

        _safe_print(f"[Gemini OCR] อ่านคะแนนไม่สำเร็จ ข้อความจาก Gemini: {res_text[:120]}")
        return None
