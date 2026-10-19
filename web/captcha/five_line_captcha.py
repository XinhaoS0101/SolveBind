from __future__ import annotations

import html
import json
import random
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseCaptcha, CaptchaResult, CaptchaType

Color = Optional[str]

COLORS = ("b", "y", "k", "w")


def _all_lines() -> List[List[Tuple[int, int]]]:
    lines: List[List[Tuple[int, int]]] = []
    for r in range(5):
        lines.append([(r, c) for c in range(5)])
    for c in range(5):
        lines.append([(r, c) for r in range(5)])
    lines.append([(i, i) for i in range(5)])
    lines.append([(i, 4 - i) for i in range(5)])
    return lines


_ALL_LINES = _all_lines()


def _line_has_five(grid: List[List[Color]], color: str) -> bool:
    for line in _ALL_LINES:
        if all(grid[r][c] == color for r, c in line):
            return True
    return False


def _any_five(grid: List[List[Color]]) -> bool:
    for c in COLORS:
        if _line_has_five(grid, c):
            return True
    return False


def _generate_solvable_board(max_attempts: int = 200) -> List[List[Color]]:
    lines = _ALL_LINES
    for _ in range(max_attempts):
        line = random.choice(lines)
        win_color = random.choice(COLORS)
        empty_idx = random.randint(0, 4)
        line_set = set(line)

        grid: List[List[Color]] = [[None] * 5 for _ in range(5)]
        for i, (r, c) in enumerate(line):
            if i != empty_idx:
                grid[r][c] = win_color

        off: List[Tuple[int, int]] = [
            (r, c)
            for r in range(5)
            for c in range(5)
            if (r, c) not in line_set and grid[r][c] is None
        ]
        if not off:
            continue
        r5, c5 = random.choice(off)
        grid[r5][c5] = win_color
        er, ec = line[empty_idx]

        counts: Dict[str, int] = {x: 0 for x in COLORS}
        for r in range(5):
            for c in range(5):
                v = grid[r][c]
                if v:
                    counts[v] += 1

        others = [x for x in COLORS if x != win_color]
        for r in range(5):
            for c in range(5):
                if grid[r][c] is not None:
                    continue
                if (r, c) == (er, ec):
                    continue
                pick_pool: List[Optional[str]] = [None]
                for x in others:
                    if counts[x] < 4:
                        pick_pool.append(x)
                choice = random.choice(pick_pool)
                grid[r][c] = choice
                if choice:
                    counts[choice] += 1

        if _any_five(grid):
            continue
        if counts[win_color] != 5:
            continue
        if any(counts[c] >= 5 for c in others):
            continue
        return grid
    raise RuntimeError("five_line_captcha: failed to generate board")


