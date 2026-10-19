from __future__ import annotations

from collections import deque
from typing import List, Optional, Tuple

from PIL import Image

from hll.tools.controller import back, ime_shown, tap, type_text
from hll.tools.base import ToolContext, ToolResult
from hll.tools.crop import locate_captcha_area
from hll.tools.registry import ToolRegistry


def _screen_size(context: ToolContext) -> Tuple[int, int]:
    if context.width and context.height:
        return max(int(context.width), 1), max(int(context.height), 1)
    with Image.open(context.screenshot_file) as image:
        return max(image.width, 1), max(image.height, 1)


def _clamp_point(x: int, y: int, width: int, height: int) -> Tuple[int, int]:
    return max(0, min(int(x), width - 1)), max(0, min(int(y), height - 1))


def execute_tap_point(action: str, context: ToolContext, match) -> ToolResult:
    width, height = _screen_size(context)
    x, y = _clamp_point(int(match.group("x")), int(match.group("y")), width, height)
    tap(context.env.cfg.adb_path, x, y)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "tap",
        "tool_name": "TapPoint",
        "label": f"TapPoint ({x}, {y})",
        "point": [x, y],
    })


def execute_type_text(action: str, context: ToolContext, match) -> ToolResult:
    text = (match.group("text") or "").strip()
    type_text(context.env.cfg.adb_path, text)
    exec_info = {
        "action_type": "type",
        "tool_name": "TypeText",
        "label": "TypeText",
        "text": text,
    }
    try:
        if ime_shown(context.env.cfg.adb_path):
            back(context.env.cfg.adb_path)
            exec_info["keyboard_dismissed"] = True
    except Exception:
        pass
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def _is_input_border(pixel: Tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return 200 <= r <= 245 and 200 <= g <= 245 and 200 <= b <= 248 and max(pixel) - min(pixel) <= 18


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
                min_x, max_x = min(min_x, cx), max(max_x, cx)
                min_y, max_y = min(min_y, cy), max(max_y, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny][nx] and not visited[ny][nx]:
                        visited[ny][nx] = True
                        queue.append((nx, ny))
            boxes.append((min_x, min_y, max_x + 1, max_y + 1, count))
    return boxes


def locate_text_input(screenshot_file: str) -> Tuple[Tuple[int, int, int, int], str]:

    image = Image.open(screenshot_file).convert("RGB")
    width, height = image.size
    card = locate_captcha_area(screenshot_file) or (
        int(width * 0.08),
        int(height * 0.18),
        int(width * 0.92),
        int(height * 0.88),
    )
    x1, y1, x2, y2 = card
    crop = image.crop(card)
    scale = min(1.0, 360 / float(max(crop.width, crop.height)))
    scan = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))))
    pixels = scan.load()
    mask = [[_is_input_border(pixels[x, y]) for x in range(scan.width)] for y in range(scan.height)]
    candidates = []
    for bx1, by1, bx2, by2, count in _component_boxes(mask):
        bw = bx2 - bx1
        bh = by2 - by1
        if bw < scan.width * 0.35 or not (12 <= bh <= scan.height * 0.20):
            continue
        if by1 < scan.height * 0.25:
            continue
        fill = count / float(max(1, bw * bh))
        if fill > 0.75:
            continue
        score = bw * bh * (1.0 + by1 / max(1, scan.height))
        candidates.append((score, (bx1, by1, bx2, by2)))
    if candidates:
        _, box = max(candidates, key=lambda item: item[0])
        inv = 1.0 / scale
        lx1, ly1, lx2, ly2 = box
        return (
            max(0, int(round(x1 + lx1 * inv))),
            max(0, int(round(y1 + ly1 * inv))),
            min(width - 1, int(round(x1 + lx2 * inv))),
            min(height - 1, int(round(y1 + ly2 * inv))),
        ), "detected"


    cw = x2 - x1
    ch = y2 - y1
    return (
        int(x1 + cw * 0.12),
        int(y1 + ch * 0.58),
        int(x2 - cw * 0.12),
        int(y1 + ch * 0.70),
    ), "estimated"


def execute_input_captcha_text(action: str, context: ToolContext, match) -> ToolResult:
    text = (match.group("text") or "").strip()
    width, height = _screen_size(context)
    bbox, method = locate_text_input(context.screenshot_file)
    x1, y1, x2, y2 = bbox
    cx, cy = _clamp_point((x1 + x2) // 2, (y1 + y2) // 2, width, height)
    tap(context.env.cfg.adb_path, cx, cy)
    type_text(context.env.cfg.adb_path, text)
    exec_info = {
        "action_type": "input_captcha_text",
        "tool_name": "InputCaptchaText",
        "label": f"InputCaptchaText -> Tap ({cx}, {cy}) + type",
        "point": [cx, cy],
        "input_bbox": [x1, y1, x2, y2],
        "input_locator": method,
        "text": text,
    }
    try:
        if ime_shown(context.env.cfg.adb_path):
            back(context.env.cfg.adb_path)
            exec_info["keyboard_dismissed"] = True
    except Exception:
        pass
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def register_action_tools(registry: ToolRegistry) -> None:
    registry.register(
        name="TapPoint",
        pattern=r"TapPoint\s*\(\s*(?P<x>-?\d+)\s*,\s*(?P<y>-?\d+)\s*\)",
        handler=execute_tap_point,
        description=(
            "TapPoint(x, y): tap one absolute screen point with bounds clamping. "
            "Use structured tools first when available."
        ),
    )
    registry.register(
        name="TypeText",
        pattern=r"TypeText\s*<text>(?P<text>.*?)</text>",
        handler=execute_type_text,
        description=(
            "TypeText <text>(value)</text>: type text into the currently focused field. "
            "Use InputCaptchaText when the field is not focused."
        ),
    )
    registry.register(
        name="InputCaptchaText",
        pattern=r"InputCaptchaText\s*<text>(?P<text>.*?)</text>",
        handler=execute_input_captcha_text,
        description=(
            "InputCaptchaText <text>(value)</text>: locate the main captcha text input, "
            "focus it, and type the value in one action."
        ),
    )
