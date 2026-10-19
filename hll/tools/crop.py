from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

from hll.tools.controller import tap
from hll.tools.base import ToolContext, ToolResult
from hll.tools.registry import ToolRegistry


def _screen_size(context: ToolContext) -> Tuple[int, int]:
    if context.width and context.height:
        return max(int(context.width), 1), max(int(context.height), 1)
    with Image.open(context.screenshot_file) as image:
        w, h = image.size
    return max(w, 1), max(h, 1)


def _clamp_region(
    x1: int, y1: int, x2: int, y2: int, width: int, height: int
) -> Optional[Tuple[int, int, int, int]]:
    x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
    y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2


def _crop_dir(context: ToolContext) -> Path:
    base = getattr(context.env.cfg, "judgement_dir", "judgement")
    out = Path(base) / "tool_crops"
    out.mkdir(parents=True, exist_ok=True)
    return out


def execute_crop_region(action: str, context: ToolContext, match) -> ToolResult:
    width, height = _screen_size(context)
    coords = tuple(int(match.group(name)) for name in ("x1", "y1", "x2", "y2"))
    region = _clamp_region(*coords, width=width, height=height)
    if region is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "crop_region",
            "tool_name": "CropRegion",
            "read_only": True,
            "label": f"CropRegion {coords} (invalid)",
            "prompt_feedback": (
                f"CropRegion received an invalid region {coords} on a "
                f"{width}x{height} screen. Provide x1<x2, y1<y2 within bounds."
            ),
            "error": "invalid_region",
        })

    x1, y1, x2, y2 = region
    image = Image.open(context.screenshot_file).convert("RGB")
    crop = image.crop((x1, y1, x2, y2))
    out_path = _crop_dir(context) / f"crop_{x1}_{y1}_{x2}_{y2}.jpg"
    crop.save(out_path, "JPEG", quality=95)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "crop_region",
        "tool_name": "CropRegion",
        "read_only": True,
        "label": f"CropRegion ({x1}, {y1}, {x2}, {y2})",
        "region": [x1, y1, x2, y2],
        "prompt_image": str(out_path),
        "prompt_feedback": (
            f"A cropped view of region ({x1}, {y1}, {x2}, {y2}) on the "
            f"{width}x{height} screen is attached as the second image. Coordinates "
            "in this crop are relative to its top-left; add the offset to map back "
            "to the full screen."
        ),
    })


def execute_zoom(action: str, context: ToolContext, match) -> ToolResult:
    width, height = _screen_size(context)
    coords = tuple(int(match.group(name)) for name in ("x1", "y1", "x2", "y2"))
    region = _clamp_region(*coords, width=width, height=height)
    if region is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "zoom",
            "tool_name": "Zoom",
            "read_only": True,
            "label": f"Zoom {coords} (invalid)",
            "prompt_feedback": (
                f"Zoom received an invalid region {coords} on a {width}x{height} "
                "screen. Provide x1<x2, y1<y2 within bounds."
            ),
            "error": "invalid_region",
        })

    x1, y1, x2, y2 = region
    image = Image.open(context.screenshot_file).convert("RGB")
    crop = image.crop((x1, y1, x2, y2))

    factor = 2
    target = (min(crop.width * factor, 1600), min(crop.height * factor, 1600))
    zoomed = crop.resize(target, Image.LANCZOS)
    out_path = _crop_dir(context) / f"zoom_{x1}_{y1}_{x2}_{y2}.jpg"
    zoomed.save(out_path, "JPEG", quality=95)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "zoom",
        "tool_name": "Zoom",
        "read_only": True,
        "label": f"Zoom ({x1}, {y1}, {x2}, {y2})",
        "region": [x1, y1, x2, y2],
        "prompt_image": str(out_path),
        "prompt_feedback": (
            f"A magnified view of region ({x1}, {y1}, {x2}, {y2}) is attached as the "
            "second image. It is enlarged for readability; map any coordinates back "
            "to the full screen using the region's top-left offset and the original size."
        ),
    })


