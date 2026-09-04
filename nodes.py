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
    def tick(self, env, brain, memory, trace_log: list):
        raise NotImplementedError

    def reset(self):
        """重設節點的執行狀態，供父節點完成、失敗或取消時呼叫。"""


# ==========================================
# 節點實作
# ==========================================
class SequenceNode(Node):
    """具備記憶狀態的順序節點 (Memory Sequence)"""
    def __init__(self, name, children):
        self.name = name
        self.children = children
        self.current_child_idx = 0
        self._announced = False

    def tick(self, env, brain, memory, trace_log: list):
        if not self._announced:
            msg = f"\n▶[Sequence: {self.name}] 啟動執行..."
            print(msg); trace_log.append(msg)
            self._announced = True

        while self.current_child_idx < len(self.children):
            child = self.children[self.current_child_idx]
            state = child.tick(env, brain, memory, trace_log)

            if state == NodeState.RUNNING:
                return NodeState.RUNNING

            elif state == NodeState.FAILURE:
                fail_msg = f" └─ [Sequence: {self.name}] 在子節點「{child.name}」失敗，Sequence 中斷並回傳 FAILURE。"
                print(fail_msg); trace_log.append(fail_msg)
                self.reset()
                return NodeState.FAILURE

            elif state == NodeState.SUCCESS:
                self.current_child_idx += 1

        success_msg = f" └─ [Sequence: {self.name}] 所有子節點全數通過，回傳 SUCCESS。"
        print(success_msg); trace_log.append(success_msg)
        self.reset()
        return NodeState.SUCCESS

    def reset(self):
        self.current_child_idx = 0
        self._announced = False
        for child in self.children:
            child.reset()

class SelectorNode(Node):
    def __init__(self, name, children):
        self.name = name
        self.children = children
        self.current_child_idx = 0
        self._announced = False

    def tick(self, env, brain, memory, trace_log: list):
        if not self._announced:
            msg = f"\n▶[Selector: {self.name}] 嘗試容錯分支..."
            print(msg); trace_log.append(msg)
            self._announced = True

        while self.current_child_idx < len(self.children):
            child = self.children[self.current_child_idx]
            state = child.tick(env, brain, memory, trace_log)
            if state == NodeState.SUCCESS:
                success_msg = f" └─ [Selector: {self.name}] 子節點「{child.name}」成功，短路提早結束並回傳 SUCCESS。"
                print(success_msg); trace_log.append(success_msg)
                self.reset()
                return NodeState.SUCCESS
            if state == NodeState.RUNNING:
                return NodeState.RUNNING
            self.current_child_idx += 1

        fail_msg = f" └─ [Selector: {self.name}] 所有分支皆失敗！觸發系統熔斷回傳 FAILURE。"
        print(fail_msg); trace_log.append(fail_msg)
        self.reset()
        return NodeState.FAILURE

    def reset(self):
        self.current_child_idx = 0
        self._announced = False
        for child in self.children:
            child.reset()

