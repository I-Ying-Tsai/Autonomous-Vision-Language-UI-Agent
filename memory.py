import json
import os

class MemoryManager:
    def __init__(self, filepath="compiler/memory/game_knowledge.json"):
        self.filepath = filepath
        self.cache = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print(f"[MemoryManager] 警告：快取檔案解析失敗，建立新快取。")
                return {}
        return {}

    def _save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=4, ensure_ascii=False)

    @staticmethod
    def _valid_dimensions(screen_width, screen_height):
        return screen_width > 0 and screen_height > 0

    @staticmethod
    def _valid_normalized_coord(norm_x, norm_y):
        return (
            isinstance(norm_x, (int, float))
            and isinstance(norm_y, (int, float))
            and 0.0 <= norm_x <= 1.0
            and 0.0 <= norm_y <= 1.0
        )

    def get_target_coord(self, game_name, scene_name, target_name, screen_width, screen_height):
        """
        查詢目標座標，將 JSON 內的正規化座標 (norm_x, norm_y)
        即時轉換為當前設備的實體像素座標 (x, y)
        """
        game_memory = self.cache.get(game_name, {})
        scene_memory = game_memory.get(scene_name, {})

        target = scene_memory.get(target_name)

        if not self._valid_dimensions(screen_width, screen_height):
            raise ValueError("screen dimensions must be positive")

        if target and "norm_x" in target and "norm_y" in target:
            if not self._valid_normalized_coord(target["norm_x"], target["norm_y"]):
                print(f"[MemoryManager] 忽略越界快取座標: {game_name} -> {scene_name} -> {target_name}")
                return None
            # 將 0.0~1.0 的正規化數值，轉換為實體螢幕的像素座標
            x = min(screen_width - 1, int(target["norm_x"] * screen_width))
            y = min(screen_height - 1, int(target["norm_y"] * screen_height))
            return x, y

        return None

    def update_target_coord(self, game_name, scene_name, target_name, x, y, screen_width, screen_height):
        """
        將新座標轉換為正規化座標 (norm_x, norm_y) 並寫入記憶，
        同時保證原有的 Metadata (aliases, prompt) 不被覆寫
        """
        if not self._valid_dimensions(screen_width, screen_height):
            raise ValueError("screen dimensions must be positive")
        if not (0 <= x < screen_width and 0 <= y < screen_height):
            raise ValueError(
                f"target coordinate ({x}, {y}) is outside {screen_width}x{screen_height}"
            )

        if game_name not in self.cache:
            self.cache[game_name] = {}
        if scene_name not in self.cache[game_name]:
            self.cache[game_name][scene_name] = {}

        # 計算正規化座標 (保留至小數點後 4 位)
        norm_x = round(x / screen_width, 4)
        norm_y = round(y / screen_height, 4)

        existing_data = self.cache[game_name][scene_name].get(target_name, {})
        existing_data["norm_x"] = norm_x
        existing_data["norm_y"] = norm_y

        self.cache[game_name][scene_name][target_name] = existing_data
        self._save()
        print(f"[記憶] 已更新黃金快取: {target_name} -> (norm_x: {norm_x}, norm_y: {norm_y})")

    def invalidate_target(self, game_name, scene_name, target_name):
        """
        [防線一] 清除無效的快取座標
        注意：這裡採用「軟刪除」，只清除座標，保留 Metadata 供重新定位使用
        """
        try:
            target_data = self.cache[game_name][scene_name][target_name]

            removed = False
            if "norm_x" in target_data:
                del target_data["norm_x"]
                removed = True
            if "norm_y" in target_data:
                del target_data["norm_y"]
                removed = True

            if removed:
                self._save()
                print(f"[記憶] 已清除失效的快取座標: {game_name} -> {scene_name} -> {target_name}")
                return True
            return False

        except KeyError:
            return False