def _is_card_pixel(pixel: Tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return min(r, g, b) >= 205


def _largest_component(mask: List[List[bool]]) -> Optional[Tuple[int, int, int, int, int]]:
    if not mask or not mask[0]:
        return None
    height = len(mask)
    width = len(mask[0])
    visited = [[False] * width for _ in range(height)]
    best: Optional[Tuple[int, int, int, int, int]] = None
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
            box = (min_x, min_y, max_x + 1, max_y + 1, count)
            if best is None or count > best[4]:
                best = box
    return best


def locate_captcha_area(screenshot_file: str) -> Optional[Tuple[int, int, int, int]]:
    path = Path(screenshot_file)
    if not path.exists():
        return None
    image = Image.open(path).convert("RGB")
    image_width, image_height = image.size
    max_dim = 360
    scale = min(1.0, max_dim / float(max(image_width, image_height)))
    scan = image.resize((max(1, int(image_width * scale)), max(1, int(image_height * scale))))
    sw, sh = scan.size
    pixels = scan.load()
    mask = [[_is_card_pixel(pixels[x, y]) for x in range(sw)] for y in range(sh)]
    best = _largest_component(mask)
    if best is None:
        return None
    x1, y1, x2, y2, count = best

    if count < (sw * sh) * 0.05:
        return None
    inv = 1.0 / scale
    return (
        max(0, int(round(x1 * inv))),
        max(0, int(round(y1 * inv))),
        min(image_width, int(round(x2 * inv))),
        min(image_height, int(round(y2 * inv))),
    )


def execute_locate_captcha_area(action: str, context: ToolContext, match) -> ToolResult:
    region = locate_captcha_area(context.screenshot_file)
    if region is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "locate_captcha_area",
            "tool_name": "LocateCaptchaArea",
            "read_only": True,
            "label": "LocateCaptchaArea (not found)",
            "prompt_feedback": (
                "Could not confidently locate a captcha card region. Use the full "
                "screenshot and judge the real verification area visually."
            ),
            "error": "not_found",
        })
    x1, y1, x2, y2 = region
    image = Image.open(context.screenshot_file).convert("RGB")
    crop = image.crop((x1, y1, x2, y2))
    out_path = _crop_dir(context) / f"captcha_area_{x1}_{y1}_{x2}_{y2}.jpg"
    crop.save(out_path, "JPEG", quality=95)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "locate_captcha_area",
        "tool_name": "LocateCaptchaArea",
        "read_only": True,
        "label": f"LocateCaptchaArea -> ({x1}, {y1}, {x2}, {y2})",
        "region": [x1, y1, x2, y2],
        "prompt_image": str(out_path),
        "prompt_feedback": (
            f"The real captcha card region is approximately ({x1}, {y1}, {x2}, {y2}). "
            "A crop of it is attached as the second image. Focus interactions inside "
            "this region and ignore decoy elements outside it."
        ),
    })


def execute_tap_region_center(action: str, context: ToolContext, match) -> ToolResult:

    width, height = _screen_size(context)
    coords = tuple(int(match.group(name)) for name in ("x1", "y1", "x2", "y2"))
    region = _clamp_region(*coords, width=width, height=height)
    if region is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "tap", "tool_name": "TapRegionCenter",
            "label": f"TapRegionCenter {coords} (invalid)",
            "error": "invalid_region",
        })
    x1, y1, x2, y2 = region
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    tap(context.env.cfg.adb_path, cx, cy)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "tap", "tool_name": "TapRegionCenter",
        "label": f"TapRegionCenter ({x1},{y1},{x2},{y2}) -> Tap ({cx}, {cy})",
        "point": [cx, cy], "region": [x1, y1, x2, y2],
    })


def register_crop_tools(registry: ToolRegistry) -> None:
    region_args = r"\(\s*(?P<x1>\d+)\s*,\s*(?P<y1>\d+)\s*,\s*(?P<x2>\d+)\s*,\s*(?P<y2>\d+)\s*\)"
    registry.register(
        name="CropRegion",
        pattern=r"CropRegion\s*" + region_args,
        handler=execute_crop_region,
        read_only=True,
        description=(
            "CropRegion(x1, y1, x2, y2): get a cropped view of a screen region as an "
            "extra image next step. Read-only; use it to inspect small content closely."
        ),
    )
    registry.register(
        name="TapRegionCenter",
        pattern=r"TapRegionCenter\s*" + region_args,
        handler=execute_tap_region_center,
        description=(
            "TapRegionCenter(x1, y1, x2, y2): tap the center of a region. Use it to act on "
            "a region you located (select a candidate, click a target, pick a board cell)."
        ),
    )
    registry.register(
        name="Zoom",
        pattern=r"Zoom\s*" + region_args,
        handler=execute_zoom,
        read_only=True,
        description=(
            "Zoom(x1, y1, x2, y2): get a magnified view of a screen region as an extra "
            "image next step. Read-only; use it when text or markers are too small to read."
        ),
    )
    registry.register(
        name="LocateCaptchaArea",
        pattern=r"LocateCaptchaArea\s*(?:\(\s*\))?",
        handler=execute_locate_captcha_area,
        read_only=True,
        description=(
            "LocateCaptchaArea(): find the real captcha card region and return its "
            "bounding box plus a crop. Read-only; use it to ignore decoy page elements."
        ),
    )