class ActionNode(Node):
    """
    純粹的動作節點：專注於執行點擊與轉場確認。
    門禁檢查已回歸 ConditionNode，不再於動作前強加 VLM 檢查。
    """
    def __init__(
        self,
        name,
        target_desc,
        game_name,
        target_type="unknown",
        context_desc=None,
        post_check_prompt=None,
        pre_check_prompt=None,
    ):
        self.name = name
        self.target_desc = target_desc
        self.game_name = game_name
        self.target_type = target_type
        self.context_desc = context_desc
        self.post_check_prompt = post_check_prompt

    def tick(self, env, brain, memory, trace_log: list):
        msg = f"\n▶[ActionNode: {self.name}] 執行點擊「{self.target_desc}」..."
        print(msg); trace_log.append(msg)

        raw_screen = env.capture_screen()
        screen_width, screen_height = env.get_screen_size(raw_screen)

        # 1. 優先查詢快取（快取命中即零 VLM 延遲，直接點擊！）
        scene_name = self.context_desc or "global_scene"
        cached_coord = memory.get_target_coord(
            self.game_name, scene_name, self.target_desc, screen_width, screen_height
        )

        if cached_coord:
            global_x, global_y = cached_coord
            cache_msg = f" ├─ [記憶] 命中快取座標: ({global_x}, {global_y})"
            print(cache_msg); trace_log.append(cache_msg)
        else:
            # 2. 快取未命中，啟動三階定位管線（找不到會直接回傳 None 並中斷）
            search_msg = f" ├─ [Grounding] 無快取，啟動視覺定位尋找目標..."
            print(search_msg); trace_log.append(search_msg)

            if self.context_desc:
                coord = brain.locate_target(
                    raw_screen,
                    self.target_desc,
                    target_type=self.target_type,
                    context_desc=self.context_desc,
                )
            else:
                coord = brain.locate_target(
                    raw_screen,
                    self.target_desc,
                    target_type=self.target_type,
                )
            if not coord:
                fail_msg = f" └─ [ActionNode 失敗] 畫面上未發現目標「{self.target_desc}」，動作終止。"
                print(fail_msg); trace_log.append(fail_msg)
                return NodeState.FAILURE
            global_x, global_y = coord

        # 3. 點擊
        try:
            action_timestamp = env.tap(
                global_x,
                global_y,
                wait_time=2,
                expected_size=(screen_width, screen_height),
            )
            after_screen = env.capture_screen(
                after_timestamp=action_timestamp,
                timeout=5.0,
            )
        except (RuntimeError, TimeoutError, ValueError) as exc:
            fail_msg = f" └─ [ActionNode 失敗] 裝置操作失敗: {exc}"
            print(fail_msg); trace_log.append(fail_msg)
            memory.invalidate_target(self.game_name, scene_name, self.target_desc)
            return NodeState.FAILURE

        # 4. 轉場驗證 (Post-Check)
        verify_msg = f" ├─ [Post-Check] 執行點擊後轉場驗證..."
        print(verify_msg); trace_log.append(verify_msg)

        # Older Brain implementations only accept the two screen frames.  Do
        # not pass the optional keyword unless the IR actually supplied a
        # semantic postcondition.  This keeps mixed-version installations from
        # crashing while preserving strict state verification when requested.
        if self.post_check_prompt:
            is_changed = brain.verify_transition(
                raw_screen,
                after_screen,
                expected_state=self.post_check_prompt,
            )
        else:
            is_changed = brain.verify_transition(raw_screen, after_screen)
        if is_changed:
            success_msg = f" └─ [ActionNode 成功] 轉場通過，寫入/更新座標快取。"
            print(success_msg); trace_log.append(success_msg)
            memory.update_target_coord(
                self.game_name, scene_name, self.target_desc, global_x, global_y, screen_width, screen_height
            )
            return NodeState.SUCCESS
        else:
            fail_msg = f" └─ [ActionNode 失敗] 點擊後無畫面轉場，清除該座標快取。"
            print(fail_msg); trace_log.append(fail_msg)
            memory.invalidate_target(self.game_name, scene_name, self.target_desc)
            return NodeState.FAILURE

class GuardedActionNode(ActionNode):
    """向下相容名稱；門禁與 postcondition 由明確的節點參數控制。"""

class ConditionNode(Node):
    def __init__(
        self,
        name,
        check_prompt,
        max_retries=200,
        interval=5,
        required_consecutive_matches=3,
    ):
        self.name = name
        self.check_prompt = check_prompt
        self.max_retries = max_retries
        self.interval = interval
        self.retries = 0
        self.next_check_at = 0.0
        self.required_consecutive_matches = max(1, int(required_consecutive_matches))
        self.consecutive_matches = 0

    def tick(self, env, brain, memory, trace_log: list):
        if self.retries == 0:
            msg = f"\n▶[Condition: {self.name}] 開始檢查並等待畫面出現: 「{self.check_prompt}」"
            print(msg); trace_log.append(msg)

        if time.monotonic() < self.next_check_at:
            return NodeState.RUNNING

        # 取得 ScreenFrame 物件
        screen = env.capture_screen()

        matched = brain.check_presence(screen, self.check_prompt)
        self.retries += 1
        if matched:
            self.consecutive_matches += 1
            if self.consecutive_matches >= self.required_consecutive_matches:
                success_msg = (
                    " └─ [Condition 成功] 條件連續成立 "
                    f"{self.required_consecutive_matches} 次，確認目標畫面穩定。"
                )
                print(success_msg); trace_log.append(success_msg)
                self.reset()
                return NodeState.SUCCESS
            progress_msg = (
                " └─ 條件暫時成立，等待穩定確認 "
                f"({self.consecutive_matches}/{self.required_consecutive_matches})..."
            )
            print(progress_msg); trace_log.append(progress_msg)
        else:
            self.consecutive_matches = 0

        if self.retries >= self.max_retries:
            fail_msg = f" └─ [Condition 失敗] 已達最大等待次數 ({self.max_retries})，系統宣告等待超時。"
            print(fail_msg); trace_log.append(fail_msg)
            self.reset()
            return NodeState.FAILURE

        self.next_check_at = time.monotonic() + self.interval
        if not matched:
            print(f" └─ 條件尚未成立 (第 {self.retries}/{self.max_retries} 次輪詢)，{self.interval} 秒後再次檢查...")
        return NodeState.RUNNING

    def reset(self):
        self.retries = 0
        self.next_check_at = 0.0
        self.consecutive_matches = 0
