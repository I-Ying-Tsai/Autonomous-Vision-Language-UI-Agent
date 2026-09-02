from __future__ import annotations

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
    check_prompt: Optional[str] = None
    normalized_coord: Optional[List[float]] = None
    fallback_strategy: Optional[str] = None
    children: List[IRStep] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> IRStep:
        """Recursively converts dict into typed IRStep with null-safety."""
        if not isinstance(data, dict):
            return cls()

        raw_children = data.get("children") or []
        children = [cls.from_dict(c) for c in raw_children if isinstance(c, dict)]

        return cls(
            step_type=data.get("step_type") or StepType.SEQUENCE.value,
            name=data.get("name") or "",
            description=data.get("description") or "",
            target=data.get("target"),
            target_type=data.get("target_type") or TargetType.UNKNOWN.value,
            context_desc=data.get("context_desc"),
            pre_check_prompt=data.get("pre_check_prompt"),
            check_prompt=data.get("check_prompt"),
            normalized_coord=data.get("normalized_coord"),
            fallback_strategy=data.get("fallback_strategy"),
            children=children,
        )


@dataclass
class IRBlueprint:
    task_name: str = "Untitled Task"
    steps: List[IRStep] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> IRBlueprint:
        if not isinstance(data, dict):
            return cls()

        raw_steps = data.get("steps") or []
        steps = [IRStep.from_dict(s) for s in raw_steps if isinstance(s, dict)]
        return cls(
            task_name=data.get("task_name") or "Untitled Task",
            steps=steps,
        )


@dataclass
class BugReport:
    status: str = "FAILED"
    error_category: Union[ErrorCategory, str] = ErrorCategory.SYNTAX_ERROR.value
    target_layer: str = "L3"
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