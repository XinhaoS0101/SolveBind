from __future__ import annotations

import shlex
import re
import stat
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hll.domain import ActionKind, Decision, ExecutionResult, Observation
from hll.trace_visual import draw_action_overlay
from hll.tools.ocr import OcrTool


HLL_OBSERVATION_ACTIONS = {
    ActionKind.GET_SCREENSHOT,
    ActionKind.GET_OBSERVATION,
    ActionKind.GET_SERVER_STATS,
    ActionKind.SUMMARIZE_TRAJECTORY,
    ActionKind.WAIT_PAGE_READY,
}
HLL_READ_ONLY_TOOL_ACTIONS = {
    ActionKind.LOCATE_CAPTCHA_AREA,
    ActionKind.LOCATE_GRID,
    ActionKind.DETECT_BOARD,
    ActionKind.DETECT_CLICK_TARGETS,
    ActionKind.LOCATE_SLIDER_TRACK,
    ActionKind.LOCATE_SLIDER_HANDLE,
    ActionKind.LOCATE_GAP,
    ActionKind.ESTIMATE_DRAG_OFFSET,
    ActionKind.CORRECT_SLIDER_AFTER_FAILURE,
    ActionKind.CROP_REGION,
    ActionKind.ZOOM_REGION,
    ActionKind.CLASSIFY_REGION,
    ActionKind.NORMALIZE_TEXT,
    ActionKind.READ_CLICK_SEQUENCE,
    ActionKind.READ_LOGIC_PROMPT,
    ActionKind.SOLVE_ARITHMETIC,
    ActionKind.FIND_MATCH,
    ActionKind.FIND_WINNING_MOVE,
    ActionKind.COMPARE_SIMILARITY,
    ActionKind.DETECT_COLOR_MARKERS,
} | HLL_OBSERVATION_ACTIONS
READ_ONLY_ACTIONS = {ActionKind.OCR} | HLL_READ_ONLY_TOOL_ACTIONS
HLL_TOOL_ACTIONS = {
    ActionKind.TAP,
    ActionKind.TYPE,
    ActionKind.INPUT_TEXT,
    ActionKind.DRAG,
    ActionKind.DRAG_BY,
    ActionKind.SUBMIT,
    ActionKind.REFRESH,
    ActionKind.TAP_GRID_CELL,
    ActionKind.MOVE_GRID_PIECE,
    ActionKind.TAP_REGION_CENTER,
    ActionKind.CLICK_TARGET,
    ActionKind.CLEAR_SELECTION,
    ActionKind.SUBMIT_CAPTCHA,
    ActionKind.REFRESH_CAPTCHA,
} | HLL_READ_ONLY_TOOL_ACTIONS


class ToolExecutor:
    def __init__(
        self,
        environment: Any,
        *,
        ocr_tool: OcrTool | None = None,
        model_base_url: str = "",
        model_api_key: str = "",
        model_name: str = "",
        environment_action_kinds: set[ActionKind] | None = None,
    ) -> None:
        self.environment = environment
        self.ocr_tool = ocr_tool
        self.environment_action_kinds = frozenset(environment_action_kinds or ())
        self.hll_tools = HllToolExecutor(
            environment,
            model_base_url=model_base_url,
            model_api_key=model_api_key,
            model_name=model_name,
        )

    def execute(
        self,
        decision: Decision,
        observation: Observation,
    ) -> ExecutionResult:
        if decision.action.kind in self.environment_action_kinds:
            return self.environment.execute(decision)
        if decision.action.kind is ActionKind.OCR:
            if self.ocr_tool is None:
                return ExecutionResult(
                    ok=False,
                    elapsed_seconds=0.0,
                    details={
                        "read_only": True,
                        "tool_name": "OCRRegion",
                        "action": "ocr",
                        "error": "OCR is disabled",
                    },
                    error="OCR is disabled",
                )
            return self.ocr_tool.execute(decision.action, observation)
        if decision.action.kind in HLL_TOOL_ACTIONS:
            return self.hll_tools.execute(decision, observation)
        return self.environment.execute(decision)


