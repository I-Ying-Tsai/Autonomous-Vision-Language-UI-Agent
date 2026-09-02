import json
import os
import re
import ollama

class KnowledgeManager:
    """知識庫管理員：負責載入並匹配遊戲專屬的固定座標與英文 Prompt"""
    def __init__(self, db_path="compiler/memory/game_knowledge.json"):
        self.db_path = db_path
        self.db = self._load_db()

    def _load_db(self) -> dict:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[KnowledgeManager] 警告：無法讀取知識庫檔案 ({e})")
                return {}
        return {}

    def lookup(self, game_name: str, target_keyword: str) -> dict:
        """根據遊戲名稱與中文按鈕名，尋找知識庫中的精準匹配"""
        if not game_name or game_name not in self.db:
            return None
        
        game_data = self.db[game_name].get("global_scene", {})
        target_lower = target_keyword.lower().strip()
        
        for eng_prompt, info in game_data.items():
            if not isinstance(info, dict):
                continue

            raw_aliases = info.get("aliases") or []
            aliases = [str(a).lower() for a in raw_aliases]
            
            if target_lower in aliases or target_lower == eng_prompt.lower():
                return {
                    "eng_prompt": eng_prompt,
                    "norm_x": info.get("norm_x"),
                    "norm_y": info.get("norm_y")
                }
        return None


