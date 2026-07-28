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
    """Layer 1: 先審核原始邏輯 ➔ 再進行 TEXT/ICON 分類與 KB 注入 (Two-Pass)"""
    def __init__(self, model_name="qwen3.5:9b", db_path="compiler/memory/game_knowledge.json"):
        self.model_name = model_name
        self.kb = KnowledgeManager(db_path=db_path)

    def _stage1_parse_structure(self, conversation_history: list) -> str:
        """Pass 1：專注生成 ASCII 樹狀圖與完整捕捉所有目標 (含桌面 App)"""
        response = ollama.chat(
            model=self.model_name,
            messages=conversation_history,
            options={'temperature': 0.2}
        )
        return response['message']['content']

    def _stage2_classify_targets(self, targets: list) -> dict:
        """Pass 2：專注於判斷 TEXT/ICON 並翻譯英文，回傳強型別 JSON 字典"""
        if not targets:
            return {}

        system_prompt = """
你是 UI 實體分類師。請分析輸入的按鈕/圖示名稱，判斷它是實體文字還是圖示，並回傳 JSON：
- 若為畫面上的實體文字：type 填 "TEXT"，val 保持原文字內容。
- 若為圖示/圖形/App Icon：type 填 "ICON"，val 翻譯為精確的英文描述。

[回傳格式範例]
{
  "傳說風暴": {"type": "TEXT", "val": "傳說風暴"},
  "Y": {"type": "ICON", "val": "green corret icon"},
  "取消": {"type": "TEXT", "val": "取消"}
}
"""
        user_prompt = f"請分類並處理以下 UI 目標列表：\n{json.dumps(targets, ensure_ascii=False)}"

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                format='json',
                options={'temperature': 0.0}
            )
            return json.loads(response['message']['content'])
        except Exception as e:
            print(f"[Layer 1 Pass 2] 警告：標籤分類失敗 ({e})，預設使用 TEXT 處理")
            return {t: {"type": "TEXT", "val": t} for t in targets}

    def parse_and_confirm(self, raw_input: str) -> str:
        print(f"\n[Layer 1] 正在調用 {self.model_name} 執行 Pass 1 (邏輯樹狀梳理)...")
        
        # 提示詞關鍵更新：強調連開啟 App 本身也要用「」包裹！
        stage1_system_prompt = """
你是自動化流程分析師，負責將使用者的需求拆解為具體步驟與邏輯分支。

【嚴格規則】
1. 第一行必須提取目標應用程式名稱，格式為：<GAME>遊戲名稱</GAME> (未提及則填 <GAME>None</GAME>)，若是需要點開應用程式，就將遊戲名稱用「」包裹。
2. 所有需要點擊或辨識的目標，請一律用「」包裹名稱。
4. 保持白話易懂，只輸出邏輯步驟與狀態判斷，不需要寫任何程式碼。
"""
        
        conversation_history = [
            {'role': 'system', 'content': stage1_system_prompt},
            {'role': 'user', 'content': f"請分析以下操作需求：\n{raw_input}"}
        ]

        # -------------------------------------------------------------
        # 階段一：人類審核 Pass 1 (確認步驟與「」標記是否齊全)
        # -------------------------------------------------------------
        while True:
            draft_text = self._stage1_parse_structure(conversation_history)
            conversation_history.append({'role': 'assistant', 'content': draft_text})

            game_match = re.search(r'<GAME>(.*?)</GAME>', draft_text, re.DOTALL | re.IGNORECASE)
            game_name = game_match.group(1).strip() if game_match else None
            
            raw_targets = re.findall(r'「(.*?)」', draft_text)
            unique_targets = list(dict.fromkeys(raw_targets))

            print("\n" + "="*60)
            print("【Layer 1 草稿審核】請檢查邏輯與點擊目標是否完整：")
            print("="*60)
            print(draft_text)
            print("-" * 40)
            print(f"抓取到的待分類目標列表: {unique_targets}")
            print("="*60)

            confirm = input("\n請確認邏輯與標記目標是否完整？(輸入 'y' 進入屬性分類 / 或直接輸入修改意見): ").strip()
            
            if confirm.lower() == 'y':
                print("\n[Layer 1] 人類審核通過！開始進行 Pass 2 屬性分類與知識庫對齊...")
                break
            elif confirm:
                print("\n正在根據您的建議重新調整邏輯樹...")
                conversation_history.append({
                    'role': 'user', 
                    'content': f"我有修改建議，請修正剛才的邏輯步驟與「」標記：\n{confirm}"
                })

        # -------------------------------------------------------------
        # 階段二：審核通過後，自動進行 TEXT/ICON 分類與 Knowledge Base 注入
        # -------------------------------------------------------------
        classified_map = {}
        if unique_targets:
            classified_map = self._stage2_classify_targets(unique_targets)

        clean_text = draft_text
        hit_summary = []

        for target in unique_targets:
            info = classified_map.get(target, {"type": "TEXT", "val": target})
            t_type = info.get("type", "TEXT")
            t_val = info.get("val", target)

            # 知識庫對齊 (若知識庫有命中，以知識庫為準)
            kb_hit = self.kb.lookup(game_name, target) if game_name else None
            if kb_hit:
                eng_key = kb_hit['eng_prompt']
                clean_text = clean_text.replace(f"「{target}」", f"「{t_type}:{eng_key}」")
                hit_summary.append(f"  • 「{target}」 ➔ 知識庫命中 Key: \"{eng_key}\" (座標: {kb_hit['norm_x']}, {kb_hit['norm_y']})")
            else:
                clean_text = clean_text.replace(f"「{target}」", f"「{t_type}:{t_val}」")
                hit_summary.append(f"  • 「{target}」 ➔ 自動推導屬性 {t_type}: \"{t_val}\"")

        print("\n" + "="*60)
        print("【Layer 1 最終完成之純淨標記文本】")
        print("="*60)
        print(clean_text)
        
        if hit_summary:
            print("\n" + "-"*40)
            print("[屬性分類與知識庫對齊紀錄]:")
            for log in hit_summary:
                print(log)
        print("="*60)

        return clean_text

# ==========================================
# 本地測試專區
# ==========================================
if __name__ == "__main__":
    parser = Layer1IntentParser(model_name="qwen3.5:9b")
    test_input = "進入未來之戰，然後等待載入畫面。如果跳出廣告彈窗，就點擊右上角的 X 關掉它，然後再點確定。如果沒彈窗就直接等大廳出現。"
    
    final_confirmed_text = parser.parse_and_confirm(test_input)
    print("\n【交接給 Layer 2 的最終文本】:\n")
    print(final_confirmed_text)