class HllToolExecutor:


    def __init__(
        self,
        environment: Any,
        *,
        model_base_url: str = "",
        model_api_key: str = "",
        model_name: str = "",
    ) -> None:
        self.environment = environment
        self.model_base_url = model_base_url
        self.model_api_key = model_api_key
        self.model_name = model_name
        self._registry: Any | None = None
        self._observation_registry: Any | None = None
        self._action_history: list[str] = []
        self._adb_wrapper_path: Path | None = None
        self._last_grid_shape: tuple[int, int] | None = None
        self._grid_snapshot: dict[str, Any] | None = None
        self._click_target_snapshot: dict[str, Any] | None = None

    def execute(self, decision: Decision, observation: Observation) -> ExecutionResult:
        started = time.monotonic()
        details: dict[str, Any] = {
            "action": decision.action.kind.value,
            "args": dict(decision.action.args),
            "executor": "hll_tools",
        }
        tool_call = ""
        previous_page_views = self._page_views()
        try:
            tool_call = self._tool_call(decision)
            context = self._context(observation)
            result = None
            original_tool_call = tool_call
            registry = (
                self._observation_registry_obj()
                if decision.action.kind in HLL_OBSERVATION_ACTIONS
                else self._registry_obj()
            )
            result = registry.execute_action(decision.action, context, tool_call)
            details["tool_dispatch"] = "direct" if result.handled else "legacy_registry"
            if not result.handled:
                for candidate in _tool_call_candidates(tool_call):
                    result = registry.try_execute(candidate, context)
                    if result.handled:
                        tool_call = candidate
                        break
            if result is None or not result.handled:
                result = self._unsupported_tool_result(original_tool_call)
            exec_info = dict(result.exec_info or {})
            details.update(exec_info)
            details["tool_call"] = tool_call
            if tool_call != original_tool_call:
                details["tool_call_normalized_from"] = original_tool_call
            self._annotate_details(
                decision,
                details,
                previous_page_views,
                screenshot_path=observation.screenshot_path,
            )
            self._remember_grid_shape(decision, details, observation)
            self._remember_click_targets(decision, details)
            self._action_history.append(tool_call)
            error = str(exec_info.get("error", "") or "")
            return ExecutionResult(
                ok=bool(result.handled) and not error,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
                error=error,
            )
        except Exception as exc:
            details["tool_call"] = tool_call
            details["error"] = f"{type(exc).__name__}: {exc}"
            return ExecutionResult(
                ok=False,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
                error=details["error"],
            )

    def _registry_obj(self) -> Any:
        if self._registry is None:
            from hll.tools import build_default_registry

            self._registry = build_default_registry()
        return self._registry

    def _observation_registry_obj(self) -> Any:
        if self._observation_registry is None:
            from hll.tools import build_observation_registry

            self._observation_registry = build_observation_registry()
        return self._observation_registry

    def _tool_call(self, decision: Decision) -> str:
        kind = decision.action.kind
        args = dict(decision.action.args)
        if kind is ActionKind.TAP:
            return f"TapPoint({_int_arg(args, 'x')}, {_int_arg(args, 'y')})"
        if kind is ActionKind.TYPE:
            return f"TypeText <text>{str(args.get('text', ''))}</text>"
        if kind is ActionKind.INPUT_TEXT:
            return f"InputCaptchaText <text>{str(args.get('text', ''))}</text>"
        if kind is ActionKind.DRAG:
            return (
                f"Drag ({_int_arg(args, 'x1')}, {_int_arg(args, 'y1')}), "
                f"({_int_arg(args, 'x2')}, {_int_arg(args, 'y2')})"
            )
        if kind is ActionKind.DRAG_BY:
            return (
                f"DragBy({_int_arg(args, 'x')}, {_int_arg(args, 'y')}, "
                f"{_int_arg(args, 'dx')}, {_int_arg(args, 'dy')})"
            )
        if kind is ActionKind.TAP_GRID_CELL:
            index = _int_arg(args, "index", "cell_index")
            rows = _optional_int_arg(args, "rows", "grid_rows")
            cols = _optional_int_arg(args, "cols", "grid_cols")
            if (rows is None or cols is None) and self._last_grid_shape is not None:
                rows, cols = self._last_grid_shape
            if rows is not None and cols is not None:
                return f"TapGridCell({index}, {rows}, {cols})"
            return f"TapGridCell({index})"
        if kind is ActionKind.MOVE_GRID_PIECE:
            source = _int_arg(args, "from_index")
            target = _int_arg(args, "to_index")
            rows = _optional_int_arg(args, "rows", "grid_rows")
            cols = _optional_int_arg(args, "cols", "grid_cols")
            if (rows is None or cols is None) and self._last_grid_shape is not None:
                rows, cols = self._last_grid_shape
            if rows is not None and cols is not None:
                return f"MoveGridPiece({source}, {target}, {rows}, {cols})"
            return f"MoveGridPiece({source}, {target})"
        if kind in {ActionKind.SUBMIT, ActionKind.SUBMIT_CAPTCHA}:
            return "SubmitCaptcha()"
        if kind in {ActionKind.REFRESH, ActionKind.REFRESH_CAPTCHA}:
            return "RefreshCaptcha()"
        if kind is ActionKind.TAP_REGION_CENTER:
            return _region_call("TapRegionCenter", args)
        if kind is ActionKind.CLICK_TARGET:
            if "index" in args:
                return f"ClickTarget({_int_arg(args, 'index')})"
            return f"ClickTarget <text>{str(args.get('label', args.get('text', '')))}</text>"
        if kind is ActionKind.CROP_REGION:
            return _region_call("CropRegion", args)
        if kind is ActionKind.ZOOM_REGION:
            return _region_call("Zoom", args)
        if kind is ActionKind.CLASSIFY_REGION:
            return _region_call("ClassifyRegion", args)
        if kind is ActionKind.COMPARE_SIMILARITY:
            return (
                f"CompareSimilarity({_int_arg(args, 'x1')}, {_int_arg(args, 'y1')}, "
                f"{_int_arg(args, 'x2')}, {_int_arg(args, 'y2')}), "
                f"({_int_arg(args, 'x3')}, {_int_arg(args, 'y3')}, "
                f"{_int_arg(args, 'x4')}, {_int_arg(args, 'y4')})"
            )
        if kind is ActionKind.NORMALIZE_TEXT:
            return f"NormalizeText <text>{str(args.get('text', ''))}</text>"
        if kind is ActionKind.SOLVE_ARITHMETIC:
            return f"SolveArithmetic <text>{str(args.get('expr', args.get('text', '')))}</text>"
        if kind is ActionKind.DETECT_COLOR_MARKERS:
            return f"DetectColorMarkers({str(args.get('color', 'green'))})"
        if kind is ActionKind.LOCATE_GRID:
            return _rows_cols_call("LocateGrid", args)
        if kind is ActionKind.DETECT_BOARD:
            return _rows_cols_call("DetectBoard", args)
        tool_call = _NO_ARG_TOOL_CALLS.get(kind)
        if tool_call:
            return tool_call
        return f"{kind.value}()"

    def _unsupported_tool_result(self, tool_call: str) -> Any:
        from hll.tools.base import ToolResult

        return ToolResult(
            handled=True,
            keep_running=True,
            exec_info={
                "action_type": "unknown",
                "tool_name": "UnknownHllTool",
                "label": tool_call,
                "error": f"unsupported HLL tool action: {tool_call}",
            },
        )

    def _context(self, observation: Observation) -> Any:
        from hll.tools.base import ToolContext

        output_dir = Path(observation.screenshot_path).resolve().parent
        cfg = SimpleNamespace(
            adb_path=self._hll_adb_path(output_dir),
            API_url=self.model_base_url,
            token=self.model_api_key,
            caption_model=self.model_name,
            screenshot_dir=str(output_dir),
            judgement_dir=str(output_dir),
            captcha_url=str(getattr(self.environment, "captcha_url", "") or ""),
            post_action_poll_interval_sec=0.2,
        )
        tool_env = SimpleNamespace(
            cfg=cfg,
            ocr_detection=None,
            ocr_recognition=None,
            groundingdino_model=None,
        )
        return ToolContext(
            env=tool_env,
            screenshot_file=observation.screenshot_path,
            width=observation.width,
            height=observation.height,
            perception_infos=[],
            instruction=observation.instruction,
            action_history=list(self._action_history),
            task_profile=None,
            captcha_url=cfg.captcha_url,
            trajectory_summary=self._trajectory_summary(),
            safe_state=dict(observation.safe_state),
            click_target_snapshot=self._click_target_snapshot,
            grid_snapshot=self._grid_snapshot,
        )

    def _hll_adb_path(self, output_dir: Path) -> str:
        adb_path = str(getattr(self.environment, "adb_path", "adb") or "adb")
        serial = str(getattr(self.environment, "device_serial", "") or "").strip()
        if not serial:
            return adb_path

        # Bind every tool ADB call to the selected device through one executable wrapper.

        if self._adb_wrapper_path and self._adb_wrapper_path.exists():
            return str(self._adb_wrapper_path)
        wrapper = output_dir / "hll_adb"
        script = "\n".join(
            [
                "#!/bin/sh",
                f"exec {shlex.quote(adb_path)} -s {shlex.quote(serial)} \"$@\"",
                "",
            ]
        )
        wrapper.write_text(script, encoding="utf-8")
        current_mode = wrapper.stat().st_mode
        wrapper.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self._adb_wrapper_path = wrapper
        return str(wrapper)

    def _trajectory_summary(self) -> dict[str, Any]:
        recent = [
            {"iter": index + 1, "action": action}
            for index, action in enumerate(self._action_history[-8:])
        ]
        return {
            "total_steps": len(self._action_history),
            "recent_actions": recent,
            "no_effect_count": 0,
            "repeated_action_count": 0,
            "refresh_count": sum(1 for action in self._action_history if "RefreshCaptcha" in action),
        }

    def _remember_grid_shape(
        self,
        decision: Decision,
        details: dict[str, Any],
        observation: Observation,
    ) -> None:
        if decision.action.kind in {ActionKind.REFRESH, ActionKind.REFRESH_CAPTCHA}:
            self._grid_snapshot = None
            self._last_grid_shape = None
            return
        tool_name = str(details.get("tool_name", "") or "")
        if tool_name not in {"LocateGrid", "DetectBoard", "TapGridCell", "MoveGridPiece"}:
            return
        rows = _optional_int_arg(details, "grid_rows", "rows")
        cols = _optional_int_arg(details, "grid_cols", "cols")
        if rows is not None and cols is not None:
            self._last_grid_shape = (max(1, rows), max(1, cols))
        bbox = details.get("grid_bbox", details.get("board_bbox"))
        if not details.get("grid_detected") or not isinstance(bbox, list) or len(bbox) != 4:
            return
        try:
            self._grid_snapshot = {
                "bbox": [int(value) for value in bbox],
                "rows": max(1, int(rows or 0)),
                "cols": max(1, int(cols or 0)),
                "width": int(observation.width),
                "height": int(observation.height),
            }
        except (TypeError, ValueError):
            return

    def _remember_click_targets(
        self,
        decision: Decision,
        details: dict[str, Any],
    ) -> None:
        if decision.action.kind in {ActionKind.REFRESH, ActionKind.REFRESH_CAPTCHA}:
            self._click_target_snapshot = None
            return
        tool_name = str(details.get("tool_name", ""))
        if tool_name not in {"DetectClickTargets", "ClickTarget"}:
            return
        targets = (
            details.get("targets")
            if tool_name == "DetectClickTargets"
            else details.get("detected_targets")
        )
        if not isinstance(targets, list) or not targets:
            return
        if tool_name == "ClickTarget" and self._click_target_snapshot is not None:
            return
        self._click_target_snapshot = {
            "snapshot_id": str(details.get("target_snapshot_id", "")),
            "targets": [dict(target) for target in targets if isinstance(target, dict)],
            "click_count": 1 if tool_name == "ClickTarget" else 0,
        }

    def _page_views(self) -> int:
        stats_reader = getattr(self.environment, "get_stats", None)
        if not callable(stats_reader):
            return 0
        try:
            return int(stats_reader().get("page_views", 0) or 0)
        except Exception:
            return 0

    def _annotate_details(
        self,
        decision: Decision,
        details: dict[str, Any],
        previous_page_views: int,
        screenshot_path: str = "",
    ) -> None:
        action = decision.action
        tool_name = str(details.get("tool_name", "") or "")
        read_only = action.kind in HLL_READ_ONLY_TOOL_ACTIONS or bool(
            details.get("read_only", False)
        )
        if read_only:
            details["read_only"] = True
        if not details.get("deferred_submit") and (
            tool_name in {"SubmitCaptcha", "SubmitPrimary"} or action.kind in {
            ActionKind.SUBMIT,
            ActionKind.SUBMIT_CAPTCHA,
            }
        ):
            details["verification_action"] = True
        if tool_name == "RefreshCaptcha" or action.kind in {
            ActionKind.REFRESH,
            ActionKind.REFRESH_CAPTCHA,
        }:
            details["state_changed"] = True
            self._wait_for_refresh_if_available(previous_page_views)
        if action.kind in {
            ActionKind.TAP,
            ActionKind.TAP_GRID_CELL,
            ActionKind.MOVE_GRID_PIECE,
            ActionKind.TAP_REGION_CENTER,
            ActionKind.CLICK_TARGET,
            ActionKind.CLEAR_SELECTION,
            ActionKind.DRAG,
            ActionKind.DRAG_BY,
            ActionKind.TYPE,
            ActionKind.INPUT_TEXT,
        }:
            details["interaction_progress"] = True
        if action.kind in {ActionKind.TYPE, ActionKind.INPUT_TEXT}:
            details["ready_to_submit"] = True
        if bool(action.args.get("complete", False)):
            details["ready_to_submit"] = True
        self._attach_suggested_actions(details)
        self._attach_visual_debug_overlay(details, screenshot_path, read_only=read_only)

    @staticmethod
    def _attach_visual_debug_overlay(
        details: dict[str, Any],
        screenshot_path: str,
        *,
        read_only: bool,
    ) -> None:
        if not screenshot_path or not _has_visual_anchor(details):
            return
        overlay_path = draw_action_overlay(
            screenshot_path,
            details,
            label=str(details.get("tool_name") or details.get("action") or "action"),
        )
        if not overlay_path:
            return
        details["debug_overlay_path"] = overlay_path
        if not read_only:
            details["action_overlay_path"] = overlay_path

    def _wait_for_refresh_if_available(self, previous_page_views: int) -> None:
        waiter = getattr(self.environment, "_wait_for_page_view_after", None)
        if not callable(waiter):
            return
        try:
            waiter(previous_page_views)
        except Exception:
            return

    @staticmethod
    def _attach_suggested_actions(details: dict[str, Any]) -> None:
        suggested_drag = details.get("suggested_drag")
        if (
            isinstance(suggested_drag, list)
            and len(suggested_drag) == 4
            and all(isinstance(value, (int, float)) for value in suggested_drag)
        ):
            x1, y1, x2, y2 = [int(round(float(value))) for value in suggested_drag]
            action = {
                "action": "drag",
                "args": {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "duration_ms": 800,
                    "complete": True,
                },
            }
            details["suggested_action"] = action
            details["canonical_action"] = action
            return

        suggested = details.get("suggested_next_actions")
        if not isinstance(suggested, list) or not suggested:
            return
        converted = _tool_call_to_hll_action(str(suggested[0]))
        if converted is not None:
            details["suggested_action"] = converted
            details["canonical_action"] = converted


