from __future__ import annotations

import re

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class StepType(Enum):
    WAIT_CONDITION = "wait_condition"
    GUARDED_ACTION = "guarded_action"
    SEQUENCE = "sequence"
    SELECTOR = "selector"


class ErrorCategory(Enum):
    SYNTAX_ERROR = "SYNTAX_ERROR"
    VLM_PROMPT_INVALID = "VLM_PROMPT_INVALID"
    LOGICAL_DEADLOCK = "LOGICAL_DEADLOCK"
    UNHANDLED_STATE = "UNHANDLED_STATE"


class TargetType(Enum):
    TEXT = "text"
    ICON = "icon"
    UNKNOWN = "unknown"


@dataclass
class IRStep:
    step_type: str = StepType.SEQUENCE.value
    name: str = ""
    description: str = ""
    target: Optional[str] = None
    target_type: str = TargetType.UNKNOWN.value
    context_desc: Optional[str] = None
    pre_check_prompt: Optional[str] = None
    post_check_prompt: Optional[str] = None
    check_prompt: Optional[str] = None
    normalized_coord: Optional[List[float]] = None
    fallback_strategy: Optional[str] = None
    children: List[IRStep] = field(default_factory=list)

    @classmethod
    def from_dict(
        cls,
        data: dict,
        warnings: Optional[List[str]] = None,
        path: str = "step",
    ) -> IRStep:
        """Normalize common model variations into the four canonical node types."""
        warnings = warnings if warnings is not None else []
        if not isinstance(data, dict):
            warnings.append(f"{path}: non-object step became an empty sequence")
            return cls()

        raw_children = data.get("children") or data.get("steps") or []
        if "children" not in data and "steps" in data:
            warnings.append(f"{path}: field 'steps' normalized to 'children'")
        if not isinstance(raw_children, list):
            warnings.append(f"{path}.children: non-list value was ignored")
            raw_children = []
        children = []
        for index, child in enumerate(raw_children):
            if isinstance(child, dict):
                children.append(cls.from_dict(child, warnings, f"{path}.children[{index}]"))
            else:
                warnings.append(f"{path}.children[{index}]: non-object child was ignored")

        raw_step_value = data.get("step_type") or data.get("type") or ""
        if "step_type" not in data and "type" in data:
            warnings.append(f"{path}: field 'type' normalized to 'step_type'")
        raw_step_type = str(raw_step_value).strip().lower()
        aliases = {
            "noop": StepType.SEQUENCE.value,
            "no_op": StepType.SEQUENCE.value,
            "skip": StepType.SEQUENCE.value,
            "pass": StepType.SEQUENCE.value,
            "action": StepType.GUARDED_ACTION.value,
            "guardedaction": StepType.GUARDED_ACTION.value,
            "guarded-action": StepType.GUARDED_ACTION.value,
            "click": StepType.GUARDED_ACTION.value,
            "tap": StepType.GUARDED_ACTION.value,
            "condition": StepType.WAIT_CONDITION.value,
            "waitcondition": StepType.WAIT_CONDITION.value,
            "wait-condition": StepType.WAIT_CONDITION.value,
            "wait": StepType.WAIT_CONDITION.value,
            "check": StepType.WAIT_CONDITION.value,
            "fallback": StepType.SELECTOR.value,
            "if_else": StepType.SELECTOR.value,
        }
        valid_step_types = {item.value for item in StepType}
        if raw_step_type in aliases:
            step_type = aliases[raw_step_type]
            warnings.append(
                f"{path}: step_type {raw_step_type!r} normalized to {step_type!r}"
            )
        elif raw_step_type in valid_step_types:
            step_type = raw_step_type
        else:
            if children:
                step_type = StepType.SEQUENCE.value
            elif data.get("target") or data.get("target_desc"):
                step_type = StepType.GUARDED_ACTION.value
            elif (
                data.get("check_prompt")
                or data.get("condition_prompt")
                or data.get("context_desc")
                or data.get("description")
            ):
                step_type = StepType.WAIT_CONDITION.value
            else:
                step_type = StepType.SEQUENCE.value
            warnings.append(
                f"{path}: unknown/missing step_type {raw_step_type!r} inferred as {step_type!r}"
            )

        raw_target_type = str(data.get("target_type") or TargetType.UNKNOWN.value).strip().lower()
        target_aliases = {
            "ocr": TargetType.TEXT.value,
            "label": TargetType.TEXT.value,
            "image": TargetType.ICON.value,
            "visual": TargetType.ICON.value,
            "symbol": TargetType.ICON.value,
        }
        target_type = target_aliases.get(raw_target_type, raw_target_type)
        if target_type not in {item.value for item in TargetType}:
            warnings.append(
                f"{path}: target_type {raw_target_type!r} normalized to 'unknown'"
            )
            target_type = TargetType.UNKNOWN.value

        def optional_text(field_name, *aliases):
            value = data.get(field_name)
            if value is None:
                for alias in aliases:
                    if data.get(alias) is not None:
                        value = data.get(alias)
                        warnings.append(
                            f"{path}: field {alias!r} normalized to {field_name!r}"
                        )
                        break
            if value is None:
                return None
            if not isinstance(value, str):
                warnings.append(f"{path}.{field_name}: value converted to text")
            return str(value).strip()

        name = optional_text("name") or ""
        target = optional_text("target", "target_desc")
        description = optional_text("description") or ""
        context_desc = optional_text("context_desc")
        pre_check_prompt = optional_text("pre_check_prompt")
        post_check_prompt = optional_text("post_check_prompt", "expected_state")
        check_prompt = optional_text("check_prompt", "condition_prompt")

        return cls(
            step_type=step_type,
            name=name,
            description=description,
            target=target,
            target_type=target_type,
            context_desc=context_desc,
            pre_check_prompt=pre_check_prompt,
            post_check_prompt=post_check_prompt,
            check_prompt=check_prompt,
            normalized_coord=data.get("normalized_coord"),
            fallback_strategy=data.get("fallback_strategy"),
            children=children,
        )


