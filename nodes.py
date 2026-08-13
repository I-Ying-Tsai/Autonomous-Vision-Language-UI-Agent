import time

# ==========================================
# 基礎類別定義
# ==========================================
class NodeState:
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"

class Node:
    """行為樹基類"""
    # [新增] 擴充 trace_log 陣列，用於記錄犯罪現場
    def tick(self, env, brain, memory, trace_log: list):
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

    def tick(self, env, brain, memory, trace_log: list):
        msg = f"\n▶[Sequence: {self.name}] 啟動執行..."
        print(msg); trace_log.append(msg)
        
        while self.current_child_idx < len(self.children):
            child = self.children[self.current_child_idx]
            state = child.tick(env, brain, memory, trace_log)
            
            if state == NodeState.RUNNING:
                return NodeState.RUNNING
                
            elif state == NodeState.FAILURE:
                fail_msg = f" └─ [Sequence: {self.name}] 在子節點「{child.name}」失敗，Sequence 中斷並回傳 FAILURE。"
                print(fail_msg); trace_log.append(fail_msg)
                self.current_child_idx = 0
                return NodeState.FAILURE
                
            elif state == NodeState.SUCCESS:
                self.current_child_idx += 1
        
        success_msg = f" └─ [Sequence: {self.name}] 所有子節點全數通過，回傳 SUCCESS。"
        print(success_msg); trace_log.append(success_msg)
        self.current_child_idx = 0
        return NodeState.SUCCESS

class SelectorNode(Node):
    def __init__(self, name, children):
        self.name = name
        self.children = children

    def tick(self, env, brain, memory, trace_log: list):
        msg = f"\n▶[Selector: {self.name}] 嘗試容錯分支..."
        print(msg); trace_log.append(msg)
        
        for child in self.children:
            state = child.tick(env, brain, memory, trace_log)
            if state == NodeState.SUCCESS:
                success_msg = f" └─ [Selector: {self.name}] 子節點「{child.name}」成功，短路提早結束並回傳 SUCCESS。"
                print(success_msg); trace_log.append(success_msg)
                return NodeState.SUCCESS
                
        fail_msg = f" └─ [Selector: {self.name}] 所有分支皆失敗！觸發系統熔斷回傳 FAILURE。"
        print(fail_msg); trace_log.append(fail_msg)
        return NodeState.FAILURE

class GuardedActionNode(Node):
    # [保留修正] 強制要求傳入 game_name
    def __init__(self, name, target_desc, pre_check_prompt, game_name):
        self.name = name
        self.target_desc = target_desc
        self.pre_check_prompt = pre_check_prompt
        self.game_name = game_name

    def tick(self, env, brain, memory, trace_log: list):
        msg = f"\n▶[GuardedNode: {self.name}] 開始尋找並點擊「{self.target_desc}」..."
        print(msg); trace_log.append(msg)
        
        screen_width, screen_height = env.get_screen_size()
        
        raw_screen = env.capture_screen()
        from PIL import Image
        with Image.open(raw_screen) as img:
            before_img = img.copy().convert('RGB')

        if self.pre_check_prompt:
            check_msg = f" ├─ [Pre-Check] 門禁檢查: 「{self.pre_check_prompt}」"
            print(check_msg); trace_log.append(check_msg)
            if not brain.check_presence(raw_screen, self.pre_check_prompt):
                fail_msg = f" └─ [GuardedNode 失敗] 前置條件不符合，畫面上沒有發現目標，拒絕點擊！"
                print(fail_msg); trace_log.append(fail_msg)
                return NodeState.FAILURE

        cached_coord = memory.get_target_coord(
            self.game_name, "global_scene", self.target_desc, screen_width, screen_height
        )
        
        if cached_coord:
            global_x, global_y = cached_coord
            cache_msg = f" ├─ [記憶] 命中快取座標: ({global_x}, {global_y})"
            print(cache_msg); trace_log.append(cache_msg)
        else:
            search_msg = f" ├─ [Grounding] 無快取，啟動視覺定位尋找目標..."
            print(search_msg); trace_log.append(search_msg)
            
            # [核心修改] 呼叫大腦的新路由器 locate_target
            coord = brain.locate_target(raw_screen, self.target_desc)
            
            if not coord:
                fail_msg = f" └─ [GuardedNode 失敗] 視覺定位失敗，無法獲取實體座標。"
                print(fail_msg); trace_log.append(fail_msg)
                return NodeState.FAILURE
            global_x, global_y = coord

        env.tap(global_x, global_y, wait_time=5)

        after_screen = env.capture_screen()
        with Image.open(after_screen) as img:
            after_img = img.copy().convert('RGB') 

        verify_msg = f" ├─ [Post-Check] 執行點擊後轉場驗證..."
        print(verify_msg); trace_log.append(verify_msg)
        is_changed = brain.is_screen_changed_math(before_img, after_img)
        
        if not is_changed:
            is_changed = brain.check_screen_changed_vlm(raw_screen, after_screen)

        if is_changed:
            success_msg = f" └─ [GuardedNode 成功] 轉場驗證通過，任務執行完畢並寫入快取。"
            print(success_msg); trace_log.append(success_msg)
            memory.update_target_coord(
                self.game_name, "global_scene", self.target_desc, global_x, global_y, screen_width, screen_height
            )
            return NodeState.SUCCESS
        else:
            fail_msg = f" └─ [GuardedNode 失敗] 點擊後畫面未產生轉場，判斷為點擊無效，清除該座標快取。"
            print(fail_msg); trace_log.append(fail_msg)
            memory.invalidate_target(self.game_name, "global_scene", self.target_desc)
            return NodeState.FAILURE

class ConditionNode(Node):
    def __init__(self, name, check_prompt, max_retries=200, interval=5):
        self.name = name
        self.check_prompt = check_prompt
        self.max_retries = max_retries
        self.interval = interval
        self.retries = 0

    def tick(self, env, brain, memory, trace_log: list):
        # 為了避免在 trace_log 塞滿 200 次的輪詢紀錄，我們只記錄關鍵的開始、成功與超時
        if self.retries == 0:
            msg = f"\n▶[Condition: {self.name}] 開始檢查並等待畫面出現: 「{self.check_prompt}」"
            print(msg); trace_log.append(msg)
            
        screen = env.capture_screen()
        
        if brain.check_presence(screen, self.check_prompt):
            success_msg = f" └─ [Condition 成功] 條件成立！偵測到目標畫面。"
            print(success_msg); trace_log.append(success_msg)
            self.retries = 0
            return NodeState.SUCCESS
        else:
            self.retries += 1
            if self.retries >= self.max_retries:
                fail_msg = f" └─ [Condition 失敗] 已達最大等待次數 ({self.max_retries})，系統宣告等待超時。"
                print(fail_msg); trace_log.append(fail_msg)
                self.retries = 0
                return NodeState.FAILURE
            
            print(f" └─ 條件尚未成立 (第 {self.retries}/{self.max_retries} 次輪詢)，休息 {self.interval} 秒後繼續等待...")
            time.sleep(self.interval)
            return NodeState.RUNNING