def _has_visual_anchor(details: dict[str, Any]) -> bool:
    for key in (
        "mapped_point",
        "point",
        "mapped_path",
        "start",
        "end",
        "region",
        "grid_bbox",
        "button_bbox",
        "input_bbox",
    ):
        value = details.get(key)
        if isinstance(value, (list, tuple)) and value:
            return True
    return False


def _tool_call_to_hll_action(value: str) -> dict[str, Any] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if match := re.fullmatch(
        r"(?:Tap|TapPoint)\s*\(\s*(?P<x>-?\d+(?:\.\d+)?)\s*,\s*(?P<y>-?\d+(?:\.\d+)?)\s*\)",
        raw,
        re.IGNORECASE,
    ):
        return {"action": "tap", "args": _match_ints(match, "x", "y")}
    if match := re.fullmatch(
        r"Drag\s*\(\s*(?P<x1>-?\d+(?:\.\d+)?)\s*,\s*(?P<y1>-?\d+(?:\.\d+)?)\s*\)\s*,\s*"
        r"\(\s*(?P<x2>-?\d+(?:\.\d+)?)\s*,\s*(?P<y2>-?\d+(?:\.\d+)?)\s*\)",
        raw,
        re.IGNORECASE,
    ):
        return {"action": "drag", "args": _match_ints(match, "x1", "y1", "x2", "y2")}
    if match := re.fullmatch(
        r"DragBy\s*\(\s*(?P<x>-?\d+)\s*,\s*(?P<y>-?\d+)\s*,\s*"
        r"(?P<dx>-?\d+)\s*,\s*(?P<dy>-?\d+)\s*\)",
        raw,
        re.IGNORECASE,
    ):
        return {"action": "drag_by", "args": _match_ints(match, "x", "y", "dx", "dy")}
    if match := re.fullmatch(
        r"TapGridCell\s*\(\s*(?P<index>\d+)"
        r"(?:\s*,\s*(?P<rows>\d+)\s*,\s*(?P<cols>\d+))?\s*\)",
        raw,
        re.IGNORECASE,
    ):
        args = _match_ints(match, "index")
        if match.group("rows") and match.group("cols"):
            args.update(_match_ints(match, "rows", "cols"))
        return {"action": "tap_grid_cell", "args": args}
    if match := re.fullmatch(
        r"MoveGridPiece\s*\(\s*(?P<from_index>\d+)\s*,\s*(?P<to_index>\d+)"
        r"(?:\s*,\s*(?P<rows>\d+)\s*,\s*(?P<cols>\d+))?\s*\)",
        raw,
        re.IGNORECASE,
    ):
        args = _match_ints(match, "from_index", "to_index")
        if match.group("rows") and match.group("cols"):
            args.update(_match_ints(match, "rows", "cols"))
        return {"action": "move_grid_piece", "args": args}
    if re.fullmatch(r"(?:SubmitCaptcha|SubmitPrimary|VerifyCaptcha)\s*(?:\(\s*\))?", raw, re.IGNORECASE):
        return {"action": "submit", "args": {"raw": raw}}
    if re.fullmatch(r"(?:RefreshCaptcha|DismissDialog|TryAgain)\s*(?:\(\s*\))?", raw, re.IGNORECASE):
        return {"action": "refresh", "args": {"raw": raw}}
    if match := re.fullmatch(r"(?:Type|TypeText)\s*<text>(?P<text>.*?)</text>", raw, re.IGNORECASE):
        return {"action": "type", "args": {"text": match.group("text")}}
    if match := re.fullmatch(r"InputCaptchaText\s*<text>(?P<text>.*?)</text>", raw, re.IGNORECASE):
        return {"action": "input_text", "args": {"text": match.group("text")}}
    if match := re.fullmatch(
        r"(?P<name>OCRRegion|TapRegionCenter)\s*\(\s*(?P<x1>-?\d+)\s*,\s*(?P<y1>-?\d+)\s*,\s*"
        r"(?P<x2>-?\d+)\s*,\s*(?P<y2>-?\d+)\s*\)",
        raw,
        re.IGNORECASE,
    ):
        action = "ocr" if match.group("name").lower() == "ocrregion" else "tap_region_center"
        return {"action": action, "args": _match_ints(match, "x1", "y1", "x2", "y2")}
    if match := re.fullmatch(r"ClickTarget\s*\(\s*(?P<index>\d+)\s*\)", raw, re.IGNORECASE):
        return {"action": "click_target", "args": _match_ints(match, "index")}
    if match := re.fullmatch(r"ClickTarget\s*<text>(?P<label>.*?)</text>", raw, re.IGNORECASE):
        return {"action": "click_target", "args": {"label": match.group("label")}}
    return None


