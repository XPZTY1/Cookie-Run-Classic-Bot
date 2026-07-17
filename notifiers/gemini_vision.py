import os
import time

import cv2
from google import genai  # pip install google-genai  (ใช้สำหรับ Gemini แทนการยิง REST ตรงๆ)

from config import GEMINI_MODEL
from secrets_loader import GEMINI_API_KEY

# ---------------------------------------------------------------------------
# Gemini Vision: บรรยายภาพหน้าจอเป็นข้อความ (ใช้ตอนหยุดทำงานเพื่อแจ้งเตือน)
# ---------------------------------------------------------------------------
# หมายเหตุ: ฟังก์ชันนี้ใช้ "บรรยายว่าหน้าจอแสดงอะไร" เพื่อแจ้งเตือนเท่านั้น
# ไม่ได้ใช้ตัดสินใจกดปุ่มหรือช่วยผ่านด่านใดๆ ทั้งสิ้น

GEMINI_DESCRIBE_PROMPT = (
    # "นี่คือภาพหน้าจอเกมมือถือ ช่วยบรรยายสั้นๆ (ไม่เกิน 2-3 ประโยค) "
    # "ว่าตอนนี้หน้าจอกำลังแสดงอะไรอยู่ เช่น ข้อความ error, หน้าต่างแจ้งเตือน, "
    # "หรือสถานการณ์ทั่วไปที่เห็นในภาพ ตอบเป็นภาษาไทยเท่านั้น "
    # "ช่วยฉันทำโจทย์ในรูปภาพหน่อย โดยบอกตำแหน่งเป็นแกน X กับ Y ตำแหน่งในรูป "
    # "ให้บอกแค่คำตอบไม่ต้องแนะนำอะไร บอกว่าโจทย์มันคืออะไร และคำตอบคืออันไหนบ้าง โดยจะให้ตอบมากสุดแค่ 2 คำตอบ"
    # "บอกมาแค่ตัวเลข เช่น (1,2),(3,2) ข้างหน้าคือ X หลังคือ Y"
    # "อยากได้พิกัดของรูปเป็นพิกัดของหน้าจอเลย"
    # "ห้ามมีตัวอักษร ให้มีแค่ตัวเลขกับวงเล็บเพียงอย่างเดียว"
    """วิเคราะห์ภาพในรูปให้หน่อย แล้วหาตำแหน่งการ์ดที่มันมีรูปภาพต่างจากการ์ดอื่น โดยบอกเป็นพิกัด x และ y โดย x จะมี 3 และ y มี 2 
    โดยมันจะมีให้กด 2 รูป
    บอกมาเป็นแบบนี้ เช่น (1,2),(2,1)
"""

)

_gemini_client = None


def get_gemini_client():
    """
    สร้าง (หรือคืนค่า) genai.Client() แบบ lazy-load
    ใช้ SDK ทางการแทนการยิง REST เอง เพราะ SDK จัดการรูปแบบ API key ให้อัตโนมัติ
    ไม่ว่าจะเป็น key แบบเก่า (AIza...) หรือแบบใหม่ (AQ. ... Auth key)
    """
    global _gemini_client
    if _gemini_client is None and GEMINI_API_KEY:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


