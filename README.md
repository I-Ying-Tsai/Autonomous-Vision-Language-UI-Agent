# Autonomous Vision-Language UI Agent

An adaptive Android GUI automation framework that compiles natural-language requirements into a validated Behavior Tree intermediate representation (IR), then executes that IR through multimodal visual grounding, UI target memory, and bounded failure recovery.

## Architecture

1. **Intent Parsing** converts instructions into a reviewed task structure and lets a human classify click targets as text or icons.
2. **IR Compilation** produces and validates an `IRBlueprint`.
3. **IR Runtime** builds Behavior Tree nodes directly from the validated IR. Generated Python is an optional export format and is not automatically executed.
4. **Runtime and Recovery** uses ADB, OCR, Set-of-Mark grounding, VLM fallback, postconditions, execution traces, and bounded IR patching.

```text
Natural Language -> Reviewed Intent -> Validated IR -> IR Executor
                                                       |
                                +----------------------+
                                | Runtime              |
                                | - ADB frame stream   |
                                | - OCR / SoM / VLM    |
                                | - Target memory      |
                                | - Postconditions     |
                                +----------------------+
                                      | failure
                                      v
                              Visual + trace diagnosis
                                      |
                                      v
                              Validated IR patch
```

## Main Components

| Module | Responsibility |
| --- | --- |
| `environment.py` | Synchronized ADB commands, bounded startup, fresh-frame barriers, and screenshot-based dimensions |
| `brain.py` | Target-type-aware OCR / SoM / VLM grounding and transition verification |
| `nodes.py` | Stateful Sequence, Selector, Condition, and Action Behavior Tree nodes |
| `memory.py` | Bounds-checked normalized target coordinates with soft invalidation |
| `compiler/schemas.py` | IR models and structural validation |
| `compiler/ir_executor.py` | Direct conversion from validated IR to runtime nodes |
| `compiler/layer1_intent.py` | Intent parsing and human-assisted target classification |
| `compiler/layer2_ir.py` | Initial IR generation and structural patching |
| `compiler/layer3_codegen.py` | Optional Python export |
| `compiler/layer4_sandbox.py` | Screenshot and trace-assisted failure diagnosis |
| `main.py` | Explicit CLI, task lifecycle, execution, and bounded repair generations |

## Runtime Correctness

- Coordinates use the actual screenshot width and height, not `adb wm size`, so landscape and portrait coordinate systems remain aligned.
- Cached normalized coordinates outside `[0, 1]` are ignored. Pixel coordinates are checked again before every tap or swipe.
- ADB capture and input commands share a lock and have command timeouts.
- Post-action verification waits for a frame captured after the input command.
- Text targets start with OCR; icon targets skip OCR and start with Set-of-Mark grounding.
- If an action defines `post_check_prompt`, that expected state is authoritative. Otherwise, the runtime measures the percentage of materially changed pixels and uses VLM verification for ambiguous transitions.
- Selector and Sequence nodes preserve RUNNING state and reset child state when a branch completes.

## Requirements

- Python 3.10+
- Android Debug Bridge available as `adb`
- Ollama
- `qwen2.5-coder:7b`
- `qwen3-vl:8b`

Install Python dependencies and local models:

```bash
python -m pip install -r requirements.txt
ollama pull qwen2.5-coder:7b
ollama pull qwen3-vl:8b
adb devices
```

## Configuration

Defaults can be overridden without editing source code:

| Environment variable | Default |
| --- | --- |
| `UI_AGENT_DEVICE_ID` | `127.0.0.1:16384` |
| `UI_AGENT_ADB_PATH` | `adb` |
| `UI_AGENT_MODEL_GENERAL` | `qwen3.5:9b` |
| `UI_AGENT_MODEL_CODER` | `qwen2.5-coder:7b` |
| `UI_AGENT_MODEL_VISION` | `qwen3-vl:8b` |

## Usage

Compile a task into validated IR:

```bash
python main.py compile --task "Open the app and wait for its home screen"
```

Run the current IR directly:

```bash
python main.py run
```

Run without automatic IR patching:

```bash
python main.py run --no-heal
```

Use another blueprint or export Python for inspection:

```bash
python main.py compile --task "..." --output workspace/my_task.json
python main.py run --blueprint workspace/my_task.json
python main.py compile --task "..." --export-python workspace/exported_task.py
```

The tracked Python example is never selected implicitly:

```bash
python main.py run-example
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The unit suite covers Behavior Tree RUNNING semantics, target-type propagation, postconditions, IR validation, direct IR execution, and coordinate bounds.

## Known Limitations

- Complex natural-language branching can still be mistranslated by the local compiler model.
- Layer 4 diagnosis and IR patching are model-driven and should not be trusted for high-impact UI actions without an approval layer.
- UI target memory currently uses a global scene namespace; scene fingerprints and confidence decay remain future work.
- The image-difference fallback can be affected by animated backgrounds. Prefer explicit `post_check_prompt` values in IR.
- `layer4_red_team.py` remains experimental and is not part of the default runtime path.
