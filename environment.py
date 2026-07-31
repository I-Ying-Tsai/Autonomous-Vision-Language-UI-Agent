import subprocess
import time
import os
import re
from config import ADB_PATH, DEVICE_ID, WORKSPACE_DIR

class Environment:
    def capture_screen(self, filename="global_screen.png"):
        filepath = os.path.join(WORKSPACE_DIR, filename)
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} shell screencap -p /sdcard/screen.png", shell=True)
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} pull /sdcard/screen.png {filepath}", shell=True)
        return filepath

    def get_screen_size(self):
        """[新增] 獲取設備當前的螢幕解析度 (寬, 高)"""
        try:
            result = subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} shell wm size", shell=True, capture_output=True, text=True)
            output = result.stdout.strip()
            
            match = re.findall(r'(\d+)x(\d+)', output)
            if match:
                width, height = int(match[-1][0]), int(match[-1][1])
                return width, height
        except Exception as e:
            print(f"[ADB] 獲取螢幕尺寸失敗: {e}")
            
        return 1920, 1080

    def tap(self, x, y, wait_time=2):
        print(f"[ADB] 執行點擊: ({x}, {y})")
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} shell input tap {x} {y}", shell=True)
        time.sleep(wait_time)

    def swipe(self, x1, y1, x2, y2, duration=500, wait_time=2):
        print(f"[ADB] 執行滑動: ({x1}, {y1}) -> ({x2}, {y2})")
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} shell input swipe {x1} {y1} {x2} {y2} {duration}", shell=True)
        time.sleep(wait_time)