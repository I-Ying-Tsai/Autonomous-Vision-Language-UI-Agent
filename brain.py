import base64
import json
import ollama
import re
import os
import io
import cv2
import numpy as np
from PIL import Image, ImageChops, ImageStat
from typing import Optional, List, Tuple, Dict
from pydantic import BaseModel, Field
from config import MODEL_NAME, WORKSPACE_DIR
from environment import ScreenFrame

class TargetDecision(BaseModel):
    target_label_id: int = Field(description="The integer label ID that corresponds to the target element. Return 0 if none of the labels match the target.")
    reasoning: str = Field(default="", description="Brief explanation for why this label was chosen or why none match.")

class GenericUISoMAnnotator:
    def __init__(self, min_ratio: float = 0.012, max_ratio: float = 0.18):
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio

    def generate_candidates_som(self, frame: ScreenFrame, output_path: str) -> Dict[int, Tuple[int, int]]:
        img = frame.as_cv2.copy() # [修改] 直接從記憶體取 cv2 物件
        
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

        min_dist = int(min_dim * 0.02)
        filtered_boxes = self._deduplicate_candidates(raw_candidates, min_dist=min_dist)
        filtered_boxes = filtered_boxes[:45]

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

    def _get_b64_from_file(self, img_path):
        """僅供讀取本機實體檔案 (如 SoM output) 使用"""
        with open(img_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def locate_target(self, frame: ScreenFrame, target_desc) -> Optional[Tuple[int, int]]:
        print(f"[Brain] 啟動【泛用 SoM 標籤模型】尋找: {target_desc}")
        
        # 第一道防線：SoM 離散預測
        coord = self._locate_target_som(frame, target_desc)
        if coord:
            return coord
            
        # 第二道防線：直接坐標回歸
        print(f"[Brain] SoM 標籤未命中，啟動【VLM 直接座標回歸 (0-1000)】尋找: {target_desc}")
        return self._get_center_point(frame, target_desc)
    
    def _locate_target_som(self, frame: ScreenFrame, target_desc) -> Optional[Tuple[int, int]]:
        som_output_path = os.path.join(WORKSPACE_DIR, "temp_candidates_som.png")
        try:
            label_map = self.som_annotator.generate_candidates_som(frame, som_output_path)
            candidate_count = len(label_map)
            
            if candidate_count == 0:
                print("   [Brain] OpenCV 未搜尋到任何 UI 候選點。")
                return None
                
            prompt = (
                f"There are {candidate_count} numbered labels in the image.\n"
                f"Your target is: 「{target_desc}」.\n"
                "Which label ID exactly points to this target?\n"
                "Return strictly JSON with the format: {\"target_label_id\": <number>, \"reasoning\": \"<explanation>\"}\n"
                "If none of the labels cover the target, return 0 for target_label_id."
            )
            
            res = ollama.chat(
                model=MODEL_NAME, 
                messages=[
                    {'role': 'system', 'content': 'You are a precise GUI Automation Agent. Output ONLY valid JSON matching the schema.'},
                    {'role': 'user', 'content': prompt, 'images': [self._get_b64_from_file(som_output_path)]}
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
                num_match = re.search(r'target_label_id.*?(\d+)', raw_content)
                target_id = int(num_match.group(1)) if num_match else 0
                reason = "Regex Fallback Extraction"
            
            print(f"   [Brain] 模型決策結果: ID=[{target_id}], 理由: {reason}")
            
            if target_id in label_map and target_id != 0:
                coord = label_map[target_id]
                print(f"   [Brain] SoM 定位成功！精確點擊像素座標 : {coord}")
                return coord
            return None
        except Exception as e:
            print(f"   [Brain] SoM 定位發生異常: {e}")
            return None
        finally:
            if os.path.exists(som_output_path):
                os.remove(som_output_path)

    def _get_center_point(self, frame: ScreenFrame, target_desc):
        prompt = (
            f"Find the exact center point of the UI element or text 「{target_desc}」 in the image. "
            "Output the coordinates strictly in the format: [y, x] using a 0 to 1000 scale, where [0,0] is top-left and [1000,1000] is bottom-right."
        )
        try:
            res = ollama.chat(
                model=MODEL_NAME, 
                messages=[{'role': 'user', 'content': prompt, 'images': [frame.as_base64]}],
                options={'temperature': 0.1}
            )
            text = res['message']['content']
            
            # 使用正則提取 [y, x]
            match = re.search(r'\[\s*(\d+)\s*,\s*(\d+)\s*\]', text)
            if match:
                norm_y, norm_x = int(match.group(1)), int(match.group(2))
                
                # 從 0-1000 比例尺映射回實際像素
                img = frame.as_cv2
                h, w, _ = img.shape
                
                pixel_x = int((norm_x / 1000.0) * w)
                pixel_y = int((norm_y / 1000.0) * h)
                
                print(f"   [Brain] VLM 座標回歸成功！[比例尺: {norm_x}, {norm_y}] -> [實體像素: {pixel_x}, {pixel_y}]")
                return pixel_x, pixel_y
            else:
                print(f"   [Brain] 無法從模型輸出解析座標: {text}")
                return None
        except Exception as e:
            print(f"   [Brain] 座標回歸異常: {e}")
            return None

    def verify_transition(self, frame1, frame2, lower_bound=3.0, upper_bound=40.0) -> bool:
        """
        三段式自適應轉場驗證：結合數學極值過濾與 VLM 灰色地帶語意審查
        """
        try:
            # 1. 數學像素計算
            diff = ImageChops.difference(frame1.as_pil, frame2.as_pil)
            stat = ImageStat.Stat(diff)
            diff_ratio = (sum(stat.mean) / 3.0) / 255.0 * 100.0
            
            print(f" ├─ [轉場驗證] 點擊前後像素變更率: {diff_ratio:.2f}%")
            
            # 2. 自適應動態分流 (Adaptive Routing)
            if diff_ratio < lower_bound:
                print(f" ├─ [決策: 數學] 變更率低於 {lower_bound}%，判定為無效點擊。")
                return False
                
            elif diff_ratio > upper_bound:
                print(f" ├─ [決策: 數學] 變更率高於 {upper_bound}%，判定為顯著全螢幕轉場！")
                return True
                
            else:
                print(f" ├─ [決策: VLM] 變更率介於 ({lower_bound}% ~ {upper_bound}%)，AI 判斷中...")
                return self.check_screen_changed_vlm(frame1, frame2)
                
        except Exception as e:
            print(f" ├─ [轉場驗證異常]: {e}，退回保守 VLM 驗證...")
            return self.check_screen_changed_vlm(frame1, frame2)

    def check_screen_changed_vlm(self, frame1, frame2):
        prompt = (
            "Compare Picture A (before action) and Picture B (after action). "
            "Has the user interface transitioned successfully? "
            "Opening a new app, showing a loading screen, a new large popup dialog, or moving to a different page all count as a successful transition (YES). "
            "Only answer YES if there is a functional UI change. Answer strictly YES or NO."
        )
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [frame1.as_base64, frame2.as_base64]}],
            options={'temperature': 0.1}
        )
        return "YES" in res['message']['content'].upper()

    def check_presence(self, frame: ScreenFrame, prompt_desc):
        return self._check_presence_b64(frame.as_base64, prompt_desc)

    def _check_presence_b64(self, b64_img, prompt_desc):
        """內部呼叫方法，支援傳入字串格式的 base64 (供二分搜裁切後使用)"""
        prompt = f"Does the text, icon or state for 「{prompt_desc}」 appear clearly in this image? Answer strictly with YES or NO."
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [b64_img]}],
            options={'temperature': 0.1}
        )
        return "YES" in res['message']['content'].upper()