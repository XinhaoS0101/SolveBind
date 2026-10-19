from __future__ import annotations

import html as html_escape
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .base import BaseCaptcha, CaptchaResult, CaptchaType
except ImportError:
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from web.captcha.base import BaseCaptcha, CaptchaResult, CaptchaType


class LogicArithmeticCaptcha(BaseCaptcha):

    KINDS = (
        "rotate",
        "visual",
        "sequence",


    )

    def __init__(self, **kwargs):
        super().__init__(CaptchaType.MATH, **kwargs)
        self._challenge_kind: str = "arithmetic"
        self._initial_rotation: int = 0
        self._correct_visual_idx: int = 0
        self._sequence_correct_idx: int = 0
        self._sequence_options_json: str = "[]"
        self._ref_sequence_json: str = "[]"
        self._weekday_expected: str = ""
        self._weekday_question: str = ""
        self._arith_expr: str = ""
        self._visual_prompt: str = ""
        self._visual_letters_json: str = "[]"
        self._rotate_label: str = "A"

    def generate(self) -> Dict[str, Any]:
        self._challenge_kind = random.choice(self.KINDS)
        if self._challenge_kind == "rotate":
            self._gen_rotate()
        elif self._challenge_kind == "visual":
            self._gen_visual()
        elif self._challenge_kind == "sequence":
            self._gen_sequence()
        elif self._challenge_kind == "weekday":
            self._gen_weekday()
        else:
            self._gen_arithmetic()

        self._generated = True
        return {"kind": self._challenge_kind, "answer": self._answer}

    def _gen_rotate(self) -> None:
        steps = list(range(15, 360, 15))
        self._initial_rotation = random.choice(steps)
        self._rotate_label = random.choice("ABCDGHKMNPQRSTUVWXYZ")

        canonical_delta = (-self._initial_rotation) % 360
        self._answer = f"rotate|{canonical_delta}"

    def _gen_visual(self) -> None:
        n = 6
        idx_sideways = random.randrange(n)
        idx_upright = random.choice([i for i in range(n) if i != idx_sideways])
        letters: List[Dict[str, Any]] = []
        pool = [c for c in "ABCDEFGHJKLMNPQRSTUVWXYZ" if c != "F"]
        random.shuffle(pool)
        pi = 0
        for i in range(n):
            if i == idx_sideways:
                ch, rot = "F", 90
            elif i == idx_upright:
                ch, rot = "F", 0
            else:
                ch = pool[pi]
                pi += 1
                rot = random.choice([0, 15, -15, 30, -30, 45])
            letters.append(
                {
                    "letter": ch,
                    "rotate": rot,
                    "idx": i,
                    "hue": random.randint(180, 320),
                }
            )
        random.shuffle(letters)
        self._visual_letters_json = json.dumps(letters, ensure_ascii=False)
        self._correct_visual_idx = next(
            x["idx"] for x in letters if x["letter"] == "F" and x["rotate"] == 90
        )
        self._visual_prompt = "Click the sideways uppercase F."
        self._answer = f"visual|{self._correct_visual_idx}"

    def _gen_sequence(self) -> None:
        icons = ["🐰", "❄️", "🏺", "💎", "🍎", "⭐", "🚌", "🎵"]
        ref = random.sample(icons, 4)
        options: List[List[str]] = []
        correct = ref[:]
        options.append(correct[:])
        for _ in range(3):
            cand = ref[:]
            while cand == correct or cand in options:
                cand = random.sample(icons, 4)
            options.append(cand)
        random.shuffle(options)
        self._sequence_correct_idx = options.index(correct)
        self._ref_sequence_json = json.dumps(ref, ensure_ascii=False)
        self._sequence_options_json = json.dumps(options, ensure_ascii=False)
        self._answer = f"sequence|{self._sequence_correct_idx}"

    def _gen_weekday(self) -> None:
        qa: List[Tuple[str, str]] = [
            ("If tomorrow is Saturday, what day is today?", "Friday"),
            ("If yesterday was Monday, what day is today?", "Tuesday"),
            ("If the day after tomorrow is Wednesday, what day is today?", "Monday"),
            ("If three days from now is Friday, what day is today?", "Tuesday"),
            ("If today is Sunday, what day was yesterday?", "Saturday"),
        ]
        self._weekday_question, self._weekday_expected = random.choice(qa)
        self._answer = f"weekday|{self._weekday_expected}"

    def _gen_arithmetic(self) -> None:
        op = random.choice(["+", "-", "*"])
        if op == "*":
            a, b = random.randint(2, 12), random.randint(2, 12)
            ans = a * b
        elif op == "+":
            a, b = random.randint(10, 89), random.randint(10, 89)
            ans = a + b
        else:
            a = random.randint(30, 99)
            b = random.randint(10, a - 1)
            ans = a - b
        self._arith_expr = f"{a} {op} {b}"
        self._answer = f"arithmetic|{ans}"

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        kind = self._challenge_kind
        esc = html_escape.escape

        common_hint = (
            '<p class="logic-hint">Use the controls below to solve the challenge, then click Verify. Click Refresh for a new challenge.</p>'
        )

        if kind == "rotate":
            body = f"""
<div class="logic-block">
  <p class="logic-prompt">Rotate the character until it is upright, then click Verify.</p>
  <div class="logic-rotate-wrap">
    <button type="button" class="logic-arrow" id="rot-left" aria-label="Rotate counterclockwise">↺</button>
    <div class="logic-rotate-ring">
      <span id="rot-char" class="logic-rotate-char">{esc(self._rotate_label)}</span>
    </div>
    <button type="button" class="logic-arrow" id="rot-right" aria-label="Rotate clockwise">↻</button>
  </div>
  <p class="logic-sub">Each tap rotates by 15°. Current adjustment: <span id="rot-steps">0</span> steps.</p>
</div>"""

            script = f"""
(function() {{
  const initial = {self._initial_rotation};
  let delta = 0;
  const ring = document.querySelector('.logic-rotate-ring');
  const stepsEl = document.getElementById('rot-steps');
  function paint() {{
    ring.style.transform = 'rotate(' + (initial + delta) + 'deg)';
    stepsEl.textContent = String(Math.round(delta / 15));
  }}
  document.getElementById('rot-left').onclick = () => {{ delta -= 15; paint(); }};
  document.getElementById('rot-right').onclick = () => {{ delta += 15; paint(); }};
  paint();
  window.__logicSync = function() {{
    document.getElementById('captcha-input').value = 'rotate|' + delta;
  }};
}})();
"""

        elif kind == "visual":
            letters = json.loads(self._visual_letters_json)
            cells = []
            for item in letters:
                cells.append(
                    f"""<button type="button" class="logic-letter" data-idx="{item['idx']}"
          style="transform:rotate({item['rotate']}deg);color:hsl({item['hue']},70%,35%)">{esc(item['letter'])}</button>"""
                )
            grid = "\n".join(cells)
            body = f"""
<div class="logic-block logic-visual">
  <p class="logic-prompt">{esc(self._visual_prompt)}</p>
  <div class="logic-letter-grid" id="letter-grid">{grid}</div>
</div>"""
            script = """
(function() {
  let picked = '';
  document.querySelectorAll('.logic-letter').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.logic-letter').forEach(b => b.classList.remove('picked'));
      btn.classList.add('picked');
      picked = btn.getAttribute('data-idx');
    });
  });
  window.__logicSync = function() {
    document.getElementById('captcha-input').value = 'visual|' + picked;
  };
})();
"""

        elif kind == "sequence":
            ref = json.loads(self._ref_sequence_json)
            ref_html = "".join(
                f'<div class="seq-dot"><span>{html_escape.escape(x)}</span></div>'
                for x in ref
            )
            body = f"""
<div class="logic-block logic-seq">
  <p class="logic-prompt">Compare the top-to-bottom order on the left and use the arrows to find the matching option on the right.</p>
  <div class="seq-panels">
    <div class="seq-ref">
      <div class="seq-ref-title">Match this order</div>
      <div class="seq-col">{ref_html}</div>
    </div>
    <div class="seq-picker">
      <div id="seq-canvas" class="seq-canvas"></div>
      <div class="seq-nav">
        <button type="button" class="btn-mini" id="seq-prev">◀</button>
        <span id="seq-idx">1 / 4</span>
        <button type="button" class="btn-mini" id="seq-next">▶</button>
      </div>
    </div>
  </div>
</div>"""
            options_js_literal = json.dumps(
                json.loads(self._sequence_options_json), ensure_ascii=True
            )
            script = f"""
(function() {{
  const options = {options_js_literal};
  let i = 0;
  const canvas = document.getElementById('seq-canvas');
  const lab = document.getElementById('seq-idx');
  function row(seq) {{
    return '<div class="seq-row">' + seq.map(function(e) {{
      return '<span class="seq-icon">' + e + '</span>';
    }}).join('<span class="seq-join">·</span>') + '</div>';
  }}
  function paint() {{
    canvas.innerHTML = row(options[i]);
    lab.textContent = (i + 1) + ' / ' + options.length;
  }}
  document.getElementById('seq-prev').onclick = function() {{
    i = (i - 1 + options.length) % options.length; paint();
  }};
  document.getElementById('seq-next').onclick = function() {{
    i = (i + 1) % options.length; paint();
  }};
  paint();
  window.__logicSync = function() {{
    document.getElementById('captcha-input').value = 'sequence|' + i;
  }};
}})();
"""

        elif kind == "weekday":
            body = f"""
<div class="logic-block">
  <p class="logic-prompt">{esc(self._weekday_question)}</p>
  <label class="logic-label" for="weekday-ans">Answer</label>
  <input type="text" id="weekday-ans" class="logic-text-input" autocomplete="off"
    placeholder="For example: Friday" />
</div>"""
            script = """
(function() {
  window.__logicSync = function() {
    var v = document.getElementById('weekday-ans').value.trim();
    document.getElementById('captcha-input').value = 'weekday|' + v;
  };
})();
"""

        else:
            body = f"""
<div class="logic-block">
  <p class="logic-prompt">Calculate the result of the expression below.</p>
  <div class="logic-arith">{esc(self._arith_expr)} = ?</div>
  <label class="logic-label" for="arith-ans">Answer (integer)</label>
  <input type="text" id="arith-ans" class="logic-text-input" inputmode="numeric" autocomplete="off" />
</div>"""
            script = """
(function() {
  window.__logicSync = function() {
    var v = document.getElementById('arith-ans').value.trim();
    document.getElementById('captcha-input').value = 'arithmetic|' + v;
  };
})();
"""

        styles = """
<style>
.logic-block { margin-bottom: 8px; }
.logic-prompt { font-size: 15px; color: #374151; font-weight: 600; margin: 0 0 12px; line-height: 1.5; }
.logic-hint { font-size: 13px; color: #9ca3af; margin: 0 0 8px; }
.logic-sub { font-size: 13px; color: #6b7280; margin-top: 8px; }
.logic-rotate-wrap { display: flex; align-items: center; justify-content: center; gap: 16px; }
.logic-arrow {
  width: 44px; height: 44px; border-radius: 50%; border: 2px solid #e5e7eb;
  background: #f9fafb; font-size: 20px; cursor: pointer; color: #4b5563;
}
.logic-arrow:hover { border-color: #4f46e5; color: #4f46e5; }
.logic-rotate-ring {
  width: 120px; height: 120px; border-radius: 50%; border: 2px solid #d1d5db;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(180deg,#f3f4f6,#e5e7eb);
  transform-origin: center center;
}
.logic-rotate-char {
  font-size: 42px; font-weight: 800; color: #6b7280; display: inline-block;
  transform-origin: center center;
}
.logic-visual .logic-letter-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
  background: #f3f4f6; padding: 16px; border-radius: 12px; min-height: 140px;
}
.logic-letter {
  font-size: 28px; font-weight: 800; border: none; background: transparent; cursor: pointer;
  padding: 12px; border-radius: 8px; transition: background .15s;
  transform-origin: center center;
}
.logic-letter:hover { background: rgba(79,70,229,0.08); }
.logic-letter.picked { outline: 2px solid #4f46e5; background: rgba(79,70,229,0.12); }
.seq-panels { display: grid; grid-template-columns: 1fr 1.2fr; gap: 16px; align-items: start; }
@media (max-width: 520px) { .seq-panels { grid-template-columns: 1fr; } }
.seq-ref { background: #f9fafb; border-radius: 12px; padding: 12px; border: 1px solid #e5e7eb; }
.seq-ref-title { font-size: 12px; color: #6b7280; margin-bottom: 8px; font-weight: 600; }
.seq-col { display: flex; flex-direction: column; gap: 8px; align-items: center; }
.seq-dot span { font-size: 22px; }
.seq-dot {
  width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  border: 2px solid #a5b4fc; background: #eef2ff;
}
.seq-picker { background: #1f2937; border-radius: 12px; padding: 16px; color: #e5e7eb; }
.seq-canvas { min-height: 56px; display: flex; align-items: center; justify-content: center; }
.seq-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: center; }
.seq-icon { font-size: 24px; }
.seq-join { opacity: 0.5; }
.seq-nav { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 12px; }
.btn-mini {
  width: 36px; height: 36px; border-radius: 50%; border: none; background: #374151; color: #fff;
  cursor: pointer; font-size: 14px;
}
.btn-mini:hover { background: #4f46e5; }
.logic-label { display: block; font-size: 13px; color: #6b7280; margin-bottom: 6px; font-weight: 500; }
.logic-text-input {
  width: 100%; padding: 12px 14px; border: 2px solid #e5e7eb; border-radius: 12px; font-size: 16px;
}
.logic-text-input:focus { border-color: #4f46e5; outline: none; box-shadow: 0 0 0 4px rgba(79,70,229,0.1); }
.logic-arith { font-size: 22px; font-weight: 700; color: #1f2937; margin-bottom: 12px; letter-spacing: 0.02em; }
@media (max-width: 420px) {
  .logic-rotate-wrap { gap: 10px; }
  .logic-rotate-ring { width: 96px; height: 96px; }
  .logic-rotate-char { font-size: 34px; }
  .logic-arrow { width: 40px; height: 40px; }
  .logic-visual .logic-letter-grid { gap: 10px; padding: 12px; min-height: 124px; }
  .logic-letter { font-size: 24px; padding: 8px; }
}
</style>
"""

        return f"""{styles}
{common_hint}
{body}
<input type="hidden" id="captcha-input" name="captcha" value="" />
<script>
{script}
(function() {{
  const form = document.getElementById('captcha-form');
  if (form) {{
    form.addEventListener('submit', function() {{
      if (typeof window.__logicSync === 'function') window.__logicSync();
    }}, true);
  }}
}})();
</script>
"""

    def verify(self, user_input: Any) -> CaptchaResult:
        if not self._generated:
            return CaptchaResult(
                success=False,
                message="Captcha not generated. Please refresh.",
                expected=None,
                received=str(user_input),
            )

        raw = (user_input or "").strip()
        if "|" not in raw:
            return CaptchaResult(
                success=False,
                message="Invalid submission format.",
                expected=self._answer,
                received=raw,
            )

        kind, _, payload = raw.partition("|")
        payload = payload.strip()

        if kind == "rotate":
            return self._verify_rotate(payload)
        if kind == "visual":
            return self._verify_visual(payload)
        if kind == "sequence":
            return self._verify_sequence(payload)
        if kind == "weekday":
            return self._verify_weekday(payload)
        if kind == "arithmetic":
            return self._verify_arithmetic(payload)

        return CaptchaResult(
            success=False,
            message="Unknown challenge kind.",
            expected=self._answer,
            received=raw,
        )

    def _verify_rotate(self, payload: str) -> CaptchaResult:
        try:
            delta = int(payload)
        except ValueError:
            return CaptchaResult(
                success=False,
                message="Please use the rotation controls.",
                expected=self._answer,
                received=payload,
            )
        initial = self._initial_rotation

        ang = (initial + delta) % 360
        ok = ang == 0
        return CaptchaResult(
            success=ok,
            message="Verification successful!" if ok else "The character is not upright yet. Keep rotating it.",
            expected=self._answer,
            received=payload,
        )

    def _verify_visual(self, payload: str) -> CaptchaResult:
        if not payload.isdigit():
            return CaptchaResult(
                success=False,
                message="Please click one letter.",
                expected=self._answer,
                received=payload,
            )
        idx = int(payload)
        ok = idx == self._correct_visual_idx
        return CaptchaResult(
            success=ok,
            message="Verification successful!" if ok else "Incorrect choice.",
            expected=self._answer,
            received=payload,
        )

    def _verify_sequence(self, payload: str) -> CaptchaResult:
        if not payload.isdigit():
            return CaptchaResult(
                success=False,
                message="Please use the arrows to choose one option.",
                expected=self._answer,
                received=payload,
            )
        idx = int(payload)
        ok = idx == self._sequence_correct_idx
        return CaptchaResult(
            success=ok,
            message="Verification successful!" if ok else "The sequence does not match.",
            expected=self._answer,
            received=payload,
        )

    def _verify_weekday(self, payload: str) -> CaptchaResult:
        norm_u = self._normalize_weekday(payload)
        norm_e = self._normalize_weekday(self._weekday_expected)
        ok = norm_u == norm_e and norm_u != ""
        return CaptchaResult(
            success=ok,
            message="Verification successful!" if ok else "Incorrect answer.",
            expected=self._weekday_expected,
            received=payload,
        )

    def _normalize_weekday(self, s: str) -> str:
        s = re.sub(r"\s+", "", s.strip())
        mapping = {
            "monday": "1",
            "tuesday": "2",
            "wednesday": "3",
            "thursday": "4",
            "friday": "5",
            "saturday": "6",
            "sunday": "7",
        }
        low = s.lower()
        if low in mapping:
            return mapping[low]
        if s in mapping:
            return mapping[s]
        cn_keys = sorted(
            [k for k in mapping if k.isascii() is False],
            key=len,
            reverse=True,
        )
        for k in cn_keys:
            if k in s:
                return mapping[k]
        return ""

    def _verify_arithmetic(self, payload: str) -> CaptchaResult:
        try:
            n = int(payload)
        except ValueError:
            return CaptchaResult(
                success=False,
                message="Please enter an integer answer.",
                expected=self._answer,
                received=payload,
            )
        expected = int(self._answer.split("|", 1)[1])
        ok = n == expected
        return CaptchaResult(
            success=ok,
            message="Verification successful!" if ok else "Incorrect calculation result.",
            expected=str(expected),
            received=payload,
        )


if __name__ == "__main__":
    _demo = LogicArithmeticCaptcha()
    _demo.generate()
    print(
        "[logic_arithmetic_captcha] Module loaded successfully. Example challenge:",
        _demo._challenge_kind,
        "| Debug answer:",
        _demo.get_answer(),
    )
    print(
        "[logic_arithmetic_captcha] To start the captcha page, run this from the project root:\n"
        "  python web/captcha/run_logic_arithmetic_server.py --port 8000"
    )
