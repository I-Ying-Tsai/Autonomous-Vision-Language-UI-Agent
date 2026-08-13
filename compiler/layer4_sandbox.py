import json
import re
import os
import base64
import ollama

# ==========================================
# 模組 1：沙盒微型行為樹引擎
# ==========================================
trace_log = []
sandbox_env = {"current_screen": "unknown", "is_deadlock": False}

def log_trace(msg):
    trace_log.append(msg)
    print(msg)

class ConditionNode:
    def __init__(self, name, check_prompt, max_retries=1, interval=1):
        self.name = name
        self.check_prompt = check_prompt.lower()
    
    def tick(self):
        expected = False
        if "lobby" in self.check_prompt and "lobby" in sandbox_env["current_screen"]:
            expected = True
        elif "popup" in self.check_prompt and "popup" in sandbox_env["current_screen"]:
            expected = True
        elif "ad" in self.check_prompt and "ad popup" in sandbox_env["current_screen"]:
            expected = True
        
        if expected:
            log_trace(f"[TICK] ConditionNode({self.name}) -> 畫面符合預期: SUCCESS")
            return "SUCCESS"
        else:
            log_trace(f"[TICK] ConditionNode({self.name}) -> 畫面不符: FAILURE (當前畫面: {sandbox_env['current_screen']})")
            return "FAILURE"

class GuardedActionNode:
    def __init__(self, name, target_desc, pre_check_prompt=None):
        self.name = name
        self.target_desc = target_desc
    
    def tick(self):
        log_trace(f"[TICK] ActionNode({self.name}) -> 點擊目標: {self.target_desc}")
        if "未來之戰" in self.target_desc:
            log_trace(f"   ↳ (模擬器: App 啟動中...)")
        elif "close" in self.target_desc.lower() or "x" in self.target_desc.lower():
            if sandbox_env.get("is_deadlock"):
                log_trace(f"   ↳ (模擬器: 點擊無效，畫面依然卡死！)")
            else:
                log_trace(f"   ↳ (模擬器: 彈窗已關閉，切換至大廳)")
                sandbox_env["current_screen"] = "game lobby"
        return "SUCCESS"

class SequenceNode:
    def __init__(self, name="Sequence", children=None):
        self.name = name
        self.children = children or []
    
    def tick(self):
        log_trace(f"[TICK] SequenceNode({self.name}) 開始執行...")
        for child in self.children:
            result = child.tick()
            if result == "FAILURE":
                log_trace(f"[TICK] SequenceNode({self.name}) -> 子節點失敗，Sequence 中斷並回傳 FAILURE")
                return "FAILURE"
        log_trace(f"[TICK] SequenceNode({self.name}) -> 全數通過: SUCCESS")
        return "SUCCESS"

class SelectorNode:
    def __init__(self, name="Selector", children=None):
        self.name = name
        self.children = children or []
    
    def tick(self):
        log_trace(f"[TICK] SelectorNode({self.name}) 開始執行...")
        for child in self.children:
            result = child.tick()
            if result == "SUCCESS":
                log_trace(f"[TICK] SelectorNode({self.name}) -> 遇到 SUCCESS，提早結束並回傳 SUCCESS")
                return "SUCCESS"
        log_trace(f"[TICK] SelectorNode({self.name}) -> 全數失敗: FAILURE")
        return "FAILURE"


