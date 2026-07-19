import base64
import json
import ollama
import re
from config import MODEL_NAME

class Brain:
    def _get_b64(self, img_path):
        with open(img_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def plan(self, img_path, goal):
        """Layer 1: 規劃層 (鎖定文字標籤)"""
        prompt = f"""
        任務目標：{goal}
        請仔細掃描螢幕截圖：
        1. 閱讀畫面上所有的應用程式文字標籤。
        2. 根據是否在畫面上找到「未來之戰」的文字，決定動作：
           - [tap]: 畫面存在「未來之戰」文字。
           - [swipe]: 畫面沒有「未來之戰」文字，需要翻頁。
           - [wait]: 黑屏或載入中。
           - [done]: 已進入遊戲主畫面。

        請嚴格回傳 JSON：
        {{
            "observation": "列出看到的 APP 文字標籤",
            "scene_name": "場景名稱",
            "action_type": "tap/swipe/wait/done",
            "target_element_desc": "未來之戰",
            "goal_achieved": false
        }}
        """
        res = ollama.chat(model=MODEL_NAME, format="json", messages=[
            {'role': 'user', 'content': prompt, 'images': [self._get_b64(img_path)]}
        ])
        return json.loads(res['message']['content'])

    def get_center_point(self, img_path, element_desc, is_landscape=False):
        """Layer 2 & 4: 定位層 (抓取目標中心點，具備橫向螢幕自適應)"""
        prompt = f"Find the exact center point of the text 「{element_desc}」. Output the coordinates in the format: [y, x] using a 0-1000 scale."
        
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [self._get_b64(img_path)]}],
            options={'temperature': 0.5, 'top_p': 0.9}
        )
        text = res['message']['content']
        
        match = re.search(r'\[(\d+),\s*(\d+)\]', text)
        if match:
            v1, v2 = int(match.group(1)), int(match.group(2))
            # 解決 Qwen 橫向螢幕 X/Y 軸錯亂的問題
            if is_landscape:
                cx_1000, cy_1000 = v1, v2
            else:
                cx_1000, cy_1000 = v2, v1
            return cx_1000, cy_1000
        return None, None

    def check_presence(self, img_path, target_desc):
        """Layer 3: 擴張掃描層 (二元判定)"""
        prompt = f"Does the text 「{target_desc}」 appear clearly in this image? Answer strictly with YES or NO."
        res = ollama.chat(
            model=MODEL_NAME, 
            messages=[{'role': 'user', 'content': prompt, 'images': [self._get_b64(img_path)]}],
            options={'temperature': 0.1} # 降低隨機性，要確定的答案
        )
        return "YES" in res['message']['content'].upper()