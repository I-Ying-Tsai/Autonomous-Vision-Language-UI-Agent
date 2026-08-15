import os
import time
import json
import importlib
from environment import Environment
from brain import Brain
from memory import MemoryManager
from nodes import NodeState
from config import MEMORY_FILE, WORKSPACE_DIR

from compiler.layer1_intent import Layer1IntentParser
from compiler.layer2_ir import Layer2IRGenerator
from compiler.layer3_codegen import Layer3CodeGenerator
from compiler.layer4_sandbox import Layer4SandboxQA
from compiler.schemas import IRBlueprint

BLUEPRINT_PATH = os.path.join(WORKSPACE_DIR, "current_blueprint.json")

def load_blueprint() -> IRBlueprint:
    if os.path.exists(BLUEPRINT_PATH):
        with open(BLUEPRINT_PATH, 'r', encoding='utf-8') as f:
            return IRBlueprint.from_dict(json.load(f))
    return None

def save_blueprint(blueprint: IRBlueprint):
    """保存新世代的 IR 藍圖供未來修補使用"""
    import dataclasses
    with open(BLUEPRINT_PATH, 'w', encoding='utf-8') as f:
        json.dump(dataclasses.asdict(blueprint), f, ensure_ascii=False, indent=2)

def initial_compilation(user_prompt: str):
    """系統第一次啟動時，從自然語言進行完整 AOT 編譯"""
    print("\n[系統] 偵測到全新任務，啟動初始編譯 Pipeline...")
    l1 = Layer1IntentParser(model_name="qwen2.5-coder:7b")
    clean_text = l1.parse_and_confirm(user_prompt)
    
    if clean_text:
        l2 = Layer2IRGenerator(model_name="qwen2.5-coder:7b")
        blueprint = l2.generate_blueprint(clean_text)
        
        if blueprint:
            save_blueprint(blueprint)
            l3 = Layer3CodeGenerator(model_name="qwen2.5-coder:7b")
            code = l3.generate_code(blueprint)
            with open("task_definitions.py", "w", encoding="utf-8") as f:
                f.write(code)
            print("[系統] 初始編譯完成！")
            return True
    return False

def main():
    print("==================================================")
    print(" Autonomous Vision-Language UI Agent")
    print("==================================================")
    
    env = Environment()
    brain = Brain()
    memory = MemoryManager(MEMORY_FILE)
    
    if not os.path.exists("task_definitions.py"):
        user_intent = input("請輸入您的自動化任務需求: ")
        if not initial_compilation(user_intent):
            print("[系統] 初始編譯失敗，程式終止。")
            return

    generation = 1
    while True:
        print(f"\n>>> 啟動第 {generation} 代行為樹執行緒 <<<")
        
        import task_definitions
        importlib.reload(task_definitions) 
        tree = task_definitions.build_startup_tree()
        
        trace_log = []
        tick_count = 0
        max_ticks = 300
        task_success = False
        
        while tick_count < max_ticks:
            tick_count += 1
            print(f"\n--- [ Gen {generation} | Tick {tick_count} ] ---")
            
            state = tree.tick(env, brain, memory, trace_log)
            
            if state == NodeState.SUCCESS:
                print("\n[系統] 任務樹執行完畢！所有目標已順利達成！")
                task_success = True
                break
                
            elif state == NodeState.RUNNING:
                time.sleep(3)
                
            elif state == NodeState.FAILURE:
                print("\n[系統] 任務樹觸發熔斷！啟動黑盒子自我修復機制 (Layer 4)...")
                
                error_img_name = f"error_state_gen{generation}.png"
                error_screen_path = os.path.join(WORKSPACE_DIR, error_img_name)
                
                env.capture_screen().save(error_screen_path)
                
                full_trace_str = "\n".join(trace_log)
                
                with open("task_definitions.py", "r", encoding="utf-8") as f:
                    current_code = f.read()
                current_blueprint = load_blueprint()
                
                if not current_blueprint:
                    print("[系統錯誤] 找不到 current_blueprint.json，無法進行增補修復")
                    return
                
                # ==========================================
                # [核心修改] 呼叫雙腦架構的 Layer 4 並傳入截圖
                # ==========================================
                qa = Layer4SandboxQA(vision_model="qwen3-vl:8b", logic_model="qwen2.5-coder:7b")
                report = qa.evaluate(
                    layer1_tree=current_blueprint.task_name,
                    generated_code=current_code,
                    test_scenario="Runtime 執行期遭遇死結或非預期畫面",
                    raw_trace=full_trace_str,
                    error_image_path=error_screen_path
                )
                
                # 加入防呆機制：確保 report 是字典且格式正確
                if isinstance(report, dict) and report.get("target_layer") in ["L2", "L3"] and report.get("status") != "PASS":
                    print(f"\n[系統] 根據雙腦黑盒子建議進行外科手術重構...")
                    
                    l2 = Layer2IRGenerator(model_name="qwen2.5-coder:7b")
                    new_blueprint = l2.patch_blueprint(current_blueprint, report)
                    
                    if new_blueprint:
                        save_blueprint(new_blueprint)
                        
                        l3 = Layer3CodeGenerator(model_name="qwen2.5-coder:7b")
                        new_code = l3.generate_code(new_blueprint)
                        
                        # 覆寫原本的 Python 腳本
                        with open("task_definitions.py", "w", encoding="utf-8") as f:
                            f.write(new_code)
                            
                        print("\n[系統] 新代碼編譯完成！即將熱重載 (Hot Reload) 進行下一世代演化...")
                        generation += 1
                        break # 跳出內層 Tick 迴圈，啟動新世代
                    else:
                        print("\n[系統] Layer 2 藍圖修補失敗，終止執行。")
                        return
                else:
                    print(f"\n[系統] 雙腦黑盒子判定無法自動修復，或回傳格式異常 (診斷結果: {report.get('diagnostic_message')})。系統終止。")
                    return
                    
        if task_success or tick_count >= max_ticks:
            if tick_count >= max_ticks:
                print("\n[系統] 達到最大 Tick 限制 (300)，強制終止任務。")
            break

if __name__ == "__main__":
    main()