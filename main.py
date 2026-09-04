import argparse
import dataclasses
import importlib
import json
import os
import time

from compiler.schemas import IRBlueprint, IRValidationError, validate_blueprint
from config import MEMORY_FILE, MODEL_CODER, MODEL_VISION, WORKSPACE_DIR
from nodes import NodeState


BLUEPRINT_PATH = os.path.join(WORKSPACE_DIR, "current_blueprint.json")


def load_blueprint(path=BLUEPRINT_PATH) -> IRBlueprint:
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 IR blueprint: {path}")
    with open(path, "r", encoding="utf-8") as file:
        warnings = []
        blueprint = IRBlueprint.from_dict(json.load(file), warnings=warnings)
        validate_blueprint(blueprint, warnings=warnings)
        for warning in warnings:
            print(f"[IR 正規化警告] {warning}")
        return blueprint


def save_blueprint(blueprint: IRBlueprint, path=BLUEPRINT_PATH):
    validate_blueprint(blueprint)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(dataclasses.asdict(blueprint), file, ensure_ascii=False, indent=2)


def compile_task(user_prompt: str, output_path=BLUEPRINT_PATH, export_python=None):
    """將自然語言編譯為 validated IR；Python 僅作為選用匯出格式。"""
    from compiler.layer1_intent import Layer1IntentParser
    from compiler.layer2_ir import Layer2IRGenerator
    from compiler.layer3_codegen import Layer3CodeGenerator

    print("\n[系統] 啟動自然語言到 IR 的編譯 Pipeline...")
    clean_text = Layer1IntentParser(model_name=MODEL_CODER).parse_and_confirm(user_prompt)
    if not clean_text:
        raise RuntimeError("Layer 1 未產生有效任務")

    blueprint = Layer2IRGenerator(model_name=MODEL_CODER).generate_blueprint(clean_text)
    if not blueprint:
        raise RuntimeError("Layer 2 未產生有效 IR blueprint")
    save_blueprint(blueprint, output_path)
    print(f"[系統] 已儲存 validated IR: {output_path}")

    if export_python:
        code = Layer3CodeGenerator(model_name=MODEL_CODER).generate_code(blueprint)
        if not code:
            raise RuntimeError("Layer 3 Python 匯出失敗")
        with open(export_python, "w", encoding="utf-8") as file:
            file.write(code)
        print(f"[系統] 已匯出 Python（不會由主流程自動執行）: {export_python}")
    return blueprint


def _request_repair(blueprint, trace_log, env, generation):
    from compiler.layer2_ir import Layer2IRGenerator
    from compiler.layer4_sandbox import Layer4SandboxQA

    error_screen_path = os.path.join(WORKSPACE_DIR, f"error_state_gen{generation}.png")
    env.capture_screen().save(error_screen_path)
    blueprint_json = json.dumps(dataclasses.asdict(blueprint), ensure_ascii=False, indent=2)

    qa = Layer4SandboxQA(vision_model=MODEL_VISION, logic_model=MODEL_CODER)
    report = qa.evaluate(
        layer1_tree=blueprint_json,
        generated_code="Runtime directly executes the validated IR shown above.",
        test_scenario="Validated IR runtime encountered a terminal Behavior Tree failure.",
        raw_trace="\n".join(trace_log),
        error_image_path=error_screen_path,
    )
    if not isinstance(report, dict):
        print("[系統] QA 回傳格式不是 JSON object，停止自動修補。")
        return None
    if report.get("status") == "PASS" or report.get("target_layer") != "L2":
        print(f"[系統] 診斷不適合修改 IR，停止自動修補: {report}")
        return None

    patched = Layer2IRGenerator(model_name=MODEL_CODER).patch_blueprint(blueprint, report)
    if patched:
        validate_blueprint(patched)
    return patched


