import subprocess
import time
import os
from config import ADB_PATH, DEVICE_ID, WORKSPACE_DIR

class Environment:
    def capture_screen(self, filename="global_screen.png"):
        filepath = os.path.join(WORKSPACE_DIR, filename)
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} shell screencap -p /sdcard/screen.png", shell=True)
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} pull /sdcard/screen.png {filepath}", shell=True)
        return filepath

    def tap(self, x, y, wait_time=2):
        print(f"[ADB] 執行點擊: ({x}, {y})")
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} shell input tap {x} {y}", shell=True)
        time.sleep(wait_time)

    def swipe(self, x1, y1, x2, y2, duration=500, wait_time=2):
        print(f"[ADB] 執行滑動: ({x1}, {y1}) -> ({x2}, {y2})")
        subprocess.run(f"{ADB_PATH} -s {DEVICE_ID} shell input swipe {x1} {y1} {x2} {y2} {duration}", shell=True)
        time.sleep(wait_time)