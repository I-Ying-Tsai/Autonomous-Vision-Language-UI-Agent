import os

DEVICE_ID = "127.0.0.1:16384"
ADB_PATH = r".\platform-tools\adb"

MODEL_NAME = "qwen2.5vl:7b"

WORKSPACE_DIR = "workspace"
MEMORY_FILE = os.path.join("compiler", "memory", "game_knowledge.json")

os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)