import os
import json
import time
from datetime import datetime
import config


class StatsManager:
    def __init__(self, device_id):
        self.device_id = device_id
        self.session_stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "watchdog_resets": 0,
            "adb_disconnects": 0,
            "start_time": None,
            "elapsed_seconds": 0,
            "last_score": 0,
            "last_coins": 0,
            "last_boxes": 0,
            "scores_history": [],
            "coins_history": [],
            "boxes_history": []
        }

    def reset_session(self):
        self.session_stats["start_time"] = time.time()
        self.session_stats["total_runs"] = 0
        self.session_stats["successful_runs"] = 0
        self.session_stats["watchdog_resets"] = 0
        self.session_stats["adb_disconnects"] = 0
        self.session_stats["scores_history"].clear()
        self.session_stats["coins_history"].clear()
        self.session_stats["boxes_history"].clear()

    def get_performance_metrics(self):
        """คำนวณอัตราการฟาร์ม Coins/Hr, Runs/Hr, Boxes/Hr และ Success Rate %"""
        if self.session_stats["start_time"] is None:
            return {
                "coins_per_hour": 0,
                "runs_per_hour": 0,
                "boxes_per_hour": 0.0,
                "boxes_per_run": 0.0,
                "total_boxes": 0,
                "success_rate_pct": 0.0
            }

        elapsed_sec = time.time() - self.session_stats["start_time"]
        elapsed_hours = elapsed_sec / 3600.0

        total_coins = sum(self.session_stats["coins_history"])
        total_boxes = sum(self.session_stats["boxes_history"])
        total_runs = self.session_stats["total_runs"]
        success_runs = self.session_stats["successful_runs"]

        coins_per_hr = int(total_coins / elapsed_hours) if elapsed_hours > 0.01 else 0
        runs_per_hr = int(total_runs / elapsed_hours) if elapsed_hours > 0.01 else 0
        boxes_per_hr = round(total_boxes / elapsed_hours, 1) if elapsed_hours > 0.01 else 0.0
        boxes_per_run = round(total_boxes / total_runs, 2) if total_runs > 0 else 0.0
        success_rate = round((success_runs / total_runs) * 100, 1) if total_runs > 0 else 0.0

        return {
            "coins_per_hour": coins_per_hr,
            "runs_per_hour": runs_per_hr,
            "boxes_per_hour": boxes_per_hr,
            "boxes_per_run": boxes_per_run,
            "total_boxes": total_boxes,
            "success_rate_pct": success_rate,
        }

    def load_global_stats(self):
        """โหลดสถิติรวมทั้งหมดจากไฟล์ json (แยกตามพอร์ตของอินสแตนซ์)"""
        stats_path = config.get_stats_file_path(self.device_id)
        if os.path.exists(stats_path):
            try:
                with open(stats_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "all_time_runs": 0,
            "all_time_success": 0,
            "all_time_watchdog_resets": 0,
            "all_time_boxes": 0,
            "history": []
        }

    def save_global_stats(self, session_done=False):
        """บันทึกสถิติรวมและข้อมูลประวัติประจุลงไฟล์ json (แยกตามพอร์ตของอินสแตนซ์)"""
        stats_path = config.get_stats_file_path(self.device_id)
        global_stats = self.load_global_stats()

        if session_done and self.session_stats["start_time"] is not None:
            elapsed = int(time.time() - self.session_stats["start_time"])
            self.session_stats["elapsed_seconds"] = elapsed

            global_stats["all_time_runs"] += self.session_stats["total_runs"]
            global_stats["all_time_success"] += self.session_stats["successful_runs"]
            global_stats["all_time_watchdog_resets"] += self.session_stats["watchdog_resets"]
            global_stats["all_time_boxes"] = global_stats.get("all_time_boxes", 0) + sum(self.session_stats["boxes_history"])

            history_entry = {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "runs": self.session_stats["total_runs"],
                "success": self.session_stats["successful_runs"],
                "boxes": sum(self.session_stats["boxes_history"]),
                "watchdog_resets": self.session_stats["watchdog_resets"],
                "adb_disconnects": self.session_stats["adb_disconnects"],
                "duration_seconds": elapsed
            }
            global_stats["history"].append(history_entry)
            if len(global_stats["history"]) > 50:
                global_stats["history"].pop(0)

        try:
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(global_stats, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Stats] ไม่สามารถเขียนไฟล์สถิติได้: {e}")

    def print_session_report(self):
        """แสดงรายงานสถิติประจุใน Console"""
        if self.session_stats["start_time"] is None:
            return
        elapsed = int(time.time() - self.session_stats["start_time"])
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        print("\n" + "=" * 40)
        print(f"[{self.device_id}] 📊 สรุปสถิติการทำงานในเซสชันนี้")
        print(f"⏱️ เวลาที่เปิดบอท: {h:02d}:{m:02d}:{s:02d}")
        print(f"🔄 เล่นเกมทั้งหมด: {self.session_stats['total_runs']} รอบ")
        print(f"🏆 เล่นผ่านสมบูรณ์: {self.session_stats['successful_runs']} รอบ")
        print(f"⚠️ โดนรีเซ็ตจากบอทค้าง: {self.session_stats['watchdog_resets']} ครั้ง")
        print(f"📡 ADB หลุดสะสม: {self.session_stats['adb_disconnects']} ครั้ง")
        print("=" * 40 + "\n")