# ==========================================
# 模組 2：Layer 4 雙腦協作 QA 審查員 (Multi-Agent Evaluator)
# ==========================================
class Layer4SandboxQA:
    def __init__(self, vision_model="qwen3-vl:8b", logic_model="qwen2.5-coder:7b"):
        self.vision_model = vision_model
        self.logic_model = logic_model

    def _encode_image(self, image_path: str) -> str:
        """將圖片轉為 base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _stage1_vision_pass(self, image_path: str) -> str:
        """第一階段：讓視覺模型看圖說故事"""
        print(f"\n[Layer 4 - Stage 1] 啟動視覺大腦 ({self.vision_model}) 分析錯誤截圖...")
        
        prompt = """
        Analyze this screenshot from a mobile device carefully.
        1. Describe the current overall UI state (e.g., is it a game lobby, a loading screen, the home desktop, or a popup ad?).
        2. Are there any visible popups, modal windows, or error messages?
        3. List the most prominent buttons or interactive elements you can see (especially "X", "Close", "Confirm", or specific app icons).
        Keep the description concise but highly accurate.
        """
        
        try:
            res = ollama.chat(
                model=self.vision_model,
                messages=[
                    {
                        'role': 'user', 
                        'content': prompt,
                        'images': [self._encode_image(image_path)]
                    }
                ],
                options={'temperature': 0.1}
            )
            vision_desc = res['message']['content']
            print(f" └─ 視覺回報: {vision_desc.strip()}")
            return vision_desc
        except Exception as e:
            print(f" └─ 視覺分析失敗: {e}")
            return "Vision analysis failed. Unable to provide visual context."

    def evaluate(self, layer1_tree: str, generated_code: str, test_scenario: str, raw_trace: str, error_image_path: str = None) -> dict:
        """第二階段：邏輯大腦進行 CoT 推理與產出修復藍圖"""
        
        # 1. 獲取視覺上下文 (如果有傳圖片)
        vision_context = "No screenshot provided for this error."
        if error_image_path and os.path.exists(error_image_path):
            vision_context = self._stage1_vision_pass(error_image_path)

        print(f"\n[Layer 4 - Stage 2] 啟動邏輯大腦 ({self.logic_model}) 進行綜合診斷...")

        # 2. 嚴格的英文邏輯指令 (套用我們先前優化的提示詞)
        system_prompt = """
You are a QA Test Architect for an autonomous UI agent and an expert in Behavior Tree (BT) underlying logic.
Your task is to review the execution Trace Log, the Visual Context of the screen, and use logical deduction to identify logical flaws in the generated Python code.

[Behavior Tree Fundamentals]
Strictly apply these rules during your deduction:
1. SelectorNode: Executes children from left to right. Returns SUCCESS immediately if ANY child succeeds. Returns FAILURE only if ALL children fail.
2. SequenceNode: Executes children from left to right. Returns FAILURE immediately if ANY child fails. Returns SUCCESS only if ALL children succeed.

[Minimal Modification Principle (CRITICAL)]
Your modification suggestions must be precise like a surgical strike. NEVER destroy, overwrite, or delete existing functional node logic to avoid catastrophic forgetting.
Your `fixed_hint` must explicitly state:
1. Insertion point: Before or after which existing node? Or wrapping which existing node in a new parent?
2. Node type: Should the new logic be a ConditionNode, GuardedActionNode, or SelectorNode?
3. Specific content: Keep original UI targets in Traditional Chinese (e.g., "確定", "未來之戰").

