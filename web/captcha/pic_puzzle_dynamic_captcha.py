from __future__ import annotations

from typing import Any, Dict, List, Optional

from .dynamic_captcha import DynamicCaptchaMixin
from .pic_puzzle_captcha import PicPuzzleCaptcha


class PicPuzzleDynamicCaptcha(DynamicCaptchaMixin, PicPuzzleCaptcha):
    dynamic_type = "pic_puzzle_dynamic"

    def build_dynamic_script(self) -> str:
        return """
  const grid = document.getElementById('pic-puzzle-grid');
  const input = document.getElementById('captcha-input');
  if (!grid || !input) return;

  let lastOrder = null;
  let lastAnswer = '';

  function getCurrentOrder() {
    if (typeof window.__picPuzzleGetCommittedOrder === 'function') {
      return window.__picPuzzleGetCommittedOrder();
    }
    return null;
  }

  function countOrderDiff(prev, next) {
    if (!prev || !next || prev.length !== next.length) return -1;
    let diff = 0;
    for (let i = 0; i < prev.length; i++) {
      if (prev[i] !== next[i]) diff++;
    }
    return diff;
  }

  function attachTileListeners(tile) {
    if (!tile || tile.__dynamicBound) return;
    tile.__dynamicBound = true;

    tile.addEventListener('dragstart', function() {
      record('tile_drag_start', { slot: Number(tile.dataset.slot || -1) });
    });
    tile.addEventListener('dragenter', function() {
      record('tile_drag_enter', { slot: Number(tile.dataset.slot || -1) });
    });
    tile.addEventListener('drop', function() {
      record('tile_drop', { slot: Number(tile.dataset.slot || -1) });
    });
    tile.addEventListener('click', function() {
      record('tile_tap', { slot: Number(tile.dataset.slot || -1) });
    });
  }

  function scanTiles() {
    grid.querySelectorAll('.pic-puzzle-tile').forEach(attachTileListeners);
  }

  const observer = new MutationObserver(scanTiles);
  observer.observe(grid, { childList: true, subtree: true });
  scanTiles();

  window.setTimeout(function() {
    lastOrder = getCurrentOrder();
    if (lastOrder) {
      record('initial_order', { order: lastOrder.slice() });
    }
  }, 50);

  window.setInterval(function() {
    const nextAnswer = String(input.value || '');
    if (nextAnswer !== lastAnswer) {
      const nextOrder = getCurrentOrder();
      const diffCount = countOrderDiff(lastOrder, nextOrder);

      if (nextAnswer) {
        record('swap_commit', {
          answer: nextAnswer,
          order: nextOrder ? nextOrder.slice() : null,
          diff_count: diffCount,
        });
      } else {
        record('swap_clear', {});
      }

      lastAnswer = nextAnswer;
      if (nextOrder) {
        lastOrder = nextOrder.slice();
      }
    }
  }, 120);
"""

    def _parse_order(self, order: Any) -> Optional[List[int]]:
        if order is None:
            return None
        if isinstance(order, list):
            try:
                return [int(x) for x in order]
            except (ValueError, TypeError):
                return None
        return None

    def _count_order_diff(self, prev: Optional[List[int]], next_order: Optional[List[int]]) -> int:
        if prev is None or next_order is None:
            return -1
        if len(prev) != len(next_order):
            return -1
        return sum(1 for a, b in zip(prev, next_order) if a != b)

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]):
        swaps = self._events_of_type(telemetry, "swap_commit")
        taps = self._events_of_type(telemetry, "tile_tap")
        drag_starts = self._events_of_type(telemetry, "tile_drag_start")
        drag_enters = self._events_of_type(telemetry, "tile_drag_enter")
        drops = self._events_of_type(telemetry, "tile_drop")
        duration_ms = self._event_duration_ms(telemetry)

        if not swaps:
            return self._behavior_fail(
                "Dynamic check failed: no swap interaction was recorded.",
                telemetry,
                duration_ms=duration_ms,
            )

        used_tap_flow = len(taps) >= 2
        used_drag_flow = bool(drag_starts and (drag_enters or drops))
        if not used_tap_flow and not used_drag_flow:
            return self._behavior_fail(
                "Dynamic check failed: the swap trail did not look like a real drag or tap sequence.",
                telemetry,
                tap_events=len(taps),
                drag_events=len(drag_starts),
            )

        for swap in swaps:
            diff_count = swap.get("diff_count", -1)
            if isinstance(diff_count, (int, float)) and diff_count > 2:
                return self._behavior_fail(
                    "Dynamic check failed: illegal state transition (too many positions changed at once).",
                    telemetry,
                    diff_count=diff_count,
                )

        if swaps:
            last_swap_answer = swaps[-1].get("answer", "")
            if answer and last_swap_answer and answer != last_swap_answer:
                return self._behavior_fail(
                    "Dynamic check failed: final submitted answer does not match last recorded swap.",
                    telemetry,
                    submitted=answer,
                    recorded=last_swap_answer,
                )

        return self._behavior_pass(
            telemetry,
            swap_events=len(swaps),
            tap_events=len(taps),
            drag_start_events=len(drag_starts),
            duration_ms=duration_ms,
        )
