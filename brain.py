import base64
import json
import ollama
import re
import os
import cv2
import numpy as np
from typing import Optional, List, Tuple, Dict
from config import MODEL_NAME, WORKSPACE_DIR
from environment import ScreenFrame
from rapidocr_onnxruntime import RapidOCR
import Levenshtein

class GenericUISoMAnnotator:
    def __init__(self, min_ratio: float = 0.008, max_ratio: float = 0.45):
        # 微調 min_ratio 至 0.008，避免漏抓過小的關閉按鈕或圖示
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio

    def generate_candidates_som(self, frame: ScreenFrame, output_path: str) -> Dict[int, Tuple[int, int]]:
        img = frame.as_cv2.copy()

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
        self.som_annotator = GenericUISoMAnnotator(min_ratio=0.008, max_ratio=0.45)
        # 初始化 RapidOCR ONNX 推論引擎
        self.ocr = RapidOCR()

    def _get_b64_from_file(self, img_path):
        with open(img_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def locate_target(
        self,
        frame: ScreenFrame,
        target_desc: str,
        target_type: str = "unknown",
        tier: int = 0,
        context_desc: str = None,
    ) -> Optional[Tuple[int, int]]:
        """
        三階自適應視覺定位路由器 (Adaptive Multi-Tier Grounding)
        - Tier 0: RapidOCR (最快、文字精準，非文字則秒速失敗)
        - Tier 1: SoM 標籤模型 (OpenCV 邊緣標籤 + VLM 選號)
        - Tier 2: VLM 座標回歸 (0-1000 比例尺中心點預測保底)
        """
        clean_desc = target_desc.replace("「", "").replace("」", "").strip()
        clean_context = (context_desc or "").replace("「", "").replace("」", "").strip()
        visual_desc = clean_desc
        if clean_context:
            visual_desc = f"{clean_desc}. Task context: {clean_context}"

        target_type = (target_type or "unknown").lower()
        if target_type == "text":
            pipeline = [
                ("RapidOCR 引擎", lambda: self._locate_text_ocr(frame, clean_desc)),
                ("SoM 標籤模型", lambda: self._locate_target_som(frame, visual_desc)),
                ("VLM 座標回歸 (0-1000)", lambda: self._get_center_point(frame, visual_desc)),
            ]
        elif target_type == "icon":
            pipeline = [
                ("SoM 標籤模型", lambda: self._locate_target_som(frame, visual_desc)),
                ("VLM 座標回歸 (0-1000)", lambda: self._get_center_point(frame, visual_desc)),
            ]
        else:
            pipeline = [
                ("RapidOCR 引擎", lambda: self._locate_text_ocr(frame, clean_desc)),
                ("SoM 標籤模型", lambda: self._locate_target_som(frame, visual_desc)),
                ("VLM 座標回歸 (0-1000)", lambda: self._get_center_point(frame, visual_desc)),
            ]

        selected_idx = tier % len(pipeline)
        method_name, method_fn = pipeline[selected_idx]
        print(f"[Brain] [策略輪替 Tier {selected_idx}] 啟動【{method_name}】尋找: {clean_desc}")

        coord = method_fn()
        if coord:
            return coord

        # 若指定 Tier 未命中，自動順延執行管線中的其餘定位方式
        for i in range(1, len(pipeline)):
            next_idx = (selected_idx + i) % len(pipeline)
            next_name, next_fn = pipeline[next_idx]
            print(f"[Brain] 【{method_name}】無座標，自動順延至【{next_name}】...")
            coord = next_fn()
            if coord:
                return coord

        return None

    def _locate_text_ocr(self, frame: ScreenFrame, target_desc: str) -> Optional[Tuple[int, int]]:
        try:
            result, _ = self.ocr(frame.as_cv2)
            if not result:
                return None

            best_match = None
            highest_ratio = 0.0

            detected_summary = [line[1] for line in result]
            print(f"   [RapidOCR 視線快照] 畫面上看到的文字: {detected_summary}")

            target_clean = target_desc.strip().lower()
            target_chars = set(target_clean)

            for line in result:
                box, detected_text, _ = line
                det_clean = detected_text.strip().lower()

                similarity = Levenshtein.ratio(target_clean, det_clean)
                overlap_ratio = len(target_chars & set(det_clean)) / max(1, len(target_chars))

                if target_clean in det_clean or det_clean in target_clean or similarity > 0.6 or overlap_ratio >= 0.5:
                    combined_score = max(similarity, overlap_ratio)
                    if combined_score > highest_ratio:
                        highest_ratio = combined_score
                        best_match = box

            if best_match:
                center_x = int(sum([p[0] for p in best_match]) / 4)
                center_y = int(sum([p[1] for p in best_match]) / 4)
                print(f"   [Brain] RapidOCR 定位成功！命中「{target_desc}」，實體座標: ({center_x}, {center_y})")
                return center_x, center_y

            print("   [Brain] RapidOCR 畫面未發現匹配字串。")
            return None
        except Exception as e:
            print(f"   [Brain] RapidOCR 辨識異常: {e}")
            return None

    def _locate_target_som(self, frame: ScreenFrame, target_desc: str) -> Optional[Tuple[int, int]]:
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

    def _get_center_point(self, frame: ScreenFrame, target_desc: str):
        prompt = (
            f"Find the exact center point of the UI element or text 「{target_desc}」 in the image. "
            "Only return coordinates when the requested target is clearly visible and belongs to the stated task context. "
            "If it is absent, ambiguous, obscured, or the screen is still loading, output exactly NONE. "
            "Otherwise output coordinates strictly as [y, x] on a 0 to 1000 scale, where [0,0] is top-left and [1000,1000] is bottom-right."
        )
        try:
            res = ollama.chat(
                model=MODEL_NAME,
                messages=[{'role': 'user', 'content': prompt, 'images': [frame.as_base64]}],
                options={'temperature': 0.1}
            )
            text = res['message']['content']
            if '</think>' in text:
                text = text.split('</think>')[-1].strip()

            match = re.search(r'\[\s*(\d+)\s*,\s*(\d+)\s*\]', text)
            if match:
                norm_y, norm_x = int(match.group(1)), int(match.group(2))
                if not (0 <= norm_x <= 1000 and 0 <= norm_y <= 1000):
                    print(f"   [Brain] 模型回傳越界比例座標: [{norm_y}, {norm_x}]")
                    return None

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

    def verify_transition(
        self,
        frame1,
        frame2,
        lower_bound=3.0,
        upper_bound=12.0,
        expected_state=None,
    ) -> bool:
        try:
            if expected_state:
                matched = self.check_presence(frame2, expected_state)
                print(
                    f" ├─ [Postcondition] {expected_state!r}: "
                    f"{'符合' if matched else '不符合'}"
                )
                return matched

            before = frame1.as_cv2
            after = frame2.as_cv2
            if before.shape != after.shape:
                return self.check_screen_changed_vlm(frame1, frame2)

            pixel_delta = cv2.absdiff(before, after)
            changed_mask = np.max(pixel_delta, axis=2) >= 20
            diff_ratio = float(np.count_nonzero(changed_mask)) / changed_mask.size * 100.0

            print(f" ├─ [轉場驗證] 點擊前後像素變更率: {diff_ratio:.2f}%")

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
            try:
                return self.check_screen_changed_vlm(frame1, frame2)
            except Exception as fallback_error:
                print(f" ├─ [VLM 轉場驗證異常]: {fallback_error}")
                return False

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
        content = res['message']['content']
        if '</think>' in content:
            content = content.split('</think>')[-1].strip()
        return bool(re.match(r'^\s*YES\b', content, re.IGNORECASE))

    def check_presence(self, frame: ScreenFrame, prompt_desc):
        return self._check_presence_b64(frame.as_base64, prompt_desc)

    def _check_presence_b64(self, b64_img, prompt_desc):
        clean_desc = prompt_desc.replace("「", "").replace("」", "").strip()
        prompt = (
            "You are a conservative GUI state verifier. Evaluate the requested state "
            "using only visible evidence in the screenshot.\n"
            f"Requested state: {clean_desc}\n"
            "Answer YES only when the entire requested state is clearly satisfied. "
            "Do not answer YES merely because the app logo, artwork, or matching theme is visible. "
            "If readiness or completed loading is requested, splash screens, black transition screens, "
            "loading animations, progress bars, downloads, and uncertain states are NO. "
            "Answer strictly YES or NO."
        )
        try:
            res = ollama.chat(
                model=MODEL_NAME,
                messages=[{'role': 'user', 'content': prompt, 'images': [b64_img]}],
                options={'temperature': 0.1}
            )
            content = res['message']['content']
            if '</think>' in content:
                content = content.split('</think>')[-1].strip()
            return bool(re.match(r'^\s*YES\b', content, re.IGNORECASE))
        except Exception as e:
            print(f"[Brain] check_presence 發生異常: {e}")
            return False