[CoT Deep Thinking Guide] (You MUST enclose your step-by-step reasoning inside <think> tags)
1. Intent Alignment: What specific actions are EXPECTED based on the Layer 1 logic tree?
2. Visual Check: What does the 'Visual Context' report about the current screen? Is the expected target even there?
3. Trace Tracking: At which node did the execution stop or short-circuit in the Trace Log?
4. Logic Deduction: WHY did the code fail? (e.g., Target missing on screen? BT structure didn't handle fallback?)
5. Structural Refactoring: How should the tree be refactored following the Minimal Modification Principle?
6. Conclusion: Assign to L3 if it's a Syntax/API error. Assign to L2 if it's a BT structure/condition logic error. Return PASS if perfect.

[Strict JSON Output Format]
After the </think> tag, output ONLY a JSON dictionary in this exact format:
{
  "status": "PASS" or "FAILED",
  "target_layer": "L2" or "L3" or "NONE",
  "diagnostic_message": "Explanation of the error, referencing BOTH the trace log and the visual context.",
  "fixed_hint": "Specific refactoring instructions strictly following the minimal modification principle."
}
"""
        
        user_prompt = f"""
[Layer 1 Original Logic Tree (Source of Truth)]
{layer1_tree}

[Layer 3 Generated Python Code]
{generated_code}

[Current Sandbox Test Scenario]
{test_scenario}

[Sandbox Execution Trace Log]
{raw_trace}

[Visual Context (What the VLM sees on the screen right now)]
{vision_context}

Please perform deep logical deduction and return the JSON diagnostic report.
"""

        try:
            response = ollama.chat(
                model=self.logic_model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                options={'temperature': 0.1}
            )
            
            raw_output = response['message']['content']
            
            if '</think>' in raw_output:
                think_process, json_part = raw_output.split('</think>', 1)
                think_process = think_process.replace('<think>', '').strip()
                json_part = json_part.strip()
            else:
                think_process = "無思考過程 (Warning: Model bypassed CoT)"
                json_part = raw_output.strip()

            json_match = re.search(r'```json\n(.*?)\n```', json_part, re.DOTALL)
            if not json_match:
                json_match = re.search(r'```\n(.*?)\n```', json_part, re.DOTALL)
            final_json_str = json_match.group(1).strip() if json_match else json_part
            
            print("\n" + "="*60)
            print("【Layer 4 QA 審查員思考過程 (CoT)】")
            print("="*60)
            print(think_process)
            print("="*60)

            return json.loads(final_json_str)
            
        except Exception as e:
            print(f"\n[Layer 4] 診斷失敗 (JSON 解析錯誤或呼叫失敗): {e}")
            return {"status": "FAILED", "target_layer": "NONE", "diagnostic_message": "L4 本身解析錯誤", "fixed_hint": ""}


# ==========================================
# 模組 3：本地執行與模擬測試
# ==========================================
if __name__ == "__main__":
    
    layer1_tree = """
    <GAME>未來之戰</GAME>
    1. 啟動應用程式「未來之戰」。
    2. 判斷是否出現廣告彈窗？
       ┌─── [是] 點擊「ICON:close icon」，再點擊「TEXT:確定」。
       └─── [否] 直接等待大廳畫面出現。
    """
    
    bad_generated_code = """
def build_startup_tree():
    step1 = GuardedActionNode(name="開啟未來之戰", target_desc="未來之戰")
    check_ad = ConditionNode(name="檢查是否有廣告彈窗", check_prompt="ad popup")
    close_ad = GuardedActionNode(name="關閉廣告", target_desc="close icon")
    dismiss_seq = SequenceNode(name="清理廣告", children=[close_ad])
    selector = SelectorNode(name="處理廣告", children=[check_ad, dismiss_seq])
    return SequenceNode(name="主流程", children=[step1, selector])
"""

    print("[Sandbox] 載入虛擬環境與測資...")
    test_scenario = "測資 B：啟動遊戲後，畫面上出現了廣告彈窗 (ad popup)。"
    sandbox_env["current_screen"] = "ad popup"
    sandbox_env["is_deadlock"] = False
    trace_log.clear()

    mock_globals = {
        "SequenceNode": SequenceNode,
        "SelectorNode": SelectorNode,
        "ConditionNode": ConditionNode,
        "GuardedActionNode": GuardedActionNode
    }
    
    try:
        exec(bad_generated_code, mock_globals)
        tree = mock_globals["build_startup_tree"]()
        print("\n[Sandbox] 開始 Tick 行為樹...")
        tree.tick()
    except Exception as e:
        log_trace(f"執行階段崩潰: {e}")

    full_trace = "\n".join(trace_log)
    
    # 呼叫 L4 雙腦 QA (沒有實體圖片時，傳入 None 測試容錯)
    qa = Layer4SandboxQA(vision_model="qwen3-vl:8b", logic_model="qwen2.5-coder:7b")
    report = qa.evaluate(layer1_tree, bad_generated_code, test_scenario, full_trace, error_image_path=None)
    
    print("\n【Layer 4 產出的修復診斷書 (BugReport JSON)】")
    print(json.dumps(report, ensure_ascii=False, indent=2))