from __future__ import annotations

from typing import Any, Dict, List

from .click_real_captcha import ClickRealCaptcha
from .dynamic_captcha import DynamicCaptchaMixin


class ClickRealDynamicCaptcha(DynamicCaptchaMixin, ClickRealCaptcha):
    dynamic_type = "click_real_dynamic"

    def build_dynamic_script(self) -> str:
        return """
  const container = document.querySelector('.click-image-container');
  const clearBtn = document.getElementById('clear-clicks');
  const input = document.getElementById('captcha-input');
  if (!container || !input) return;

  container.addEventListener('click', function(evt) {
    const rect = container.getBoundingClientRect();
    const scaleX = container.dataset.nominalWidth
      ? parseFloat(container.dataset.nominalWidth) / rect.width
      : 1.0;
    const scaleY = container.dataset.nominalHeight
      ? parseFloat(container.dataset.nominalHeight) / rect.height
      : 1.0;
    const localX = (evt.clientX - rect.left) * scaleX;
    const localY = (evt.clientY - rect.top) * scaleY;
    const nextCount = String(input.value || '').split(';').filter(Boolean).length;
    record('target_click', {
      x: localX,
      y: localY,
      clickCount: nextCount,
    });
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', function() {
      record('clear_clicks', {});
    });
  }
"""

    def verify_behavior(self, answer: str, telemetry: List[Dict[str, Any]]):
        target_clicks = self._events_of_type(telemetry, "target_click")
        clears = self._events_of_type(telemetry, "clear_clicks")
        duration_ms = self._event_duration_ms(telemetry)

        if len(target_clicks) < self.click_count:
            return self._behavior_fail(
                "Dynamic check failed: not enough click interactions were recorded.",
                telemetry,
                click_events=len(target_clicks),
            )

        coords = {
            (round(float(event.get("x", 0.0)), 1), round(float(event.get("y", 0.0)), 1))
            for event in target_clicks
        }
        if len(coords) < self.click_count:
            return self._behavior_fail(
                "Dynamic check failed: repeated click positions were too similar.",
                telemetry,
                unique_positions=len(coords),
            )

        target_chars = getattr(self, "_target_chars", None)
        if target_chars and len(target_clicks) >= 3 and len(target_chars) >= 3:
            rel_offsets = []
            char_radius = 25.0
            for i, click in enumerate(target_clicks[:len(target_chars)]):
                click_x = float(click.get("x", 0.0))
                click_y = float(click.get("y", 0.0))
                target = target_chars[i]
                target_x = float(target.get("x", 0.0))
                target_y = float(target.get("y", 0.0))
                rel_x = (click_x - target_x) / char_radius
                rel_y = (click_y - target_y) / char_radius
                rel_offsets.append((rel_x, rel_y))

            if len(rel_offsets) >= 3:
                x_vals = [o[0] for o in rel_offsets]
                y_vals = [o[1] for o in rel_offsets]
                x_mean = sum(x_vals) / len(x_vals)
                y_mean = sum(y_vals) / len(y_vals)
                x_var = sum((v - x_mean) ** 2 for v in x_vals) / len(x_vals)
                y_var = sum((v - y_mean) ** 2 for v in y_vals) / len(y_vals)

                if x_var < 0.005 and y_var < 0.005:
                    return self._behavior_fail(
                        "Dynamic check failed: click offset pattern relative to targets is unnaturally consistent.",
                        telemetry,
                        x_variance=round(x_var, 6),
                        y_variance=round(y_var, 6),
                    )

        return self._behavior_pass(
            telemetry,
            click_events=len(target_clicks),
            clear_events=len(clears),
            duration_ms=duration_ms,
        )
