from __future__ import annotations

from typing import Any, Mapping


SAFE_DETAIL_KEYS = {
    "telemetry_events",
    "telemetry_event_counts",
    "telemetry_duration_ms",
    "duration_ms",
    "point_count",
    "net_distance",
    "path_length",
    "straightness_ratio",
    "max_jump",
    "x_span",
    "y_span",
    "click_events",
    "clear_events",
    "unique_positions",
    "toggle_events",
    "final_count",
    "touched_tiles",
    "selection_changes",
    "rotate_clicks",
    "visual_picks",
    "sequence_navs",
    "text_inputs",
    "swap_events",
    "tap_events",
    "drag_start_events",
    "selection_events",
    "move_events",
    "drag_events",
    "drop_events",
    "repeat_count",
    "reason",
}


def safe_verification_feedback(result: Any, *, attempt: int) -> dict[str, Any]:
    success = bool(getattr(result, "success", False))
    raw_message = str(getattr(result, "message", "") or "")
    dynamic_rejection = raw_message.startswith("Dynamic check failed")
    if success:
        reason_code = "verified"
    elif dynamic_rejection:
        reason_code = "dynamic_behavior_rejected"
    else:
        reason_code = "content_rejected"

    raw_extra = getattr(result, "extra", None)
    details: dict[str, Any] = {}
    if isinstance(raw_extra, Mapping):
        for key in SAFE_DETAIL_KEYS:
            if key in raw_extra:
                sanitized = _safe_value(raw_extra[key])
                if sanitized is not None:
                    details[key] = sanitized

    feedback: dict[str, Any] = {
        "attempt": int(attempt),
        "success": success,
        "reason_code": reason_code,
        "answer_exposed": False,
        "details": details,
    }
    if dynamic_rejection:
        feedback["message"] = raw_message
    return feedback


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if isinstance(item, (str, int, float, bool)):
                result[str(key)] = item
        return result
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, (str, int, float, bool)) for item in value):
            return list(value)
    return None