@dataclass
class IRBlueprint:
    task_name: str = "Untitled Task"
    app_name: str = ""
    steps: List[IRStep] = field(default_factory=list)

    @classmethod
    def from_dict(
        cls,
        data: dict,
        warnings: Optional[List[str]] = None,
    ) -> IRBlueprint:
        warnings = warnings if warnings is not None else []
        if not isinstance(data, dict):
            return cls()

        raw_steps = data.get("steps") or []
        if not isinstance(raw_steps, list):
            warnings.append("steps: non-list value was ignored")
            raw_steps = []
        steps = []
        for index, step in enumerate(raw_steps):
            if isinstance(step, dict):
                steps.append(IRStep.from_dict(step, warnings, f"steps[{index}]"))
            else:
                warnings.append(f"steps[{index}]: non-object step was ignored")
        if "app_name" not in data and data.get("game_name"):
            warnings.append("field 'game_name' normalized to 'app_name'")
        return cls(
            task_name=str(data.get("task_name") or "Untitled Task").strip(),
            app_name=str(data.get("app_name") or data.get("game_name") or "").strip(),
            steps=steps,
        )


class IRValidationError(ValueError):
    pass


def derive_wait_check_prompt(step: IRStep, app_name: str = "") -> str:
    """Turn an imperative wait label into a visually testable state prompt."""
    source = (step.context_desc or step.description or step.name or "").strip()
    state = re.sub(r"^(?:Else\s*分支[:：]?|否則[:：]?|等待|等到|直到|直至)\s*", "", source, flags=re.IGNORECASE)
    state = state.replace("_", " ").strip(" ：:") or source

    loading_terms = ("載入", "加载", "啟動", "启动", "登入", "登录")
    game_terms = ("遊戲", "游戏", "頁面", "页面", "主城", "大廳", "大厅")
    if any(term in source for term in loading_terms) and any(term in source for term in game_terms):
        app = app_name or "目標應用程式"
        return (
            f"{app} 的遊戲內介面或遊戲內彈窗已清楚顯示，"
            "且目前不是裝置桌面、啟動畫面或載入畫面"
        )

    return f"畫面已經清楚達成以下狀態：{state}"


