from compiler.schemas import IRBlueprint, IRStep, StepType, validate_blueprint
from nodes import ConditionNode, GuardedActionNode, SelectorNode, SequenceNode


class IRExecutor:
    """將驗證後的 IR 直接建成 Behavior Tree，不執行 LLM 產生的 Python。"""

    def __init__(
        self,
        default_condition_retries=60,
        default_condition_interval=2.0,
        default_condition_confirmations=3,
    ):
        self.default_condition_retries = default_condition_retries
        self.default_condition_interval = default_condition_interval
        self.default_condition_confirmations = default_condition_confirmations

    def build_tree(self, blueprint: IRBlueprint):
        validate_blueprint(blueprint)
        game_name = blueprint.app_name or blueprint.task_name.split("_", 1)[0]
        children = [self._build_step(step, game_name) for step in blueprint.steps]
        if len(children) == 1:
            return children[0]
        return SequenceNode(name=blueprint.task_name, children=children)

    def _build_step(self, step: IRStep, game_name: str, ancestors=()):
        if step.step_type == StepType.SEQUENCE.value:
            return SequenceNode(
                name=step.name,
                children=[
                    self._build_step(child, game_name, (*ancestors, step.name))
                    for child in step.children
                ],
            )
        if step.step_type == StepType.SELECTOR.value:
            return SelectorNode(
                name=step.name,
                children=[
                    self._build_step(child, game_name, (*ancestors, step.name))
                    for child in step.children
                ],
            )
        if step.step_type == StepType.WAIT_CONDITION.value:
            check_prompt = step.check_prompt or step.context_desc or step.description or step.name
            return ConditionNode(
                name=step.name,
                check_prompt=check_prompt,
                max_retries=self.default_condition_retries,
                interval=self.default_condition_interval,
                required_consecutive_matches=self.default_condition_confirmations,
            )
        if step.step_type == StepType.GUARDED_ACTION.value:
            inherited_context = " > ".join(item for item in ancestors[-2:] if item)
            return GuardedActionNode(
                name=step.name,
                target_desc=step.target,
                target_type=step.target_type,
                game_name=game_name,
                context_desc=step.context_desc or inherited_context or None,
                post_check_prompt=step.post_check_prompt,
            )
        raise ValueError(f"unsupported step type: {step.step_type}")
