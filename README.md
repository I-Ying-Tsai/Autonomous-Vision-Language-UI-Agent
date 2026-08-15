# Autonomous Vision-Language UI Agent

基於 **行為樹 (Behavior Tree, BT)** 與 **多模態視覺語言模型 (VLM)** 的 Android 自動化 Agent 系統。透過自然語言編譯為可執行代碼、帶守衛機制的行為樹執行引擎，以及執行期故障診斷機制，構建自動化閉環。

---

## 系統架構圖 (Architecture Overview)

```
[ 自然語言任務需求 ]
         │
         ▼
 ┌────────────────────────────────────────────────────────┐
 │ 【Layer 1: Intent Parser】 (Two-Pass + 人類審核)        │
 │  • Pass 1: 生成 ASCII 步驟草稿，提取 UI 實體標籤       │
 │  • Pass 2: 目標分類 (TEXT/ICON) 並對齊知識庫預設 Prompt │
 └────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────┐
 │ 【Layer 2: IR Generator】                              │
 │  • 編譯為結構化中間表示層藍圖 (IRBlueprint / IRStep)    │
 └────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────┐
 │ 【Layer 3: Code Generator】                            │
 │  • 讀取動態術語字典 (Glossary)，生成 task_definitions.py│
 └────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────┐
 │ 【Runtime 行為樹執行引擎】 (nodes.py + brain.py)        │
 │  • 節點架構: SequenceNode / SelectorNode / GuardedAction│
 │  • 視覺定位: SoM 候選標籤決策 / VLM 座標回歸        │
 │  • 記憶快取: 跨解析度正規化黃金座標快取                 │
 │  • 轉場驗證: 數學像素差值 ➔ VLM 雙圖語意比對           │
 └────────────────────────────────────────────────────────┘
         │
         ├───────────────────────────────┐
         ▼ [執行成功]                    ▼ [觸發熔斷 FAILURE]
    [ 任務達成退出 ]            ┌───────────────────────────────────┐
                                │ 【Layer 4: Sandbox & QA 診斷】    │
                                │  • 結合錯誤截圖與 Trace Log 診斷  │
                                │  • 產出 Fixed Hint 進行外科手術修補│
                                └───────────────────────────────────┘
                                                 │
                                                 ▼ (熱重載進入下一世代)
                                        [ Layer 2 增補 ➔ L3 重編譯 ]

```

---

## 模組介紹 (Core Modules)

### 1. AOT 編譯管線 (`compiler/`)

* **Layer 1 (Intent Parser)**：透過大語言模型梳理自然語言步驟，讓人確認結構後，將點擊目標分類為 `TEXT`（文字）或 `ICON`（圖示），並查詢 `game_knowledge.json` 進行別名與 Prompt 對齊。


* **Layer 2 (IR Generator)**：將意圖轉換為強型別的 JSON 中介表示（IR），支援初始編譯與基於診斷書的熱增補修補（`patch_blueprint`）。


* **Layer 3 (Code Generator)**：將藍圖轉譯為符合行為樹 API 的 Python 原始碼（`task_definitions.py`），並透過術語字典強化 VLM 提示詞準確度。


* **Layer 4 (Sandbox QA & Red Team)**：
* `BTRouteExpander`：以符號執行展開行為樹所有可能路徑。


* `RedTeamPruner`：自動剪枝並挑選出 Happy Path、容錯路徑與死結路徑作為測試矩陣。


* `Layer4SandboxQA`：雙腦協作評估器，結合視覺回報與 Trace Log 推導修復方向。





### 2. 行為樹執行引擎 (`nodes.py`)

* **`SequenceNode`**：順序執行，任一子節點失敗即中斷並回傳 `FAILURE`。


* **`SelectorNode`**：條件容錯分支，任一子節點成功即短路回傳 `SUCCESS`。


* **`GuardedActionNode`**：
* **Pre-Check**：動作前以 VLM 確認目標存在。


* **Grounding**：優先查詢正規化快取座標，無快取時啟動視覺定位。


* **Post-Check**：動作後透過「數學像素比對 + VLM 語意」驗證是否產生畫面切換，成功寫入記憶，失敗則軟刪除快取並熔斷。




* **`ConditionNode`**：畫面狀態輪詢與等待超時控制。



### 3. 視覺感知與定位大腦 (`brain.py`)