class Layer1IntentParser:
    """Layer 1: 原始邏輯梳理 ➔ 人工互動式勾選 TEXT/ICON ➔ 知識庫對齊"""
    def __init__(self, model_name="qwen2.5-coder:7b", db_path="compiler/memory/game_knowledge.json"):
        self.model_name = model_name
        self.kb = KnowledgeManager(db_path=db_path)

    def _stage1_parse_structure(self, conversation_history: list) -> str:
        """Pass 1：專注生成乾淨的邏輯樹狀圖 (純文字，嚴禁出現 TEXT/ICON 標籤)"""
        response = ollama.chat(
            model=self.model_name,
            messages=conversation_history,
            options={'temperature': 0.1}
        )
        return response['message']['content']

    def _manual_classify_targets(self, targets: list, game_name: str) -> dict:
        """[人工勾選取代 AI 推斷] 透過互動式 CLI 讓使用者指派屬性"""
        classified_map = {}
        print("\n" + "="*60)
        print("【UI 目標屬性標註】請指定目標為文字 (TEXT) 或圖示 (ICON)：")
        print("="*60)

        for idx, target in enumerate(targets, 1):
            # 先檢查知識庫是否已有紀錄
            kb_hit = self.kb.lookup(game_name, target) if game_name else None
            
            print(f"\n目標 [{idx}/{len(targets)}]: 「{target}」")
            if kb_hit:
                print(f" ├─ [知識庫已有命中] 英文 Key: \"{kb_hit['eng_prompt']}\" (座標: {kb_hit['norm_x']}, {kb_hit['norm_y']})")
                choice = input(" └─ 是否直接套用知識庫？ [Y/n] (預設 Y): ").strip().lower()
                if choice in ["", "y"]:
                    classified_map[target] = {
                        "type": "ICON" if "icon" in kb_hit['eng_prompt'].lower() else "TEXT",
                        "val": kb_hit['eng_prompt'],
                        "from_kb": True,
                        "kb_data": kb_hit
                    }
                    continue

            # 人手動勾選
            print(" ├─ [1] 實體文字 (TEXT) - 畫面可直接看見文字，給 OCR 辨識 (預設)")
            print(" ├─ [2] 圖示/圖標 (ICON) - 無純文字之圖案/App 圖標，需英文視覺描述給 VLM")
            t_choice = input(" └─ 請選擇類型 [1/2] (Enter 預設為 1): ").strip()

            if t_choice == "2":
                t_type = "ICON"
                default_desc = f"{target} icon"
                eng_desc = input(f"    └─ 請輸入該圖示的英文視覺特徵 (預設: \"{default_desc}\"): ").strip()
                t_val = eng_desc if eng_desc else default_desc
            else:
                t_type = "TEXT"
                t_val = target

            classified_map[target] = {
                "type": t_type,
                "val": t_val,
                "from_kb": False
            }

        return classified_map

    def parse_and_confirm(self, raw_input: str) -> str:
        print(f"\n[Layer 1] 正在調用 {self.model_name} 執行邏輯樹狀梳理...")
        
        # 修正後的提示詞：嚴格去除範例中的 TEXT:/ICON: 前綴，防止少樣本污染
        stage1_system_prompt = """
你是自動化流程分析師，負責將使用者的需求拆解為具體步驟與邏輯分支。

【嚴格規則】
1. 第一行必須提取目標應用程式名稱，格式為：<GAME>遊戲名稱</GAME> (未提及則填 <GAME>None</GAME>)。
2. 【極度重要】只有真正需要「點擊 (Tap/Click)」的按鈕、圖標或 App 名稱，才可以使用「」包裹！
3. 【嚴禁括號】任何「等待狀態」、「畫面名稱」、「條件描述」，一律保持白話純文字，絕對嚴禁加上「」括號！
4. 不要產生重複步驟（例如不要同時寫進入 App 又寫點擊 App 圖示）。
5. 嚴禁在「」內自行加入 TEXT: 或 ICON: 前綴！保持最純粹的按鈕名稱。

【格式範例】
<GAME>蝦皮購物</GAME>
├─── [開始] 點擊「蝦皮購物」應用程式
│    ├─── 等待首頁載入完成
│    └─── 判斷：是否出現紅包彈窗？
│          ├─── [是]
│          │    ├─── 點擊「關閉按鈕」
│          │    └─── 點擊「確定」
│          └─── [否]
│               └─── 點擊「每日特賣」
"""
        
        conversation_history = [
            {'role': 'system', 'content': stage1_system_prompt},
            {'role': 'user', 'content': f"請分析以下操作需求：\n{raw_input}"}
        ]

        # 階段一：結構審核
        while True:
            draft_text = self._stage1_parse_structure(conversation_history)
            conversation_history.append({'role': 'assistant', 'content': draft_text})

            game_match = re.search(r'<GAME>(.*?)</GAME>', draft_text, re.DOTALL | re.IGNORECASE)
            game_name = game_match.group(1).strip() if game_match else None
            
            # 提取並過濾可能被 LLM 殘留污染的標籤
            raw_targets = re.findall(r'「(.*?)」', draft_text)
            cleaned_targets = []
            for t in raw_targets:
                clean_t = re.sub(r'^(TEXT|ICON):', '', t).strip()
                cleaned_targets.append(clean_t)
            unique_targets = list(dict.fromkeys(cleaned_targets))

            print("\n" + "="*60)
            print("【Layer 1 草稿審核】請檢查邏輯與點擊目標是否完整：")
            print("="*60)
            print(draft_text)
            print("-" * 40)
            print(f"抓取到的待分類目標列表: {unique_targets}")
            print("="*60)

            confirm = input("\n請確認邏輯是否正確？(輸入 'y' 進入手動屬性標記 / 或直接輸入修改意見): ").strip()
            
            if confirm.lower() == 'y':
                break
            elif confirm:
                print("\n正在根據您的建議重新調整邏輯樹...")
                conversation_history.append({
                    'role': 'user', 
                    'content': f"我有修改建議，請修正剛才的邏輯步驟：\n{confirm}"
                })

        # 階段二：手動指定屬性
        classified_map = self._manual_classify_targets(unique_targets, game_name)

        clean_text = draft_text
        hit_summary = []

        for target, info in classified_map.items():
            t_type = info["type"]
            t_val = info["val"]
            
            # 正則替換（容許原本文字裡可能有殘留的 TEXT:/ICON:）
            pattern = rf'「(?:TEXT:|ICON:)?{re.escape(target)}」'
            clean_text = re.sub(pattern, f"「{t_type}:{t_val}」", clean_text)

            if info.get("from_kb"):
                kb_hit = info["kb_data"]
                hit_summary.append(f"  • 「{target}」 ➔ [知識庫直接套用] Key: \"{t_val}\" (座標: {kb_hit['norm_x']}, {kb_hit['norm_y']})")
            else:
                hit_summary.append(f"  • 「{target}」 ➔ [人工標記] {t_type}: \"{t_val}\"")

        print("\n" + "="*60)
        print("【Layer 1 最終完成之純淨標記文本】")
        print("="*60)
        print(clean_text)
        
        if hit_summary:
            print("\n" + "-"*40)
            print("[屬性對齊紀錄]:")
            for log in hit_summary:
                print(log)
        print("="*60)

        return clean_text