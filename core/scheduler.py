import time
import random
from datetime import datetime
from config import (
    AUTO_REST_INTERVAL_MINUTES,
    AUTO_REST_DURATION_MINUTES,
)
from notifiers.line_notifier import send_line_message


class SchedulerManager:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.next_rest_time = None
        self.is_resting = False

    def calculate_next_rest(self):
        """คำนวณสุ่มเวลาพักบอทรอบถัดไป"""
        interval = random.randint(*AUTO_REST_INTERVAL_MINUTES) * 60
        self.next_rest_time = time.time() + interval
        print(f"[{self.bot.device_id}] 🕒 [Scheduler] กำหนดการหยุดพักบอทรอบถัดไปในอีก {interval // 60} นาที")

    def check_and_trigger_rest(self):
        """ตรวจสอบว่าถึงกำหนดเวลาพักสายตาของบอทหรือยัง ถ้าถึงจะเข้าสู่โหมดพักนอน"""
        if not self.bot.running or self.next_rest_time is None:
            return False

        if time.time() >= self.next_rest_time:
            self.is_resting = True
            rest_duration_min = random.randint(*AUTO_REST_DURATION_MINUTES)
            rest_duration_sec = rest_duration_min * 60

            msg = f"[{self.bot.device_id}] 😴 [Scheduler] บอทเริ่มหยุดพักสายตาจำลองมนุษย์เป็นเวลา {rest_duration_min} นาที เพื่อความปลอดภัย..."
            print(msg)
            send_line_message(msg)

            rest_end = time.time() + rest_duration_sec
            while time.time() < rest_end:
                if not self.bot.running:
                    self.is_resting = False
                    return False
                time.sleep(1)

            self.is_resting = False
            msg_resume = f"[{self.bot.device_id}] 🚀 [Scheduler] พักสายตาเสร็จแล้ว! บอทเริ่มวิ่งต่อ..."
            print(msg_resume)
            send_line_message(msg_resume)

            self.calculate_next_rest()
            return True

        return False

    def is_within_schedule(self):
        """ตรวจสอบว่าเวลาปัจจุบันอยู่ในช่วงเวลาที่อนุญาตให้บอทรันหรือไม่"""
        if not self.bot.get_setting("SCHEDULE_ENABLED", False):
            return True

        now = datetime.now()
        curr_min = now.hour * 60 + now.minute

        active_hours = self.bot.get_setting("ACTIVE_HOURS", [])
        if not active_hours:
            return True

        for h_start, m_start, h_end, m_end in active_hours:
            start_min = h_start * 60 + m_start
            end_min = h_end * 60 + m_end
            if start_min <= curr_min < end_min:
                return True
        return False

    def check_and_trigger_schedule(self):
        """ตรวจสอบตารางเวลาทำงาน หากอยู่นอกช่วงเวลา บอทจะหยุดพักสลีปและรอจนกว่าจะเข้าช่วงเวลาถัดไป"""
        if not self.bot.running or not self.bot.get_setting("SCHEDULE_ENABLED", False):
            return False

        if not self.is_within_schedule():
            msg = f"[{self.bot.device_id}] ⏰ [Schedule] อยู่นอกช่วงเวลาทำงานที่อนุญาต! บอทจะหยุดพักสลีปชั่วคราว..."
            self.bot.log_info(msg)
            send_line_message(msg)

            while self.bot.running and not self.is_within_schedule():
                check_interval = float(self.bot.get_setting("SCHEDULE_CHECK_INTERVAL", 30) or 30)
                time.sleep(check_interval)

            if not self.bot.running:
                return False

            msg_resume = f"[{self.bot.device_id}] ⏰ [Schedule] เข้าสู่ช่วงเวลาทำงานแล้ว! บอทเริ่มรันต่อ..."
            self.bot.log_info(msg_resume)
            send_line_message(msg_resume)
            return True
        return False
