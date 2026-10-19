from __future__ import annotations

from typing import Any, Dict, List

from .dynamic_captcha import DynamicCaptchaMixin
from .logic_arithmetic_captcha import LogicArithmeticCaptcha


class LogicArithmeticDynamicCaptcha(DynamicCaptchaMixin, LogicArithmeticCaptcha):
    dynamic_type = "logic_arithmetic_dynamic"

    def build_dynamic_script(self) -> str:
        return """
  record('page_ready', {});

  let rotateHistory = [];
  let visualHistory = [];
  let seqHistory = [];
  let spatialHistory = [];
  let pathHistory = [];
  let textHistory = [];

  document.querySelectorAll('.logic-arrow').forEach(function(btn) {
    btn.addEventListener('click', function() {
      const control = btn.id || '';
      rotateHistory.push(control);
      record('rotate_click', {
        control: control,
        history_len: rotateHistory.length,
      });
    });
  });

  document.querySelectorAll('.logic-letter').forEach(function(btn) {
    btn.addEventListener('click', function() {
      const idx = Number(btn.getAttribute('data-idx') || -1);
      visualHistory.push(idx);
      record('visual_pick', {
        idx: idx,
        history_len: visualHistory.length,
      });
    });
  });

  const seqPrev = document.getElementById('seq-prev');
  const seqNext = document.getElementById('seq-next');
  if (seqPrev) {
    seqPrev.addEventListener('click', function() {
      seqHistory.push('prev');
      record('sequence_nav', { control: 'prev', history_len: seqHistory.length });
    });
  }
  if (seqNext) {
    seqNext.addEventListener('click', function() {
      seqHistory.push('next');
      record('sequence_nav', { control: 'next', history_len: seqHistory.length });
    });
  }

  document.querySelectorAll('.logic-scene').forEach(function(scene) {
    scene.addEventListener('click', function(evt) {
      const rect = scene.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8) return;
      const point = {
        x: ((evt.clientX - rect.left) / rect.width) * 100,
        y: ((evt.clientY - rect.top) / rect.height) * 100,
      };
      spatialHistory.push(point);
      record('spatial_pick', {
        x: point.x,
        y: point.y,
        history_len: spatialHistory.length,
      });
    });
  });

  [['path-arrow-l', 'prev'], ['path-arrow-r', 'next']].forEach(function(spec) {
    const btn = document.getElementById(spec[0]);
    if (!btn) return;
    btn.addEventListener('click', function() {
      pathHistory.push(spec[1]);
      record('path_nav', { control: spec[1], history_len: pathHistory.length });
    });
  });

  const weekdayInput = document.getElementById('weekday-ans');
  if (weekdayInput) {
    weekdayInput.addEventListener('input', function() {
      const val = String(weekdayInput.value || '');
      textHistory.push(val);
      record('text_input', {
        length: val.length,
        value: val,
        history_len: textHistory.length,
      });
    });
  }

  const arithInput = document.getElementById('arith-ans');
  if (arithInput) {
    arithInput.addEventListener('input', function() {
      const val = String(arithInput.value || '');
      textHistory.push(val);
      record('text_input', {
        length: val.length,
        value: val,
        history_len: textHistory.length,
      });
    });
  }
"""

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]):
        kind, _, payload = answer.partition("|")
        duration_ms = self._event_duration_ms(telemetry)

        if kind == "rotate":
            rotate_clicks = self._events_of_type(telemetry, "rotate_click")
            if not rotate_clicks:
                return self._behavior_fail(
                    "Dynamic check failed: rotation controls were not used.",
                    telemetry,
                    duration_ms=duration_ms,
                )

            if len(rotate_clicks) >= 6:
                loop_result = self._detect_repeated_wrong_loop(
                    rotate_clicks,
                    "control",
                    loop_threshold=3,
                )
                if loop_result.get("repeated_loop_detected"):
                    return self._behavior_fail(
                        "Dynamic check failed: repeated rotation pattern detected.",
                        telemetry,
                        repeated_pattern=loop_result.get("pattern"),
                        repeat_count=loop_result.get("repeat_count"),
                    )

            return self._behavior_pass(
                telemetry,
                rotate_clicks=len(rotate_clicks),
                duration_ms=duration_ms,
            )

        if kind == "visual":
            picks = self._events_of_type(telemetry, "visual_pick")
            if not picks:
                return self._behavior_fail(
                    "Dynamic check failed: no visual selection was recorded.",
                    telemetry,
                    duration_ms=duration_ms,
                )

            if len(picks) >= 6:
                loop_result = self._detect_repeated_wrong_loop(
                    picks,
                    "idx",
                    loop_threshold=3,
                )
                if loop_result.get("repeated_loop_detected"):
                    return self._behavior_fail(
                        "Dynamic check failed: repeated visual pick pattern detected.",
                        telemetry,
                        repeated_pattern=loop_result.get("pattern"),
                        repeat_count=loop_result.get("repeat_count"),
                    )

            return self._behavior_pass(
                telemetry,
                visual_picks=len(picks),
                duration_ms=duration_ms,
            )

        if kind == "sequence":
            navs = self._events_of_type(telemetry, "sequence_nav")
            if not navs:
                return self._behavior_fail(
                    "Dynamic check failed: sequence navigation controls were not used.",
                    telemetry,
                    duration_ms=duration_ms,
                )

            if len(navs) >= 6:
                loop_result = self._detect_repeated_wrong_loop(
                    navs,
                    "control",
                    loop_threshold=3,
                )
                if loop_result.get("repeated_loop_detected"):
                    return self._behavior_fail(
                        "Dynamic check failed: repeated sequence navigation pattern detected.",
                        telemetry,
                        repeated_pattern=loop_result.get("pattern"),
                        repeat_count=loop_result.get("repeat_count"),
                    )

            return self._behavior_pass(
                telemetry,
                sequence_navs=len(navs),
                duration_ms=duration_ms,
            )

        if kind in {"colorref", "uprightpick", "sidewayspick", "sizepick"}:
            picks = self._events_of_type(telemetry, "spatial_pick")
            if not picks:
                return self._behavior_fail(
                    "Dynamic check failed: no spatial selection was recorded.",
                    telemetry,
                    duration_ms=duration_ms,
                )
            return self._behavior_pass(
                telemetry,
                spatial_picks=len(picks),
                duration_ms=duration_ms,
            )

        if kind == "pathmatch":
            navs = self._events_of_type(telemetry, "path_nav")
            if not navs:
                return self._behavior_fail(
                    "Dynamic check failed: path navigation controls were not used.",
                    telemetry,
                    duration_ms=duration_ms,
                )
            if len(navs) >= 6:
                loop_result = self._detect_repeated_wrong_loop(
                    navs,
                    "control",
                    loop_threshold=3,
                )
                if loop_result.get("repeated_loop_detected"):
                    return self._behavior_fail(
                        "Dynamic check failed: repeated path navigation pattern detected.",
                        telemetry,
                        repeated_pattern=loop_result.get("pattern"),
                        repeat_count=loop_result.get("repeat_count"),
                    )
            return self._behavior_pass(
                telemetry,
                path_navs=len(navs),
                duration_ms=duration_ms,
            )

        text_inputs = self._events_of_type(telemetry, "text_input")
        if not text_inputs:
            return self._behavior_fail(
                "Dynamic check failed: no typed interaction was recorded.",
                telemetry,
                duration_ms=duration_ms,
            )

        if text_inputs:
            last_input = text_inputs[-1]
            recorded_value = str(last_input.get("value", ""))
            if payload and recorded_value != payload:
                return self._behavior_fail(
                    "Dynamic check failed: submitted text does not match last recorded input.",
                    telemetry,
                    submitted=payload,
                    recorded=recorded_value,
                )

        return self._behavior_pass(
            telemetry,
            text_inputs=len(text_inputs),
            duration_ms=duration_ms,
        )
