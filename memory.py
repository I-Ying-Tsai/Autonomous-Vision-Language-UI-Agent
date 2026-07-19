import json
import os

class MemoryManager:
    def __init__(self, filepath):
        self.filepath = filepath
        self.cache = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=4, ensure_ascii=False)

    def get_target_coord(self, scene_name, target_name):
        """查詢目標座標，回傳 (x, y) 或是 None"""
        scene_memory = self.cache.get(scene_name, {})
        target = scene_memory.get(target_name)
        if target:
            return target.get('x'), target.get('y')
        return None

    def update_target_coord(self, scene_name, target_name, x, y):
        """將新座標寫入記憶"""
        if scene_name not in self.cache:
            self.cache[scene_name] = {}
        self.cache[scene_name][target_name] = {"x": x, "y": y}
        self._save()

    def invalidate_target(self, scene_name, target_name):
        """[防線一] 清除無效的快取座標"""
        if scene_name in self.cache and target_name in self.cache[scene_name]:
            del self.cache[scene_name][target_name]
            self._save()
            print(f"[記憶] 已清除失效的快取座標: {scene_name} -> {target_name}")
            return True
        return False