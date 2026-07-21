import time
from environment import Environment
from brain import Brain
from memory import MemoryManager
from nodes import NodeState
from task_definitions import build_startup_tree
from config import MEMORY_FILE

def main():
    print("啟動 Agent (行為樹驅動模式)\n")
    
    # 1. 初始化底層模組
    env = Environment()
    brain = Brain()
    memory = MemoryManager(MEMORY_FILE)
    
    # 2. 載入我們設計的任務樹
    tree = build_startup_tree()
    
    # 3. 執行 Tick 迴圈 (心跳機制)
    tick_count = 0
    max_ticks = 300
    
    while tick_count < max_ticks:
        tick_count += 1
        print(f"=================== [ Tick {tick_count} ] ===================")
        
        # 將環境、大腦、記憶傳遞給整棵樹去執行
        state = tree.tick(env, brain, memory)
        
        if state == NodeState.SUCCESS:
            print("\n[系統] 任務樹執行完畢，已成功達成所有目標！")
            break
        elif state == NodeState.FAILURE:
            print("\n[系統] 任務樹執行失敗！防爆熔斷機制已觸發，請檢查日誌。")
            break
        elif state == NodeState.RUNNING:
            print("\n[系統] 任務樹正在等待條件成立，休息 5 秒後進行下一次 Tick...")
            time.sleep(3)
            
    if tick_count >= max_ticks:
        print("\n[系統] 達到最大 Tick 限制，強制終止任務。")

if __name__ == "__main__":
    main()