from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


ACTION_SPECS: tuple[dict[str, Any], ...] = (
    {
        "action": "click",
        "description": "Tap a visible UI element by index or screenshot coordinates.",
        "args_schema": {
            "oneOf": [
                {"required": ["index"]},
                {"required": ["x", "y"]},
            ],
            "properties": {
                "index": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "type": "object",
        },
    },
    {
        "action": "long_press",
        "description": "Long-press a visible UI element by index or screenshot coordinates.",
        "args_schema": {
            "oneOf": [
                {"required": ["index"]},
                {"required": ["x", "y"]},
            ],
            "properties": {
                "index": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "type": "object",
        },
    },
    {
        "action": "double_tap",
        "description": "Double-tap a visible UI element by index or screenshot coordinates.",
        "args_schema": {
            "oneOf": [
                {"required": ["index"]},
                {"required": ["x", "y"]},
            ],
            "properties": {
                "index": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "type": "object",
        },
    },
    {
        "action": "input_text",
        "description": "Focus an optional target, replace its text, and press Enter.",
        "args_schema": {
            "properties": {
                "text": {"type": "string"},
                "index": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "clear_text": {"type": "boolean"},
            },
            "required": ["text"],
            "type": "object",
        },
    },
    {
        "action": "scroll",
        "description": (
            "Reveal more content in a direction; index optionally selects "
            "a scrollable element."
        ),
        "args_schema": {
            "properties": {
                "direction": {"enum": ["up", "down", "left", "right"]},
                "index": {"type": "integer"},
            },
            "required": ["direction"],
            "type": "object",
        },
    },
    {
        "action": "swipe",
        "description": "Swipe the whole screen in one direction.",
        "args_schema": {
            "properties": {
                "direction": {"enum": ["up", "down", "left", "right"]},
            },
            "required": ["direction"],
            "type": "object",
        },
    },
    {
        "action": "navigate_back",
        "description": "Press the Android Back button.",
        "args_schema": {"properties": {}, "type": "object"},
    },
    {
        "action": "navigate_home",
        "description": "Go to the Android home screen.",
        "args_schema": {"properties": {}, "type": "object"},
    },
    {
        "action": "keyboard_enter",
        "description": "Press the keyboard Enter key.",
        "args_schema": {"properties": {}, "type": "object"},
    },
    {
        "action": "open_app",
        "description": "Open an installed app by its human-readable name.",
        "args_schema": {
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
            "type": "object",
        },
    },
    {
        "action": "wait",
        "description": "Wait briefly for the current screen to update.",
        "args_schema": {"properties": {}, "type": "object"},
    },
    {
        "action": "answer",
        "description": "Answer an information-retrieval question before declaring completion.",
        "args_schema": {
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "type": "object",
        },
    },
    {
        "action": "status",
        "description": "End the episode as complete or infeasible.",
        "args_schema": {
            "properties": {
                "goal_status": {"enum": ["complete", "infeasible"]},
            },
            "required": ["goal_status"],
            "type": "object",
        },
    },
)


_ALLOWED_ARGS = {
    "click": {"index", "x", "y"},
    "long_press": {"index", "x", "y"},
    "double_tap": {"index", "x", "y"},
    "input_text": {"text", "index", "x", "y", "clear_text"},
    "scroll": {"direction", "index"},
    "swipe": {"direction"},
    "navigate_back": set(),
    "navigate_home": set(),
    "keyboard_enter": set(),
    "open_app": {"app_name"},
    "wait": set(),
    "answer": {"text"},
    "status": {"goal_status"},
}
_DIRECTIONS = {"up", "down", "left", "right"}


@dataclass(frozen=True)
class AndroidWorldAction:
    kind: str
    args: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.kind,
            "args": dict(self.args),
            "reason": self.reason,
        }


def build_action_schema_prompt() -> str:
    lines = ["### MCP-style Android action catalog ###"]
    for spec in ACTION_SPECS:
        schema = json.dumps(
            spec["args_schema"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        lines.append(
            f"- {spec['action']} args_schema={schema}: {spec['description']}"
        )
    return "\n".join(lines)


def parse_androidworld_action(text: str) -> AndroidWorldAction:
    payload = _extract_json_object(text)
    raw_kind = str(payload.get("action", payload.get("action_type", ""))).strip()
    if not raw_kind:
        raise ValueError("model action is missing action/action_type")

    raw_args = payload.get("args")
    if raw_args is None:
        raw_args = {
            key: value
            for key, value in payload.items()
            if key not in {"action", "action_type", "reason", "rationale"}
        }
    if not isinstance(raw_args, Mapping):
        raise ValueError("model action args must be an object")

    reason = str(payload.get("reason", payload.get("rationale", "")))
    kind, args, reason = _normalize_alias(raw_kind.lower(), dict(raw_args), reason)
    args = _normalize_args(kind, args)
    _validate_action(kind, args)
    return AndroidWorldAction(kind=kind, args=args, reason=reason)


def _normalize_alias(
    kind: str,
    args: dict[str, Any],
    reason: str,
) -> tuple[str, dict[str, Any], str]:
    if kind == "tap":
        kind = "click"
    elif kind == "type":
        kind = "input_text"
    elif kind == "key":
        key = str(args.pop("key", "")).upper()
        key_actions = {
            "BACK": "navigate_back",
            "HOME": "navigate_home",
            "ENTER": "keyboard_enter",
        }
        if key not in key_actions:
            raise ValueError("key action must use BACK, HOME, or ENTER")
        kind = key_actions[key]
    elif kind == "finish":
        kind = "status"
        nested_reason = str(args.pop("reason", ""))
        reason = reason or nested_reason
        args = {
            "goal_status": str(
                args.get("goal_status", args.get("status", "complete"))
            )
        }
    if "clear_existing" in args and "clear_text" not in args:
        args["clear_text"] = args.pop("clear_existing")
    if "target_index" in args and "index" not in args:
        args["index"] = args.pop("target_index")
    return kind, args, reason


def _normalize_args(kind: str, args: dict[str, Any]) -> dict[str, Any]:
    for key in ("index", "x", "y"):
        if key in args:
            args[key] = _coerce_int(args[key], key)
    if "direction" in args:
        args["direction"] = str(args["direction"]).lower()
    if "goal_status" in args:
        args["goal_status"] = str(args["goal_status"]).lower()
    if kind == "input_text":
        args.setdefault("clear_text", True)
    if "clear_text" in args and not isinstance(args["clear_text"], bool):
        raise ValueError("clear_text must be a boolean")
    return args


def _validate_action(kind: str, args: Mapping[str, Any]) -> None:
    allowed = _ALLOWED_ARGS.get(kind)
    if allowed is None:
        raise ValueError(
            f"unknown AndroidWorld action {kind!r}; expected one of: "
            + ", ".join(_ALLOWED_ARGS)
        )
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ValueError(f"{kind} has unknown arguments: {', '.join(unknown)}")

    if kind in {"click", "long_press", "double_tap"}:
        has_index = "index" in args
        has_point = "x" in args and "y" in args
        if has_index == has_point:
            raise ValueError(f"{kind} requires either index or x/y")
    if kind == "input_text" and "text" not in args:
        raise ValueError("input_text requires text")
    if kind == "input_text" and "index" in args and (
        "x" in args or "y" in args
    ):
        raise ValueError("input_text accepts either index or x/y, not both")
    if kind in {"scroll", "swipe"} and args.get("direction") not in _DIRECTIONS:
        raise ValueError(f"{kind} requires direction up/down/left/right")
    if kind == "open_app" and not str(args.get("app_name", "")).strip():
        raise ValueError("open_app requires app_name")
    if kind == "answer" and "text" not in args:
        raise ValueError("answer requires text")
    if kind == "status" and args.get("goal_status") not in {
        "complete",
        "infeasible",
    }:
        raise ValueError("status requires goal_status complete/infeasible")
    if ("x" in args) != ("y" in args):
        raise ValueError(f"{kind} requires both x and y when using coordinates")


def _coerce_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not number.is_integer():
        number = round(number)
    return int(number)


def _extract_json_object(text: str) -> Mapping[str, Any]:
    decoder = json.JSONDecoder()
    fallback: Mapping[str, Any] | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            if "action" in value or "action_type" in value:
                return value
            if fallback is None:
                fallback = value
    if fallback is not None:
        return fallback
    raise ValueError(f"model did not return a JSON action: {text[:500]!r}")
