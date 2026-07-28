import json
import re
import ollama
# 假設 schemas.py 有定義 IRBlueprint (此處使用字典模擬 Layer 2 的輸出)

class BTRouteExpander:
    """第一階段：將 Layer 2 的 IR JSON 展開為所有可能的實體路徑"""
    
    def expand_paths(self, node_dict: dict) -> list:
        """
        遞迴展開行為樹。
        回傳格式: list of tuple (path_history_list, final_outcome_str)
        """
        step_type = node_dict.get('step_type', 'unknown')
        name = node_dict.get('name', 'Unnamed')
        children = node_dict.get('children', [])

        if step_type in ['guarded_action', 'wait_condition', 'unknown']:
            # 葉節點：只有兩種可能 (成功 或 失敗)
            return [
                ([f"[{name}] = SUCCESS"], "SUCCESS"),
                ([f"[{name}] = FAILURE"], "FAILURE")
            ]
            
        elif step_type == 'sequence':
            # Sequence 規則：遇到 FAILURE 立刻停止，全部 SUCCESS 才算 SUCCESS
            all_paths = []
            current_success_prefixes = [[]]
            
            for child in children:
                child_paths = self.expand_paths(child)
                new_success_prefixes = []
                
                for prefix in current_success_prefixes:
                    for cp_history, cp_outcome in child_paths:
                        if cp_outcome == "FAILURE":
                            # Sequence 斷路，這條路線結束
                            all_paths.append((prefix + cp_history, "FAILURE"))
                        elif cp_outcome == "SUCCESS":
                            # 繼續往下一個子節點走
                            new_success_prefixes.append(prefix + cp_history)
                current_success_prefixes = new_success_prefixes
                
            # 把全部都成功的路線加進去
            for prefix in current_success_prefixes:
                all_paths.append((prefix, "SUCCESS"))
                
            return all_paths

        elif step_type == 'selector':
            # Selector 規則：遇到 SUCCESS 立刻停止，全部 FAILURE 才算 FAILURE
            all_paths = []
            current_failure_prefixes = [[]]
            
            for child in children:
                child_paths = self.expand_paths(child)
                new_failure_prefixes = []
                
                for prefix in current_failure_prefixes:
                    for cp_history, cp_outcome in child_paths:
                        if cp_outcome == "SUCCESS":
                            # Selector 斷路，這條路線成功結束
                            all_paths.append((prefix + cp_history, "SUCCESS"))
                        elif cp_outcome == "FAILURE":
                            # 繼續往下一個子節點嘗試
                            new_failure_prefixes.append(prefix + cp_history)
                current_failure_prefixes = new_failure_prefixes
                
            # 把全部都失敗的路線加進去
            for prefix in current_failure_prefixes:
                all_paths.append((prefix, "FAILURE"))
                
            return all_paths
            
        return []

class RedTeamPruner:
    """第二階段：LLM 測試總監進行啟發式剪枝 (Heuristic Pruning)"""
    def __init__(self, model_name="qwen3.5:9b"):
        self.model_name = model_name

    def prune_and_generate(self, all_paths: list) -> list:
        print(f"\n[Layer 4.1] 啟動測試總監 ({self.model_name}) 進行路徑剪枝...")
        
        # 將物理路徑轉為易讀的字串格式
        path_texts = []
        for i, (history, outcome) in enumerate(all_paths, 1):
            path_str = " ➔ ".join(history)
            path_texts.append(f"Path {i}: {path_str}  => 最終狀態 [{outcome}]")
        
        paths_context = "\n".join(path_texts)

        system_prompt = """
你是自動化系統的 QA 測試總監。
前方工程師利用符號執行 (Symbolic Execution) 展開了行為樹的所有可能物理路徑。

【你的任務】
物理路徑中有很多是「測試價值極低」的 (例如：第一步點擊 App 就失敗)。
請從這些路徑中，挑選出 3 條最值得丟入沙盒測試的測資。
必須包含：
1. 順風局 (Happy Path): 一路成功走到最後。
2. 容錯局 (Recovery Path): 中間有失敗，但觸發了容錯機制 (Selector)，最後成功。
3. 死結局 (Deadlock Path): 容錯機制也失敗，導致任務徹底失敗。

【嚴格 JSON 輸出規範】
不要輸出思考過程，只輸出純 JSON。
{
  "selected_test_cases": [
    {
      "path_id": "你選擇的 Path 數字",
      "scenario_name": "為這個測資取個名字",
      "reason": "為什麼選它？"
    }
  ]
}
"""
        # 注意：我們移除了 Ollama 的 format='json' 參數，避免 Qwen3.5 報錯
        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': f"請從以下路徑中篩選出 3 條測資：\n\n{paths_context}"}
                ],
                options={'temperature': 0.1}
            )
            
            raw_output = response['message']['content']
            
            # 暴力且穩健的 Regex 提取
            json_match = re.search(r'```(?:json)?\n?(.*?)\n?```', raw_output, re.DOTALL)
            final_json_str = json_match.group(1).strip() if json_match else raw_output.strip()
            
            # 清理可能的殘留思考標籤
            if '</think>' in final_json_str:
                final_json_str = final_json_str.split('</think>')[-1].strip()
                
            matrix = json.loads(final_json_str)
            return matrix.get("selected_test_cases", [])
            
        except Exception as e:
            print(f"\n[Layer 4.1] 剪枝解析失敗: {e}")
            print(f"LLM 原始輸出: {raw_output}")
            return []


# ==========================================
# 本地串接測試
# ==========================================
if __name__ == "__main__":
    # 這裡模擬 Layer 2 產出的 IRBlueprint JSON 字典
    # 這就是你所說的「遺失的 Parsing 層的正確輸入格式」！
    layer2_ir_mock = {
        "step_type": "sequence",
        "name": "主流程",
        "children": [
            {
                "step_type": "guarded_action",
                "name": "開啟未來之戰"
            },
            {
                "step_type": "selector",
                "name": "處理廣告",
                "children": [
                    {
                        "step_type": "wait_condition",
                        "name": "檢查是否在大廳 (乾淨狀態)"
                    },
                    {
                        "step_type": "sequence",
                        "name": "清理廣告流程",
                        "children": [
                            {"step_type": "guarded_action", "name": "點擊關閉 X"},
                            {"step_type": "guarded_action", "name": "點擊確定"}
                        ]
                    }
                ]
            }
        ]
    }

    print("[Layer 4.1] 開始物理路徑展開 (BT Path Expansion)...")
    expander = BTRouteExpander()
    all_possible_paths = expander.expand_paths(layer2_ir_mock)
    
    print(f"成功展開 {len(all_possible_paths)} 條所有可能路徑！\n")
    for i, (history, outcome) in enumerate(all_possible_paths, 1):
        print(f"Path {i}: {' ➔ '.join(history)}  => [{outcome}]")

    if all_possible_paths:
        pruner = RedTeamPruner(model_name="qwen3.5:9b")
        test_matrix = pruner.prune_and_generate(all_possible_paths)
        
        print("\n" + "="*60)
        print("【Layer 4.1 最終生成的紅軍測資矩陣 (Test Matrix)】")
        print("="*60)
        print(json.dumps(test_matrix, ensure_ascii=False, indent=2))
        print("="*60)