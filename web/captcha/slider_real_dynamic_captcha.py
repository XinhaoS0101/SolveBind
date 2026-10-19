from __future__ import annotations

from typing import Any, Dict, List

from .dynamic_captcha import DynamicCaptchaMixin
from .slider_real_captcha import SliderRealCaptcha


class SliderRealDynamicCaptcha(DynamicCaptchaMixin, SliderRealCaptcha):
    dynamic_type = "slider_real_dynamic"

    def build_dynamic_script(self) -> str:
        return """
  const handle = document.getElementById('slider-handle');
  if (!handle) return;
  let dragging = false;

  function pointFromEvent(evt) {
    const p = evt.touches && evt.touches.length ? evt.touches[0] : evt;
    return { x: p.clientX || 0, y: p.clientY || 0 };
  }

  function onStart(evt) {
    dragging = true;
    const pt = pointFromEvent(evt);
    record('drag_start', pt);
  }

  function onMove(evt) {
    if (!dragging) return;
    const pt = pointFromEvent(evt);
    record('drag_move', pt);
  }

  function onEnd(evt) {
    if (!dragging) return;
    dragging = false;
    const pt = pointFromEvent(evt.changedTouches && evt.changedTouches.length ? evt.changedTouches[0] : evt);
    record('drag_end', pt);
  }

  handle.addEventListener('mousedown', onStart);
  handle.addEventListener('touchstart', onStart, { passive: true });
  document.addEventListener('mousemove', onMove);
  document.addEventListener('touchmove', onMove, { passive: true });
  // Capture release before the base widget's bubbling listener auto-submits.
  document.addEventListener('mouseup', onEnd, true);
  document.addEventListener('touchend', onEnd, { capture: true, passive: true });
  document.addEventListener('touchcancel', onEnd, { capture: true, passive: true });
"""

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]):
        starts = self._events_of_type(telemetry, "drag_start")
        ends = self._events_of_type(telemetry, "drag_end")
        points = self._extract_pointer_points(telemetry)
        metrics = self._trajectory_metrics(points)
        duration_ms = round(metrics["duration_ms"], 2)

        if not starts or not ends:
            return self._behavior_fail(
                "Dynamic check failed: the slider must be dragged before verification.",
                telemetry,
                duration_ms=duration_ms,
                reason="missing_drag_chain",
            )
        if metrics["net_distance"] < 35:
            return self._behavior_fail(
                "Dynamic check failed: the slider trajectory did not contain enough real movement.",
                telemetry,
                duration_ms=duration_ms,
                net_distance=round(metrics["net_distance"], 2),
                reason="insufficient_displacement",
            )
        if metrics["max_jump"] > max(110.0, metrics["path_length"] * 0.88):
            return self._behavior_fail(
                "Dynamic check failed: the slider trajectory looked like a jump instead of a continuous drag.",
                telemetry,
                duration_ms=duration_ms,
                max_jump=round(metrics["max_jump"], 2),
                path_length=round(metrics["path_length"], 2),
                reason="teleport_like",
            )

        return self._behavior_pass(
            telemetry,
            duration_ms=duration_ms,
            point_count=int(metrics["point_count"]),
            net_distance=round(metrics["net_distance"], 2),
            path_length=round(metrics["path_length"], 2),
            straightness_ratio=round(metrics["straightness_ratio"], 3),
            max_jump=round(metrics["max_jump"], 2),
            x_span=round(metrics["x_span"], 2),
            y_span=round(metrics["y_span"], 2),
        )
