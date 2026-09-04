import subprocess
import time
import re
import io
import threading
import cv2
import base64
import numpy as np
from PIL import Image
from config import ADB_PATH, DEVICE_ID

class ScreenFrame:
    """記憶體中的畫面載體，實作 Lazy Evaluation 快取轉換"""
    def __init__(self, raw_bytes: bytes):
        # [防護] 尋找 PNG 魔術數字表頭，過濾 ADB 雜訊
        png_magic = b'\x89PNG\r\n\x1a\n'
        start_idx = raw_bytes.find(png_magic)
        if start_idx < 0:
            raise ValueError("ADB screencap output does not contain a PNG header")
        if start_idx > 0:
            self._raw_bytes = raw_bytes[start_idx:]
        else:
            self._raw_bytes = raw_bytes

        self._cv2_img = None
        self._pil_img = None
        self._b64_str = None
        self.timestamp = time.time()

    @property
    def as_base64(self) -> str:
        """供 Ollama VLM 使用"""
        if self._b64_str is None:
            self._b64_str = base64.b64encode(self._raw_bytes).decode("utf-8")
        return self._b64_str

    @property
    def as_cv2(self) -> np.ndarray:
        """供 OpenCV SoM 標記使用"""
        if self._cv2_img is None:
            nparr = np.frombuffer(self._raw_bytes, np.uint8)
            self._cv2_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if self._cv2_img is None:
                raise ValueError("Unable to decode screenshot as an OpenCV image")
        return self._cv2_img

    @property
    def as_pil(self) -> Image.Image:
        """供 Pillow 像素比對或二分搜裁切使用"""
        if self._pil_img is None:
            self._pil_img = Image.open(io.BytesIO(self._raw_bytes)).convert('RGB')
        return self._pil_img

    def save(self, filepath: str):
        """供系統崩潰時，將原始記憶體 Bytes 寫入硬碟給 Layer 4 診斷用"""
        with open(filepath, 'wb') as f:
            f.write(self._raw_bytes)


class Environment:
    def __init__(self, target_fps: int = 3, startup_timeout: float = 15.0, command_timeout: float = 10.0):
        """
        初始化環境並自動啟動背景串流執行緒
        :param target_fps: 背景擷取幀率 (預設 3 FPS，兼顧即時性與低 CPU 負載)
        """
        if target_fps <= 0 or startup_timeout <= 0 or command_timeout <= 0:
            raise ValueError("FPS and timeout values must be positive")
        self.target_fps = target_fps
        self._latest_frame: ScreenFrame = None
        self._lock = threading.Lock()
        self._adb_lock = threading.Lock()
        self._is_running = False
        self._thread = None
        self.command_timeout = command_timeout

        # 自動啟動背景串流
        self._start_stream(startup_timeout=startup_timeout)

    def _adb_command(self, *args, capture_output=False, text=False):
        command = [ADB_PATH, "-s", DEVICE_ID, *[str(arg) for arg in args]]
        try:
            with self._adb_lock:
                return subprocess.run(
                    command,
                    capture_output=capture_output,
                    text=text,
                    timeout=self.command_timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"ADB command timed out: {' '.join(command)}") from exc

    def _start_stream(self, startup_timeout: float):
        """啟動生產者執行緒"""
        self._is_running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        print(f"[Env] 背景截圖串流已啟動 (目標頻率: {self.target_fps} FPS)...")

        # 等待第一幀成功寫入，防止主執行緒一開始拿到 None
        deadline = time.monotonic() + startup_timeout
        while self.get_latest_frame() is None and self._thread.is_alive():
            if time.monotonic() >= deadline:
                self.stop_stream()
                raise RuntimeError(
                    f"無法在 {startup_timeout:.1f} 秒內從 ADB 裝置 {DEVICE_ID} 取得第一幀"
                )
            time.sleep(0.05)

        if self.get_latest_frame() is None:
            raise RuntimeError("ADB 背景截圖執行緒已停止，且未取得任何畫面")

    def stop_stream(self):
        """關閉背景串流"""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _capture_loop(self):
        """生產者核心：持續向 ADB 擷取最新畫面並加鎖寫入記憶體"""
        interval = 1.0 / self.target_fps

        while self._is_running:
            start_time = time.time()
            try:
                result = self._adb_command("exec-out", "screencap", "-p", capture_output=True)

                if result.returncode == 0 and len(result.stdout) > 0:
                    frame = ScreenFrame(result.stdout)
                    with self._lock:
                        self._latest_frame = frame
            except Exception as e:
                print(f"[Env 背景串流異常]: {e}")

            # 動態休眠，穩定維持 target_fps
            elapsed = time.time() - start_time
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

    def get_latest_frame(self) -> ScreenFrame:
        """消費者核心：安全讀取最新畫面"""
        with self._lock:
            return self._latest_frame

    def capture_screen(self, filename=None, after_timestamp=None, timeout=5.0) -> ScreenFrame:
        """取得最新畫面；可要求畫面必須晚於指定動作時間。"""
        deadline = time.monotonic() + timeout
        while True:
            frame = self.get_latest_frame()
            if frame is not None and (after_timestamp is None or frame.timestamp > after_timestamp):
                if filename:
                    frame.save(filename)
                return frame
            if time.monotonic() >= deadline:
                raise TimeoutError("等待動作後的新畫面逾時")
            time.sleep(0.02)

    def get_screen_size(self, frame: ScreenFrame = None):
        """以實際截圖座標系為準，避免橫豎屏與 wm size 不一致。"""
        frame = frame or self.get_latest_frame()
        if frame is not None:
            image = frame.as_cv2
            if image is not None:
                height, width = image.shape[:2]
                return width, height

        try:
            result = self._adb_command("shell", "wm", "size", capture_output=True, text=True)
            output = result.stdout.strip()
            match = re.findall(r'(\d+)x(\d+)', output)
            if match:
                width, height = int(match[-1][0]), int(match[-1][1])
                return width, height
        except Exception as e:
            print(f"[ADB] 獲取螢幕尺寸失敗: {e}")
        return 1920, 1080

    def tap(self, x, y, wait_time=2, expected_size=None):
        width, height = self.get_screen_size()
        if expected_size and (width, height) != tuple(expected_size):
            raise RuntimeError(
                f"畫面尺寸在定位後由 {tuple(expected_size)} 變為 {(width, height)}，取消點擊"
            )
        x, y = int(x), int(y)
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"拒絕越界點擊 ({x}, {y})，目前畫面為 {width}x{height}")
        print(f"[ADB] 執行點擊: ({x}, {y})")
        result = self._adb_command("shell", "input", "tap", x, y)
        if result.returncode != 0:
            raise RuntimeError(f"ADB tap 失敗，return code={result.returncode}")
        action_timestamp = time.time()
        time.sleep(wait_time)
        return action_timestamp

    def swipe(self, x1, y1, x2, y2, duration=500, wait_time=2):
        width, height = self.get_screen_size()
        coords = (int(x1), int(y1), int(x2), int(y2))
        if not all((0 <= x < width and 0 <= y < height) for x, y in ((coords[0], coords[1]), (coords[2], coords[3]))):
            raise ValueError(f"拒絕越界滑動 {coords}，目前畫面為 {width}x{height}")
        print(f"[ADB] 執行滑動: ({x1}, {y1}) -> ({x2}, {y2})")
        result = self._adb_command("shell", "input", "swipe", *coords, int(duration))
        if result.returncode != 0:
            raise RuntimeError(f"ADB swipe 失敗，return code={result.returncode}")
        action_timestamp = time.time()
        time.sleep(wait_time)
        return action_timestamp
