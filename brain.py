import base64
import json
import ollama
import re
import os
from PIL import Image, ImageChops, ImageStat
from config import MODEL_NAME, WORKSPACE_DIR

class Brain:
    def _get_b64(self, img_path):
        with open(img_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    # ==========================================
    # [通用轉場驗證 1] 純數學像素比對 (支援 RAM 物件直讀)
    # ==========================================
    def is_screen_changed_math(self, img1, img2, threshold=12.0):
        """計算兩張截圖的平均像素差異，可直接接收 PIL Image 物件避免 Disk I/O"""
        try:
            # 如果傳進來的是字串(路徑)，就讀取；如果是物件，就直接用
            if isinstance(img1, str): img1 = Image.open(img1).convert('RGB')
            if isinstance(img2, str): img2 = Image.open(img2).convert('RGB')
            
            diff = ImageChops.difference(img1, img2)
            stat = ImageStat.Stat(diff)
            diff_ratio = (sum(stat.mean) / 3.0) / 255.0 * 100.0
            
            print(f" ├─ [數學比對] 點擊前後畫面像素變更率: {diff_ratio:.2f}% (門檻: {threshold}%)")
            return diff_ratio > threshold
        except Exception as e:
            print(f" ├─ [數學比對異常]: {e}")
            return False

    # ==========================================
    # [通用轉場驗證 2] VLM 通用雙圖對比 (無寫死文字)
    # ==========================================
    def check_screen_changed_vlm(self, img1_path, img2_path):
        """直接詢問 VLM 畫面是否已完成轉場/切換"""
        prompt = "Compare Picture A (before action) and Picture B (after action). Has the user interface or screen navigated or transitioned significantly? Answer strictly YES or NO."
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [self._get_b64(img1_path), self._get_b64(img2_path)]}],
            options={'temperature': 0.1}
        )
        return "YES" in res['message']['content'].upper()

    # ==========================================
    # [標準介面] 門禁與狀態檢查器
    # ==========================================
    def check_presence(self, img_path, prompt_desc):
        prompt = f"Does the text, icon or state for 「{prompt_desc}」 appear clearly in this image? Answer strictly with YES or NO."
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [self._get_b64(img_path)]}],
            options={'temperature': 0.1}
        )
        return "YES" in res['message']['content'].upper()

    def _get_center_point(self, img_path, element_desc, is_landscape=False):
        prompt = f"Find the exact center point of the text or icon 「{element_desc}」. Output coordinates in the format: [y, x] using a 0-1000 scale."
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [self._get_b64(img_path)]}],
            options={'temperature': 0.5, 'top_p': 0.9}
        )
        text = res['message']['content']
        match = re.search(r'\[(\d+),\s*(\d+)\]', text)
        if match:
            v1, v2 = int(match.group(1)), int(match.group(2))
            if is_landscape: return v1, v2
            return v2, v1
        return None, None

    # ==========================================
    # [標準介面] 精確定位器 (自動清理裁切碎片)
    # ==========================================
    def locate_target_binary_search(self, img_path, target_desc):
        """
        [正中央同心圓擴張搜尋]
        不依賴 VLM 初始猜測，直接從螢幕正中央向外擴張尋寶，並搭配 1D 二元切分。
        """
        temp_crop_path = os.path.join(WORKSPACE_DIR, "temp_localization_crop.png")
        
        try:
            with Image.open(img_path) as img:
                width, height = img.size

            cx = width // 2
            cy = height // 2

            print(f"   [Brain] 啟動正中央同心圓擴張，初始落點: ({cx}, {cy})")
            
            # 從中央擴張時，步長設為 200，能以最少次數涵蓋全螢幕
            box_size = 150   
            expansion_step = 150
            max_expansions = 12
            
            prev_left, prev_top, prev_right, prev_bottom = None, None, None, None
            found_box = None
            target_found = False

            # 2. 同心圓擴張尋寶
            for attempt in range(max_expansions + 1):
                left = max(0, cx - box_size // 2)
                top = max(0, cy - box_size // 2)
                right = min(width, cx + box_size // 2)
                bottom = min(height, cy + box_size // 2)
                
                # 防呆：確保邊界合法
                if right <= left: right = left + 1
                if bottom <= top: bottom = top + 1
                
                with Image.open(img_path) as img:
                    img.crop((left, top, right, bottom)).save(temp_crop_path)
                    
                if self.check_presence(temp_crop_path, target_desc):
                    print(f"   [Brain] 擴張第 {attempt} 次 ({right-left}x{bottom-top}): 成功捕獲目標！")
                    target_found = True
                    
                    if attempt == 0:
                        found_box = (left, top, right, bottom)
                    else:
                        # 邊緣鎖定：檢查目標究竟出現在東、南、西、北哪一個新擴張的環帶中
                        strips = {
                            "TOP": (left, top, right, prev_top),
                            "BOTTOM": (left, prev_bottom, right, bottom),
                            "LEFT": (left, prev_top, prev_left, prev_bottom),
                            "RIGHT": (prev_right, prev_top, right, prev_bottom)
                        }
                        strip_matched = False
                        for strip_name, coords in strips.items():
                            sl, st, sr, sb = coords
                            if sr <= sl or sb <= st: continue 
                            
                            with Image.open(img_path) as img:
                                img.crop((sl, st, sr, sb)).save(temp_crop_path)
                                
                            if self.check_presence(temp_crop_path, target_desc):
                                print(f"   [Brain] 邊緣鎖定: 目標位於 [{strip_name}] 區域")
                                found_box = (sl, st, sr, sb)
                                strip_matched = True
                                break
                                
                        if not strip_matched:
                            found_box = (left, top, right, bottom)
                    break
                else:
                    prev_left, prev_top, prev_right, prev_bottom = left, top, right, bottom
                    box_size += expansion_step

            # 3. 1D 二元切分逼近法
            if target_found and found_box:
                cur_left, cur_top, cur_right, cur_bottom = found_box
                print(f"   [Brain] 啟動 1D 二元切分逼近精確座標...")
                
                while (cur_right - cur_left) > 100 or (cur_bottom - cur_top) > 100:
                    if (cur_right - cur_left) > (cur_bottom - cur_top):
                        mid = (cur_left + cur_right) // 2
                        test_box = (cur_left, cur_top, mid, cur_bottom)
                        dir_name = "左半邊"
                    else:
                        mid = (cur_top + cur_bottom) // 2
                        test_box = (cur_left, cur_top, cur_right, mid)
                        dir_name = "上半邊"
                        
                    with Image.open(img_path) as img:
                        img.crop(test_box).save(temp_crop_path)
                        
                    if self.check_presence(temp_crop_path, target_desc):
                        if dir_name == "左半邊": cur_right = mid
                        else: cur_bottom = mid
                    else:
                        if dir_name == "左半邊": cur_left = mid
                        else: cur_top = mid
                        
                global_x = (cur_left + cur_right) // 2
                global_y = (cur_top + cur_bottom) // 2
                return global_x, global_y

            return None

        finally:
            if os.path.exists(temp_crop_path):
                os.remove(temp_crop_path)