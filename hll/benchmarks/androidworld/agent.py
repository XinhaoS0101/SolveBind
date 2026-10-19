from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image
from android_world.agents import base_agent
from android_world.env import interface, json_action

from hll.benchmarks.androidworld.actions import (
    AndroidWorldAction,
    build_action_schema_prompt,
    parse_androidworld_action,
)
from hll.model import ModelMessage, ModelRequestError, VisionModel


_PROMPT_HEADER = """You operate an Android phone to complete a general user task.
Use the current screenshot, visible UI element list, goal, and recent action history.
Return exactly one JSON object and no markdown:
{"action":"...","args":{...},"reason":"short reason"}

Choose one action from the MCP-style action catalog below. The action field must
match a listed snake_case name and args must match that action's schema."""


_WORKFLOW_GUIDE = """### General Android task workflow ###
1. Read the full user goal and inspect the current screen before acting.
2. Prefer open_app when the goal names an app. Use a listed UI element index when
   it uniquely identifies the target; otherwise use screenshot coordinates.
3. Execute one grounded action at a time, then use the next observation to check
   whether it worked. Do not repeat an ineffective action without changing the target.
4. The screenshot is authoritative. Accessibility elements can lag during screen
   transitions; if they disagree with the screenshot, use screenshot coordinates or wait.
5. Use scroll to reveal content that is not visible. Use navigate_back to recover
   from the wrong screen without discarding useful progress.
6. Use input_text with clear_text=true when replacing existing field content.
7. For information-retrieval questions, call answer with the final answer, then use
   status complete on the following step.
8. Use status complete after the requested state is achieved so the episode stops early.
   AndroidWorld's official evaluator independently scores the final device state.
9. Use status infeasible only when the task cannot be completed after bounded recovery."""


SYSTEM_PROMPT = "\n\n".join(
    (_PROMPT_HEADER, _WORKFLOW_GUIDE, build_action_schema_prompt())
)


