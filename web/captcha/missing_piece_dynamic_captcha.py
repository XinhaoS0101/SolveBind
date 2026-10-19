from __future__ import annotations

from typing import Any, Dict, List

from .dynamic_captcha import DynamicCaptchaMixin
from .missing_piece_captcha import MissingPieceCaptcha


class MissingPieceDynamicCaptcha(DynamicCaptchaMixin, MissingPieceCaptcha):
    dynamic_type = "missing_piece_dynamic"

    def build_dynamic_script(self) -> str:
        return """
  const grid = document.getElementById('candidates-grid');
  const input = document.getElementById('captcha-input');
  if (!grid || !input) return;

  let lastValue = String(input.value || '');
  let selectionHistory = [];

  grid.addEventListener('click', function(evt) {
    const item = evt.target.closest('[data-candidate-index]');
    if (!item) return;
    record('candidate_click', {
      candidate: Number(item.dataset.candidateIndex || -1),
    });
  });

  window.setInterval(function() {
    const nextValue = String(input.value || '');
    if (nextValue !== lastValue) {
      if (nextValue) {
        const candidateNum = Number(nextValue);
        selectionHistory.push(candidateNum);
        record('candidate_select', {
          candidate: candidateNum,
          historyLength: selectionHistory.length,
        });
      }
      lastValue = nextValue;
    }
  }, 120);
"""

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]):
        clicks = self._events_of_type(telemetry, "candidate_click")
        selects = self._events_of_type(telemetry, "candidate_select")
        duration_ms = self._event_duration_ms(telemetry)

        if not selects:
            return self._behavior_fail(
                "Dynamic check failed: no candidate selection was recorded.",
                telemetry,
                click_events=len(clicks),
            )

        last_select = selects[-1]
        selected_candidate = str(last_select.get("candidate", ""))
        if selected_candidate != answer:
            return self._behavior_fail(
                "Dynamic check failed: submitted answer did not match the recorded final selection.",
                telemetry,
                selected=selected_candidate,
                submitted=answer,
            )

        if len(selects) >= 6:
            loop_result = self._detect_repeated_wrong_loop(
                selects,
                "candidate",
                loop_threshold=3,
            )
            if loop_result.get("repeated_loop_detected"):
                return self._behavior_fail(
                    "Dynamic check failed: repeated wrong selection pattern detected.",
                    telemetry,
                    repeated_pattern=loop_result.get("pattern"),
                    repeat_count=loop_result.get("repeat_count"),
                )

        return self._behavior_pass(
            telemetry,
            click_events=len(clicks),
            selection_events=len(selects),
            duration_ms=duration_ms,
        )