* **SoM (Set-of-Mark) 特化定位**：利用 OpenCV（邊緣檢測、矩形形態學擴張、輪廓列表提取）動態抓取畫面中的 UI 候選框並疊加編號標籤，由 VLM 進行多選一標籤決策，實現高精度的離散定位。


* **VLM 座標回歸**：當 SoM 未命中時，透過 0-1000 比例尺的 VLM 座標回歸直接預測目標中心點，達到 $O(1)$ 的定位。


* **自適應轉場驗證**：結合極速的數學像素變異率分流（極低雜訊過濾與顯著全螢幕轉場直接通過），僅在灰色地帶啟動 VLM 語意審查，兼顧效能與抗動畫干擾能力。



### 4. 跨解析度記憶系統 (`memory.py`)

* 使用正規化浮點數座標（`norm_x`, `norm_y` 介於 0.0 ~ 1.0）儲存黃金座標，自動按當前設備解析度換算。


* 支援失效快取的「軟刪除」（保留 Metadata，僅清除座標值）。



### 5. 背景異步串流與記憶體快取 ('environment.py')

採用生產者-消費者執行緒模型，透過 adb exec-out 進行零磁碟 I/O 的背景畫面串流，並透過 Lazy Evaluation 支援 OpenCV 與 Base64 按需解碼，將取圖延遲從數百毫秒大幅降至 30ms 以內。
---

## 檔案結構 (Directory Structure)

```text
.
├── config.py                 # ADB、裝置 ID、模型名稱與工作目錄配置
├── environment.py            # ADB 底層封裝
├── brain.py                  # 視覺大腦
├── memory.py                 # 正規化座標快取與遊戲記憶管理
├── nodes.py                  # 行為樹節點實作
├── main.py                   # 系統進入點
├── requirements.txt          # Python 相依套件
├── compiler/
│   ├── schemas.py            # Pydantic / Dataclass IR 資料結構與 BugReport 定義
│   ├── layer1_intent.py      # L1 自然語言解析與目標分類
│   ├── layer2_ir.py          # L2 IR 藍圖生成與外科手術式修補
│   ├── layer3_codegen.py     # L3 Python 代碼生成器
│   ├── layer4_sandbox.py     # L4 沙盒環境與雙腦 QA 診斷評估器
│   ├── layer4_red_team.py    # L4 符號路徑展開與測試矩陣剪枝
│   └── memory/
│       └── game_knowledge.json # 遊戲專屬 Prompt 與座標知識庫
└── workspace/                # 執行期截圖、藍圖 JSON 與除錯快照

```

---

## 安裝與快速開始 (Quick Start)

### 1. 環境需求

* Python 3.10+
* Android 模擬器或實體裝置（開啟 USB 偵錯）
* 本地部署 [Ollama](https://ollama.ai/) 並拉取相應模型（如 `qwen3-vl:8b`, `qwen2.5-coder:7b`）



### 2. 安裝套件

```bash
pip install -r requirements.txt

```

### 3. 配置連線

在 `config.py` 中修改 ADB 連線位址與路徑：

```python
DEVICE_ID = "127.0.0.1:16384"
ADB_PATH = r".\platform-tools\adb"

```

### 4. 啟動 Agent

```bash
python main.py

```

首次啟動時輸入自然語言任務需求（例如：`"點擊進入未來之戰，若有廣告彈窗則點擊 X 關閉並點確定，最後等待大廳出現"`），系統將自動完成編譯並開始執行。

---

## 目前已知問題與待優化項目 (Known Issues & Limitations)

1. **Layer 4 自動學習與修復能力不足（待修改）**
* 當任務觸發熔斷進入 Layer 4 後，模型對現場問題的定位能力有限，且難以穩定產出具體有效的修補方案，導致自我演化閉環成功率偏低，此診斷與修補管線需重新重構與修改。




2. **實體狀態與行為樹脫節 (State Desynchronization)**
* 當行為樹失敗重載時，新一代行為樹會從第 1 步重新執行，但實體裝置畫面仍停留在當前遊戲畫面，導致開頭在遊戲畫面中尋找桌面圖示而再次失敗。




3. **動作維度受限 (Action Space)**
* 目前行為樹節點僅實作點擊（`tap`），缺少滑動（`swipe`）、長按（`long-press`）與文字輸入（`input text`）等節點類型。




4. **全域場景記憶隔離缺乏**
* 目前快取一律預設為 `"global_scene"`，缺乏多頁面狀態機管理，跨介面同名元素可能產生快取混淆。