def validate_blueprint(
    blueprint: IRBlueprint,
    warnings: Optional[List[str]] = None,
) -> IRBlueprint:
    """Accept repairable model noise while blocking ambiguous unsafe behavior."""
    warnings = warnings if warnings is not None else []
    if not isinstance(blueprint, IRBlueprint):
        raise IRValidationError("blueprint must be an IRBlueprint")
    if not blueprint.steps:
        raise IRValidationError("blueprint must contain at least one step")

    valid_step_types = {item.value for item in StepType}
    valid_target_types = {item.value for item in TargetType}

    def validate_step(step: IRStep, path: str):
        if step.step_type not in valid_step_types:
            raise IRValidationError(f"{path}: unknown step_type {step.step_type!r}")
        if not step.name:
            step.name = f"Unnamed {step.step_type}"
            warnings.append(f"{path}: missing name was generated as {step.name!r}")
        if step.target_type not in valid_target_types:
            warnings.append(f"{path}: invalid target_type changed to 'unknown'")
            step.target_type = TargetType.UNKNOWN.value
        if step.step_type == StepType.SELECTOR.value and not step.children:
            raise IRValidationError(f"{path}: empty selector has no safe outcome")
        if step.step_type == StepType.SELECTOR.value and len(step.children) == 1:
            warnings.append(f"{path}: selector has only one branch")
        if step.step_type == StepType.SEQUENCE.value and not step.children:
            warnings.append(f"{path}: empty sequence accepted as a successful no-operation branch")
        if step.step_type in {StepType.SEQUENCE.value, StepType.SELECTOR.value}:
            if step.target:
                warnings.append(f"{path}: target on composite node was ignored")
                step.target = None
                step.target_type = TargetType.UNKNOWN.value
        elif step.children:
            raise IRValidationError(f"{path}: leaf node cannot contain children")
        if step.step_type == StepType.GUARDED_ACTION.value and not step.target:
            raise IRValidationError(f"{path}: guarded_action requires target")
        if step.step_type == StepType.WAIT_CONDITION.value and not step.check_prompt:
            step.check_prompt = derive_wait_check_prompt(step, blueprint.app_name)
            warnings.append(
                f"{path}: missing check_prompt was derived as {step.check_prompt!r}"
            )
        if step.normalized_coord is not None:
            if (
                not isinstance(step.normalized_coord, (list, tuple))
                or len(step.normalized_coord) != 2
                or not all(isinstance(value, (int, float)) for value in step.normalized_coord)
                or not all(0.0 <= value <= 1.0 for value in step.normalized_coord)
            ):
                warnings.append(f"{path}: invalid normalized_coord was discarded")
                step.normalized_coord = None
        for index, child in enumerate(step.children):
            validate_step(child, f"{path}.children[{index}]")
        if step.step_type == StepType.SELECTOR.value:
            for index, child in enumerate(step.children[:-1]):
                if child.step_type == StepType.SEQUENCE.value and not child.children:
                    warnings.append(
                        f"{path}.children[{index}]: successful empty sequence makes later selector branches unreachable"
                    )
        signatures = [
            (child.step_type, child.name, child.target, child.check_prompt)
            for child in step.children
        ]
        if len(signatures) != len(set(signatures)):
            warnings.append(f"{path}: duplicate child nodes detected")

    for index, step in enumerate(blueprint.steps):
        validate_step(step, f"steps[{index}]")
    return blueprint


@dataclass
class BugReport:
    status: str = "FAILED"
    error_category: Union[ErrorCategory, str] = ErrorCategory.SYNTAX_ERROR.value
    target_layer: str = "NONE"
    failed_test_case: str = ""
    error_node_name: str = ""
    diagnostic_message: str = ""
    trace_log: str = ""


def get_bug_report_attr(
    bug_report: Union[BugReport, dict, None], attr_name: str, default: str = ""
) -> str:
    if not bug_report:
        return default

    if isinstance(bug_report, dict):
        raw_val = bug_report.get(attr_name)
    else:
        raw_val = getattr(bug_report, attr_name, None)

    if raw_val is None:
        return default

    if isinstance(raw_val, Enum):
        return str(raw_val.value)

    return str(raw_val)
