# Autonomous Vision-Language UI Agent

An adaptive GUI automation framework for mobile application and game interfaces, integrating Large Language Models (LLMs), Vision-Language Models (VLMs), and Behavior Trees (BT). The system compiles natural language operational requirements into strongly typed behavior tree blueprints, executing actions via an adaptive visual grounding router, zero-latency caching, and closed-loop diagnostic self-healing.

---

## System Architecture

```text
[ Natural Language Request ]
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ Layer 1: Intent Parser (HITL Semantic Disambiguation)  │ [source: 7]
│   • Pass 1: Logical structure extraction (ASCII Tree)  │
│   • Pass 2: Interactive manual tagging (TEXT / ICON)   │
│   • Knowledge Base: Normalized coordinates alignment   │
└────────────────────────────────────────────────────────┘
            │ (Sanitized labeled text)
            ▼
┌────────────────────────────────────────────────────────┐
│ Layer 2: Intermediate Representation (IR) Compiler     │ [source: 8]
│   • Strongly typed IR generation (IRBlueprint JSON)    │
│   • Minimal invasive structural patch engine           │
└────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ Layer 3: Code Generator & AST Sanitizer                │ [source: 9]
│   • Dynamic glossary term injection                    │
│   • Strict target_desc immutability verification       │
│   • Deterministic script compilation (task_defs.py)    │
└────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ Runtime Execution Engine                               │ [source: 13]
│   • Environment: 3 FPS background streamer (Lazy-eval) │ [source: 4]
│   • Brain: 3-Tier Grounding (OCR -> SoM -> VLM Regr.)  │ [source: 2]
│   • Memory: Soft-delete cache & coordinate normalizer  │ [source: 6]
└────────────────────────────────────────────────────────┘
            │
            ├─────────────────────────────┐
            ▼ (Node FAILURE / Exception)   ▼ (Node SUCCESS)
┌──────────────────────────────┐ [ Task Completed ]
│ Layer 4: Multi-Agent QA      │ [source: 11]
│   • State dump (PNG + Trace) │
│   • Vision: Layout audit     │
│   • Logic: CoT root-cause    │
└──────────────────────────────┘
            │ (BugReport JSON)
            └───► Trigger Layer 2 Patch ➔ Generation++ Hot Reload [source: 8, 13]

```

---

## Component Specifications

| Module | Scope | Architecture & Implementation |
| --- | --- | --- |
| `environment.py` | Device I/O & Streaming | Asynchronous daemon capturing frames at 3 FPS via ADB. `ScreenFrame` provides lazy evaluation for OpenCV (`as_cv2`), PIL (`as_pil`), and Base64 (`as_base64`) with PNG header sanitization.

 |
| `brain.py` | Multimodal Perception | **Three-Tier Grounding Pipeline**: Tier 0 RapidOCR (Levenshtein matching) $\to$ Tier 1 Set-of-Mark (Canny/Contour tagging + VLM selection) $\to$ Tier 2 VLM $0\sim1000$ coordinate regression. Transition verification using structural pixel differencing with VLM arbitration fallback.

 |
| `nodes.py` | Behavior Tree Execution | Stateful `SequenceNode`, short-circuit `SelectorNode`, polling `ConditionNode`, and side-effect-only `ActionNode` (cache-prioritized execution with post-action verification).

 |
| `memory.py` | Coordinate Persistence | Stores resolution-invariant normalized coordinates ($0.0 \le \text{norm\_x}, \text{norm\_y} \le 1.0$). Implements soft-deletion on failed transitions to preserve target metadata while purging invalid coordinates.

 |
| `compiler/` | Compilation Pipeline | **L1**: Human-in-the-loop (HITL) manual entity classification. **L2**: IR schema compilation and patching. **L3**: Defensive Python script generation with regex enforcement. **L4**: Symbolic path expansion, heuristic test pruning, and dual-model sandbox verification.

 |
| `main.py` | Orchestration & Lifecycle | Generation supervisor managing execution states, fault capture, L4 escalation, and in-memory module hot-reloading via `importlib.reload` without process termination.

 |

---

## Runtime Execution Flow

