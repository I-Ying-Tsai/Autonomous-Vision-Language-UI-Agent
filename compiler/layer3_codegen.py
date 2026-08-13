import json
import os
import re
import ollama
import dataclasses
from compiler.schemas import IRBlueprint

class Layer3CodeGenerator:
    def __init__(self, model_name="qwen2.5-coder:7b"):
        self.model_name = model_name
        # 定義字典檔的路徑
        self.glossary_path = "workspace/glossary.json"

    def _load_glossary(self) -> str:
        """動態讀取外部術語字典"""
        if os.path.exists(self.glossary_path):
            try:
                with open(self.glossary_path, "r", encoding="utf-8") as f:
                    glossary_data = json.load(f)
                    return json.dumps(glossary_data, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Layer 3 警告] 無法讀取字典檔: {e}")
        return "{}"

    def generate_code(self, blueprint: IRBlueprint) -> str:
        print(f"\n[Layer 3] 正在調用 {self.model_name} 將 IR 藍圖編譯為 Python 原始碼...")
        
        dynamic_glossary = self._load_glossary()

        json_payload = json.dumps(dataclasses.asdict(blueprint), ensure_ascii=False, indent=2)

        system_prompt = f"""
You are a Senior Core Python Engineer and Automation Testing Expert. Your task is to translate a Behavior Tree blueprint (IR JSON) into executable Python source code.

[VLM Prompt Generation Rules (Dynamic Glossary)]
To ensure the Vision-Language Model (VLM) accurately recognizes the screen, strictly and preferentially refer to the English translations in the JSON dictionary below when deriving `check_prompt` and `pre_check_prompt`.
If a UI term is not in the dictionary, use the most precise English description that fits the UI structure.

Current Dynamic Glossary:
{dynamic_glossary}

[Underlying API Interface Rules (nodes.py)]
You MUST strictly implement and fill parameters for the following 4 node classes:
1. `SequenceNode(name: str, children: list)`: Linear execution.
2. `SelectorNode(name: str, children: list)`: Conditional/Fallback branches.
3. `ConditionNode(name: str, check_prompt: str, max_retries: int, interval: int)`: Used for waiting or status checking.
   - [CRITICAL] Derive and generate a precise English VLM recognition prompt for `check_prompt` based on the JSON node's name and context.
   - Default to max_retries=5, interval=3. If it's a time-consuming action like "waiting for loading", set max_retries=20, interval=5.
4. `GuardedActionNode(name: str, target_desc: str, pre_check_prompt: str, game_name: str)`: Executes a click action.
   - `target_desc` must be filled with the 'target' value from JSON (Keep original language, e.g., Traditional Chinese).
   - `pre_check_prompt` must be an English description of the target for VLM pre-checking.
   - [CRITICAL] `game_name` must be derived from the JSON blueprint or context (e.g., "未來之戰", "購物商城").

[Coding Style Requirements]
1. The top of the file MUST include: `from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode`
2. The function name MUST be exactly: `def build_startup_tree():`
3. You must write in the format of "defining node variables first -> assembling children later".
4. When encountering If-Else popups or fallback logic (SelectorNode), design defensively: the first child of the Selector should usually be a ConditionNode (checking for a clean state), and the second child a SequenceNode (executing clear/fix actions).
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
        max_retries=20,
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
            {'role': 'user', 'content': f"Please strictly translate the following IR JSON blueprint into a Python script. (Put your reasoning in a <think> block):\n{json_payload}"}
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