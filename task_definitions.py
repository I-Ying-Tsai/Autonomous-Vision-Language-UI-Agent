from nodes import SequenceNode, SelectorNode, GuardedActionNode, ConditionNode

def build_startup_tree():
    """任務樹：未來之戰_遊戲流程"""
    
    # 注意：target_desc 嚴格保持原始 target，不可追加 "app icon"
    step1_launch = GuardedActionNode(
        name="點擊未來之戰應用程式",
        target_desc="未來之戰",
        pre_check_prompt="game icon on desktop",
        game_name="未來之戰"
    )

    step2_wait_loading = ConditionNode(
        name="等待遊戲畫面載入完成",
        check_prompt="game lobby without any popup windows",
        max_retries=10,
        interval=2
    )

    step3_ad_selector = SelectorNode(
        name="判斷：是否出現廣告",
        children=[
            SequenceNode(
                name="If 分支：有廣告",
                children=[
                    GuardedActionNode(
                        name="點擊X",
                        target_desc="X",
                        pre_check_prompt="close icon (X)",
                        game_name="未來之戰"
                    ),
                    GuardedActionNode(
                        name="點擊確定",
                        target_desc="確定",
                        pre_check_prompt="confirm button",
                        game_name="未來之戰"
                    )
                ]
            ),
            ConditionNode(
                name="Else 分支：無廣告_繼續進行遊戲操作",
                check_prompt="game lobby without any popup windows",
                max_retries=10,
                interval=2
            )
        ]
    )

    step4_wait_modal = ConditionNode(
        name="等待模態對話框出現",
        check_prompt="popup window",
        max_retries=10,
        interval=2
    )

    step5_handle_modal = SequenceNode(
        name="處理模態對話框",
        children=[
            GuardedActionNode(
                name="點擊模態對話框的X",
                target_desc="模態對話框的X",
                pre_check_prompt="close icon (X)",
                game_name="未來之戰"
            ),
            GuardedActionNode(
                name="點擊模態對話框的確定",
                target_desc="模態對話框的確定",
                pre_check_prompt="confirm button",
                game_name="未來之戰"
            )
        ]
    )

    return SequenceNode(
        name="最終自動化流程",
        children=[step1_launch, step2_wait_loading, step3_ad_selector, step4_wait_modal, step5_handle_modal]
    )