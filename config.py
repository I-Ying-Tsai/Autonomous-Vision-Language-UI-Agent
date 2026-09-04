import os

DEVICE_ID = os.getenv("UI_AGENT_DEVICE_ID", "127.0.0.1:16384")
ADB_PATH = os.getenv("UI_AGENT_ADB_PATH", "adb")

MODEL_GENERAL = os.getenv("UI_AGENT_MODEL_GENERAL", "qwen3.5:9b")
MODEL_CODER = os.getenv("UI_AGENT_MODEL_CODER", "qwen2.5-coder:7b")
MODEL_VISION = os.getenv("UI_AGENT_MODEL_VISION", "qwen3-vl:8b")
MODEL_NAME = MODEL_VISION

WORKSPACE_DIR = "workspace"
MEMORY_FILE = os.path.join("compiler", "memory", "game_knowledge.json")

os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
