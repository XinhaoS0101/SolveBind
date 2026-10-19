from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .dynamic_captcha import DynamicCaptchaMixin
from .five_line_captcha import FiveLineCaptcha


class FiveLineDynamicCaptcha(DynamicCaptchaMixin, FiveLineCaptcha):
    dynamic_type = "five_line_dynamic"

    def build_dynamic_script(self) -> str:
        return """
  const grid = document.getElementById('fl-grid');
  const field = document.getElementById('captcha-input');
  if (!grid || !field) return;

  let lastValue = String(field.value || '');
  let moveHistory = [];

  function countGridDiff(prevGrid, nextGrid) {
    if (!prevGrid || !nextGrid) return -1;
    let diff = 0;
    for (let r = 0; r < 5; r++) {
      for (let c = 0; c < 5; c++) {
        if (prevGrid[r][c] !== nextGrid[r][c]) diff++;
      }
    }
    return diff;
  }

  grid.addEventListener('click', function(evt) {
    const cell = evt.target.closest('.fl-cell');
    if (!cell) return;
    const r = Number(cell.dataset.r || -1);
    const c = Number(cell.dataset.c || -1);
    record('cell_click', { r, c });
  });

  grid.addEventListener('dragstart', function(evt) {
    const cell = evt.target.closest('.fl-cell');
    if (!cell) return;
    record('piece_drag_start', {
      r: Number(cell.dataset.r || -1),
      c: Number(cell.dataset.c || -1),
    });
  });

  grid.addEventListener('drop', function(evt) {
    const cell = evt.target.closest('.fl-cell');
    if (!cell) return;
    record('piece_drop', {
      r: Number(cell.dataset.r || -1),
      c: Number(cell.dataset.c || -1),
    });
  });

  window.setInterval(function() {
    const nextValue = String(field.value || '');
    if (nextValue !== lastValue) {
      try {
        const prevGrid = lastValue ? JSON.parse(lastValue) : null;
        const nextGrid = nextValue ? JSON.parse(nextValue) : null;
        const diffCount = countGridDiff(prevGrid, nextGrid);

        if (prevGrid && nextGrid) {
          let fromPos = null;
          let toPos = null;
          for (let r = 0; r < 5; r++) {
            for (let c = 0; c < 5; c++) {
              const prevCell = prevGrid[r][c];
              const nextCell = nextGrid[r][c];
              if (prevCell && !nextCell) fromPos = { r, c };
              if (!prevCell && nextCell) toPos = { r, c, value: nextCell };
            }
          }
          if (fromPos || toPos) {
            const moveInfo = {
              from_r: fromPos ? fromPos.r : -1,
              from_c: fromPos ? fromPos.c : -1,
              to_r: toPos ? toPos.r : -1,
              to_c: toPos ? toPos.c : -1,
              diff_count: diffCount,
              history_len: moveHistory.length + 1,
            };
            moveHistory.push(moveInfo);
            record('move_commit', moveInfo);
          }
        }
      } catch (err) {
        record('board_update', {});
      }
      lastValue = nextValue;
    }
  }, 120);
"""

    def _parse_board_state(self, answer: str) -> Optional[List[List[Any]]]:
        if not answer:
            return None
        try:
            return json.loads(answer)
        except (json.JSONDecodeError, TypeError):
            return None

    def _count_board_diff(self, prev: Optional[List[List[Any]]], next_state: Optional[List[List[Any]]]) -> int:
        if prev is None or next_state is None:
            return -1
        if len(prev) != 5 or len(next_state) != 5:
            return -1
        diff = 0
        for r in range(5):
            for c in range(5):
                if prev[r][c] != next_state[r][c]:
                    diff += 1
        return diff

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]):
        cell_clicks = self._events_of_type(telemetry, "cell_click")
        drag_starts = self._events_of_type(telemetry, "piece_drag_start")
        drops = self._events_of_type(telemetry, "piece_drop")
        moves = self._events_of_type(telemetry, "move_commit")
        duration_ms = self._event_duration_ms(telemetry)

        if not moves:
            return self._behavior_fail(
                "Dynamic check failed: no board move was recorded.",
                telemetry,
                click_events=len(cell_clicks),
                drag_events=len(drag_starts),
            )

        used_click_flow = len(cell_clicks) >= 2
        used_drag_flow = bool(drag_starts and drops)
        if not used_click_flow and not used_drag_flow:
            return self._behavior_fail(
                "Dynamic check failed: the board interaction did not look like a real move sequence.",
                telemetry,
                click_events=len(cell_clicks),
                drag_events=len(drag_starts),
                drop_events=len(drops),
            )

        for move in moves:
            diff_count = move.get("diff_count", -1)
            if isinstance(diff_count, (int, float)) and diff_count > 2:
                return self._behavior_fail(
                    "Dynamic check failed: illegal board state transition (too many cells changed at once).",
                    telemetry,
                    diff_count=diff_count,
                )

        if len(moves) >= 6:
            move_signatures = []
            for m in moves:
                sig = (m.get("from_r"), m.get("from_c"), m.get("to_r"), m.get("to_c"))
                move_signatures.append(sig)

            loop_result = self._detect_repeated_wrong_loop(
                [{"sig": str(s)} for s in move_signatures],
                "sig",
                loop_threshold=3,
            )
            if loop_result.get("repeated_loop_detected"):
                return self._behavior_fail(
                    "Dynamic check failed: repeated move pattern detected.",
                    telemetry,
                    repeated_pattern=loop_result.get("pattern"),
                    repeat_count=loop_result.get("repeat_count"),
                )

        return self._behavior_pass(
            telemetry,
            move_events=len(moves),
            click_events=len(cell_clicks),
            drag_events=len(drag_starts),
            duration_ms=duration_ms,
        )
