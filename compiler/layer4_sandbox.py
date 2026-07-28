import json
import re
import ollama

# ==========================================
# 模組 1：沙盒微型行為樹引擎 (Mock Engine)
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
# 模組 2：Layer 4 QA 審查員 (LLM Evaluator)
# ==========================================
class Layer4SandboxQA:
    def __init__(self, model_name="qwen3.5:9b"):
        self.model_name = model_name

    def evaluate(self, layer1_tree: str, generated_code: str, test_scenario: str, raw_trace: str) -> dict:
        print(f"\n[Layer 4] 啟動 QA 審查員 ({self.model_name}) 進行軌跡比對與邏輯推理...")

        system_prompt = """
你是自動化系統的 QA 測試架構師，同時也是精通行為樹 (Behavior Tree) 底層運作邏輯的專家。
你的任務是審查沙盒的執行軌跡 (Trace Log)，靠自己的邏輯推演找出程式碼中的邏輯漏洞。

【行為樹運作基礎 (BT Fundamentals)】
請在推演時，嚴格基於以下兩大原則：
1. SelectorNode (選擇節點)：從左到右執行子節點。只要遇到【任何一個】子節點回傳 SUCCESS，就會【立刻停止並回傳 SUCCESS】。只有全部子節點都失敗才回傳 FAILURE。
2. SequenceNode (順序節點)：從左到右執行子節點。只要遇到【任何一個】子節點回傳 FAILURE，就會【立刻停止並回傳 FAILURE】。全部子節點成功才回傳 SUCCESS。

【CoT 深度思考指南】(必須在 <think> 中一步步推演)
1. 意圖對齊：根據 Layer 1 的邏輯樹，在當前測資情境下，【期望】最終發生哪些具體動作？
2. 軌跡追蹤：閱讀 Trace Log，沙盒中【實際】發生了什麼？在哪個節點發生了中斷或提早結束？
3. 邏輯推演 (最關鍵)：結合【BT Fundamentals】，為什麼程式碼會這樣執行？是不是因為某個檢查條件回傳了 SUCCESS，導致父節點 (Selector) 認為任務完成而提前停止了？
4. 結構重構：如果不希望它提早停止，或者希望它能走到後面的 Sequence 節點，目前的條件判斷 (例如：檢查是否有異常) 是不是放錯位置或邏輯顛倒了？應該如何重構條件節點的正反邏輯與排列順序，才能讓行為樹正確流轉？
5. 結論歸屬：語法/API錯誤退回 L3；行為樹結構與條件邏輯錯誤退回 L2。若完全符合預期則 PASS。

【嚴格 JSON 輸出規範】
請在 </think> 之後，只輸出以下格式的 JSON 字典：
{
  "status": "PASS" 或 "FAILED",
  "target_layer": "L2" 或 "L3" 或 "NONE",
  "diagnostic_message": "指出哪個節點引發了短路或錯誤",
  "fixed_hint": "基於你的推演，給出具體的重構建議 (如何調整條件或順序)"
}
"""
        
        user_prompt = f"""
【Layer 1 原始邏輯樹 (Source of Truth)】
{layer1_tree}

【Layer 3 生成的 Python 程式碼】
{generated_code}

【當前沙盒測資情境】
{test_scenario}

【沙盒執行軌跡 (Trace Log)】
{raw_trace}

請進行深度邏輯推演並回傳 JSON 診斷書。
"""

        try:
            response = ollama.chat(
                model=self.model_name,
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
                think_process = "無思考過程"
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
            print(f"\n[Layer 4] 診斷失敗: {e}")
            return {"status": "FAILED", "target_layer": "L4", "diagnostic_message": "L4 本身解析錯誤", "fixed_hint": ""}


# ==========================================
# 模組 3：本地執行與模擬測試 (測試致命 Bug)
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
    print("\n" + "-"*40)
    print("【沙盒原始軌跡 (Trace Log)】")
    print(full_trace)
    print("-"*40)

    # 呼叫 L4 QA 進行推演 (使用 qwen3.5:9b)
    qa = Layer4SandboxQA(model_name="qwen3.5:9b")
    report = qa.evaluate(layer1_tree, bad_generated_code, test_scenario, full_trace)
    
    print("\n【Layer 4 產出的修復診斷書 (BugReport JSON)】")
    print(json.dumps(report, ensure_ascii=False, indent=2))