from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, Pattern

from hll.domain import Action, ActionKind
from hll.tools.base import ToolContext, ToolResult


ToolHandler = Callable[[str, ToolContext, re.Match[str]], ToolResult]


@dataclass
class ToolSpec:
    name: str
    pattern: Pattern[str]
    handler: ToolHandler
    description: str = ""
    read_only: bool = False
    action_kinds: tuple[ActionKind, ...] = ()
    input_schema: Mapping[str, Any] | None = None
    affordances: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: List[ToolSpec] = []
        self._tools_by_action: dict[ActionKind, ToolSpec] = {}

    def register(
        self,
        name: str,
        pattern: str,
        handler: ToolHandler,
        description: str = "",
        read_only: bool = False,
        action_kind: ActionKind | Iterable[ActionKind] | None = None,
        input_schema: Mapping[str, Any] | None = None,
        affordances: Iterable[str] = (),
        preconditions: Iterable[str] = (),
    ) -> None:
        action_kinds = _normalize_action_kinds(action_kind, name)
        spec = ToolSpec(
            name=name,
            pattern=re.compile(pattern, re.IGNORECASE),
            handler=handler,
            description=description,
            read_only=read_only,
            action_kinds=action_kinds,
            input_schema=input_schema or _default_input_schema(action_kinds),
            affordances=tuple(affordances),
            preconditions=tuple(preconditions),
        )
        self._tools.append(spec)
        for kind in action_kinds:
            self._tools_by_action.setdefault(kind, spec)

    def try_execute(self, action: str, context: ToolContext) -> ToolResult:
        normalized = (action or "").strip()
        for spec in self._tools:
            match = spec.pattern.fullmatch(normalized)
            if match:
                return spec.handler(normalized, context, match)
        return ToolResult(handled=False)

    def execute_action(
        self,
        action: Action,
        context: ToolContext,
        tool_call: str,
    ) -> ToolResult:
        """Resolve structured actions through ToolSpec while retaining string-handler compatibility."""

        spec = self._tools_by_action.get(action.kind)
        if spec is None:
            return ToolResult(handled=False)
        normalized = (tool_call or "").strip()
        match = spec.pattern.fullmatch(normalized)
        if match is None:
            return ToolResult(
                handled=True,
                keep_running=True,
                exec_info={
                    "tool_name": spec.name,
                    "error": f"invalid args for {action.kind.value}: {dict(action.args)}",
                },
            )
        return spec.handler(normalized, context, match)

    def spec_for_action(self, action_kind: ActionKind) -> ToolSpec | None:
        return self._tools_by_action.get(action_kind)

    def tool_names(self) -> List[str]:


        return [spec.name for spec in self._tools]

    def tool_menu(self) -> str:


        return ", ".join(self.tool_names())

    def prompt_block(self) -> str:


        action_lines = self._prompt_lines(read_only=False)
        readonly_lines = self._prompt_lines(read_only=True)
        sections: List[str] = []
        if action_lines:
            sections.append(
                "### Captcha action tools (prefer these over raw coordinates when they fit the task) ###\n"
                + "\n".join(action_lines)
            )
        if readonly_lines:
            sections.append(
                "### Auxiliary perception tools (read-only; they do not change the page, "
                "their result is shown to you next step) ###\n"
                + "\n".join(readonly_lines)
                + "\n- Do not call the same read-only tool repeatedly without acting on its result; "
                "read-only inspection has a separate small budget and should lead to a concrete action."
            )
        return "\n\n".join(sections)

    def prompt_description(self) -> str:
        descriptions = [spec.description.strip() for spec in self._tools if spec.description.strip()]
        return "\n".join(descriptions)

    def schema_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for spec in self._tools:
            for kind in spec.action_kinds:
                entries.append(_schema_entry(spec, kind))
        return entries

    def _prompt_lines(self, *, read_only: bool) -> list[str]:
        lines: list[str] = []
        for spec in self._tools:
            if spec.read_only is not read_only:
                continue
            for kind in spec.action_kinds:
                entry = _schema_entry(spec, kind)
                schema = json.dumps(
                    entry["input_schema"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                lines.append(
                    "- "
                    f"{entry['action']} args_schema={schema} "
                    f"tool={entry['tool']} read_only={entry['read_only']}"
                    f"{_prompt_constraints(entry)}: "
                    f"{entry['description']}"
                )
        return lines


def _schema_entry(spec: ToolSpec, kind: ActionKind) -> dict[str, Any]:
    entry = {
        "action": kind.value,
        "tool": spec.name,
        "read_only": spec.read_only,
        "input_schema": dict(spec.input_schema or _object_schema()),
        "description": spec.description.strip(),
    }
    if spec.affordances:
        entry["affordances"] = list(spec.affordances)
    if spec.preconditions:
        entry["preconditions"] = list(spec.preconditions)
    return entry


def _prompt_constraints(entry: Mapping[str, Any]) -> str:
    parts = []
    for key in ("affordances", "preconditions"):
        values = entry.get(key)
        if values:
            parts.append(f" {key}={','.join(str(value) for value in values)}")
    return "".join(parts)


def _normalize_action_kinds(
    value: ActionKind | Iterable[ActionKind] | None,
    tool_name: str,
) -> tuple[ActionKind, ...]:
    if value is None:
        return _ACTION_KINDS_BY_TOOL_NAME.get(tool_name, ())
    if isinstance(value, ActionKind):
        return (value,)
    return tuple(value)


def _default_input_schema(action_kinds: tuple[ActionKind, ...]) -> Mapping[str, Any]:
    if not action_kinds:
        return _object_schema()
    return _ACTION_INPUT_SCHEMAS.get(action_kinds[0], _object_schema())


def _object_schema(
    properties: Mapping[str, Any] | None = None,
    required: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties or {}),
        "required": list(required),
    }


def _int_prop(description: str = "") -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "integer"}
    if description:
        prop["description"] = description
    return prop


