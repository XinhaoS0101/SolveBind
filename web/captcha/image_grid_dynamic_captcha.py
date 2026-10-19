from __future__ import annotations

from typing import Any, Dict, List

from .dynamic_captcha import DynamicCaptchaMixin
from .image_grid_captcha import ImageGridCaptcha


class ImageGridDynamicCaptcha(DynamicCaptchaMixin, ImageGridCaptcha):
    dynamic_type = "image_grid_dynamic"

    def build_dynamic_script(self) -> str:
        return """
  const grid = document.getElementById('img-grid');
  const input = document.getElementById('captcha-input');
  if (!grid || !input) return;

  let lastSelection = String(input.value || '');

  function decorateCells() {
    Array.from(grid.children).forEach(function(cell, idx) {
      cell.setAttribute('data-grid-index', String(idx));
    });
  }

  const observer = new MutationObserver(decorateCells);
  observer.observe(grid, { childList: true });
  decorateCells();

  grid.addEventListener('click', function(evt) {
    const cell = evt.target.closest('[data-grid-index]');
    if (!cell) return;
    window.setTimeout(function() {
      const currentSelection = String(input.value || '');
      record('tile_toggle', {
        idx: Number(cell.getAttribute('data-grid-index')),
        selectionCount: currentSelection.split(',').filter(Boolean).length,
        selection: currentSelection,
      });
    }, 0);
  });

  window.setInterval(function() {
    const currentSelection = String(input.value || '');
    if (currentSelection !== lastSelection) {
      record('selection_change', {
        prev: lastSelection,
        next: currentSelection,
      });
      lastSelection = currentSelection;
    }
  }, 150);
"""

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]):
        toggles = self._events_of_type(telemetry, "tile_toggle")
        selection_changes = self._events_of_type(telemetry, "selection_change")
        duration_ms = self._event_duration_ms(telemetry)
        final_count = len([part for part in answer.split(",") if part.strip()])

        if len(toggles) < final_count:
            return self._behavior_fail(
                "Dynamic check failed: not enough grid interactions were recorded.",
                telemetry,
                toggle_events=len(toggles),
                final_count=final_count,
            )

        touched_indices = {
            int(event.get("idx", -1))
            for event in toggles
            if isinstance(event.get("idx"), (int, float))
        }
        if len(touched_indices) < final_count:
            return self._behavior_fail(
                "Dynamic check failed: the interaction trail did not cover enough tiles.",
                telemetry,
                touched_tiles=len(touched_indices),
                final_count=final_count,
            )

        if len(selection_changes) >= 6:
            selections = [ev.get("next", "") for ev in selection_changes]
            loop_result = self._detect_repeated_wrong_loop(
                [{"sel": s} for s in selections],
                "sel",
                loop_threshold=3,
            )
            if loop_result.get("repeated_loop_detected"):
                return self._behavior_fail(
                    "Dynamic check failed: repeated selection pattern detected (possible retry loop).",
                    telemetry,
                    repeated_pattern=loop_result.get("pattern"),
                    repeat_count=loop_result.get("repeat_count"),
                )

        return self._behavior_pass(
            telemetry,
            toggle_events=len(toggles),
            duration_ms=duration_ms,
            touched_tiles=len(touched_indices),
            selection_changes=len(selection_changes),
        )