class FiveLineCaptcha(BaseCaptcha):

    def __init__(self, **kwargs):
        super().__init__(CaptchaType.FIVE_LINE, **kwargs)
        self._grid: List[List[Color]] = []

    def generate(self) -> Dict[str, Any]:
        self._grid = _generate_solvable_board()
        self._answer = json.dumps(self._grid, separators=(",", ":"))
        self._generated = True
        return {"type": "five_line", "grid": self._grid}

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        grid_json = json.dumps(self._grid)
        field_esc = html.escape(grid_json, quote=True)

        return f"""
<style>
  .fl-widget {{
    --fl-bg: #ffffff;
    --fl-grid-bg: #e5eaf0;
    --fl-text: #222222;
    --fl-accent: #4a90d9;
    --fl-slot: #d8dee6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: var(--fl-text);
    background: var(--fl-bg);
    border-radius: 12px;
    border: 1px solid #e0e4ea;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
    overflow: hidden;
    max-width: 340px;
    margin: 0 auto;
  }}
  .fl-widget-top {{
    height: 3px;
    background: linear-gradient(90deg, #3d7ec4, var(--fl-accent));
  }}
  .fl-instruction {{
    padding: 14px 16px 10px;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.45;
    text-align: center;
  }}
  .fl-board-wrap {{
    margin: 0 14px 14px;
    padding: 14px;
    background: var(--fl-grid-bg);
    border-radius: 10px;
  }}
  .fl-grid {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 8px;
    user-select: none;
  }}
  .fl-cell {{
    aspect-ratio: 1;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    position: relative;
    background: radial-gradient(circle at 50% 55%, var(--fl-slot) 0%, #c5ccd6 55%, #aeb6c2 100%);
    box-shadow:
      inset 0 2px 4px rgba(255,255,255,.65),
      inset 0 -3px 6px rgba(0,0,0,.12);
    transition: transform .12s ease, box-shadow .12s ease;
  }}
  .fl-cell:hover {{ filter: brightness(1.02); }}
  .fl-cell.fl-selected {{
    box-shadow:
      inset 0 2px 4px rgba(255,255,255,.5),
      inset 0 -3px 6px rgba(0,0,0,.1),
      0 0 0 3px rgba(74, 144, 217, .55);
  }}
  .fl-cell.fl-drop-target {{
    box-shadow:
      inset 0 2px 4px rgba(255,255,255,.5),
      0 0 0 3px rgba(79, 70, 229, .35);
  }}
  .fl-piece {{
    width: 78%;
    height: 78%;
    border-radius: 50%;
    pointer-events: none;
    box-shadow:
      inset -4px -5px 8px rgba(0,0,0,.22),
      inset 5px 6px 10px rgba(255,255,255,.55),
      0 3px 6px rgba(0,0,0,.18);
  }}
  .fl-piece-b {{
    background: radial-gradient(circle at 28% 28%, #9fd8ff 0%, #3eb0ff 35%, #1a8ee6 70%, #0d6ebd 100%);
  }}
  .fl-piece-y {{
    background: radial-gradient(circle at 28% 28%, #fff6c2 0%, #f5c542 40%, #e6a818 78%, #c48a0a 100%);
  }}
  .fl-piece-k {{
    background: radial-gradient(circle at 28% 28%, #5a5a62 0%, #3a3a42 45%, #1f1f24 85%, #121216 100%);
  }}
  .fl-piece-w {{
    background: radial-gradient(circle at 28% 28%, #ffffff 0%, #f3f3f5 50%, #dcdce0 100%);
    box-shadow:
      inset -3px -4px 6px rgba(0,0,0,.12),
      inset 4px 5px 8px rgba(255,255,255,.95),
      0 2px 5px rgba(0,0,0,.12);
    border: 1px solid rgba(0,0,0,.06);
  }}
</style>
<div class="fl-widget" id="fl-widget">
  <div class="fl-widget-top" aria-hidden="true"></div>
  <div class="fl-instruction">Click and drop to line up five identical items in a row</div>
  <div class="fl-board-wrap">
    <div class="fl-grid" id="fl-grid" role="grid" aria-label="Five in a row board"></div>
  </div>
</div>
<input type="hidden" name="captcha" id="captcha-input" value="{field_esc}" />
<script>
(function() {{
  const COLS = {{ b: 'fl-piece-b', y: 'fl-piece-y', k: 'fl-piece-k', w: 'fl-piece-w' }};
  let grid = {grid_json};
  const elGrid = document.getElementById('fl-grid');
  const elField = document.getElementById('captcha-input');
  let sel = null;
  let dragFrom = null;

  function syncField() {{
    elField.value = JSON.stringify(grid);
  }}

  function clearDropHints() {{
    elGrid.querySelectorAll('.fl-drop-target').forEach(function(x) {{ x.classList.remove('fl-drop-target'); }});
  }}

  function render() {{
    elGrid.innerHTML = '';
    for (let r = 0; r < 5; r++) {{
      for (let c = 0; c < 5; c++) {{
        const cell = document.createElement('div');
        cell.className = 'fl-cell';
        cell.dataset.r = r;
        cell.dataset.c = c;
        cell.setAttribute('role', 'gridcell');
        const v = grid[r][c];
        if (v) {{
          const p = document.createElement('div');
          p.className = 'fl-piece ' + (COLS[v] || '');
          cell.appendChild(p);
          cell.setAttribute('draggable', 'true');
        }} else {{
          cell.setAttribute('draggable', 'false');
        }}
        if (sel && sel.r === r && sel.c === c) cell.classList.add('fl-selected');
        elGrid.appendChild(cell);
      }}
    }}
    syncField();
  }}

  function tryMove(fr, fc, tr, tc) {{
    const piece = grid[fr][fc];
    const dest = grid[tr][tc];
    if (!piece || dest != null) return;
    grid[fr][fc] = null;
    grid[tr][tc] = piece;
    sel = null;
    render();
  }}

  elGrid.addEventListener('click', function(e) {{
    const cell = e.target.closest('.fl-cell');
    if (!cell) return;
    const r = +cell.dataset.r, c = +cell.dataset.c;
    const v = grid[r][c];
    if (v) {{
      sel = {{ r, c }};
      render();
      return;
    }}
    if (sel) tryMove(sel.r, sel.c, r, c);
  }});

  elGrid.addEventListener('dragstart', function(e) {{
    const cell = e.target.closest('.fl-cell');
    if (!cell) return;
    const r = +cell.dataset.r, c = +cell.dataset.c;
    if (!grid[r][c]) {{ e.preventDefault(); return; }}
    dragFrom = {{ r: r, c: c }};
    e.dataTransfer.setData('text/plain', 'fl');
    e.dataTransfer.effectAllowed = 'move';
  }});

  elGrid.addEventListener('dragover', function(e) {{
    e.preventDefault();
    clearDropHints();
    const cell = e.target.closest('.fl-cell');
    if (!cell) return;
    const r = +cell.dataset.r, c = +cell.dataset.c;
    if (grid[r][c] == null) {{
      e.dataTransfer.dropEffect = 'move';
      cell.classList.add('fl-drop-target');
    }}
  }});

  elGrid.addEventListener('dragleave', function(e) {{
    if (!elGrid.contains(e.relatedTarget)) clearDropHints();
  }});

  elGrid.addEventListener('drop', function(e) {{
    e.preventDefault();
    clearDropHints();
    const cell = e.target.closest('.fl-cell');
    if (!cell || !dragFrom) return;
    const r = +cell.dataset.r, c = +cell.dataset.c;
    tryMove(dragFrom.r, dragFrom.c, r, c);
    dragFrom = null;
  }});

  elGrid.addEventListener('dragend', function() {{
    clearDropHints();
    dragFrom = null;
  }});

  render();
}})();
</script>
"""

    def verify(self, user_input: Any) -> CaptchaResult:
        if not self._generated:
            self.generate()

        raw = (user_input or "").strip()
        if not raw:
            return CaptchaResult(
                success=False,
                message="Please tap Verify after lining up five identical pieces.",
                expected=self._answer,
                received=raw,
            )

        try:
            final = json.loads(raw)
        except json.JSONDecodeError:
            return CaptchaResult(
                success=False,
                message="Invalid submission.",
                expected=self._answer,
                received=raw,
            )

        if not self._is_valid_grid(final):
            return CaptchaResult(
                success=False,
                message="Invalid board data.",
                expected=self._answer,
                received=raw,
            )

        normalized = self._normalize_grid(final)
        if not self._is_single_legal_move(self._grid, normalized):
            return CaptchaResult(
                success=False,
                message="The submitted board does not match a valid single move from the current puzzle.",
                expected=self._answer,
                received=raw,
            )

        if not _any_five(normalized):
            return CaptchaResult(
                success=False,
                message="No five identical pieces in a row (horizontal, vertical, or diagonal).",
                expected=self._answer,
                received=raw,
            )

        return CaptchaResult(success=True, message="Verification succeeded.")

    def _is_valid_grid(self, g: Any) -> bool:
        if not isinstance(g, list) or len(g) != 5:
            return False
        for row in g:
            if not isinstance(row, list) or len(row) != 5:
                return False
            for cell in row:
                if cell is not None and cell not in COLORS:
                    if cell == "":
                        continue
                    return False
        return True

    def _normalize_grid(self, grid: List[List[Any]]) -> List[List[Color]]:
        normalized: List[List[Color]] = []
        for row in grid:
            normalized.append([None if cell == "" else cell for cell in row])
        return normalized

    def _is_single_legal_move(
        self, initial: List[List[Color]], final: List[List[Color]]
    ) -> bool:
        diffs: List[Tuple[int, int]] = []
        for r in range(5):
            for c in range(5):
                if initial[r][c] != final[r][c]:
                    diffs.append((r, c))

        if len(diffs) != 2:
            return False

        src: Optional[Tuple[int, int]] = None
        dst: Optional[Tuple[int, int]] = None
        moved_piece: Optional[str] = None
        for r, c in diffs:
            start = initial[r][c]
            end = final[r][c]
            if start in COLORS and end is None:
                src = (r, c)
                moved_piece = start
            elif start is None and end in COLORS:
                dst = (r, c)
            else:
                return False

        if src is None or dst is None or moved_piece is None:
            return False
        return final[dst[0]][dst[1]] == moved_piece

    def get_answer(self) -> Optional[str]:
        return self._answer