def _tool_call_candidates(value: str) -> list[str]:

    raw = (value or "").strip()
    if not raw:
        return [raw]

    candidates = [raw]
    without_empty_call = re.sub(r"\(\s*\)\s*$", "", raw).strip()
    if without_empty_call and without_empty_call != raw:
        candidates.append(without_empty_call)
    return candidates


def _match_ints(match: re.Match[str], *names: str) -> dict[str, int]:
    return {name: int(float(match.group(name))) for name in names}


def _int_arg(args: dict[str, Any], *names: str, default: int = 0) -> int:
    value = _optional_int_arg(args, *names)
    return default if value is None else value


def _optional_int_arg(args: dict[str, Any], *names: str) -> int | None:
    for name in names:
        if name not in args:
            continue
        try:
            return int(float(args[name]))
        except Exception:
            continue
    return None


def _region_call(name: str, args: dict[str, Any]) -> str:
    return (
        f"{name}({_int_arg(args, 'x1', 'left')}, {_int_arg(args, 'y1', 'top')}, "
        f"{_int_arg(args, 'x2', 'right')}, {_int_arg(args, 'y2', 'bottom')})"
    )


def _rows_cols_call(name: str, args: dict[str, Any]) -> str:
    rows = _optional_int_arg(args, "rows")
    cols = _optional_int_arg(args, "cols")
    if rows is None or cols is None:
        return name
    return f"{name}({rows}, {cols})"


