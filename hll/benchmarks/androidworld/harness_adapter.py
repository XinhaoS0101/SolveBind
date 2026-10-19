from __future__ import annotations

import datetime
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from PIL import Image
from android_world import checkpointer as checkpointer_lib
from android_world import constants
from android_world.env import adb_utils, json_action

from hll.agent import CaptchaAgent
from hll.benchmarks.androidworld.agent import _serialize_ui_elements
from hll.benchmarks.androidworld.profile import build_androidworld_system_prompt
from hll.benchmarks.androidworld.tools import (
    AndroidWorldOcrTool,
    AndroidWorldToolExecutor,
)
from hll.domain import (
    Action,
    ActionKind,
    Decision,
    Evaluation,
    EvaluationStatus,
    ExecutionResult,
    Observation,
    Task,
)
from hll.metrics import intentional_sleep
from hll.executor import ToolExecutor
from hll.harness import Harness, HarnessConfig
from hll.workflow import WorkflowConfig, WorkflowPolicy


class AndroidWorldTaskEnvironment:


    def __init__(
        self,
        env: Any,
        task_eval: Any,
        *,
        adb_path: str,
        device_serial: str,
        max_steps: int,
        max_ui_elements: int = 120,
        wait_to_stabilize: bool = True,
        transition_pause: float | None = None,
    ) -> None:
        self.env = env
        self.task_eval = task_eval
        self.adb_path = adb_path
        self.device_serial = device_serial
        self.max_steps = max(1, int(max_steps))
        self.max_ui_elements = max(1, int(max_ui_elements))
        self.wait_to_stabilize = bool(wait_to_stabilize)
        self.transition_pause = transition_pause
        self.captcha_url = ""
        self.task: Task | None = None
        self.output_dir: Path | None = None
        self.last_size = (0, 0)
        self.last_screenshot_path = ""
        self._pending_state: Any = None
        self._current_state: Any = None
        self._initialized = False
        self._interaction_history: list[dict[str, Any]] = []
        self._evidence_memory: list[dict[str, Any]] = []
        self._named_inputs: list[dict[str, Any]] = []
        self._last_screen_digest = ""
        self._last_mutation_step = 0
        self._last_verification_step = 0
        self._finish_guard_uses = 0
        self._auto_suffix_conflicts: dict[str, str] = {}
        self._suffix_guarded_values: set[str] = set()

    def reset(self, task: Task, output_dir: Path) -> Observation:
        self.task = task
        self.output_dir = output_dir
        self._interaction_history.clear()
        self._evidence_memory.clear()
        self._named_inputs.clear()
        self._last_screen_digest = ""
        self._last_mutation_step = 0
        self._last_verification_step = 0
        self._finish_guard_uses = 0
        self._auto_suffix_conflicts.clear()
        self._suffix_guarded_values.clear()
        try:
            self.task_eval.initialize_task(self.env)
        except Exception:
            self._initialized = bool(getattr(self.task_eval, "initialized", False))
            raise
        self._initialized = True
        self._pending_state = self.env.reset(
            go_home=bool(getattr(self.task_eval, "start_on_home_screen", True))
        )
        self.env.hide_automation_ui()
        return self.observe(0)

    def observe(self, step: int) -> Observation:
        if self.task is None or self.output_dir is None:
            raise RuntimeError("environment has not been reset")
        if step > 0 and self.transition_pause is not None:
            intentional_sleep(
                max(0.0, self.transition_pause),
                "androidworld_transition_pause",
            )
        state = self._pending_state
        self._pending_state = None
        if state is None:
            state = self.env.get_state(wait_to_stabilize=self.wait_to_stabilize)
        pixels = state.pixels
        screen_digest = hashlib.blake2b(
            pixels.tobytes(),
            digest_size=12,
        ).hexdigest()
        if self._last_screen_digest and self._interaction_history:
            latest = self._interaction_history[-1]
            if latest.get("state_changed") is None:
                latest["state_changed"] = (
                    False
                    if latest.get("read_only")
                    else screen_digest != self._last_screen_digest
                )
        self._last_screen_digest = screen_digest
        height, width = pixels.shape[:2]
        screenshot = self.output_dir / f"screen_{step:03d}.png"
        Image.fromarray(pixels).save(screenshot)
        self.last_size = (width, height)
        self.last_screenshot_path = str(screenshot.resolve())
        self._current_state = state
        logical_width, logical_height = self.env.logical_screen_size
        ui_elements = _serialize_ui_elements(
            state.ui_elements,
            limit=self.max_ui_elements,
        )
        return Observation(
            step=step,
            screenshot_path=self.last_screenshot_path,
            width=width,
            height=height,
            instruction=self.task.instruction,
            context={
                "benchmark": "androidworld",
                "logical_screen_size": [int(logical_width), int(logical_height)],
                "max_action_steps": self.max_steps,
                "ui_elements": ui_elements,
                "recent_interactions": self._interaction_history[-8:],
                "evidence_memory": self._evidence_memory[-8:],
                "named_inputs": self._named_inputs[-12:],
                "trajectory_diagnostics": {
                    "consecutive_no_effect": self._consecutive_no_effect(),
                    "repeated_action_count": self._repeated_action_count(),
                    "action_cycle_count": self._action_cycle_count(),
                },
                "finish_verification": {
                    "required": self.needs_finish_verification(),
                    "last_mutation_step": self._last_mutation_step,
                    "last_verification_step": self._last_verification_step,
                },
                "form_constraints": {
                    "auto_suffix_conflicts": dict(self._auto_suffix_conflicts),
                },
                "tool_advice": self._tool_advice(ui_elements),
            },
        )

    def execute(self, decision: Decision) -> ExecutionResult:
        started = time.monotonic()
        action = decision.action
        details: dict[str, Any] = {
            "action": action.kind.value,
            "args": dict(action.args),
            "executor": "androidworld_native",
        }
        if action.kind is ActionKind.FINISH:
            details["agent_finished"] = True
            return ExecutionResult(True, 0.0, details)

        try:
            native = self._native_action(action.kind, action.args)
            details["native_action"] = native.as_dict()
            if (
                action.kind in {ActionKind.TYPE, ActionKind.INPUT_TEXT}
                and not str(action.args.get("text", ""))
                and bool(action.args.get("clear_text", action.args.get("clear_existing")))
            ):
                self._clear_text_field(native)
                details["clear_only"] = True
            else:
                self.env.execute_action(native)
            return ExecutionResult(
                ok=True,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            details.update(error=error, recoverable=True)
            return ExecutionResult(
                ok=False,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
                error=error,
            )

    def close(self) -> None:
        if not self._initialized:
            return
        self._initialized = False
        self.task_eval.tear_down(self.env)

    def get_stats(self) -> dict[str, int]:
        return {}

    def record_execution(
        self,
        decision: Decision,
        execution: ExecutionResult,
        observation: Observation | None = None,
    ) -> None:
        details = dict(execution.details)
        target_label = self._target_label(decision, observation)
        screen_label = self._screen_label(observation)
        entry = {
            "step": len(self._interaction_history) + 1,
            "action": decision.action.kind.value,
            "args": dict(decision.action.args),
            "executor": str(details.get("executor", "")),
            "tool_name": str(details.get("tool_name", "")),
            "read_only": bool(details.get("read_only", False)),
            "ok": bool(execution.ok),
            "error": str(execution.error or details.get("error", "")),
            "target_label": target_label,
            "screen_label": screen_label,
            "reason": decision.reason,
            "state_changed": None,
        }
        self._interaction_history.append(entry)

        step = int(entry["step"])
        if execution.ok and not entry["read_only"] and decision.action.kind not in {
            ActionKind.FINISH,
            ActionKind.WAIT,
        }:
            self._last_mutation_step = step
        if execution.ok and decision.action.kind is ActionKind.GET_OBSERVATION:
            self._last_verification_step = step
        if (
            execution.ok
            and decision.action.kind in {ActionKind.TYPE, ActionKind.INPUT_TEXT}
            and decision.action.args.get("text") not in (None, "")
        ):
            self._remember_named_input(entry, str(decision.action.args["text"]))

        evidence = details.get("ocr_text") or details.get("answer")
        if evidence not in (None, "", [], {}) and bool(
            details.get("usable_evidence", True)
        ):
            self._remember_evidence(
                entry,
                "text",
                evidence,
                source_label=str(details.get("source_label", "") or screen_label),
                quality=details.get("ocr_quality"),
            )
            return
        for key in ("sequence", "challenge"):
            value = details.get(key)
            if value not in (None, "", [], {}):
                self._remember_evidence(
                    entry,
                    key,
                    value,
                    source_label=str(details.get("source_label", "") or screen_label),
                )
                return

    def trajectory_summary(self) -> dict[str, Any]:
        by_tool: dict[str, int] = {}
        for item in self._interaction_history:
            tool_name = str(item.get("tool_name", ""))
            if tool_name:
                by_tool[tool_name] = by_tool.get(tool_name, 0) + 1
        return {
            "total_steps": len(self._interaction_history),
            "recent_actions": self._interaction_history[-8:],
            "no_effect_count": sum(
                1
                for item in self._interaction_history
                if not item.get("read_only") and item.get("state_changed") is False
            ),
            "consecutive_no_effect": self._consecutive_no_effect(),
            "repeated_action_count": self._repeated_action_count(),
            "action_cycle_count": self._action_cycle_count(),
            "tool_calls_by_name": by_tool,
            "evidence_memory": self._evidence_memory[-8:],
            "named_inputs": self._named_inputs[-12:],
            "finish_verification": {
                "required": self.needs_finish_verification(),
                "last_mutation_step": self._last_mutation_step,
                "last_verification_step": self._last_verification_step,
            },
            "form_constraints": {
                "auto_suffix_conflicts": dict(self._auto_suffix_conflicts),
            },
        }

    def _remember_evidence(
        self,
        interaction: Mapping[str, Any],
        kind: str,
        value: Any,
        *,
        source_label: str = "",
        quality: Any = None,
    ) -> None:
        if isinstance(value, str):
            value = value[:4000]
        item = {
            "source_step": int(interaction["step"]),
            "source_tool": str(interaction.get("tool_name", "")),
            "source_label": source_label[:240],
            "kind": kind,
            "value": value,
        }
        if isinstance(quality, Mapping):
            item["quality"] = dict(quality)
        if source_label:
            self._evidence_memory = [
                previous
                for previous in self._evidence_memory
                if not (
                    previous.get("source_label") == source_label
                    and previous.get("kind") == kind
                )
            ]
        self._evidence_memory.append(item)

    def _remember_named_input(
        self,
        interaction: Mapping[str, Any],
        value: str,
    ) -> None:
        recent_targets = [
            str(item.get("target_label", ""))
            for item in self._interaction_history[-4:-1]
            if item.get("target_label")
        ]
        self._named_inputs.append(
            {
                "step": int(interaction["step"]),
                "value": value[:1000],
                "field": str(interaction.get("target_label", "")),
                "screen": str(interaction.get("screen_label", "")),
                "recent_targets": recent_targets,
                "reason": str(interaction.get("reason", ""))[:300],
            }
        )

    @staticmethod
    def _target_label(
        decision: Decision,
        observation: Observation | None,
    ) -> str:
        if decision.action.kind is ActionKind.OPEN_APP:
            return str(decision.action.args.get("app_name", ""))[:240]
        item = AndroidWorldTaskEnvironment._target_element(decision, observation)
        if item is None:
            return ""
        for key in ("text", "content_description", "hint_text", "resource_name"):
            if item.get(key):
                return str(item[key])[:240]
        return ""

    @staticmethod
    def _target_element(
        decision: Decision,
        observation: Observation | None,
    ) -> Mapping[str, Any] | None:
        if observation is None:
            return None
        elements = observation.context.get("ui_elements", [])
        if not isinstance(elements, list):
            return None
        index = decision.action.args.get("index")
        for item in elements:
            if isinstance(item, Mapping) and item.get("index") == index:
                return item
        if "x" not in decision.action.args or "y" not in decision.action.args:
            return None
        try:
            x = float(decision.action.args["x"])
            y = float(decision.action.args["y"])
        except (TypeError, ValueError):
            return None
        candidates: list[tuple[int, Mapping[str, Any]]] = []
        for item in elements:
            if not isinstance(item, Mapping):
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            try:
                x1, y1, x2, y2 = (float(value) for value in bbox)
            except (TypeError, ValueError):
                continue
            if x1 <= x <= x2 and y1 <= y <= y2:
                candidates.append((max(1, int((x2 - x1) * (y2 - y1))), item))
        return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None

    @staticmethod
    def _screen_label(observation: Observation | None) -> str:
        if observation is None:
            return ""
        elements = observation.context.get("ui_elements", [])
        if not isinstance(elements, list):
            return ""
        candidates: list[tuple[int, str]] = []
        for item in elements:
            if not isinstance(item, Mapping) or not item.get("text"):
                continue
            if "systemui" in str(item.get("resource_name", "")):
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            try:
                top = int(bbox[1])
            except (TypeError, ValueError):
                continue
            if top <= observation.height // 4:
                candidates.append((top, str(item["text"])[:240]))
        return min(candidates, key=lambda item: item[0])[1] if candidates else ""

    def _consecutive_no_effect(self) -> int:
        count = 0
        for item in reversed(self._interaction_history):
            if item.get("read_only"):
                continue
            changed = item.get("state_changed")
            if changed is False:
                count += 1
                continue
            break
        return count

    def _repeated_action_count(self) -> int:
        signatures = self._action_signatures()
        if not signatures:
            return 0
        latest = signatures[-1]
        count = 0
        for signature in reversed(signatures):
            if signature != latest:
                break
            count += 1
        return count

    def _action_cycle_count(self) -> int:
        signatures = self._action_signatures()
        for period in (2, 3):
            if len(signatures) < period * 2:
                continue
            block = signatures[-period:]
            repetitions = 1
            cursor = len(signatures) - period * 2
            while cursor >= 0 and signatures[cursor : cursor + period] == block:
                repetitions += 1
                cursor -= period
            if repetitions >= 2:
                return repetitions
        return 0

    def cycle_guard_reason(self, decision: Decision) -> str:
        signatures = self._action_signatures()
        candidate = (
            decision.action.kind.value,
            json.dumps(dict(decision.action.args), ensure_ascii=False, sort_keys=True),
        )
        if self._repeated_action_count() >= 3 and signatures[-1] == candidate:
            return "repeated_action_blocked"
        for period in (2, 3):
            if len(signatures) < period * 2:
                continue
            block = signatures[-period:]
            if signatures[-period * 2 : -period] == block and candidate == block[0]:
                return "action_cycle_blocked"
        return ""

    def action_guard_reason(
        self,
        decision: Decision,
        observation: Observation,
    ) -> str:
        form_reason = self._form_guard_reason(decision, observation)
        return form_reason or self.cycle_guard_reason(decision)

    def needs_finish_verification(self) -> bool:
        return bool(
            len(self._named_inputs) >= 2
            and self._last_mutation_step > self._last_verification_step
            and self._finish_guard_uses < 1
        )

    def note_finish_guard(self) -> None:
        self._finish_guard_uses += 1

    def _action_signatures(self) -> list[tuple[str, str]]:
        return [
            (
                str(item.get("action", "")),
                json.dumps(item.get("args", {}), ensure_ascii=False, sort_keys=True),
            )
            for item in self._interaction_history
            if not item.get("read_only") and item.get("ok")
        ]

    def _form_guard_reason(
        self,
        decision: Decision,
        observation: Observation,
    ) -> str:
        if decision.action.kind not in {ActionKind.CLICK, ActionKind.TAP} or not self._named_inputs:
            return ""
        target = self._target_label(decision, observation).strip().lower()
        if target not in {"ok", "create", "confirm", "done", "add"}:
            return ""
        elements = observation.context.get("ui_elements", [])
        target_element = self._target_element(decision, observation)
        if target_element is not None:
            resource = str(target_element.get("resource_name", "") or "").lower()
            if "inputmethod" in resource or "systemui" in resource:
                return ""
        value = str(self._named_inputs[-1].get("value", "")).strip()
        instruction = self.task.instruction if self.task is not None else ""
        if not value or value not in instruction:
            return ""
        if not isinstance(elements, list):
            return ""
        for item in elements:
            if not isinstance(item, Mapping) or not item.get("editable"):
                continue
            text = str(item.get("text", "") or "").strip()
            resource = str(item.get("resource_name", "") or "").lower()
            hint = str(item.get("hint_text", "") or "").lower()
            is_suffix = "ext" in resource or "extension" in hint or text.startswith(".")
            if is_suffix and text and value + text not in instruction:
                self._auto_suffix_conflicts[value] = text
                if value in self._suffix_guarded_values:
                    return ""
                self._suffix_guarded_values.add(value)
                return "unresolved_auto_suffix"
        return ""

    def _tool_advice(self, ui_elements: list[dict[str, Any]]) -> str:
        if self._action_cycle_count() >= 2:
            return (
                "An action cycle was detected. Stop alternating screens or apps; use one "
                "focused perception tool to capture the missing evidence, then proceed."
            )
        if self._consecutive_no_effect() >= 2:
            return (
                "The recent state-changing actions had no visual effect. Use one focused "
                "perception or trajectory tool now, then choose a different action."
            )
        if self._repeated_action_count() >= 2:
            return (
                "The same action has been repeated. Preserve any gathered evidence and "
                "re-ground instead of repeating it again."
            )
        input_counts: dict[str, int] = {}
        for item in self._named_inputs:
            value = str(item.get("value", ""))
            input_counts[value] = input_counts.get(value, 0) + 1
        if any(count >= 3 for count in input_counts.values()):
            return (
                "The named-input ledger contains the same value three or more times. "
                "Verify whether an existing object should be selected instead of creating "
                "or naming another one."
            )
        if self._auto_suffix_conflicts:
            return (
                "A creation form enforced a suffix not present in the requested full name. "
                "If the suffix cannot stay empty, create the object and use its rename "
                "operation to set and verify the exact requested name before finishing."
            )
        if not any(item.get("clickable") for item in ui_elements):
            return (
                "Structured UI exposes no clear clickable target. Proactively use target "
                "detection, crop, zoom, or classification when one grounds the next action."
            )
        return (
            "Perception tools are normal planning actions: use one proactively whenever "
            "text, a small target, a canvas, or cross-app evidence determines the next action."
        )

    def _native_action(
        self,
        kind: ActionKind,
        raw_args: Mapping[str, Any],
    ) -> json_action.JSONAction:
        args = dict(raw_args)
        action_type = kind.value
        if kind in {ActionKind.TYPE, ActionKind.INPUT_TEXT}:
            action_type = "input_text"
            args["clear_text"] = bool(
                args.pop("clear_existing", args.get("clear_text", True))
            )
        elif kind is ActionKind.KEY:
            key = str(args.pop("key", "")).upper()
            action_type = {
                "BACK": "navigate_back",
                "HOME": "navigate_home",
                "ENTER": "keyboard_enter",
            }.get(key, "")
            if not action_type:
                raise ValueError("key must be BACK, HOME, or ENTER")
        elif kind is ActionKind.WAIT:
            seconds = max(0.0, min(10.0, float(args.pop("seconds", 1.0))))
            intentional_sleep(seconds, "androidworld_wait_action")
            args.clear()
            action_type = "status"
            args["goal_status"] = "in_progress"

        if action_type not in {
            "click",
            "long_press",
            "double_tap",
            "input_text",
            "scroll",
            "open_app",
            "navigate_back",
            "navigate_home",
            "keyboard_enter",
            "answer",
            "status",
        }:
            raise ValueError(f"action {kind.value!r} is not native to AndroidWorld")

        self._validate_index(args)
        self._map_coordinates(args)
        return json_action.JSONAction(action_type=action_type, **args)

    def _clear_text_field(self, action: json_action.JSONAction) -> None:
        focus: dict[str, Any] = {}
        if action.index is not None:
            focus["index"] = action.index
        elif action.x is not None and action.y is not None:
            focus.update(x=action.x, y=action.y)
        if focus:
            self.env.execute_action(
                json_action.JSONAction(action_type="click", **focus)
            )
            time.sleep(1.0)
        response = adb_utils.issue_generic_request(
            [
                "shell",
                "input",
                "keycombination",
                "113",
                "29",
                "&&",
                "input",
                "keyevent",
                "67",
            ],
            self.env.controller,
        )
        adb_utils.check_ok(response, "Failed to clear the focused text field.")
        response = adb_utils.issue_generic_request(
            ["shell", "input", "keyevent", "123", *("67",) * 32],
            self.env.controller,
        )
        adb_utils.check_ok(response, "Failed to finish clearing the text field.")

    def _validate_index(self, args: Mapping[str, Any]) -> None:
        if "index" not in args:
            return
        state = self._current_state
        if state is None:
            raise RuntimeError("current UI element list is unavailable")
        index = int(args["index"])
        if index < 0 or index >= len(state.ui_elements):
            raise ValueError(
                f"UI element index {index} is outside 0..{len(state.ui_elements) - 1}"
            )

    def _map_coordinates(self, args: dict[str, Any]) -> None:
        if "x" not in args and "y" not in args:
            return
        if "x" not in args or "y" not in args:
            raise ValueError("both x and y are required")
        width, height = self.last_size
        logical_width, logical_height = self.env.logical_screen_size
        if width <= 0 or height <= 0:
            return
        args["x"] = max(
            0,
            min(int(logical_width) - 1, round(float(args["x"]) * logical_width / width)),
        )
        args["y"] = max(
            0,
            min(int(logical_height) - 1, round(float(args["y"]) * logical_height / height)),
        )


class AndroidWorldTaskEvaluator:
    """Use the official TaskEval for completion scoring."""

    def __init__(self, env: Any, task_eval: Any) -> None:
        self.env = env
        self.task_eval = task_eval

    def reset(self) -> None:
        pass

    def evaluate(
        self,
        decision: Decision,
        execution: ExecutionResult,
    ) -> Evaluation:
        if not execution.ok:
            return Evaluation(
                status=EvaluationStatus.FAILED_ATTEMPT,
                reward=-0.1,
                reason="action_execution_failed",
                signals={"official_reward": 0.0},
            )
        if decision.action.kind is not ActionKind.FINISH:
            return Evaluation(
                status=EvaluationStatus.RUNNING,
                reason="action_executed",
            )
        if str(decision.action.args.get("goal_status", "complete")) == "infeasible":
            return Evaluation(
                status=EvaluationStatus.STOPPED,
                reason="agent_declared_infeasible",
                done=True,
                signals={"official_reward": 0.0},
            )

        reward = float(self.task_eval.is_successful(self.env) or 0.0)
        successful = reward > 0.5
        return Evaluation(
            status=(
                EvaluationStatus.SUCCESS if successful else EvaluationStatus.STOPPED
            ),
            reward=reward,
            reason=("official_evaluator_success" if successful else "official_evaluator_failure"),
            done=True,
            signals={"official_reward": reward},
        )


class AndroidWorldWorkflowPolicy(WorkflowPolicy):


    def __init__(
        self,
        environment: AndroidWorldTaskEnvironment,
        config: WorkflowConfig,
    ) -> None:
        super().__init__(config)
        self.environment = environment

    def resolve(self, decision: Decision) -> Decision:
        resolved = super().resolve(decision)
        if (
            resolved.action.kind is not ActionKind.FINISH
            or not self.environment.needs_finish_verification()
        ):
            return resolved
        self.environment.note_finish_guard()
        policy = dict(resolved.policy)
        policy.update(
            resolution="overridden",
            guard="androidworld_finish_verification",
        )
        return replace(
            resolved,
            action=Action(ActionKind.GET_OBSERVATION, {}),
            proposed_action=resolved.action,
            reason="workflow:androidworld_finish_verification",
            policy=policy,
        )


def official_reward(result: Any) -> float:


    for record in reversed(result.steps):
        value = record.evaluation.signals.get("official_reward")
        if value is not None:
            return float(value or 0.0)
    return 0.0


def run_harness_suite(
    suite: Mapping[str, list[Any]],
    *,
    env: Any,
    model: Any,
    ocr_model: Any | None,
    checkpointer: Any,
    checkpoint_dir: Path,
    adb_path: str,
    device_serial: str,
    history_limit: int,
    max_ui_elements: int,
    transition_pause: float | None,
    max_read_only_steps: int,
    episode_timeout: float,
    model_base_url: str,
    model_api_key: str,
    model_name: str,
    enable_ocr: bool = False,
) -> tuple[list[dict[str, Any]], bool]:


    loaded = list(checkpointer.load())
    by_instance = {
        (
            str(item.get(constants.EpisodeConstants.TASK_TEMPLATE, "")),
            int(item.get(constants.EpisodeConstants.INSTANCE_ID, 0) or 0),
        ): item
        for item in loaded
    }
    episodes: list[dict[str, Any]] = []
    fatal_model_error = False

    for task_name, instances in suite.items():
        for instance_id, task_eval in enumerate(instances):
            previous = by_instance.get((task_name, instance_id))
            if previous is not None and previous.get(
                constants.EpisodeConstants.EXCEPTION_INFO
            ) is None:
                episodes.append(previous)
                continue

            sample_id = f"{task_name}_{instance_id:03d}"
            output_dir = checkpoint_dir / "episodes" / sample_id
            seed = task_eval.params.get(constants.EpisodeConstants.SEED)
            max_steps = max(1, int(10 * float(task_eval.complexity)))
            task = Task(
                captcha_type=task_name,
                instruction=task_eval.goal,
                config={
                    "benchmark": "androidworld",
                    "sample_id": sample_id,
                    "seed": seed,
                    "task_template": task_name,
                    "complexity": float(task_eval.complexity),
                },
            )
            environment = AndroidWorldTaskEnvironment(
                env,
                task_eval,
                adb_path=adb_path,
                device_serial=device_serial,
                max_steps=max_steps,
                max_ui_elements=max_ui_elements,
                wait_to_stabilize=transition_pause is None,
                transition_pause=transition_pause,
            )
            evaluator = AndroidWorldTaskEvaluator(env, task_eval)
            agent = CaptchaAgent(
                model,
                history_limit=history_limit,
                ocr_enabled=enable_ocr,
                system_prompt=build_androidworld_system_prompt(
                    enable_ocr=enable_ocr
                ),
            )
            ocr_tool = AndroidWorldOcrTool(ocr_model or model) if enable_ocr else None
            base_executor = ToolExecutor(
                environment,
                ocr_tool=ocr_tool,
                model_base_url=model_base_url,
                model_api_key=model_api_key,
                model_name=model_name,
                environment_action_kinds={
                    ActionKind.TYPE,
                    ActionKind.INPUT_TEXT,
                },
            )
            executor = AndroidWorldToolExecutor(base_executor, environment)
            harness = Harness(
                agent=agent,
                environment=environment,
                evaluator=evaluator,
                executor=executor,
                workflow=AndroidWorldWorkflowPolicy(
                    environment,
                    WorkflowConfig(
                        completion_mode="external",
                        auto_submit_when_ready=False,
                        selection_submit_threshold=0,
                    )
                ),
                config=HarnessConfig(
                    max_steps=max_steps,
                    max_read_only_steps=max_read_only_steps,
                    max_total_steps=max_steps,
                    timeout_seconds=episode_timeout,
                ),
                metadata={
                    "benchmark": "androidworld",
                    "runner": "captcha-harness",
                    "model": model_name,
                },
            )

            started = time.monotonic()
            result = harness.run(task, output_dir)
            score = official_reward(result)
            tool_usage = summarize_hll_tool_usage(result)
            accounting = dict(result.metrics.get("model_accounting", {}) or {})
            timing = dict(accounting.get("timing", {}) or {})
            episode = {
                constants.EpisodeConstants.GOAL: task_eval.goal,
                constants.EpisodeConstants.TASK_TEMPLATE: task_name,
                constants.EpisodeConstants.INSTANCE_ID: instance_id,
                constants.EpisodeConstants.IS_SUCCESSFUL: score,
                constants.EpisodeConstants.RUN_TIME: round(
                    time.monotonic() - started,
                    4,
                ),
                constants.EpisodeConstants.FINISH_DTIME: datetime.datetime.now(),
                constants.EpisodeConstants.EPISODE_LENGTH: len(result.steps),
                constants.EpisodeConstants.EPISODE_DATA: {
                    "hll_episode_path": str((output_dir / "episode.json").resolve()),
                    "model_usage": [dict(result.metrics.get("model_usage", {}) or {})],
                    "model_seconds": [
                        float(timing.get("model_request_seconds", 0.0) or 0.0)
                    ],
                },
                constants.EpisodeConstants.AUX_DATA: {
                    "hll_status": result.status.value,
                    "hll_reason": result.reason,
                    "model_accounting": accounting,
                    "hll_tool_usage": tool_usage,
                },
                constants.EpisodeConstants.EXCEPTION_INFO: (
                    result.reason
                    if result.status is EvaluationStatus.ERROR
                    else None
                ),
                constants.EpisodeConstants.SEED: seed,
                constants.EpisodeConstants.AGENT_NAME: "hll_captcha_harness",
            }
            instance_name = (
                task_name
                + checkpointer_lib.INSTANCE_SEPARATOR
                + str(instance_id)
            )
            checkpointer.save_episodes([episode], instance_name)
            episodes.append(episode)

            if (
                result.status is EvaluationStatus.ERROR
                and "ModelRequestError" in result.reason
            ):
                fatal_model_error = True
                break
        if fatal_model_error:
            break

    return episodes, fatal_model_error


def summarize_hll_tool_usage(result: Any) -> dict[str, Any]:


    summary: dict[str, Any] = {
        "total_calls": 0,
        "successful_calls": 0,
        "read_only_calls": 0,
        "action_calls": 0,
        "direct_dispatches": 0,
        "results_delivered": 0,
        "read_only_followed_by_action": 0,
        "by_name": {},
    }
    steps = list(result.steps)
    for index, record in enumerate(steps):
        details = dict(record.execution.details)
        executor = str(details.get("executor", ""))
        if executor not in {"hll_tools", "androidworld_tools"}:
            continue
        tool_name = str(
            details.get("tool_name", record.decision.action.kind.value)
        )
        read_only = bool(details.get("read_only", False))
        summary["total_calls"] += 1
        summary["successful_calls"] += int(record.execution.ok)
        summary["read_only_calls" if read_only else "action_calls"] += 1
        summary["direct_dispatches"] += int(
            details.get("tool_dispatch") == "direct"
        )
        by_name = summary["by_name"]
        by_name[tool_name] = int(by_name.get(tool_name, 0)) + 1
        if not read_only:
            continue
        delivered = dict(record.after.tool_results).get("tool_name") == tool_name
        summary["results_delivered"] += int(delivered)
        if index + 1 < len(steps):
            next_details = dict(steps[index + 1].execution.details)
            summary["read_only_followed_by_action"] += int(
                not bool(next_details.get("read_only", False))
            )
    return summary


__all__ = [
    "AndroidWorldTaskEnvironment",
    "AndroidWorldTaskEvaluator",
    "AndroidWorldWorkflowPolicy",
    "official_reward",
    "run_harness_suite",
    "summarize_hll_tool_usage",
]
