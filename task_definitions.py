from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode

def build_startup_tree():
    """任務樹：未來之戰_進入遊戲"""
    
    # 步驟 1：啟動 App
    step1_launch = GuardedActionNode(
        name="進入未來之戰應用程式",
        target_desc="未來之戰",
        pre_check_prompt="未來之戰 app icon on home screen",
        game_name="未來之戰"
    )

    # 步驟 2：等待遊戲畫面載入完成
    step2_wait_loading = ConditionNode(
        name="等待遊戲畫面載入完成",
        check_prompt="game UI with popup window, or clean game lobby",
        max_retries=20,
        interval=5
    )

    # 步驟 3：防禦性 Selector (狀態判定與清理)
    
    # 3-A: 檢查是否已經在遊戲大廳
    check_game_lobby_clean = ConditionNode(
        name="檢查遊戲大廳",
        check_prompt="game lobby without any popup windows",
        max_retries=1,
        interval=3
    )

    # 3-B: 清理廣告彈窗流程 (如果 3-A 失敗則執行)
    click_close_ad = GuardedActionNode(
        name="點擊關掉廣告彈窗",
        target_desc="close icon",
        pre_check_prompt="popup window or X icon",
        game_name="未來之戰"
    )

    click_confirm = GuardedActionNode(
        name="點擊確定",
        target_desc="確定",
        pre_check_prompt="confirm button",
        game_name="未來之戰"
    )

    check_game_lobby_after_dismiss = ConditionNode(
        name="確認成功進入遊戲大廳",
        check_prompt="game lobby without any popup windows",
        max_retries=5,
        interval=3
    )

    dismiss_ad_sequence = SequenceNode(
        name="清理廣告彈窗流程",
        children=[click_close_ad, click_confirm, check_game_lobby_after_dismiss]
    )

    # 組合 Selector
    step3_handle_ads = SelectorNode(
        name="判斷：是否有廣告彈窗 (容錯 Selector)",
        children=[check_game_lobby_clean, dismiss_ad_sequence]
    )

    # 最終組合
    return SequenceNode(
        name="最終自動化流程",
        children=[step1_launch, step2_wait_loading, step3_handle_ads]
    )