def _str_prop(description: str = "") -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "string"}
    if description:
        prop["description"] = description
    return prop


def _bool_prop(description: str = "") -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "boolean"}
    if description:
        prop["description"] = description
    return prop


_REGION_SCHEMA = _object_schema(
    {
        "x1": _int_prop("left screen pixel"),
        "y1": _int_prop("top screen pixel"),
        "x2": _int_prop("right screen pixel"),
        "y2": _int_prop("bottom screen pixel"),
    },
    required=("x1", "y1", "x2", "y2"),
)

_ROWS_COLS_SCHEMA = _object_schema(
    {
        "rows": _int_prop("optional row count"),
        "cols": _int_prop("optional column count"),
    }
)

_ACTION_INPUT_SCHEMAS: dict[ActionKind, Mapping[str, Any]] = {
    ActionKind.TAP: _object_schema(
        {"x": _int_prop(), "y": _int_prop(), "complete": _bool_prop()},
        required=("x", "y"),
    ),
    ActionKind.TYPE: _object_schema({"text": _str_prop()}, required=("text",)),
    ActionKind.INPUT_TEXT: _object_schema({"text": _str_prop()}, required=("text",)),
    ActionKind.DRAG: _object_schema(
        {
            "x1": _int_prop(),
            "y1": _int_prop(),
            "x2": _int_prop(),
            "y2": _int_prop(),
            "duration_ms": _int_prop(),
            "complete": _bool_prop(),
        },
        required=("x1", "y1", "x2", "y2"),
    ),
    ActionKind.DRAG_BY: _object_schema(
        {
            "x": _int_prop(),
            "y": _int_prop(),
            "dx": _int_prop(),
            "dy": _int_prop(),
            "complete": _bool_prop(),
        },
        required=("x", "y", "dx", "dy"),
    ),
    ActionKind.SUBMIT: _object_schema(),
    ActionKind.SUBMIT_CAPTCHA: _object_schema(),
    ActionKind.REFRESH: _object_schema(),
    ActionKind.REFRESH_CAPTCHA: _object_schema(),
    ActionKind.CLEAR_SELECTION: _object_schema(),
    ActionKind.OCR: _REGION_SCHEMA,
    ActionKind.LOCATE_CAPTCHA_AREA: _object_schema(),
    ActionKind.CROP_REGION: _REGION_SCHEMA,
    ActionKind.ZOOM_REGION: _REGION_SCHEMA,
    ActionKind.CLASSIFY_REGION: _REGION_SCHEMA,
    ActionKind.TAP_REGION_CENTER: _REGION_SCHEMA,
    ActionKind.LOCATE_GRID: _ROWS_COLS_SCHEMA,
    ActionKind.DETECT_BOARD: _ROWS_COLS_SCHEMA,
    ActionKind.TAP_GRID_CELL: _object_schema(
        {
            "index": _int_prop("zero-based row-major cell index"),
            "rows": _int_prop("optional row count"),
            "cols": _int_prop("optional column count"),
        },
        required=("index",),
    ),
    ActionKind.MOVE_GRID_PIECE: _object_schema(
        {
            "from_index": _int_prop("zero-based source cell index"),
            "to_index": _int_prop("zero-based destination cell index"),
            "rows": _int_prop("optional row count"),
            "cols": _int_prop("optional column count"),
        },
        required=("from_index", "to_index"),
    ),
    ActionKind.CLICK_TARGET: _object_schema(
        {
            "index": _int_prop("detected target index"),
            "label": _str_prop("detected target label"),
        }
    ),
    ActionKind.DETECT_CLICK_TARGETS: _object_schema(),
    ActionKind.LOCATE_SLIDER_TRACK: _object_schema(),
    ActionKind.LOCATE_SLIDER_HANDLE: _object_schema(),
    ActionKind.LOCATE_GAP: _object_schema(),
    ActionKind.ESTIMATE_DRAG_OFFSET: _object_schema(),
    ActionKind.CORRECT_SLIDER_AFTER_FAILURE: _object_schema(),
    ActionKind.NORMALIZE_TEXT: _object_schema({"text": _str_prop()}, required=("text",)),
    ActionKind.READ_CLICK_SEQUENCE: _object_schema(),
    ActionKind.READ_LOGIC_PROMPT: _object_schema(),
    ActionKind.SOLVE_ARITHMETIC: _object_schema({"expr": _str_prop()}, required=("expr",)),
    ActionKind.FIND_MATCH: _object_schema(),
    ActionKind.FIND_WINNING_MOVE: _object_schema(),
    ActionKind.COMPARE_SIMILARITY: _object_schema(
        {
            "x1": _int_prop(),
            "y1": _int_prop(),
            "x2": _int_prop(),
            "y2": _int_prop(),
            "x3": _int_prop(),
            "y3": _int_prop(),
            "x4": _int_prop(),
            "y4": _int_prop(),
        },
        required=("x1", "y1", "x2", "y2", "x3", "y3", "x4", "y4"),
    ),
    ActionKind.DETECT_COLOR_MARKERS: _object_schema({"color": _str_prop()}),
    ActionKind.GET_SCREENSHOT: _object_schema(),
    ActionKind.GET_OBSERVATION: _object_schema(),
    ActionKind.GET_SERVER_STATS: _object_schema(),
    ActionKind.SUMMARIZE_TRAJECTORY: _object_schema(),
    ActionKind.WAIT_PAGE_READY: _object_schema(),
}


