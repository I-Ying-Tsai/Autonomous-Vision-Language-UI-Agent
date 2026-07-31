import time

# ==========================================
# 基礎類別定義 (修復 Circular Import)
# ==========================================
class NodeState:
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"

class Node:
    """行為樹基類"""
    def tick(self, env, brain, memory):
        raise NotImplementedError

# ==========================================
# 節點實作
# ==========================================
class SequenceNode(Node):
    """具備記憶狀態的順序節點 (Memory Sequence)"""
    def __init__(self, name, children):
        self.name = name
        self.children = children
        self.current_child_idx = 0

    def tick(self, env, brain, memory):
        print(f"\n▶[Sequence: {self.name}] 啟動執行...")
        
        while self.current_child_idx < len(self.children):
            child = self.children[self.current_child_idx]
            state = child.tick(env, brain, memory)
            
            if state == NodeState.RUNNING:
                # 遇到 RUNNING，直接保留當前進度並回傳，下次 Tick 會從同一個子節點繼續
                return NodeState.RUNNING
                
            elif state == NodeState.FAILURE:
                print(f"[Sequence: {self.name}] 在子節點失敗，終止流程。")
                self.current_child_idx = 0  # 失敗時重置指標
                return NodeState.FAILURE
                
            elif state == NodeState.SUCCESS:
                # 成功，推進到下一個子節點
                self.current_child_idx += 1
        
        # 全部子節點執行完畢
        self.current_child_idx = 0  # 重置以供下次使用
        return NodeState.SUCCESS

class SelectorNode(Node):
    def __init__(self, name, children):
        self.name = name
        self.children = children

    def tick(self, env, brain, memory):
        print(f"\n[Selector: {self.name}] 嘗試容錯分支...")
        for child in self.children:
            state = child.tick(env, brain, memory)
            if state == NodeState.SUCCESS:
                return NodeState.SUCCESS
        print(f"[Selector: {self.name}] 所有分支皆失敗！觸發系統熔斷。")
        return NodeState.FAILURE

class GuardedActionNode(Node):
    def __init__(self, name, target_desc, pre_check_prompt, game_name):
        self.name = name
        self.target_desc = target_desc
        self.pre_check_prompt = pre_check_prompt
        self.game_name = game_name

    def tick(self, env, brain, memory):
        print(f"\n[GuardedNode: {self.name}] 開始執行...")
        
        screen_width, screen_height = env.get_screen_size()
        
        raw_screen = env.capture_screen()
        from PIL import Image
        with Image.open(raw_screen) as img:
            before_img = img.copy().convert('RGB')

        if self.pre_check_prompt:
            print(f" ├─ [Pre-Check] 門禁檢查: 「{self.pre_check_prompt}」")
            if not brain.check_presence(raw_screen, self.pre_check_prompt):
                print(f" └─ 前置條件不符合，拒絕點擊！")
                return NodeState.FAILURE

        cached_coord = memory.get_target_coord(
            self.game_name, "global_scene", self.target_desc, screen_width, screen_height
        )
        
        if cached_coord:
            global_x, global_y = cached_coord
            print(f" ├─ [記憶] 命中黃金快取: ({global_x}, {global_y})")
        else:
            print(f" ├─[Grounding] 啟動擴張 + 1D 二元切分定位...")
            coord = brain.locate_target_binary_search(raw_screen, self.target_desc)
            if not coord:
                print(f" └─ 定位失敗，無法獲取實體座標。")
                return NodeState.FAILURE
            global_x, global_y = coord

        env.tap(global_x, global_y, wait_time=5)

        after_screen = env.capture_screen()
        with Image.open(after_screen) as img:
            after_img = img.copy().convert('RGB') 

        print(f" ├─ [Post-Check] 啟動通用轉場驗證...")
        is_changed = brain.is_screen_changed_math(before_img, after_img)
        
        if not is_changed:
            print(f" ├─ 數學像素差異較小，啟動 VLM 雙圖通用轉場比對...")
            is_changed = brain.check_screen_changed_vlm(raw_screen, after_screen)

        if is_changed:
            print(f" └─ 通用轉場驗證通過！成功切換畫面，寫入黃金快取。")
            memory.update_target_coord(
                self.game_name, "global_scene", self.target_desc, global_x, global_y, screen_width, screen_height
            )
            return NodeState.SUCCESS
        else:
            print(f" └─ 點擊後畫面未產生顯著轉場，清除該座標快取！")
            memory.invalidate_target(self.game_name, "global_scene", self.target_desc)
            return NodeState.FAILURE

class ConditionNode(Node):
    """條件節點：純視覺檢查 (專門處理 Loading 輪詢，具備長時等待與固定間隔機制)"""
    def __init__(self, name, check_prompt, max_retries=200, interval=5):
        self.name = name
        self.check_prompt = check_prompt
        self.max_retries = max_retries
        self.interval = interval
        self.retries = 0

    def tick(self, env, brain, memory):
        print(f"\n[Condition: {self.name}] 檢查畫面狀態...")
        screen = env.capture_screen()
        
        if brain.check_presence(screen, self.check_prompt):
            print(f" └─ 條件成立！成功偵測到「{self.check_prompt}」")
            self.retries = 0
            return NodeState.SUCCESS
        else:
            self.retries += 1
            if self.retries >= self.max_retries:
                print(f" └─ 已達最大等待次數 ({self.max_retries})，條件未成立。")
                self.retries = 0
                return NodeState.FAILURE
            
            print(f" └─ 條件尚未成立 (第 {self.retries}/{self.max_retries} 次輪詢)，休息 {self.interval} 秒後繼續等待...")
            time.sleep(self.interval)
            return NodeState.RUNNING