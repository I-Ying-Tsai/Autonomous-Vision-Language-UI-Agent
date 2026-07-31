from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode

def build_startup_tree():
    """任務樹：未來之戰_進入應用程式"""
    
    # 步驟 1：點擊進入未來之戰應用程式
    step1_launch = GuardedActionNode(
        name="點擊進入未來之戰應用程式",
        target_desc="未來之戰",
        pre_check_prompt="future war app icon on home screen",
        game_name="未來之戰"
    )

    # 步驟 2：等待載入畫面完成或出現廣告彈窗
    step2_wait_loading = ConditionNode(
        name="等待載入畫面完成或出現廣告彈窗",
        check_prompt="ad popup, loading screen, or clean home screen",
        max_retries=200,
        interval=5
    )

    # 步驟 3：防禦性 Selector (狀態判定與清理)
    
    # 3-A: 檢查是否已經在乾淨首頁
    check_home_clean = ConditionNode(
        name="檢查未來之戰首頁",
        check_prompt="home screen without any ad popups",
        max_retries=1,
        interval=3
    )

    # 3-B: 清理廣告彈窗流程 (如果 3-A 失敗則執行)
    click_close_ad = GuardedActionNode(
        name="點擊右上角的關閉圖示",
        target_desc="close icon",
        pre_check_prompt="ad popup or close icon",
        game_name="未來之戰"
    )

    check_home_after_dismiss = ConditionNode(
        name="確認成功進入首頁",
        check_prompt="home screen without any ad popups",
        max_retries=5,
        interval=3
    )

    dismiss_ad_sequence = SequenceNode(
        name="清理廣告彈窗流程",
        children=[click_close_ad, check_home_after_dismiss]
    )

    # 3-C: 確認確認視窗出現並點擊確定按鈕
    click_confirm_button = GuardedActionNode(
        name="點擊確定按鈕",
        target_desc="確定",
        pre_check_prompt="confirm button",
        game_name="未來之戰"
    )

    # 3-D: 確認大廳畫面出現完成後繼續流程
    check_hall_appeared = ConditionNode(
        name="確認大廳畫面出現完成後繼續流程",
        check_prompt="main hall screen",
        max_retries=5,
        interval=3
    )

    confirm_and_wait_sequence = SequenceNode(
        name="處理確認視窗並等待大廳畫面",
        children=[click_confirm_button, check_hall_appeared]
    )

    # 組合 Selector
    step3_handle_ad_popup = SelectorNode(
        name="進入未來之戰首頁 (容錯 Selector)",
        children=[check_home_clean, dismiss_ad_sequence, confirm_and_wait_sequence]
    )

    # 最終組合
    return SequenceNode(
        name="最終自動化流程",
        children=[step1_launch, step2_wait_loading, step3_handle_ad_popup]
    )