_NO_ARG_TOOL_CALLS = {
    ActionKind.CLEAR_SELECTION: "ClearSelection()",
    ActionKind.LOCATE_CAPTCHA_AREA: "LocateCaptchaArea()",
    ActionKind.LOCATE_SLIDER_TRACK: "LocateSliderTrack()",
    ActionKind.LOCATE_SLIDER_HANDLE: "LocateSliderHandle()",
    ActionKind.LOCATE_GAP: "LocateGap()",
    ActionKind.ESTIMATE_DRAG_OFFSET: "EstimateDragOffset()",
    ActionKind.CORRECT_SLIDER_AFTER_FAILURE: "CorrectSliderAfterFailure()",
    ActionKind.DETECT_CLICK_TARGETS: "DetectClickTargets()",
    ActionKind.READ_CLICK_SEQUENCE: "ReadClickSequence()",
    ActionKind.READ_LOGIC_PROMPT: "ReadLogicPrompt()",
    ActionKind.FIND_MATCH: "FindMatch()",
    ActionKind.FIND_WINNING_MOVE: "FindWinningMove()",
    ActionKind.GET_SCREENSHOT: "GetScreenshot()",
    ActionKind.GET_OBSERVATION: "GetObservation()",
    ActionKind.GET_SERVER_STATS: "GetServerStats()",
    ActionKind.SUMMARIZE_TRAJECTORY: "SummarizeTrajectory()",
    ActionKind.WAIT_PAGE_READY: "WaitPageReady()",
}
