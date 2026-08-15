import base64
import json
import ollama
import re
import os
import cv2
import numpy as np
from PIL import Image, ImageChops, ImageStat
from typing import Optional, List, Tuple, Dict
from pydantic import BaseModel, Field
from config import MODEL_NAME, WORKSPACE_DIR

class XButtonDecision(BaseModel):
    target_label_id: int = Field(
        description="The integer label ID that corresponds to the close 'X' button of the main dialog window."
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation for why this label was chosen."
    )

class GenericUISoMAnnotator:
    """
    泛用型 UI 標籤標註器 (改用 RETR_LIST 深入抓取彈窗內部所有按鈕)
    """
    def __init__(self, min_ratio: float = 0.012, max_ratio: float = 0.18):
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio

    def generate_candidates_som(self, image_path: str, output_path: str) -> Dict[int, Tuple[int, int]]:
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"無法載入圖片：{image_path}")
        
        orig_h, orig_w, _ = img.shape
        min_dim = min(orig_h, orig_w)
        
        min_size = int(min_dim * self.min_ratio)
        max_size = int(min_dim * self.max_ratio)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edged = cv2.Canny(gray, 30, 120)
        
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dilated = cv2.dilate(edged, kernel, iterations=1)

        contours, _ = cv2.findContours(dilated, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        
        raw_candidates = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)

            if min_size <= w <= max_size and min_size <= h <= max_size:
                if 0.3 <= aspect_ratio <= 3.0:
                    raw_candidates.append((x, y, w, h))

        # 去重：以短邊的 2% 作為去重半徑
        min_dist = int(min_dim * 0.02)
        filtered_boxes = self._deduplicate_candidates(raw_candidates, min_dist=min_dist)

        # 放寬最多候選數量至 45 個
        filtered_boxes = filtered_boxes[:80]

        overlay = img.copy()
        labeled_img = img.copy()
        label_map: Dict[int, Tuple[int, int]] = {}

        for idx, (x, y, w, h) in enumerate(filtered_boxes, start=1):
            center_x = x + w // 2
            center_y = y + h // 2
            label_map[idx] = (center_x, center_y)

            text = f"[{idx}]"
            font_scale = max(0.4, min_dim / 1600.0)
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)

            label_x = max(5, x)
            label_y = max(th + 5, y - 5)

            cv2.rectangle(overlay, (label_x - 2, label_y - th - 2), (label_x + tw + 2, label_y + 2), (255, 50, 50), -1)
            cv2.putText(labeled_img, text, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 2, cv2.LINE_AA)

        cv2.addWeighted(overlay, 0.4, labeled_img, 0.6, 0, labeled_img)
        cv2.imwrite(output_path, labeled_img)
        
        return label_map

    def _deduplicate_candidates(self, boxes: List[Tuple[int, int, int, int]], min_dist: int) -> List[Tuple[int, int, int, int]]:
        boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
        unique_boxes = []
        for b in boxes:
            x, y, w, h = b
            cx, cy = x + w // 2, y + h // 2
            overlap = False
            for ux, uy, uw, uh in unique_boxes:
                ucx, ucy = ux + uw // 2, uy + uh // 2
                if abs(cx - ucx) < min_dist and abs(cy - ucy) < min_dist:
                    overlap = True
                    break
            if not overlap:
                unique_boxes.append(b)
        return unique_boxes


