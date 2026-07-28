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
    ฟังก์ชันกลาง: ส่ง image bytes (PNG) ให้ Gemini บรรยาย พร้อม retry ตอนเจอ 503 และ fallback รุ่นโมเดล
    คืนค่าเป็น string คำอธิบาย หรือ None ถ้าเรียกไม่สำเร็จ
    """
    if not GEMINI_API_KEY:
        _safe_print("[Gemini] ยังไม่ได้ตั้งค่า gemini_api_key ใน secrets.json — ข้ามการบรรยายภาพ")
        return None

    if not GEMINI_API_KEY.startswith("AIzaSy"):
        _safe_print("[Gemini] ⚠️ เตือน: gemini_api_key ใน secrets.json ดูเหมือนไม่ใช่ API Key จาก Google AI Studio (คีย์ที่ถูกต้องมักขึ้นต้นด้วย 'AIzaSy...')")

    client = get_gemini_client()
    if client is None:
        _safe_print("[Gemini] สร้าง client ไม่สำเร็จ ตรวจสอบ gemini_api_key ใน secrets.json")
        return None

    # รายชื่อโมเดลที่จะลองใช้งานเรียงตามลำดับความสำคัญ
    candidate_models = [GEMINI_MODEL, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    # ตัดชื่อโมเดลที่ซ้ำกันออก
    models_to_try = []
    for m in candidate_models:
        if m and m not in models_to_try:
            models_to_try.append(m)

    for target_model in models_to_try:
        try:
            response = None
            max_retries = 2
            for attempt in range(1, max_retries + 1):
                try:
                    response = client.models.generate_content(
                        model=target_model,
                        contents=[
                            genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                            prompt,
                        ],
                    )
                    if response and response.text:
                        return response.text.strip()
                    break
                except Exception as retry_err:
                    is_last_attempt = attempt == max_retries
                    err_str = str(retry_err)

                    # Authentication failed
                    if any(k in err_str.lower() for k in ["unauthenticated", "invalid authentication credentials", "access_token_type_unsupported"]):
                        _safe_print("[Gemini] ❌ ไม่สามารถยืนยันตัวตนได้! กรุณาตรวจสอบ gemini_api_key ใน secrets.json (ต้องเป็นคีย์จาก https://aistudio.google.com/app/apikey ขึ้นต้นด้วย AIzaSy...)")
                        return None

                    # Quota หมด
                    if "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                        _safe_print(f"[Gemini] ❌ Quota API หมดหรือเกินจำกัด! ({err_str[:120]})")
                        return None

                    # 503 = โมเดลโหลดสูงชั่วคราว, ลองใหม่ได้
                    if "503" in err_str and not is_last_attempt:
                        wait_seconds = attempt * 2
                        _safe_print(f"[Gemini ({target_model})] โมเดลโหลดสูง (503) ลองใหม่ครั้งที่ {attempt + 1}/{max_retries} ใน {wait_seconds} วิ...")
                        time.sleep(wait_seconds)
                        continue

                    # ถ้าเป็น error เรื่อง model ไม่พบ/ไม่รองรับ -> เปลี่ยนไปลองโมเดลถัดไป
                    if "not found" in err_str.lower() or "does not support image" in err_str.lower():
                        _safe_print(f"[Gemini] ⚠️ โมเดล '{target_model}' ไม่พบหรือไม่รองรับภาพ -> ลองโมเดลถัดไป...")
                        break

                    if is_last_attempt:
                        raise
                    time.sleep(1)
        except Exception as model_err:
            _safe_print(f"[Gemini ({target_model})] เกิดข้อผิดพลาด: {model_err}")
            continue

    _safe_print("[Gemini] ❌ ไม่สามารถเรียกใช้งาน Gemini Vision API ได้ทุกโมเดลที่กำหนด")
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


# Prompt สำหรับอ่านคะแนน, เหรียญ และกล่องสมบัติ/ของขวัญตอนจบเกม (OCR Score & Mystery Box Reading)
GEMINI_OCR_SCORE_PROMPT = (
    "นี่คือภาพหน้าจอสรุปผลเกม Cookie Run เมื่อจบเกม ช่วยอ่านและสกัดค่าตัวเลข 3 ค่าออกจากภาพนี้:\n"
    "1. คะแนนรวม (Score)\n"
    "2. จำนวนเหรียญที่ได้ (Coins)\n"
    "3. จำนวนกล่องสมบัติ/กล่องของขวัญที่ได้ในรอบนี้ (Boxes) (ถ้าพบไอคอนกล่อง ให้ระบุจำนวน เช่น 1, 2, 3... ถ้าไม่มีให้ตอบ 0)\n"
    "ตอบเป็นรูปแบบ JSON สั้นๆ เท่านั้น เช่น: {\"score\": 1250000, \"coins\": 3450, \"boxes\": 2}\n"
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
    อ่านคะแนน เหรียญ และจำนวนกล่องสมบัติจากภาพหน้าจอจบเกม (game_over) ด้วย Gemini Vision OCR
    คืนค่าเป็น dict {"score": int, "coins": int, "boxes": int} หรือ None ถ้าอ่านไม่สำเร็จ
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
        boxes = _parse_int_safe(data.get("boxes"))
        _safe_print(f"[Gemini OCR] อ่านข้อมูลสำเร็จ! 🏆 คะแนน: {score:,} | 🪙 เหรียญ: {coins:,} | 🎁 กล่องสมบัติ: {boxes}")
        return {"score": score, "coins": coins, "boxes": boxes}
    except Exception as e:
        _safe_print(f"[Gemini OCR] แปลงข้อมูล JSON ตรงๆ ไม่สำเร็จ ({e}) -> ลองใช้ Regex สำรอง...")
        # Fallback using regex to find numbers associated with score/coins/boxes
        try:
            score = 0
            coins = 0
            boxes = 0
            score_match = re.search(r'(?:"score"|คะแนน)\s*[:=]\s*"?([\d,\.]+)"?', res_text, re.IGNORECASE)
            coins_match = re.search(r'(?:"coins"|เหรียญ)\s*[:=]\s*"?([\d,\.]+)"?', res_text, re.IGNORECASE)
            boxes_match = re.search(r'(?:"boxes"|กล่อง)\s*[:=]\s*"?([\d,\.]+)"?', res_text, re.IGNORECASE)

            if score_match:
                score = _parse_int_safe(score_match.group(1))
            if coins_match:
                coins = _parse_int_safe(coins_match.group(1))
            if boxes_match:
                boxes = _parse_int_safe(boxes_match.group(1))

            if score > 0 or coins > 0 or boxes > 0:
                _safe_print(f"[Gemini OCR Fallback] อ่านข้อมูลสำเร็จ! 🏆 คะแนน: {score:,} | 🪙 เหรียญ: {coins:,} | 🎁 กล่องสมบัติ: {boxes}")
                return {"score": score, "coins": coins, "boxes": boxes}
        except Exception as fb_err:
            _safe_print(f"[Gemini OCR Fallback] ล้มเหลว: {fb_err}")

        _safe_print(f"[Gemini OCR] อ่านข้อมูลไม่สำเร็จ ข้อความจาก Gemini: {res_text[:120]}")
        return None