* **ActionNode Execution**:
* Check `MemoryManager` for cached normalized coordinates.


* *Cache Hit*: Dispatch immediate hardware tap via ADB with zero VLM inference overhead.


* *Cache Miss*: Route through `Brain.locate_target` (OCR $\to$ SoM $\to$ Regression).


* Capture post-action frame and evaluate difference ratio ($\Delta$):


* $\Delta > 12.0\%$: Immediate `SUCCESS`, update coordinate cache.


* $\Delta < 3.0\%$: Immediate `FAILURE`, soft-delete cached coordinates.


* $3.0\% \le \Delta \le 12.0\%$: Invoke VLM semantic transition check.






* **ConditionNode Execution**:
* Poll frame state using `Brain.check_presence` against `check_prompt`.


* Return `SUCCESS` upon detection; return `RUNNING` during intervals; return `FAILURE` when `max_retries` is exceeded.




* **Self-Healing Loop**:
* A terminal `FAILURE` dumps the current frame (`error_state_genX.png`) and execution trace.


* `Layer4SandboxQA` correlates the intent, visual snapshot, and trace via Chain-of-Thought (CoT) deduction.


* Layer 2 applies surgical AST/IR node insertions, Layer 3 recompiles the script, and the main thread increments the generation index and reloads `task_definitions.py`.





---

## Issue Backlog

| Issue ID | Domain | Severity | Defect Description | System Impact | Status / Mitigation |
| --- | --- | --- | --- | --- | --- |
| **ISSUE-01** | Knowledge Base | Critical | The pre-indexed entry for `未來之戰` in `game_knowledge.json` contains out-of-bounds coordinates (`norm_x: 1.0456`).

 | Coordinate denormalization produces tap positions off the physical display boundary. | **Pending**: Sanitize cache records to strictly enforce $0.0 \le \text{norm} \le 1.0$.

 |
| **ISSUE-02** | IR Compiler | Critical | **Deadlock between loading check and popup handler**: `step2` blocks on `"game lobby without any popup windows"` before `step3_selector` is reached.

 | If a promotional modal appears on startup, `step2` exhausts retries and aborts the pipeline, preventing `step3` from executing.

 | **In Progress**: Refactor L1/L2 prompts to bundle lobby detection and popup dismissal within the same `SelectorNode` structure.

 |
| **ISSUE-03** | Codegen Rules | Major | Application loading timeouts are under-provisioned (`max_retries=10, interval=2`, total 20s).

 | Cold starts for heavy mobile applications exceed 20s, triggering false-positive timeout failures. | **In Progress**: Constrain L3 codegen to assign `max_retries=20, interval=3` for startup phases.

 |
| **ISSUE-04** | Behavior Tree | Major | `ConditionNode.tick` utilizes blocking `time.sleep(self.interval)` inside the tick evaluation.

 | Halts the execution thread during polling, degrading responsiveness to global interrupts and watchdog counters.

 | **Planned**: Refactor to non-blocking elapsed timestamp comparison returning `RUNNING` immediately.

 |
| **ISSUE-05** | Device I/O | Major | Unsynchronized ADB command execution between the background screencap thread and the main worker thread (`tap`/`swipe`).

 | Potential race conditions and socket timeouts under high I/O throughput on constrained ADB server daemons. | **Planned**: Implement an explicit mutex or thread-safe command queue wrapping the ADB transport layer. |
| **ISSUE-06** | Diagnostics | Minor | `main.py` passes only `blueprint.task_name` into `Layer4SandboxQA` as `layer1_tree`.

 | The diagnostic model receives minimal specification context, reducing root-cause accuracy. | **Planned**: Persist the raw L1 `clean_text` within `IRBlueprint` to provide complete ground-truth specifications to L4.

 |

---

## Deployment & Execution

* **Runtime Requirements**: Python 3.10+, ADB platform tools, local Ollama instance serving `qwen2.5-coder:7b` and `qwen3-vl:8b`.


* **Connection Target**: Configured to `127.0.0.1:16384` (configurable in `config.py`).



```bash
# 1. Verify ADB transport connectivity
adb devices

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the agent supervisor
python main.py

```