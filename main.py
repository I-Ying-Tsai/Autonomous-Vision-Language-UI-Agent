import time
import os
from PIL import Image
from config import MEMORY_FILE, WORKSPACE_DIR
from memory import MemoryManager
from environment import Environment
from brain import Brain

def main():
    USER_GOAL = "在桌面上找到「未來之戰」並點擊開啟，等待載入，直到看見遊戲主畫面為止。"
    
    memory = MemoryManager(MEMORY_FILE)
    env = Environment()
    brain = Brain()
    
    print("啟動 Agent\n")
    
    step = 0
    max_steps = 15
    last_scene = None
    used_cache_last_turn = False
    
    while step < max_steps:
        step += 1
        print(f"=================== [ 回合 {step} ] ===================")
        
        screen = env.capture_screen()
        with Image.open(screen) as img:
            width, height = img.size
            is_landscape = width > height
            
        print("[大腦] 分析場景與決策中...")
        plan = brain.plan(screen, USER_GOAL)
        
        scene = plan.get('scene_name', 'unknown_scene')
        action = plan.get('action_type', 'wait')
        target = plan.get('target_element_desc', '')
        
        print(f" ├─ 當前場景: {scene}")
        print(f" ├─ 決定動作: {action}")
        print(f" └─ 目標元件: {target}")
        
        if used_cache_last_turn and scene == last_scene and action == 'tap':
            print(f"[防線] 上回合點了快取但場景沒變，清除快取記憶！")
            memory.invalidate_target(last_scene, target)
            used_cache_last_turn = False

        if plan.get('goal_achieved') or action == 'done':
            print("\n任務達成！已成功進入目標畫面。")
            break
            
        last_scene = scene
        used_cache_last_turn = False
        
        if action == 'wait':
            print("載入中，等待 5 秒...")
            time.sleep(5)
            continue
            
        elif action == 'swipe':
            env.swipe(int(width*0.8), int(height*0.5), int(width*0.2), int(height*0.5))
            continue
            
        elif action == 'tap' and target:
            # === 1. 讀取記憶 ===
            cached_coord = memory.get_target_coord(scene, target)
            if cached_coord:
                cx, cy = cached_coord
                print(f"[記憶] 命中黃金快取！直接提取座標 ({cx}, {cy})")
                env.tap(cx, cy, wait_time=5)
                used_cache_last_turn = True
                continue
                
            # === 2. 初始定位 ===
            print(f"[視覺] 呼叫 Layer 2 進行初始定位...")
            cx_1000, cy_1000 = brain.get_center_point(screen, target, is_landscape)
            
            if cx_1000 is not None:
                cx = int(cx_1000 / 1000 * width)
                cy = int(cy_1000 / 1000 * height)
                
                # === 3. 擴張尋寶機制 ===
                print(f"[Layer 3] 啟動擴張搜尋，初始落點 ({cx}, {cy})")
                
                box_size = 150       
                expansion_step = 150 
                max_expansions = 11   
                target_found_in_crop = False
                
                prev_left, prev_top, prev_right, prev_bottom = None, None, None, None
                found_box = None
                crop_path = os.path.join(WORKSPACE_DIR, "crop_verify.png")
                
                for attempt in range(max_expansions + 1):
                    left = max(0, cx - box_size // 2)
                    top = max(0, cy - box_size // 2)
                    right = min(width, cx + box_size // 2)
                    bottom = min(height, cy + box_size // 2)
                    
                    with Image.open(screen) as img:
                        cropped = img.crop((left, top, right, bottom))
                        cropped.save(crop_path)
                        
                    is_present = brain.check_presence(crop_path, target)
                    
                    if is_present:
                        print(f" ├─ 擴張第 {attempt} 次 (尺寸 {box_size}): 成功將目標納入視野！")
                        target_found_in_crop = True
                        
                        if attempt == 0:
                            found_box = (left, top, right, bottom)
                        else:
                            # 完美實踐你的想法：邊緣分析，鎖定 X 或 Y
                            print(f" ├─ [邊緣鎖定] 開始分析目標貼著哪一條擴張邊界...")
                            strips = {
                                "TOP (上邊緣)": (left, top, right, prev_top),
                                "BOTTOM (下邊緣)": (left, prev_bottom, right, bottom),
                                "LEFT (左邊緣)": (left, prev_top, prev_left, prev_bottom),
                                "RIGHT (右邊緣)": (prev_right, prev_top, right, prev_bottom)
                            }
                            
                            strip_matched = False
                            for strip_name, coords in strips.items():
                                sl, st, sr, sb = coords
                                if sr <= sl or sb <= st: continue # 撞牆的無效邊緣
                                
                                with Image.open(screen) as img:
                                    img.crop((sl, st, sr, sb)).save(crop_path)
                                    
                                if brain.check_presence(crop_path, target):
                                    print(f" ├─ 目標確認貼著 [{strip_name}]！一維座標已鎖定。")
                                    found_box = (sl, st, sr, sb)
                                    strip_matched = True
                                    break
                                    
                            if not strip_matched:
                                print(" ├─ 邊緣捕捉異常，退回大方塊搜尋。")
                                found_box = (left, top, right, bottom)
                        break
                    else:
                        print(f" ├─ 擴張第 {attempt} 次: 視野內無目標，繼續擴大。")
                        prev_left, prev_top, prev_right, prev_bottom = left, top, right, bottom
                        box_size += expansion_step
                
                # === 4. 二元切分逼近法 (取代原本的 Layer 4) ===
                if target_found_in_crop and found_box:
                    cur_left, cur_top, cur_right, cur_bottom = found_box
                    print(f"[Layer 4] 啟動 1D 二元切分逼近法，精確鎖定座標...")
                    
                    # 只要最長邊大於 120 像素，就不斷對半切
                    while (cur_right - cur_left) > 120 or (cur_bottom - cur_top) > 120:
                        if (cur_right - cur_left) > (cur_bottom - cur_top):
                            mid = (cur_left + cur_right) // 2
                            test_box = (cur_left, cur_top, mid, cur_bottom)
                            dir_name = "左半邊"
                        else:
                            mid = (cur_top + cur_bottom) // 2
                            test_box = (cur_left, cur_top, cur_right, mid)
                            dir_name = "上半邊"
                            
                        with Image.open(screen) as img:
                            img.crop(test_box).save(crop_path)
                            
                        if brain.check_presence(crop_path, target):
                            print(f" ├─ 目標在 {dir_name}，縮小一半範圍。")
                            if dir_name == "左半邊": cur_right = mid
                            else: cur_bottom = mid
                        else:
                            print(f" ├─ 目標不在 {dir_name}，反向鎖定另一半。")
                            if dir_name == "左半邊": cur_left = mid
                            else: cur_top = mid
                            
                    global_x = (cur_left + cur_right) // 2
                    global_y = (cur_top + cur_bottom) // 2
                    
                    print(f"[鎖定完成] 取得黃金座標 ({global_x}, {global_y})！寫入快取。")
                    memory.update_target_coord(scene, target, global_x, global_y)
                    env.tap(global_x, global_y, wait_time=5)
                else:
                    print(f"[搜尋失敗] 已達最大擴張次數仍未見目標，強迫重新分析或翻頁。")
                    env.swipe(int(width*0.8), int(height*0.5), int(width*0.2), int(height*0.5))
            else:
                print("[視覺] Layer 2 無法給出初始座標！強制滑動...")
                env.swipe(int(width*0.8), int(height*0.5), int(width*0.2), int(height*0.5))

    if step >= max_steps:
        print("\n達到最大步數限制，強制終止任務。")

if __name__ == "__main__":
    main()