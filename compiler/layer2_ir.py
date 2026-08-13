import json
import re
import ollama
from dataclasses import asdict
from compiler.schemas import IRBlueprint

class Layer2IRGenerator:
    """Layer 2: 狀態機與邏輯藍圖編譯層 (支援原始生成與熱增補 Patch 功能)"""
    
    def __init__(self, model_name="qwen2.5-coder:7b"):
        self.model_name = model_name

    def generate_blueprint(self, layer1_text: str) -> IRBlueprint:
        print(f"\n[Layer 2] 正在調用 {self.model_name} 編譯初始行為樹藍圖 (IR JSON)...")
        
        system_prompt = """
你是資深的系統架構師與行為樹編譯器。請將 Layer 1 的樹狀邏輯文本，一字不漏（就事論事）地轉換為嚴格的 Behavior Tree JSON 藍圖。

【節點類型 (step_type) 映射規則】
- sequence: 線性順序執行多個子步驟。
- selector: 用於 If-Else 條件分支、狀態判斷或容錯處理。
- wait_condition: 等待某個畫面、載入或狀態完成。
- guarded_action: 執行具體的點擊或互動動作。

【實體標記 (target & target_type) 提取規則】
仔細觀察文本中被「」包裹的目標：
- 若為「TEXT:內容」 ➔ target="內容", target_type="text"
- 若為「ICON:內容」 ➔ target="內容", target_type="icon"
注意：JSON 中的 target 欄位必須剝離 TEXT: 與 ICON: 前綴，也不要保留「」符號。
注意: name 欄位是用來描述該步驟的易讀名稱，請將 name 欄位中的「TEXT:...」或「ICON:...」等原始標籤清除，保持文句通順。

【JSON Schema 要求】
必須回傳以下格式，直接輸出純 JSON 字串，不要包含 markdown 標籤：
{
  "task_name": "任務名稱",
  "steps": [
    {
      "step_type": "sequence | selector | wait_condition | guarded_action",
      "name": "步驟描述",
      "target": null,
      "target_type": "text | icon | unknown",
      "children": [ ...子節點... ]
    }
  ]
}
"""

        few_shot_user = """
請轉換以下文本：
<GAME>異界抽卡大師</GAME>

├─── [開始] 進入「TEXT:異界抽卡大師」應用程式
│    ├─── 等待登入載入完成
│    └─── 判斷：是否有每日簽到彈窗？
│          ├─── [是]
│          │    ├─── 點擊「ICON:gift box icon」
│          │    └─── 點擊「TEXT:立即領取」按鈕
│          └─── [否]
│               └─── (無操作) 直接等待主城頁面
"""
        few_shot_assistant = """{
  "task_name": "異界抽卡大師_登入流程",
  "steps": [
    {
      "step_type": "guarded_action",
      "name": "進入異界抽卡大師應用程式",
      "target": "異界抽卡大師",
      "target_type": "text",
      "children": []
    },
    {
      "step_type": "wait_condition",
      "name": "等待登入載入完成",
      "target": null,
      "target_type": "unknown",
      "children": []
    },
    {
      "step_type": "selector",
      "name": "判斷：是否有每日簽到彈窗",
      "target": null,
      "target_type": "unknown",
      "children": [
        {
          "step_type": "sequence",
          "name": "If 分支：有彈窗",
          "target": null,
          "target_type": "unknown",
          "children": [
            {
              "step_type": "guarded_action",
              "name": "點擊禮盒圖示",
              "target": "gift box icon",
              "target_type": "icon",
              "children": []
            },
            {
              "step_type": "guarded_action",
              "name": "點擊立即領取",
              "target": "立即領取",
              "target_type": "text",
              "children": []
            }
          ]
        },
        {
          "step_type": "wait_condition",
          "name": "Else 分支：無彈窗_等待主城頁面",
          "target": null,
          "target_type": "unknown",
          "children": []
        }
      ]
    }
  ]
}"""

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': few_shot_user},
            {'role': 'assistant', 'content': few_shot_assistant},
            {'role': 'user', 'content': f"請嚴格就事論事，轉換以下文本：\n{layer1_text}"}
        ]

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                format='json',
                options={'temperature': 0.0}
            )
            
            raw_output = response['message']['content']
            json_str = re.sub(r'```json\n|\n```', '', raw_output).strip()
            
            blueprint_dict = json.loads(json_str)
            blueprint = IRBlueprint.from_dict(blueprint_dict)
            
            print("\n[Layer 2] IR JSON 藍圖編譯成功！強型別斷言通過。")
            return blueprint
            
        except Exception as e:
            print(f"\n[Layer 2] JSON 解析失敗: {e}")
            return None

    def patch_blueprint(self, old_blueprint: IRBlueprint, bug_report: dict) -> IRBlueprint:
        """
        [新增功能] 外科手術式修補：接收舊版 IRBlueprint 與 Layer 4 診斷書，
        在嚴格保留原有正確邏輯的前提下，更新產出新一代 IRBlueprint。
        """
        print(f"\n[Layer 2 Patch] 正在調用 {self.model_name} 對舊藍圖進行外科手術局部增補...")
        
        old_blueprint_dict = asdict(old_blueprint) if hasattr(old_blueprint, "__dataclass_fields__") else old_blueprint
        old_json_str = json.dumps(old_blueprint_dict, ensure_ascii=False, indent=2)
        
        diagnostic_message = bug_report.get("diagnostic_message", "無詳細診斷")
        fixed_hint = bug_report.get("fixed_hint", "無具體修復建議")

        system_prompt = """
你是資深系統架構師與行為樹重構專家。
你的任務是接收「舊版的行為樹藍圖 (Old IR JSON)」與「QA 審查員的修復建議 (Fixed Hint)」，進行外科手術式的最小幅度修改，產出全新一代的 JSON 藍圖。

【極度重要：最小修改原則 (Minimal Invasive Principles)】
1. 嚴格保留舊藍圖中已經存在的所有節點、名稱 (name)、目標 (target) 與結構，絕對不可任意刪除或覆寫現有的正確步驟（避免災難性遺忘）。
2. 仔細閱讀修復建議，精準地在指定的現有節點「之前」或「之後」插入新的條件 (wait_condition) 或動作 (guarded_action)，或是將目標節點包裝進新的 selector/sequence 中。
3. 確保結構完整，遵守 Behavior Tree 的邏輯流轉。

【JSON Schema 要求】
必須回傳以下格式，直接輸出純 JSON 字串，不要包含 markdown 標籤：
{
  "task_name": "任務名稱",
  "steps": [ ... 包含修補後的全新步驟陣列 ... ]
}
"""

        user_prompt = f"""
【舊版 IR JSON 藍圖】
{old_json_str}

【QA 審查員診斷訊息】
{diagnostic_message}

【QA 審查員修復建議 (Fixed Hint)】
{fixed_hint}

請嚴格遵守最小修改原則，重構並產出修正後的全新 Behavior Tree JSON 藍圖：
"""

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                format='json',
                options={'temperature': 0.1}
            )
            
            raw_output = response['message']['content']
            json_str = re.sub(r'```json\n|\n```', '', raw_output).strip()
            
            if '</think>' in json_str:
                json_str = json_str.split('</think>')[-1].strip()
                
            blueprint_dict = json.loads(json_str)
            new_blueprint = IRBlueprint.from_dict(blueprint_dict)
            
            print("\n[Layer 2 Patch] 外科手術增補完成！新一代 IR Blueprint 強型別轉換成功。")
            return new_blueprint
            
        except Exception as e:
            print(f"\n[Layer 2 Patch] 藍圖增補修復失敗: {e}")
            return None