class HllAndroidWorldAgent(base_agent.EnvironmentInteractingAgent):


    def __init__(
        self,
        env: interface.AsyncEnv,
        model: VisionModel,
        *,
        artifact_dir: str | Path,
        name: str = "hll_androidworld",
        transition_pause: float | None = None,
        history_limit: int = 8,
        max_ui_elements: int = 120,
    ) -> None:
        super().__init__(env, name=name, transition_pause=transition_pause)
        self.model = model
        self.artifact_root = Path(artifact_dir).expanduser().resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.history_limit = max(0, int(history_limit))
        self.max_ui_elements = max(1, int(max_ui_elements))
        self.history: list[dict[str, Any]] = []
        self.last_feedback = ""
        self.step_number = 0
        self.episode_number = _next_episode_number(self.artifact_root) - 1
        self.episode_dir = self.artifact_root

    def reset(self, go_home: bool = False) -> None:
        super().reset(go_home=go_home)
        self.env.hide_automation_ui()
        self.history.clear()
        self.last_feedback = ""
        self.step_number = 0
        self.episode_number += 1
        self.episode_dir = self.artifact_root / f"episode_{self.episode_number:04d}"
        self.episode_dir.mkdir(parents=True, exist_ok=True)

    def step(self, goal: str) -> base_agent.AgentInteractionResult:
        self.step_number += 1
        state = self.get_post_transition_state()
        screenshot_path = self._save_screenshot(state)
        height, width = state.pixels.shape[:2]
        logical_width, logical_height = self.env.logical_screen_size
        ui_elements = _serialize_ui_elements(
            state.ui_elements,
            limit=self.max_ui_elements,
        )
        prompt = self._build_prompt(
            goal=goal,
            screenshot_size=(width, height),
            logical_size=(logical_width, logical_height),
            ui_elements=ui_elements,
        )
        step_data: dict[str, Any] = {
            "screenshot_path": str(screenshot_path),
            "screenshot_size": [width, height],
            "logical_screen_size": [logical_width, logical_height],
            "ui_elements": ui_elements,
            "action_prompt": prompt,
            "action_raw_response": "",
            "parsed_action": None,
            "executed_action": None,
            "action_reason": "",
            "model_usage": {},
            "model_seconds": 0.0,
            "execution_seconds": 0.0,
            "error": "",
        }

        model_started = time.monotonic()
        try:
            reply = self.model.complete(
                [
                    ModelMessage(role="system", text=SYSTEM_PROMPT),
                    ModelMessage(
                        role="user",
                        text=prompt,
                        image_path=str(screenshot_path),
                    ),
                ]
            )
            usage = dict(reply.usage)
            step_data["action_raw_response"] = reply.text
            step_data["model_usage"] = usage
            if not reply.text.strip():
                retry = self.model.complete(
                    [
                        ModelMessage(role="system", text=SYSTEM_PROMPT),
                        ModelMessage(
                            role="user",
                            text=prompt,
                            image_path=str(screenshot_path),
                        ),
                    ]
                )
                usage = _merge_usage(usage, retry.usage)
                reply = retry
            step_data["action_raw_response"] = reply.text
            step_data["model_usage"] = usage
            action = parse_androidworld_action(reply.text)
        except ModelRequestError:
            raise
        except Exception as exc:
            step_data["model_seconds"] = round(time.monotonic() - model_started, 4)
            return self._failed_step(
                step_data,
                f"model_or_action_error: {type(exc).__name__}: {exc}",
            )

        step_data["model_seconds"] = round(time.monotonic() - model_started, 4)
        action = _map_screenshot_coordinates(
            action,
            screenshot_size=(width, height),
            logical_size=(logical_width, logical_height),
        )
        step_data["parsed_action"] = action.to_dict()
        step_data["action_reason"] = action.reason

        try:
            _validate_element_index(action, len(state.ui_elements))
            native_action = json_action.JSONAction(
                action_type=action.kind,
                **dict(action.args),
            )
        except Exception as exc:
            return self._failed_step(
                step_data,
                f"action_validation_error: {type(exc).__name__}: {exc}",
                action=action,
            )

        step_data["executed_action"] = native_action.as_dict()
        if action.kind == "status":
            feedback = f"agent_status_{action.args['goal_status']}"
            self._remember(action, feedback, error="")
            self.last_feedback = feedback
            step_data["feedback"] = feedback
            return base_agent.AgentInteractionResult(done=True, data=step_data)

        execution_started = time.monotonic()
        try:
            self.env.execute_action(native_action)
        except Exception as exc:
            step_data["execution_seconds"] = round(
                time.monotonic() - execution_started,
                4,
            )
            return self._failed_step(
                step_data,
                f"action_execution_error: {type(exc).__name__}: {exc}",
                action=action,
            )

        step_data["execution_seconds"] = round(
            time.monotonic() - execution_started,
            4,
        )
        feedback = "action_executed"
        self._remember(action, feedback, error="")
        self.last_feedback = feedback
        step_data["feedback"] = feedback
        return base_agent.AgentInteractionResult(done=False, data=step_data)

    def _build_prompt(
        self,
        *,
        goal: str,
        screenshot_size: tuple[int, int],
        logical_size: tuple[int, int],
        ui_elements: Sequence[Mapping[str, Any]],
    ) -> str:
        max_steps = self._max_steps if self._max_steps is not None else "unknown"
        history = (
            self.history[-self.history_limit :]
            if self.history_limit
            else []
        )
        return (
            f"Goal: {goal}\n"
            f"Step: {self.step_number}/{max_steps}\n"
            f"Screenshot size: {screenshot_size[0]}x{screenshot_size[1]}\n"
            f"Android logical size: {logical_size[0]}x{logical_size[1]}\n"
            f"Last feedback: {self.last_feedback or 'none'}\n"
            f"Recent steps: {json.dumps(history, ensure_ascii=False)}\n"
            "Visible/actionable UI elements follow. Their index values refer to the "
            "current AndroidWorld UI element list:\n"
            f"{json.dumps(list(ui_elements), ensure_ascii=False)}\n"
            "Choose the single best next action. Coordinates must be absolute pixels "
            "in the attached screenshot."
        )

    def _save_screenshot(self, state: interface.State) -> Path:
        path = self.episode_dir / f"screen_{self.step_number:03d}.png"
        Image.fromarray(state.pixels).save(path)
        return path.resolve()

    def _failed_step(
        self,
        step_data: dict[str, Any],
        error: str,
        *,
        action: AndroidWorldAction | None = None,
    ) -> base_agent.AgentInteractionResult:
        step_data["error"] = error
        step_data["feedback"] = error
        self.last_feedback = error
        if action is not None:
            self._remember(action, "action_failed", error=error)
        else:
            self.history.append(
                {
                    "step": self.step_number,
                    "action": "invalid",
                    "feedback": error,
                }
            )
        return base_agent.AgentInteractionResult(done=False, data=step_data)

    def _remember(
        self,
        action: AndroidWorldAction,
        feedback: str,
        *,
        error: str,
    ) -> None:
        item = {
            "step": self.step_number,
            "action": action.kind,
            "args": dict(action.args),
            "reason": action.reason,
            "feedback": feedback,
        }
        if error:
            item["error"] = error
        self.history.append(item)


