import json
import os
import re
import ollama
import dataclasses
from compiler.schemas import IRBlueprint, IRStep

class Layer3CodeGenerator:
    def __init__(self, model_name="qwen2.5-coder:7b"):
        self.model_name = model_name
        self.glossary_path = "workspace/glossary.json"

    def _load_glossary(self) -> str:
        if os.path.exists(self.glossary_path):
            try:
                with open(self.glossary_path, "r", encoding="utf-8") as f:
                    glossary_data = json.load(f)
                    return json.dumps(glossary_data, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Layer 3 警告] 無法讀取字典檔: {e}")
        return "{}"

    def _collect_ir_targets(self, steps: list) -> list:
        """遞迴收集 IR 藍圖中所有原始合法的 target 字串"""
        targets = []
        for step in steps:
            if step.target:
                targets.append(step.target.strip())
            if step.children:
                targets.extend(self._collect_ir_targets(step.children))
        return list(dict.fromkeys(targets))

    def _sanitize_code(self, generated_code: str, valid_targets: list) -> str:
        """
        [確定性後處理防禦]
        若 LLM 自作聰明為 target_desc 加了 "app icon"、"按鈕" 等後綴，
        自動將其還原為 IR 原始 target，確保 OCR 與快取 100% 命中。
        """
        sanitized_code = generated_code
        for orig_target in valid_targets:
            # 匹配 target_desc="<包含原始 target 且被多加後綴的字串>"
            pattern = rf'target_desc\s*=\s*["\']({re.escape(orig_target)}[^\'"]*)["\']'
            matches = re.findall(pattern, sanitized_code)
            for full_match in matches:
                if full_match != orig_target:
                    print(f" [L3 後處理校正] 偵測到竄改！已將 '{full_match}' 還原為原始目標: '{orig_target}'")
                    sanitized_code = re.sub(
                        rf'target_desc\s*=\s*["\']{re.escape(full_match)}["\']',
                        f'target_desc="{orig_target}"',
                        sanitized_code
                    )
        return sanitized_code

    def generate_code(self, blueprint: IRBlueprint) -> str:
        print(f"\n[Layer 3] 正在調用 {self.model_name} 將 IR 藍圖編譯為 Python 原始碼...")
        
        dynamic_glossary = self._load_glossary()
        json_payload = json.dumps(dataclasses.asdict(blueprint), ensure_ascii=False, indent=2)

        # -------------------------------------------------------------
        # 1. 強化 Prompt：加入 STRICT IMMUTABILITY 與負面規則
        # -------------------------------------------------------------
        system_prompt = f"""
You are a Senior Core Python Engineer and Automation Testing Expert. Your task is to translate a Behavior Tree blueprint (IR JSON) into executable Python source code.

[CRITICAL: STRICT IMMUTABILITY OF target_desc]
1. `target_desc` MUST 100% EXACTLY MATCH the `target` string defined in the JSON step.
2. NEVER append, modify, or translate `target_desc`! 
   - Prohibited additions: "app icon", "button", "圖示", "按鈕", "圖標".
   - Example Violation: JSON `"target": "未來之戰"` -> `target_desc="未來之戰 app icon"` (FORBIDDEN!)
   - Correct Output: `target_desc="未來之戰"`
3. Any alteration to `target_desc` corrupts the Memory Cache and breaks RapidOCR text matching!

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
   - [CRITICAL] `check_prompt` must describe the TARGET/RESULT state (e.g., "lobby screen", "home screen"), NOT transient states (do NOT use "loading" or "載入中").
4. `GuardedActionNode(name: str, target_desc: str, game_name: str)`: Executes a click action.
   - `target_desc`: Pure original target string from JSON. Do NOT append "app icon" or "button".
   - `game_name`: Game or app context.
   - DO NOT pass `pre_check_prompt`. All screen status verification MUST be done via `ConditionNode`.

[Coding Style Requirements]
1. The top of the file MUST include: `from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode`
2. The function name MUST be exactly: `def build_startup_tree():`
3. Define node variables first -> assemble children later.
"""

        few_shot_user = "請根據『啟動未來之戰』的 JSON 藍圖，產出高質量的行為樹腳本。"
        few_shot_assistant = '''```python
from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode

def build_startup_tree():
    """任務樹：啟動遊戲流程"""
    
    # 注意：target_desc 嚴格保持原始 target，不可追加 "app icon"
    step1_launch = GuardedActionNode(
        name="進入未來之戰應用程式",
        target_desc="未來之戰",
        pre_check_prompt="game icon on desktop",
        game_name="未來之戰"
    )

    return SequenceNode(
        name="最終自動化流程",
        children=[step1_launch]
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
                _, code_part = raw_output.split('</think>', 1)
            else:
                code_part = raw_output

            code_match = re.search(r'```python\n(.*?)\n```', code_part, re.DOTALL)
            if not code_match:
                code_match = re.search(r'```\n(.*?)\n```', code_part, re.DOTALL)
                
            final_code = code_match.group(1).strip() if code_match else code_part.strip()
            
            # -------------------------------------------------------------
            # 2. 確定性後處理：強制驗證並修正 target_desc
            # -------------------------------------------------------------
            valid_targets = self._collect_ir_targets(blueprint.steps)
            sanitized_code = self._sanitize_code(final_code, valid_targets)
            
            print("\n" + "="*60)
            print("【Layer 3 最終生成的 Python 程式碼 (task_definitions.py)】")
            print("="*60)
            print(sanitized_code)
            print("="*60)
            
            return sanitized_code
            
        except Exception as e:
            print(f"\n[Layer 3] 程式碼生成失敗: {e}")
            return ""