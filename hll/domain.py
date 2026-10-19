"""Shared protocol types must not initialize models, devices, or servers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
from typing import Any, Mapping


class ActionKind(str, Enum):

    INVALID = "invalid_action"
    OCR = "ocr"
    TAP = "tap"
    TYPE = "type"
    INPUT_TEXT = "input_text"
    DRAG = "drag"
    DRAG_BY = "drag_by"
    KEY = "key"
    WAIT = "wait"
    SUBMIT = "submit"
    CHECK = "check"
    REFRESH = "refresh"
    FINISH = "finish"


    CLICK = "click"
    LONG_PRESS = "long_press"
    DOUBLE_TAP = "double_tap"
    SCROLL = "scroll"
    OPEN_APP = "open_app"
    NAVIGATE_BACK = "navigate_back"
    NAVIGATE_HOME = "navigate_home"
    KEYBOARD_ENTER = "keyboard_enter"
    ANSWER = "answer"


    TAP_GRID_CELL = "tap_grid_cell"
    MOVE_GRID_PIECE = "move_grid_piece"
    TAP_REGION_CENTER = "tap_region_center"
    CLICK_TARGET = "click_target"
    CLEAR_SELECTION = "clear_selection"
    SUBMIT_CAPTCHA = "submit_captcha"
    REFRESH_CAPTCHA = "refresh_captcha"
    LOCATE_CAPTCHA_AREA = "locate_captcha_area"
    LOCATE_GRID = "locate_grid"
    DETECT_BOARD = "detect_board"
    DETECT_CLICK_TARGETS = "detect_click_targets"
    LOCATE_SLIDER_TRACK = "locate_slider_track"
    LOCATE_SLIDER_HANDLE = "locate_slider_handle"
    LOCATE_GAP = "locate_gap"
    ESTIMATE_DRAG_OFFSET = "estimate_drag_offset"
    CORRECT_SLIDER_AFTER_FAILURE = "correct_slider_after_failure"
    CROP_REGION = "crop_region"
    ZOOM_REGION = "zoom_region"
    CLASSIFY_REGION = "classify_region"
    NORMALIZE_TEXT = "normalize_text"
    READ_CLICK_SEQUENCE = "read_click_sequence"
    READ_LOGIC_PROMPT = "read_logic_prompt"
    SOLVE_ARITHMETIC = "solve_arithmetic"
    FIND_MATCH = "find_match"
    FIND_WINNING_MOVE = "find_winning_move"
    COMPARE_SIMILARITY = "compare_similarity"
    DETECT_COLOR_MARKERS = "detect_color_markers"
    GET_SCREENSHOT = "get_screenshot"
    GET_OBSERVATION = "get_observation"
    GET_SERVER_STATS = "get_server_stats"
    SUMMARIZE_TRAJECTORY = "summarize_trajectory"
    WAIT_PAGE_READY = "wait_page_ready"


@dataclass(frozen=True)
class Task:


    captcha_type: str
    instruction: str
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    """Expose screenshots and public interface state, never evaluator answers."""

    step: int
    screenshot_path: str
    width: int
    height: int
    instruction: str
    safe_state: Mapping[str, int] = field(default_factory=dict)
    last_feedback: str = ""
    tool_results: Mapping[str, Any] = field(default_factory=dict)
    workflow_state: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:


    kind: ActionKind
    args: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Action":
        raw_kind = value.get("action", value.get("kind", ""))
        try:
            kind = ActionKind(_normalize_action_kind(str(raw_kind)))
        except ValueError as exc:
            allowed = ", ".join(item.value for item in ActionKind)
            raise ValueError(f"unknown action {raw_kind!r}; expected one of: {allowed}") from exc

        args = value.get("args")
        if args is None:
            args = {
                key: item
                for key, item in value.items()
                if key not in {"action", "kind", "reason", "rationale"}
            }
        if not isinstance(args, Mapping):
            raise ValueError("action args must be an object")
        action = cls(kind=kind, args=dict(args))
        action.validate()
        return action

    def validate(self) -> None:
        required = {
            ActionKind.INVALID: (),
            ActionKind.OCR: ("x1", "y1", "x2", "y2"),
            ActionKind.TAP: ("x", "y"),
            ActionKind.TYPE: ("text",),
            ActionKind.INPUT_TEXT: ("text",),
            ActionKind.DRAG: ("x1", "y1", "x2", "y2"),
            ActionKind.DRAG_BY: ("x", "y", "dx", "dy"),
            ActionKind.KEY: ("key",),
            ActionKind.WAIT: (),
            ActionKind.SUBMIT: (),
            ActionKind.CHECK: (),
            ActionKind.REFRESH: (),
            ActionKind.FINISH: (),
            ActionKind.CLICK: (),
            ActionKind.LONG_PRESS: (),
            ActionKind.DOUBLE_TAP: (),
            ActionKind.SCROLL: ("direction",),
            ActionKind.OPEN_APP: ("app_name",),
            ActionKind.NAVIGATE_BACK: (),
            ActionKind.NAVIGATE_HOME: (),
            ActionKind.KEYBOARD_ENTER: (),
            ActionKind.ANSWER: ("text",),
            ActionKind.TAP_GRID_CELL: ("index",),
            ActionKind.MOVE_GRID_PIECE: ("from_index", "to_index"),
            ActionKind.TAP_REGION_CENTER: ("x1", "y1", "x2", "y2"),
            ActionKind.CLICK_TARGET: (),
            ActionKind.CLEAR_SELECTION: (),
            ActionKind.SUBMIT_CAPTCHA: (),
            ActionKind.REFRESH_CAPTCHA: (),
            ActionKind.LOCATE_CAPTCHA_AREA: (),
            ActionKind.LOCATE_GRID: (),
            ActionKind.DETECT_BOARD: (),
            ActionKind.DETECT_CLICK_TARGETS: (),
            ActionKind.LOCATE_SLIDER_TRACK: (),
            ActionKind.LOCATE_SLIDER_HANDLE: (),
            ActionKind.LOCATE_GAP: (),
            ActionKind.ESTIMATE_DRAG_OFFSET: (),
            ActionKind.CORRECT_SLIDER_AFTER_FAILURE: (),
            ActionKind.CROP_REGION: ("x1", "y1", "x2", "y2"),
            ActionKind.ZOOM_REGION: ("x1", "y1", "x2", "y2"),
            ActionKind.CLASSIFY_REGION: ("x1", "y1", "x2", "y2"),
            ActionKind.NORMALIZE_TEXT: ("text",),
            ActionKind.READ_CLICK_SEQUENCE: (),
            ActionKind.READ_LOGIC_PROMPT: (),
            ActionKind.SOLVE_ARITHMETIC: ("expr",),
            ActionKind.FIND_MATCH: (),
            ActionKind.FIND_WINNING_MOVE: (),
            ActionKind.COMPARE_SIMILARITY: ("x1", "y1", "x2", "y2", "x3", "y3", "x4", "y4"),
            ActionKind.DETECT_COLOR_MARKERS: (),
            ActionKind.GET_SCREENSHOT: (),
            ActionKind.GET_OBSERVATION: (),
            ActionKind.GET_SERVER_STATS: (),
            ActionKind.SUMMARIZE_TRAJECTORY: (),
            ActionKind.WAIT_PAGE_READY: (),
        }[self.kind]
        missing = [key for key in required if key not in self.args]
        if missing:
            raise ValueError(f"{self.kind.value} is missing arguments: {', '.join(missing)}")
        if self.kind in {
            ActionKind.CLICK,
            ActionKind.LONG_PRESS,
            ActionKind.DOUBLE_TAP,
        }:
            has_index = "index" in self.args
            has_point = "x" in self.args and "y" in self.args
            if has_index == has_point:
                raise ValueError(f"{self.kind.value} requires either index or x/y")


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str = ""
    raw_response: str = ""
    usage: Mapping[str, int] = field(default_factory=dict)
    proposed_action: Action | None = None
    policy: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    elapsed_seconds: float
    details: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""


class EvaluationStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED_ATTEMPT = "failed_attempt"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True)
class Evaluation:
    status: EvaluationStatus
    reward: float = 0.0
    reason: str = ""
    done: bool = False
    signals: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepRecord:
    step: int
    observation: Observation
    decision: Decision
    execution: ExecutionResult
    after: Observation
    evaluation: Evaluation
    workflow_before: Mapping[str, Any] = field(default_factory=dict)
    workflow_after: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeResult:
    task: Task
    success: bool
    status: EvaluationStatus
    reason: str
    steps: tuple[StepRecord, ...]
    elapsed_seconds: float
    output_dir: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    trace_schema_version: str = "1.7"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_schema_version": self.trace_schema_version,
            "task": _task_dict(self.task),
            "status": _jsonable(self.status),
            "success": self.success,
            "reason": self.reason,
            "metrics": _jsonable(self.metrics),
            "elapsed_seconds": self.elapsed_seconds,
            "output_dir": self.output_dir,
            "steps": [_step_record_dict(step) for step in self.steps],
        }

    def write_json(self, path: Path) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _task_dict(task: Task) -> dict[str, Any]:
    return _compact(
        {
            "captcha_type": task.captcha_type,
            "instruction": task.instruction,
            "config": _jsonable(task.config),
        }
    )


def _observation_dict(observation: Observation) -> dict[str, Any]:
    return _compact(
        {
            "step": observation.step,
            "screenshot_path": observation.screenshot_path,
            "width": observation.width,
            "height": observation.height,
            "instruction": observation.instruction,
            "safe_state": _jsonable(observation.safe_state),
            "last_feedback": observation.last_feedback,
            "tool_results": _jsonable(observation.tool_results),
            "workflow_state": _jsonable(observation.workflow_state),
            "context": _jsonable(observation.context),
        }
    )


def _action_dict(action: Action) -> dict[str, Any]:
    return _compact(
        {
            "action": action.kind.value,
            "args": _jsonable(action.args),
        }
    )


def _decision_dict(decision: Decision) -> dict[str, Any]:
    return _compact(
        {
            "action": _action_dict(decision.action),
            "reason": decision.reason,
            "raw_response": decision.raw_response,
            "usage": _jsonable(decision.usage),
            "proposed_action": (
                _action_dict(decision.proposed_action)
                if decision.proposed_action is not None
                else None
            ),
            "policy": _jsonable(decision.policy),
        }
    )


def _execution_dict(execution: ExecutionResult) -> dict[str, Any]:
    return _compact(
        {
            "ok": execution.ok,
            "elapsed_seconds": execution.elapsed_seconds,
            "details": _jsonable(execution.details),
            "error": execution.error,
        }
    )


def _evaluation_dict(evaluation: Evaluation) -> dict[str, Any]:
    return _compact(
        {
            "status": _jsonable(evaluation.status),
            "reward": evaluation.reward,
            "reason": evaluation.reason,
            "done": evaluation.done,
            "signals": _jsonable(evaluation.signals),
        }
    )


def _step_record_dict(record: StepRecord) -> dict[str, Any]:
    return _compact(
        {
            "step": record.step,
            "observation": _observation_dict(record.observation),
            "decision": _decision_dict(record.decision),
            "execution": _execution_dict(record.execution),
            "after": _observation_dict(record.after),
            "evaluation": _evaluation_dict(record.evaluation),
            "workflow_before": _jsonable(record.workflow_before),
            "workflow_after": _jsonable(record.workflow_after),
        }
    )


def _compact(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in value.items()
        if item is not None and item != "" and item != {} and item != []
    }


def _normalize_action_kind(value: str) -> str:
    raw = value.strip()
    snake = (
        re.sub(r"(?<!^)(?=[A-Z])", "_", raw)
        .replace("-", "_")
        .replace(" ", "_")
        .lower()
    )
    compact = re.sub(r"[^a-z0-9]+", "", snake)
    aliases = {
        "tap_point": "tap",
        "tap_point_": "tap",
        "type_text": "type",
        "input_captcha_text": "input_text",
        "ocr_region": "ocr",
        "verify_captcha": "submit_captcha",
        "submit_primary": "submit_captcha",
        "dismiss_dialog": "refresh_captcha",
        "try_again": "refresh_captcha",
        "stop": "finish",
        "status": "finish",
    }
    compact_aliases = {
        "tappoint": "tap",
        "typetext": "type",
        "inputcaptchatext": "input_text",
        "ocrregion": "ocr",
        "submitcaptcha": "submit_captcha",
        "verifycaptcha": "submit_captcha",
        "submitprimary": "submit_captcha",
        "refreshcaptcha": "refresh_captcha",
        "dismissdialog": "refresh_captcha",
        "tryagain": "refresh_captcha",
        "tapgridcell": "tap_grid_cell",
        "movegridpiece": "move_grid_piece",
        "tapregioncenter": "tap_region_center",
        "clicktarget": "click_target",
        "clearselection": "clear_selection",
        "locatecaptchaarea": "locate_captcha_area",
        "locategrid": "locate_grid",
        "detectboard": "detect_board",
        "detectclicktargets": "detect_click_targets",
        "locateslidertrack": "locate_slider_track",
        "locatesliderhandle": "locate_slider_handle",
        "locategap": "locate_gap",
        "estimatedragoffset": "estimate_drag_offset",
        "correctsliderafterfailure": "correct_slider_after_failure",
        "cropregion": "crop_region",
        "zoomregion": "zoom_region",
        "classifyregion": "classify_region",
        "normalizetext": "normalize_text",
        "readclicksequence": "read_click_sequence",
        "readlogicprompt": "read_logic_prompt",
        "solvearithmetic": "solve_arithmetic",
        "findmatch": "find_match",
        "findwinningmove": "find_winning_move",
        "comparesimilarity": "compare_similarity",
        "detectcolormarkers": "detect_color_markers",
        "getscreenshot": "get_screenshot",
        "getobservation": "get_observation",
        "getserverstats": "get_server_stats",
        "summarizetrajectory": "summarize_trajectory",
        "waitpageready": "wait_page_ready",
        "dragby": "drag_by",
    }
    return aliases.get(snake, compact_aliases.get(compact, snake))
