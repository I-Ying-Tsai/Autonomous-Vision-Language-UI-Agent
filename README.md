# Autonomous Vision-Language UI Agent

An adaptive GUI automation framework for mobile applications and games. The system converts natural-language requirements into strongly typed Behavior Tree definitions and executes them through multimodal visual grounding, coordinate caching, and automated failure recovery.

## Overview

The system is organized into four layers:

1. **Intent Parsing**
   Converts natural-language instructions into structured task descriptions with human-assisted entity classification.

2. **IR Compilation**
   Compiles structured task descriptions into a strongly typed intermediate representation (`IRBlueprint`) and applies structural patches when required.

3. **Code Generation**
   Generates deterministic Python task definitions with target validation and AST-level sanitization.

4. **Runtime and Recovery**
   Executes Behavior Trees using multimodal visual grounding and automatically diagnoses failed executions.

## System Architecture

```text
Natural Language Request
          |
          v
+----------------------------------------------+
| Layer 1: Intent Parser                       |
| - Logical structure extraction               |
| - Entity classification                      |
| - Coordinate knowledge alignment             |
+----------------------------------------------+
          |
          v
+----------------------------------------------+
| Layer 2: IR Compiler                         |
| - Strongly typed IR generation               |
| - Structural patching                        |
+----------------------------------------------+
          |
          v
+----------------------------------------------+
| Layer 3: Code Generator                     |
| - Glossary injection                         |
| - Target validation                          |
| - Deterministic Python generation            |
+----------------------------------------------+
          |
          v
+----------------------------------------------+
| Runtime Execution Engine                    |
| - 3 FPS background frame capture             |
| - OCR / SoM / VLM grounding                  |
| - Coordinate cache                           |
| - Post-action verification                   |
+----------------------------------------------+
          |
          +----------------------+
          |                      |
       SUCCESS                 FAILURE
          |                      |
          v                      v
     Task Complete       +---------------------+
                         | Layer 4: QA         |
                         | - State dump        |
                         | - Visual analysis   |
                         | - Root-cause analysis|
                         +---------------------+
                                  |
                                  v
                         Layer 2 Structural Patch
                                  |
                                  v
                         Regeneration / Hot Reload
```

## Component Specifications

| Module           | Scope                    | Implementation                                                                                                                 |
| ---------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `environment.py` | Device I/O and streaming | Asynchronous ADB frame capture at 3 FPS. `ScreenFrame` provides lazy OpenCV, PIL, and Base64 representations.                  |
| `brain.py`       | Multimodal perception    | Three-stage grounding pipeline: RapidOCR, Set-of-Mark detection, and VLM coordinate regression.                                |
| `nodes.py`       | Behavior Tree execution  | Stateful `SequenceNode`, `SelectorNode`, `ConditionNode`, and `ActionNode` implementations.                                    |
| `memory.py`      | Coordinate persistence   | Resolution-independent normalized coordinates with soft deletion after failed transitions.                                     |
| `compiler/`      | Compilation pipeline     | Intent classification, IR generation, structural patching, code generation, symbolic path expansion, and sandbox verification. |
| `main.py`        | Runtime orchestration    | Execution lifecycle management, failure handling, generation tracking, and module hot reload.                                  |

## Runtime Execution

### ActionNode

1. Check `MemoryManager` for cached coordinates.
2. Execute immediately when a valid cache entry exists.
3. Run visual grounding when no valid cache entry is available.
4. Capture the post-action frame.
5. Calculate the visual difference ratio `Delta`.

Transition rules:

```text
Delta > 12.0%       -> SUCCESS
Delta < 3.0%        -> FAILURE
3.0% <= Delta <= 12.0% -> VLM transition verification
```

Successful actions update the coordinate cache. Failed transitions trigger soft deletion of the associated coordinate.

### ConditionNode

`ConditionNode` continuously evaluates the current screen state through `Brain.check_presence`.

```text
Target detected      -> SUCCESS
Retry interval       -> RUNNING
Maximum retries hit  -> FAILURE
```

### Self-Healing

A terminal failure produces:

* Current screen capture
* Execution trace
* Structured diagnostic input

`Layer4SandboxQA` analyzes the execution state and produces a structured bug report. The compiler then applies a minimal structural patch, regenerates the task definition, increments the generation index, and reloads the generated module.

## Known Issues

| ID       | Domain       | Severity | Description                                                                                                                                                               | Status      |
| -------- | ------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| ISSUE-01 | Device I/O   | Major    | ADB commands are not synchronized between background capture and execution threads, which may cause race conditions under high I/O load.                                  | Planned     |
| ISSUE-02 | Self-Healing | Major    | The automated self-healing pipeline is not fully implemented. Failure diagnosis, structural patching, regeneration, and hot reload are currently incomplete.              | In Progress |
| ISSUE-03 | Compiler     | Major    | Logical accuracy decreases when processing long or structurally complex natural-language instructions. The compiler may generate incomplete or incorrect task structures. | In Progress |

## Requirements

* Python 3.10+
* Android Debug Bridge (ADB)
* Ollama
* `qwen2.5-coder:7b`
* `qwen3-vl:8b`

## Configuration

The default ADB connection target is:

```text
127.0.0.1:16384
```

The target can be modified in `config.py`.

## Installation

```bash
# Verify ADB connectivity
adb devices

# Install Python dependencies
pip install -r requirements.txt
```

## Execution

```bash
python main.py
```

## Project Structure

```text
.
├── compiler/
│   ├── ...
├── environment.py
├── brain.py
├── nodes.py
├── memory.py
├── main.py
├── config.py
├── requirements.txt
└── README.md
```

## Design Goals

The project focuses on:

* Deterministic task generation
* Multimodal UI grounding
* Resolution-independent coordinate persistence
* Low-latency execution through caching
* Closed-loop execution verification
* Automated failure diagnosis and recovery
* Minimal structural modification during self-healing
