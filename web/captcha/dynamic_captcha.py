from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from .base import CaptchaResult


def parse_dynamic_submission(user_input: Any) -> Tuple[Optional[str], List[Dict[str, Any]], Optional[CaptchaResult]]:
    raw = "" if user_input is None else str(user_input)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, [], CaptchaResult(
            success=False,
            message="Missing dynamic verification payload. Please try again.",
            received=raw,
        )

    answer = payload.get("answer")
    telemetry = payload.get("telemetry", [])
    if not isinstance(answer, str):
        return None, [], CaptchaResult(
            success=False,
            message="Dynamic verification payload is missing the answer.",
            received=raw,
        )
    if not isinstance(telemetry, list):
        return None, [], CaptchaResult(
            success=False,
            message="Dynamic verification payload has an invalid telemetry format.",
            received=raw,
        )
    return answer, telemetry, None


class DynamicCaptchaMixin:
    dynamic_type = "dynamic"

    def build_dynamic_script(self) -> str:
        raise NotImplementedError

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]) -> CaptchaResult:
        raise NotImplementedError

    def render_html(self) -> str:
        inner = super().render_html()
        return f"""{inner}
<script>
(function() {{
  const answerInput = document.getElementById('captcha-input');
  const form = document.getElementById('captcha-form');
  if (!answerInput || !form) return;

  const dynamicState = {{
    startedAt: Date.now(),
    type: {json.dumps(self.dynamic_type)},
    telemetry: [],
  }};

  function roundNumber(value) {{
    return typeof value === 'number' && Number.isFinite(value)
      ? Math.round(value * 100) / 100
      : value;
  }}

  function sanitizeValue(value) {{
    if (typeof value === 'number') {{
      return roundNumber(value);
    }}
    if (typeof value === 'string' || typeof value === 'boolean') {{
      return value;
    }}
    if (Array.isArray(value)) {{
      return value
        .map(sanitizeValue)
        .filter(function(item) {{ return item !== undefined; }});
    }}
    if (value && typeof value === 'object') {{
      return sanitize(value);
    }}
    return undefined;
  }}

  function sanitize(data) {{
    const out = {{}};
    if (!data || typeof data !== 'object') return out;
    Object.keys(data).forEach(function(key) {{
      const sanitized = sanitizeValue(data[key]);
      if (sanitized !== undefined) {{
        out[key] = sanitized;
      }}
    }});
    return out;
  }}

  function record(type, data) {{
    dynamicState.telemetry.push(Object.assign({{
      t: Date.now() - dynamicState.startedAt,
      type: type,
    }}, sanitize(data)));
  }}

  function buildPayload(answerValue) {{
    const serializedAnswer = String(answerValue || '');
    record('submit_prepare', {{ answerLength: serializedAnswer.length }});
    return JSON.stringify({{
      type: dynamicState.type,
      answer: serializedAnswer,
      telemetry: dynamicState.telemetry,
    }});
  }}

  window.__captchaDynamicRecord = record;
  window.__captchaBuildDynamicPayload = buildPayload;

  {self.build_dynamic_script()}

  form.addEventListener('submit', function() {{
    const answerValue = String(answerInput.value || '');
    answerInput.value = buildPayload(answerValue);
  }}, true);
}})();
</script>"""

    def verify(self, user_input: Any) -> CaptchaResult:
        answer, telemetry, error = parse_dynamic_submission(user_input)
        if error is not None:
            return error

        summary = self._telemetry_summary(telemetry)

        content_result = super().verify(answer)
        if not content_result.success:
            content_result.extra = summary
            return content_result

        behavior_result = self.verify_behavior(answer, telemetry)
        if not behavior_result.success:
            behavior_result.expected = content_result.expected
            behavior_result.received = content_result.received
            merged_failure = dict(summary)
            if behavior_result.extra:
                merged_failure.update(behavior_result.extra)
            behavior_result.extra = merged_failure
            return behavior_result

        merged_extra: Dict[str, Any] = dict(summary)
        if content_result.extra:
            merged_extra.update(content_result.extra)
        if behavior_result.extra:
            merged_extra.update(behavior_result.extra)
        content_result.extra = merged_extra or content_result.extra
        return content_result

    def _telemetry_summary(self, telemetry: List[Dict[str, Any]]) -> Dict[str, Any]:
        event_counts: Dict[str, int] = {}
        for event in telemetry:
            event_type = str(event.get("type", "unknown"))
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        return {
            "telemetry_events": len(telemetry),
            "telemetry_event_counts": event_counts,
            "telemetry_duration_ms": self._event_duration_ms(telemetry),
        }

    def _behavior_pass(self, telemetry: List[Dict[str, Any]], **extra: Any) -> CaptchaResult:
        details = {"telemetry_events": len(telemetry)}
        details.update(extra)
        return CaptchaResult(
            success=True,
            message="Dynamic behavior check passed.",
            extra=details,
        )

    def _behavior_fail(self, message: str, telemetry: List[Dict[str, Any]], **extra: Any) -> CaptchaResult:
        details = {"telemetry_events": len(telemetry)}
        details.update(extra)
        return CaptchaResult(
            success=False,
            message=message,
            extra=details,
        )

    @staticmethod
    def _events_of_type(telemetry: List[Dict[str, Any]], event_type: str) -> List[Dict[str, Any]]:
        return [event for event in telemetry if event.get("type") == event_type]

    @staticmethod
    def _event_duration_ms(telemetry: List[Dict[str, Any]]) -> int:
        if not telemetry:
            return 0
        return int(telemetry[-1].get("t", 0)) - int(telemetry[0].get("t", 0))

    @staticmethod
    def _extract_pointer_points(
        telemetry: List[Dict[str, Any]],
        allowed_types: Tuple[str, ...] = ("drag_start", "drag_move", "drag_end"),
    ) -> List[Dict[str, float]]:
        points: List[Dict[str, float]] = []
        for event in telemetry:
            event_type = event.get("type")
            if event_type not in allowed_types:
                continue
            x = event.get("x")
            y = event.get("y")
            t = event.get("t")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)) and isinstance(t, (int, float)):
                points.append(
                    {
                        "type": str(event_type),
                        "x": float(x),
                        "y": float(y),
                        "t": float(t),
                    }
                )
        return points

    @staticmethod
    def _trajectory_metrics(points: List[Dict[str, float]]) -> Dict[str, float]:
        if len(points) < 2:
            return {
                "point_count": float(len(points)),
                "path_length": 0.0,
                "net_distance": 0.0,
                "max_jump": 0.0,
                "straightness_ratio": 1.0,
                "duration_ms": 0.0,
                "x_span": 0.0,
                "y_span": 0.0,
            }

        path_length = 0.0
        max_jump = 0.0
        for prev, cur in zip(points, points[1:]):
            seg = math.hypot(cur["x"] - prev["x"], cur["y"] - prev["y"])
            path_length += seg
            max_jump = max(max_jump, seg)

        start = points[0]
        end = points[-1]
        net_distance = math.hypot(end["x"] - start["x"], end["y"] - start["y"])
        xs = [point["x"] for point in points]
        ys = [point["y"] for point in points]

        return {
            "point_count": float(len(points)),
            "path_length": path_length,
            "net_distance": net_distance,
            "max_jump": max_jump,
            "straightness_ratio": path_length / max(net_distance, 1.0),
            "duration_ms": max(end["t"] - start["t"], 0.0),
            "x_span": max(xs) - min(xs),
            "y_span": max(ys) - min(ys),
        }

    @staticmethod
    def _detect_repeated_wrong_loop(
        events: List[Dict[str, Any]],
        event_key: str,
        loop_threshold: int = 3,
    ) -> Dict[str, Any]:

        if len(events) < loop_threshold:
            return {"repeated_loop_detected": False, "sequences": []}

        sequences = []
        current_seq: List[Any] = []
        for event in events:
            value = event.get(event_key)
            if value is not None:
                current_seq.append(value)

        if len(current_seq) < loop_threshold:
            return {"repeated_loop_detected": False, "sequences": [current_seq] if current_seq else []}

        for window_size in range(2, min(len(current_seq) // 2 + 1, 6)):
            for start in range(len(current_seq) - window_size * 2 + 1):
                pattern = current_seq[start:start + window_size]
                next_pattern = current_seq[start + window_size:start + window_size * 2]
                if pattern == next_pattern:
                    repeat_count = 2
                    pos = start + window_size * 2
                    while pos + window_size <= len(current_seq):
                        if current_seq[pos:pos + window_size] == pattern:
                            repeat_count += 1
                            pos += window_size
                        else:
                            break
                    if repeat_count >= loop_threshold:
                        return {
                            "repeated_loop_detected": True,
                            "pattern": pattern,
                            "repeat_count": repeat_count,
                            "sequences": [current_seq],
                        }

        return {"repeated_loop_detected": False, "sequences": [current_seq]}