def run_blueprint(
    blueprint: IRBlueprint,
    blueprint_path=BLUEPRINT_PATH,
    enable_healing=True,
    max_generations=3,
    max_ticks=3000,
    tick_interval=0.2,
):
    """直接執行 validated IR，並在受限世代內嘗試結構修補。"""
    from brain import Brain
    from compiler.ir_executor import IRExecutor
    from environment import Environment
    from memory import MemoryManager

    validate_blueprint(blueprint)
    env = Environment()
    try:
        brain = Brain()
        memory = MemoryManager(MEMORY_FILE)
        executor = IRExecutor()
        for generation in range(1, max_generations + 1):
            print(f"\n>>> 啟動第 {generation} 代 IR 行為樹 <<<")
            tree = executor.build_tree(blueprint)
            trace_log = []

            for _ in range(1, max_ticks + 1):
                state = tree.tick(env, brain, memory, trace_log)
                if state == NodeState.SUCCESS:
                    print("\n[系統] 任務樹執行完畢。")
                    return True
                if state == NodeState.FAILURE:
                    print("\n[系統] 任務樹失敗。")
                    if not enable_healing or generation >= max_generations:
                        return False
                    patched = _request_repair(blueprint, trace_log, env, generation)
                    if not patched:
                        return False
                    blueprint = patched
                    save_blueprint(blueprint, blueprint_path)
                    print("[系統] IR 修補與驗證完成，準備執行下一世代。")
                    break
                time.sleep(tick_interval)
            else:
                print(f"\n[系統] 達到最大 Tick 限制 ({max_ticks})。")
                return False
        return False
    finally:
        env.stop_stream()


def run_example(max_ticks=3000, tick_interval=0.2):
    """明確執行 repository 內的 Python 範例，不作自動修補。"""
    from brain import Brain
    from environment import Environment
    from memory import MemoryManager

    env = Environment()
    try:
        brain = Brain()
        memory = MemoryManager(MEMORY_FILE)
        module = importlib.import_module("task_definitions")
        tree = module.build_startup_tree()
        trace_log = []
        for _ in range(max_ticks):
            state = tree.tick(env, brain, memory, trace_log)
            if state != NodeState.RUNNING:
                return state == NodeState.SUCCESS
            time.sleep(tick_interval)
        return False
    finally:
        env.stop_stream()


def build_parser():
    parser = argparse.ArgumentParser(description="Autonomous Vision-Language UI Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="自然語言 → validated IR")
    compile_parser.add_argument("--task", help="自然語言任務；省略時互動輸入")
    compile_parser.add_argument("--output", default=BLUEPRINT_PATH)
    compile_parser.add_argument("--export-python", metavar="PATH")

    run_parser = subparsers.add_parser("run", help="直接執行 validated IR")
    run_parser.add_argument("--blueprint", default=BLUEPRINT_PATH)
    run_parser.add_argument("--no-heal", action="store_true")
    run_parser.add_argument("--max-generations", type=int, default=3)
    run_parser.add_argument("--max-ticks", type=int, default=3000)

    example_parser = subparsers.add_parser("run-example", help="執行 tracked Python 範例")
    example_parser.add_argument("--max-ticks", type=int, default=3000)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compile":
            task = args.task or input("請輸入您的自動化任務需求: ").strip()
            if not task:
                raise ValueError("任務內容不可為空")
            compile_task(task, output_path=args.output, export_python=args.export_python)
            return 0
        if args.command == "run":
            blueprint = load_blueprint(args.blueprint)
            success = run_blueprint(
                blueprint,
                blueprint_path=args.blueprint,
                enable_healing=not args.no_heal,
                max_generations=args.max_generations,
                max_ticks=args.max_ticks,
            )
            return 0 if success else 1
        if args.command == "run-example":
            return 0 if run_example(max_ticks=args.max_ticks) else 1
        return 2
    except (FileNotFoundError, json.JSONDecodeError, IRValidationError, RuntimeError, ValueError) as exc:
        print(f"[系統錯誤] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