class Brain:
    def __init__(self):
        self.som_annotator = GenericUISoMAnnotator(min_ratio=0.012, max_ratio=0.18)

    def _get_b64(self, img_path):
        with open(img_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def locate_target(self, img_path, target_desc) -> Optional[Tuple[int, int]]:
        is_close_btn = any(kw in target_desc.lower() for kw in ["x", "close", "關閉", "取消"])
        
        if is_close_btn:
            print(f"[Brain] 偵測到關閉按鈕意圖，啟動【SoM 特化視覺模型】尋找: {target_desc}")
            coord = self._locate_x_button_som(img_path)
            if coord:
                return coord
            print("[Brain] SoM 特化定位失敗，退回泛用搜尋 (Fallback)...")
            
        print(f"[Brain] 啟動【泛用二分搜/VLM預測模型】尋找: {target_desc}")
        return self.locate_target_binary_search(img_path, target_desc)

    def _locate_x_button_som(self, img_path) -> Optional[Tuple[int, int]]:
        som_output_path = os.path.join(WORKSPACE_DIR, "temp_x_candidates_som.png")
        try:
            label_map = self.som_annotator.generate_candidates_som(img_path, som_output_path)
            candidate_count = len(label_map)
            
            if candidate_count == 0:
                print("   [Brain] OpenCV 未搜尋到候選點。")
                return None
                
            prompt = (
                f"There are {candidate_count} numbered labels marked with [x] in the image.\n"
                "Which label ID is the CLOSE ('X') button or DISMISS button for the modal popup / dialog window?\n"
                "Return strictly JSON with the format: {\"target_label_id\": <number>, \"reasoning\": \"<explanation>\"}"
            )
            
            print(f"   [Brain] 成功篩選出 {candidate_count} 個候選點，發送給 VLM 進行決策...")
            res = ollama.chat(
                model=MODEL_NAME, 
                messages=[
                    {'role': 'system', 'content': 'You are a precise GUI Automation Agent. Output ONLY valid JSON matching the schema.'},
                    {'role': 'user', 'content': prompt, 'images': [self._get_b64(som_output_path)]}
                ],
                options={'temperature': 0.1}
            )
            
            raw_content = res['message']['content']
            
            if '</think>' in raw_content:
                raw_content = raw_content.split('</think>')[-1].strip()

            json_match = re.search(r'\{.*?\}', raw_content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                target_id = int(data.get("target_label_id", 0))
                reason = data.get("reasoning", "")
            else:
                # 暴力正則提取數字作為備援
                num_match = re.search(r'target_label_id.*?(\d+)', raw_content)
                target_id = int(num_match.group(1)) if num_match else 0
                reason = "Regex Fallback Extraction"

            print(f"   [Brain] 模型決策結果: ID=[{target_id}], 理由: {reason}")
            
            if target_id in label_map:
                coord = label_map[target_id]
                print(f"   精確點擊像素座標 : {coord}")
                return coord
            else:
                print(f"   [Brain] 模型選取的標籤編號 [{target_id}] 無效或不在候選列表中。")
                return None
                
        except Exception as e:
            print(f"   [Brain] SoM 定位發生異常: {e}")
            return None
        finally:
            if os.path.exists(som_output_path):
                os.remove(som_output_path)

    # ---------------- 轉場與輔助比對 ----------------
    def is_screen_changed_math(self, img1, img2, threshold=12.0):
        try:
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

    def check_screen_changed_vlm(self, img1_path, img2_path):
        prompt = "Compare Picture A (before action) and Picture B (after action). Has the user interface or screen navigated or transitioned significantly? Answer strictly YES or NO."
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [self._get_b64(img1_path), self._get_b64(img2_path)]}],
            options={'temperature': 0.1}
        )
        return "YES" in res['message']['content'].upper()

    def check_presence(self, img_path, prompt_desc):
        prompt = f"Does the text, icon or state for 「{prompt_desc}」 appear clearly in this image? Answer strictly with YES or NO."
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [self._get_b64(img_path)]}],
            options={'temperature': 0.1}
        )
        return "YES" in res['message']['content'].upper()

    def locate_target_binary_search(self, img_path, target_desc):
        temp_crop_path = os.path.join(WORKSPACE_DIR, "temp_localization_crop.png")
        try:
            with Image.open(img_path) as img:
                width, height = img.size

            cx = width // 2
            cy = height // 2

            print(f"   [Brain] 啟動正中央同心圓擴張，初始落點: ({cx}, {cy})")
            
            box_size = 150   
            expansion_step = 150
            max_expansions = 12
            
            prev_left, prev_top, prev_right, prev_bottom = None, None, None, None
            found_box = None
            target_found = False

            for attempt in range(max_expansions + 1):
                left = max(0, cx - box_size // 2)
                top = max(0, cy - box_size // 2)
                right = min(width, cx + box_size // 2)
                bottom = min(height, cy + box_size // 2)
                
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