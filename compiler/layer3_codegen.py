import json
import re
import ollama
from dataclasses import asdict
from schemas import IRBlueprint

class Layer3CodeGenerator:
    """Layer 3: 核心代碼生成層 (將 IR JSON 翻譯為高階 nodes.py 腳本)"""
    
    def __init__(self, model_name="qwen3.5:9b"):
        self.model_name = model_name

    def generate_code(self, blueprint: IRBlueprint) -> str:
        print(f"\n[Layer 3] 正在調用 {self.model_name} 將 IR 藍圖編譯為 Python 原始碼...")
        
        blueprint_dict = asdict(blueprint)
        json_payload = json.dumps(blueprint_dict, ensure_ascii=False, indent=2)

        system_prompt = """
你是資深 Python 核心工程師與自動化測試專家。負責將行為樹藍圖 (IR JSON) 翻譯為可執行的 Python 原始碼。

【底層 API 介面規範 (nodes.py)】
必須嚴格遵守以下四種節點類別的實作與參數填寫：
1. `SequenceNode(name: str, children: list)` : 線性執行。
2. `SelectorNode(name: str, children: list)` : 條件/容錯分支。
3. `ConditionNode(name: str, check_prompt: str, max_retries: int, interval: int)` : 用於等待畫面或檢查狀態。
   - 【重要】請務必根據 JSON 節點的 name 與上下文，自動推導並生成精準的英文 VLM 辨識提示詞填入 `check_prompt`。
   - 預設給予 max_retries=5, interval=3。若是「等待載入完成」這類耗時動作，設定 max_retries=200, interval=5。
4. `GuardedActionNode(name: str, target_desc: str, pre_check_prompt: str, game_name: str)` : 執行點擊動作。
   - `target_desc` 填入 JSON 的 target。
   - `pre_check_prompt` 填入目標的英文描述 (供 VLM 提前檢查用)。
   - 【重要】`game_name` 必須填入從 JSON 藍圖或任務上下文中推導出的「遊戲名稱」或「App名稱」(例如: "未來之戰"、"購物商城")。

【程式碼撰寫風格】
1. 開頭必須包含：`from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode`
2. 函式名稱固定為 `def build_startup_tree():`
3. 必須採用「先定義節點變數 -> 再組裝 children」的形式撰寫。
4. 遇到 If-Else 的彈窗或容錯邏輯（SelectorNode），請參考下方範例的「防禦性行為樹設計」：也就是 Selector 的第一個子節點通常是 ConditionNode (檢查是否已經是乾淨狀態)，第二個子節點才是 SequenceNode (執行清除與修復動作)。
"""

        few_shot_user = "請根據『啟動購物商城並處理紅包彈窗』的 JSON 藍圖，產出高質量的行為樹腳本。"
        few_shot_assistant = '''```python
from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode

def build_startup_tree():
    """任務樹：啟動購物商城並處理促銷彈窗"""
    
    # 步驟 1：啟動 App
    step1_launch = GuardedActionNode(
        name="點擊桌面購物商城圖示",
        target_desc="購物商城",
        pre_check_prompt="shopping app icon on desktop",
        game_name="購物商城"
    )

    # 步驟 2：等待初始載入
    step2_wait_loading = ConditionNode(
        name="等待商城首頁載入",
        check_prompt="promo popup, banner, or clean home screen",
        max_retries=200,
        interval=5
    )

    # 步驟 3：防禦性 Selector (狀態判定與清理)
    
    # 3-A: 檢查是否已經在乾淨首頁
    check_home_clean = ConditionNode(
        name="檢查商城首頁",
        check_prompt="home screen without any promo popups",
        max_retries=1,
        interval=3
    )

    # 3-B: 清理紅包彈窗流程 (如果 3-A 失敗則執行)
    click_close_promo = GuardedActionNode(
        name="點擊紅包彈窗的關閉按鈕",
        target_desc="close banner icon",
        pre_check_prompt="promo popup or X icon",
        game_name="購物商城"
    )

    check_home_after_dismiss = ConditionNode(
        name="確認成功進入首頁",
        check_prompt="home screen without any promo popups",
        max_retries=5,
        interval=3
    )

    dismiss_promo_sequence = SequenceNode(
        name="清理促銷彈窗流程",
        children=[click_close_promo, check_home_after_dismiss]
    )

    # 組合 Selector
    step3_handle_popups = SelectorNode(
        name="進入商城首頁 (容錯 Selector)",
        children=[check_home_clean, dismiss_promo_sequence]
    )

    # 最終組合
    return SequenceNode(
        name="最終自動化流程",
        children=[step1_launch, step2_wait_loading, step3_handle_popups]
    )
```'''

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': few_shot_user},
            {'role': 'assistant', 'content': few_shot_assistant},
            {'role': 'user', 'content': f"請嚴格根據以下 IR JSON 藍圖，將其轉換為 Python 腳本（請將推導放在 <think> 區塊中）：\n{json_payload}"}
        ]

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                options={'temperature': 0.1}
            )
            
            raw_output = response['message']['content']
            
            if '</think>' in raw_output:
                think_process, code_part = raw_output.split('</think>', 1)
                think_process = think_process.replace('<think>', '').strip()
            else:
                think_process = "無思考過程"
                code_part = raw_output

            code_match = re.search(r'```python\n(.*?)\n```', code_part, re.DOTALL)
            if not code_match:
                code_match = re.search(r'```\n(.*?)\n```', code_part, re.DOTALL)
                
            final_code = code_match.group(1).strip() if code_match else code_part.strip()
            
            print("\n" + "="*60)
            print("【Layer 3 最終生成的 Python 程式碼 (task_definitions.py)】")
            print("="*60)
            print(final_code)
            print("="*60)
            
            return final_code
            
        except Exception as e:
            print(f"\n[Layer 3] 程式碼生成失敗: {e}")
            return ""

# ==========================================
# 本地串接測試 (整合 Layer 1 -> Layer 2 -> Layer 3)
# ==========================================
if __name__ == "__main__":
    from layer1_intent import Layer1IntentParser
    from layer2_ir import Layer2IRGenerator

    test_input = "點擊未來之戰，然後等待載入畫面。如果跳出廣告彈窗，就點擊右上角的 X 關掉它，然後再點確定。如果沒彈窗就直接等大廳出現。"
    
    l1_parser = Layer1IntentParser(model_name="qwen3.5:9b")
    confirmed_text = l1_parser.parse_and_confirm(test_input)

    if confirmed_text:
        l2_generator = Layer2IRGenerator(model_name="qwen2.5-coder:7b")
        blueprint = l2_generator.generate_blueprint(confirmed_text)

        if blueprint:
            l3_generator = Layer3CodeGenerator(model_name="qwen2.5-coder:7b")
            final_python_script = l3_generator.generate_code(blueprint)
            
            if final_python_script:
                with open("task_definitions.py", "w", encoding="utf-8") as f:
                    f.write(final_python_script)
                print("\n已將生成的腳本儲存至 task_definitions.py！")