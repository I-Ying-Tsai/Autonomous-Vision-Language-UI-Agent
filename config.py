import os

# ADB 與 設備設定
DEVICE_ID = "127.0.0.1:16384"
ADB_PATH = r".\platform-tools\adb"

# 模型設定
MODEL_NAME = "qwen2.5vl:7b"

# 路徑設定
WORKSPACE_DIR = "workspace"
MEMORY_FILE = os.path.join(WORKSPACE_DIR, "agent_memory.json")

# 確保工作目錄存在
os.makedirs(WORKSPACE_DIR, exist_ok=True)