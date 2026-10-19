from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

from hll.tools.controller import swipe, tap
from hll.tools.base import ToolContext, ToolResult
from hll.tools.registry import ToolRegistry


@dataclass
class ButtonGeometry:
    bbox: Tuple[int, int, int, int]

    def center(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bbox
        return int(round((x1 + x2) / 2.0)), int(round((y1 + y2) / 2.0))


def _is_verify_button_pixel(pixel: Tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return 45 <= r <= 110 and 35 <= g <= 115 and b >= 145 and b >= r + 55 and b >= g + 55


def _component_boxes(mask: List[List[bool]]) -> List[Tuple[int, int, int, int, int]]:
    if not mask or not mask[0]:
        return []

    height = len(mask)
    width = len(mask[0])
    visited = [[False] * width for _ in range(height)]
    boxes: List[Tuple[int, int, int, int, int]] = []

    for y in range(height):
        for x in range(width):
            if not mask[y][x] or visited[y][x]:
                continue

            queue = deque([(x, y)])
            visited[y][x] = True
            min_x = max_x = x
            min_y = max_y = y
            count = 0

            while queue:
                cx, cy = queue.popleft()
                count += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)

                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny][nx] and not visited[ny][nx]:
                        visited[ny][nx] = True
                        queue.append((nx, ny))

            boxes.append((min_x, min_y, max_x + 1, max_y + 1, count))

    return boxes


def _score_button_candidate(
    box: Tuple[int, int, int, int, int],
    width: int,
    height: int,
) -> float:
    x1, y1, x2, y2, count = box
    box_w = x2 - x1
    box_h = y2 - y1
    if box_w < width * 0.12 or box_h < height * 0.025:
        return 0.0
    ratio = box_w / float(max(box_h, 1))
    if ratio < 1.8 or ratio > 8.0:
        return 0.0
    center_y = (y1 + y2) / 2.0
    if center_y < height * 0.45:
        return 0.0
    fill = count / float(box_w * box_h)
    if fill < 0.35:
        return 0.0
    left_preference = 1.0 if (x1 + x2) / 2.0 < width * 0.55 else 0.65
    return count * left_preference


def locate_verify_button(screenshot_file: str) -> Optional[ButtonGeometry]:
    path = Path(screenshot_file)
    if not path.exists():
        raise FileNotFoundError(f"Screenshot not found: {screenshot_file}")

    image = Image.open(path).convert("RGB")
    image_width, image_height = image.size
    max_dim = 420
    scale = min(1.0, max_dim / float(max(image_width, image_height)))
    scan = image.resize((max(1, int(image_width * scale)), max(1, int(image_height * scale))))
    scan_width, scan_height = scan.size
    pixels = scan.load()

    mask: List[List[bool]] = []
    for y in range(scan_height):
        row: List[bool] = []
        for x in range(scan_width):
            row.append(_is_verify_button_pixel(pixels[x, y]))
        mask.append(row)

    scored = [
        (_score_button_candidate(box, scan_width, scan_height), box)
        for box in _component_boxes(mask)
    ]
    scored = [(score, box) for score, box in scored if score > 0]
    if not scored:
        return None

    _, best = max(scored, key=lambda item: item[0])
    x1, y1, x2, y2, _ = best
    inv = 1.0 / scale
    bbox = (
        max(0, int(round(x1 * inv))),
        max(0, int(round(y1 * inv))),
        min(image_width - 1, int(round(x2 * inv))),
        min(image_height - 1, int(round(y2 * inv))),
    )
    return ButtonGeometry(bbox)


def execute_submit_captcha(action: str, context: ToolContext, match) -> ToolResult:
    geometry = locate_verify_button(context.screenshot_file)
    if context.width and context.height:
        screen_width = int(context.width)
        screen_height = int(context.height)
    else:
        with Image.open(context.screenshot_file) as image:
            screen_width, screen_height = image.size
    screen_width = max(screen_width, 1)
    screen_height = max(screen_height, 1)

    if geometry is None:
        x = screen_width // 2
        start_y = int(screen_height * 0.82)
        end_y = int(screen_height * 0.28)
        moved = swipe(context.env.cfg.adb_path, x, start_y, x, end_y, 650)
        exec_info = {
            "action_type": "scroll",
            "tool_name": "SubmitCaptcha",
            "label": "SubmitCaptcha deferred: Verify button is not visible; scrolled down",
            "state_changed": moved,
            "deferred_submit": True,
            "deferred_reason": "verify_button_not_visible_scrolled",
            "verification_action": False,
            "prompt_feedback": (
                "The Verify button was not visible, so the page was scrolled down. "
                "Inspect the new screenshot and call SubmitCaptcha again once the real "
                "Verify button is visible."
            ),
        }
        if not moved:
            exec_info["error"] = "scroll_failed"
            exec_info["recoverable"] = True
        return ToolResult(handled=True, keep_running=True, exec_info=exec_info)

    x, y = geometry.center()
    x = max(0, min(x, screen_width - 1))
    y = max(0, min(y, screen_height - 1))

    tap(context.env.cfg.adb_path, x, y)

    exec_info = {
        "action_type": "tap",
        "tool_name": "SubmitCaptcha",
        "label": f"SubmitCaptcha -> Tap ({x}, {y})",
        "point": [x, y],
        "button_label": "Verify",
        "button_bbox": list(geometry.bbox),
        "mapped_point": [x, y],
    }
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def register_submit_tools(registry: ToolRegistry) -> None:
    registry.register(
        name="SubmitCaptcha",
        pattern=r"(?:SubmitCaptcha|VerifyCaptcha)\s*(?:\(\s*\))?",
        handler=execute_submit_captcha,
        description=(
            "SubmitCaptcha(): click the captcha Verify button. Use this instead of "
            "estimating pixel coordinates for the Verify button."
        ),
    )