def _serialize_ui_elements(
    elements: Sequence[Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        if getattr(element, "is_visible", None) is False:
            continue
        text_fields = {
            key: _compact_text(getattr(element, key, None))
            for key in (
                "text",
                "content_description",
                "hint_text",
                "tooltip",
                "resource_name",
                "class_name",
            )
        }
        actionable = any(
            bool(getattr(element, key, False))
            for key in (
                "is_clickable",
                "is_long_clickable",
                "is_editable",
                "is_scrollable",
            )
        )
        if not actionable and not any(text_fields.values()):
            continue

        item: dict[str, Any] = {"index": index}
        item.update({key: value for key, value in text_fields.items() if value})
        bbox = getattr(element, "bbox_pixels", None)
        if bbox is not None:
            item["bbox"] = [
                int(bbox.x_min),
                int(bbox.y_min),
                int(bbox.x_max),
                int(bbox.y_max),
            ]
        for key in (
            "is_clickable",
            "is_long_clickable",
            "is_editable",
            "is_scrollable",
            "is_checked",
            "is_selected",
        ):
            value = getattr(element, key, None)
            if value is not None:
                item[key.removeprefix("is_")] = bool(value)
        serialized.append(item)
        if len(serialized) >= limit:
            break
    return serialized


def _compact_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def _validate_element_index(action: AndroidWorldAction, element_count: int) -> None:
    if "index" not in action.args:
        return
    index = int(action.args["index"])
    if index < 0 or index >= element_count:
        raise ValueError(
            f"UI element index {index} is outside the current range 0..{element_count - 1}"
        )


def _map_screenshot_coordinates(
    action: AndroidWorldAction,
    *,
    screenshot_size: tuple[int, int],
    logical_size: tuple[int, int],
) -> AndroidWorldAction:
    if "x" not in action.args or "y" not in action.args:
        return action
    screenshot_width, screenshot_height = screenshot_size
    logical_width, logical_height = logical_size
    if screenshot_width <= 0 or screenshot_height <= 0:
        return action
    args = dict(action.args)
    args["x"] = max(
        0,
        min(
            logical_width - 1,
            round(int(args["x"]) * logical_width / screenshot_width),
        ),
    )
    args["y"] = max(
        0,
        min(
            logical_height - 1,
            round(int(args["y"]) * logical_height / screenshot_height),
        ),
    )
    return AndroidWorldAction(kind=action.kind, args=args, reason=action.reason)


def _merge_usage(
    left: Mapping[str, int],
    right: Mapping[str, int],
) -> dict[str, int]:
    keys = set(left) | set(right)
    return {
        key: int(left.get(key, 0) or 0) + int(right.get(key, 0) or 0)
        for key in keys
    }


def _next_episode_number(root: Path) -> int:
    indexes = []
    for path in root.glob("episode_*"):
        try:
            indexes.append(int(path.name.rsplit("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return max(indexes, default=0) + 1
