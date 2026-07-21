from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode

def build_startup_tree():
    """
    任務樹：啟動《未來之戰》並自動處理兩段式廣告彈窗 (附帶載入等待機制)
    """
    
    # 步驟 1：點擊桌面遊戲圖示
    step1_launch_game = GuardedActionNode(
        name="點擊桌面遊戲圖示",
        target_desc="未來之戰",
        pre_check_prompt="未來之戰"
    )

    # -------------------------------------------------------------
    # 步驟 2：耐心等待遊戲載入 (這是關鍵！等到大廳或彈窗出現才放行)
    # -------------------------------------------------------------
    step2_wait_for_loading = ConditionNode(
        name="等待遊戲載入完成",
        check_prompt="popup window, X icon, or game lobby",
        max_retries=200,
        interval=5
    )

    # -------------------------------------------------------------
    # 步驟 3：狀態判定與彈窗處理
    # -------------------------------------------------------------
    
    # 3A：檢查是否已經直接在遊戲大廳 (無彈窗)
    check_lobby_clean = ConditionNode(
        name="檢查遊戲大廳",
        check_prompt="game lobby without any popup windows",
        max_retries=1,
        interval=3
    )

    # 3B-1: 點擊廣告右上角的紅色 X
    click_close_popup = GuardedActionNode(
        name="1. 點擊廣告彈窗的關閉按鈕 (X)",
        target_desc="red X close button at top right corner",
        pre_check_prompt="popup window or X icon"
    )

    # 3B-2: 點擊挽留確認框中的「確定」按鈕
    click_confirm_dismiss = GuardedActionNode(
        name="2. 點擊二次確認框的『確定』按鈕",
        target_desc="確定",
        pre_check_prompt="確定"
    )

    # 3B-3: 關閉後驗證大廳 (轉場可能要一點時間，給 5 次緩衝)
    check_lobby_after_dismiss = ConditionNode(
        name="3. 確認成功進入主畫面",
        check_prompt="game lobby without any popup windows",
        max_retries=5,
        interval=3
    )

    # 組合 3B (點 X ➔ 點確定 ➔ 看大廳)
    dismiss_popup_sequence = SequenceNode(
        name="清理廣告彈窗流程 (連環關閉)",
        children=[click_close_popup, click_confirm_dismiss, check_lobby_after_dismiss]
    )

    # 組合 3：Selector (乾淨大廳優先，被遮住就走連環關閉流程)
    step3_handle_popups = SelectorNode(
        name="進入遊戲主頁 (含連環彈窗容錯)",
        children=[check_lobby_clean, dismiss_popup_sequence]
    )

    # 最終任務樹：點擊 ➔ 等待載入 ➔ 處理狀態
    return SequenceNode(
        name="啟動《未來之戰》自動化流程",
        children=[step1_launch_game, step2_wait_for_loading, step3_handle_popups]
    )