def _describe_image_bytes_with_gemini(image_bytes, prompt=GEMINI_DESCRIBE_PROMPT):
    """
    ฟังก์ชันกลาง: ส่ง image bytes (PNG) ให้ Gemini บรรยาย พร้อม retry ตอนเจอ 503
    คืนค่าเป็น string คำอธิบาย หรือ None ถ้าเรียกไม่สำเร็จ
    ใช้เป็น core ให้ทั้ง describe_screen_with_gemini (จับจากจอสด)
    และ describe_image_with_gemini (อ่านจากไฟล์ที่เซฟไว้)
    """
    if not GEMINI_API_KEY:
        print("[Gemini] ยังไม่ได้ตั้งค่า gemini_api_key ใน secrets.json — ข้ามการบรรยายภาพ")
        return None

    client = get_gemini_client()
    if client is None:
        print("[Gemini] สร้าง client ไม่สำเร็จ ตรวจสอบ gemini_api_key ใน secrets.json")
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
                    wait_seconds = attempt * 2  # รอเพิ่มขึ้นเรื่อยๆ: 2, 4 วิ
                    print(f"[Gemini] โมเดลโหลดสูง (503) กำลังลองใหม่ครั้งที่ {attempt + 1}/{max_retries} ใน {wait_seconds} วิ...")
                    time.sleep(wait_seconds)
                    continue
                # Model ไม่รองรับภาพ
                if "does not support image" in err_str.lower():
                    print(f"[Gemini] ❌ รุ่น '{GEMINI_MODEL}' ไม่รองรับภาพ! ลองเปลี่ยนเป็น 'gemini-2.5-flash'")
                    return None
                # Model ไม่พบใน API
                if "not found" in err_str.lower() and "v1beta" in err_str.lower():
                    print(f"[Gemini] ❌ รุ่น '{GEMINI_MODEL}' ไม่พบใน API v1beta! ต้องใช้รุ่น 2.x")
                    return None
                # Quota หมด
                if "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                    print(f"[Gemini] ❌ Quota API หมดแล้ว! รอ quota รีเซ็ต หรืออัปเกรดแผน")
                    return None
                # error อื่น → ให้ลองครั้งถัดไป ถ้าครบแล้วค่อยยกเลิก
                if is_last_attempt:
                    raise
                # ยังไม่ใช่ครั้งสุดท้าย → ลองใหม่
                wait_seconds = attempt * 2
                print(f"[Gemini] error ({err_str[:80]}...) ลองใหม่ครั้งที่ {attempt + 1}/{max_retries} ใน {wait_seconds} วิ...")
                time.sleep(wait_seconds)
                continue
        return response.text.strip() if response.text else None
    except Exception as e:
        print(f"[Gemini] เกิดข้อผิดพลาดตอนบรรยายภาพ: {e}")
        return None


def describe_screen_with_gemini(screen):
    """
    ส่งภาพหน้าจอ (numpy array ที่จับสดจาก LDPlayer) ให้ Gemini อธิบายสั้นๆ
    ใช้กับโหมด --test-gemini เพื่อทดสอบว่าเชื่อมต่อ Gemini ได้จริง โดยอ่านค่า
    จากหน้าจอ LDPlayer โดยตรง (ไม่ผ่านไฟล์ที่เซฟไว้)
    คืนค่าเป็น string คำอธิบาย หรือ None ถ้าเรียกไม่สำเร็จ
    """
    success, buffer = cv2.imencode(".png", screen)
    if not success:
        print("[Gemini] เข้ารหัสภาพไม่สำเร็จ")
        return None
    return _describe_image_bytes_with_gemini(buffer.tobytes())


def describe_image_with_gemini(image_path):
    """
    อ่านไฟล์ภาพที่เซฟไว้บนดิสก์ (เช่นภาพที่เซฟไว้ตอนเจอ PAUSE_EVENTS) แล้วส่งให้ Gemini บรรยาย
    ใช้แทน describe_screen_with_gemini ตอนเกิด pause event เพื่อให้ Gemini อ่าน
    "รูปภาพที่บันทึกไว้จริงๆ" แทนภาพสดในหน่วยความจำ
    คืนค่าเป็น string คำอธิบาย หรือ None ถ้าอ่านไฟล์/เรียกไม่สำเร็จ
    """
    if not image_path or not os.path.exists(image_path):
        print(f"[Gemini] ไม่พบไฟล์ภาพที่จะอ่าน: {image_path}")
        return None

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
    except Exception as e:
        print(f"[Gemini] อ่านไฟล์ภาพไม่สำเร็จ: {e}")
        return None

    return _describe_image_bytes_with_gemini(image_bytes)