_ACTION_KINDS_BY_TOOL_NAME: dict[str, tuple[ActionKind, ...]] = {
    "TapPoint": (ActionKind.TAP,),
    "TypeText": (ActionKind.TYPE,),
    "InputCaptchaText": (ActionKind.INPUT_TEXT,),
    "Drag": (ActionKind.DRAG,),
    "DragBy": (ActionKind.DRAG_BY,),
    "SubmitCaptcha": (ActionKind.SUBMIT, ActionKind.SUBMIT_CAPTCHA),
    "RefreshCaptcha": (ActionKind.REFRESH, ActionKind.REFRESH_CAPTCHA),
    "ClearSelection": (ActionKind.CLEAR_SELECTION,),
    "OCRRegion": (ActionKind.OCR,),
    "LocateCaptchaArea": (ActionKind.LOCATE_CAPTCHA_AREA,),
    "CropRegion": (ActionKind.CROP_REGION,),
    "Zoom": (ActionKind.ZOOM_REGION,),
    "ClassifyRegion": (ActionKind.CLASSIFY_REGION,),
    "TapRegionCenter": (ActionKind.TAP_REGION_CENTER,),
    "LocateGrid": (ActionKind.LOCATE_GRID,),
    "DetectBoard": (ActionKind.DETECT_BOARD,),
    "TapGridCell": (ActionKind.TAP_GRID_CELL,),
    "MoveGridPiece": (ActionKind.MOVE_GRID_PIECE,),
    "DetectClickTargets": (ActionKind.DETECT_CLICK_TARGETS,),
    "ClickTarget": (ActionKind.CLICK_TARGET,),
    "LocateSliderTrack": (ActionKind.LOCATE_SLIDER_TRACK,),
    "LocateSliderHandle": (ActionKind.LOCATE_SLIDER_HANDLE,),
    "LocateGap": (ActionKind.LOCATE_GAP,),
    "EstimateDragOffset": (ActionKind.ESTIMATE_DRAG_OFFSET,),
    "CorrectSliderAfterFailure": (ActionKind.CORRECT_SLIDER_AFTER_FAILURE,),
    "NormalizeText": (ActionKind.NORMALIZE_TEXT,),
    "ReadClickSequence": (ActionKind.READ_CLICK_SEQUENCE,),
    "ReadLogicPrompt": (ActionKind.READ_LOGIC_PROMPT,),
    "SolveArithmetic": (ActionKind.SOLVE_ARITHMETIC,),
    "FindMatch": (ActionKind.FIND_MATCH,),
    "FindWinningMove": (ActionKind.FIND_WINNING_MOVE,),
    "CompareSimilarity": (ActionKind.COMPARE_SIMILARITY,),
    "DetectColorMarkers": (ActionKind.DETECT_COLOR_MARKERS,),
    "GetScreenshot": (ActionKind.GET_SCREENSHOT,),
    "GetObservation": (ActionKind.GET_OBSERVATION,),
    "GetServerStats": (ActionKind.GET_SERVER_STATS,),
    "SummarizeTrajectory": (ActionKind.SUMMARIZE_TRAJECTORY,),
    "WaitPageReady": (ActionKind.WAIT_PAGE_READY,),
}
