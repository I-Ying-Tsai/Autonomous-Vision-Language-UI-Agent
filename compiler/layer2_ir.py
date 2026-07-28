import json
import re
import ollama
from schemas import IRBlueprint

class Layer2IRGenerator:
    """Layer 2: 狀態機與邏輯藍圖編譯層 (將 Layer 1 樹狀文本編譯為 Behavior Tree JSON)"""
    
    def __init__(self, model_name="qwen2.5-coder:7b"):
        self.model_name = model_name

    def generate_blueprint(self, layer1_text: str) -> IRBlueprint:
        print(f"\n[Layer 2] 正在調用 {self.model_name} 編譯行為樹藍圖 (IR JSON)...")
        
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
注意:name 欄位是用來描述該步驟的易讀名稱，請將 name 欄位中的「TEXT:...」或「ICON:...」等原始標籤清除，保持文句通順。

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

        # 單樣本 (One-Shot) 範例：使用異界抽卡大師，強迫模型學習結構映射
        few_shot_user = """
請轉換以下文本：
<GAME>異界抽卡大師</GAME>

├─── [開始] 進入「TEXT:異界抽卡大師」應用程式
│     ├─── 等待登入載入完成
│     └─── 判斷：是否有每日簽到彈窗？
│           ├─── [是]
│           │     ├─── 點擊「ICON:gift box icon」
│           │     └─── 點擊「TEXT:立即領取」按鈕
│           └─── [否]
│                 └─── (無操作) 直接等待主城頁面
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
            
        except json.JSONDecodeError as e:
            print(f"\n[Layer 2] JSON 解析失敗: {e}")
            print(f"原始輸出:\n{raw_output}")
            return None
        except Exception as e:
            print(f"\n[Layer 2] 發生非預期錯誤: {e}")
            return None


# ==========================================
# 本地串接測試
# ==========================================
if __name__ == "__main__":
    from layer1_intent import Layer1IntentParser

    # 1. 先執行 Layer 1
    l1_parser = Layer1IntentParser(model_name="qwen3.5:9b")
    test_input = "進入未來之戰，等待載入畫面。如果跳出廣告彈窗，就點擊右上角的 X 關掉它，然後再點確定。如果沒彈窗就直接等大廳出現。"
    
    confirmed_text = l1_parser.parse_and_confirm(test_input)

    # 2. 接續執行 Layer 2
    if confirmed_text:
        l2_generator = Layer2IRGenerator(model_name="qwen2.5-coder:7b")
        blueprint = l2_generator.generate_blueprint(confirmed_text)

        if blueprint:
            print("\n" + "="*60)
            print("【Layer 2 產出的強型別 IRBlueprint 資料結構】")
            print("="*60)
            import pprint
            pprint.pprint(blueprint, indent=2)