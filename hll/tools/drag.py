from __future__ import annotations

import re
import subprocess
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageStat

from hll.tools.api import inference_chat
from hll.tools.chat import add_response, init_action_chat
from hll.tools.base import ToolContext, ToolResult
from hll.tools.crop import locate_captcha_area
from hll.tools.registry import ToolRegistry

# Convert nominal image coordinates into screen-space handle movement.


_NOMINAL_IMAGE_WIDTH = 300
_NOMINAL_SLIDER_SIZE = 40
_MAX_PIECE_X = _NOMINAL_IMAGE_WIDTH - _NOMINAL_SLIDER_SIZE


def _swipe(adb_path: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 800) -> bool:

    result = subprocess.run(
        f"{adb_path} shell input swipe {x1} {y1} {x2} {y2} {duration_ms}",
        shell=True,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def execute_drag(action: str, context: ToolContext, match) -> ToolResult:
    x1, y1, x2, y2 = (int(match.group(n)) for n in ("x1", "y1", "x2", "y2"))
    width = max(int(context.width or 0), 1)
    height = max(int(context.height or 0), 1)
    clamp = lambda v, hi: max(0, min(v, hi - 1))
    x1, x2 = clamp(x1, width), clamp(x2, width)
    y1, y2 = clamp(y1, height), clamp(y2, height)
    _swipe(context.env.cfg.adb_path, x1, y1, x2, y2)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "swipe",
        "tool_name": "Drag",
        "label": f"Drag ({x1}, {y1}) -> ({x2}, {y2})",
        "start": [x1, y1],
        "end": [x2, y2],
    })


def execute_drag_by(action: str, context: ToolContext, match) -> ToolResult:
    x1, y1, dx, dy = (int(match.group(n)) for n in ("x", "y", "dx", "dy"))
    width = max(int(context.width or 0), 1)
    height = max(int(context.height or 0), 1)
    clamp = lambda v, hi: max(0, min(v, hi - 1))
    x1, y1 = clamp(x1, width), clamp(y1, height)
    x2, y2 = clamp(x1 + dx, width), clamp(y1 + dy, height)
    _swipe(context.env.cfg.adb_path, x1, y1, x2, y2)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "swipe",
        "tool_name": "DragBy",
        "label": f"DragBy ({x1}, {y1}) + ({dx}, {dy}) -> ({x2}, {y2})",
        "start": [x1, y1],
        "delta": [dx, dy],
        "end": [x2, y2],
    })


def _nearwhite(p: Tuple[int, int, int]) -> bool:
    return min(p) >= 225


def _is_grey_track(p: Tuple[int, int, int]) -> bool:
    r, g, b = p
    return 232 <= r <= 250 and 233 <= g <= 250 and 235 <= b <= 252 and (max(p) - min(p)) <= 8


def _is_photo_content(p: Tuple[int, int, int]) -> bool:
    return min(p) < 215 or max(p) - min(p) > 30


def _row_blocks(rows: List[Tuple[int, bool]]) -> List[Tuple[int, int]]:
    blocks: List[Tuple[int, int]] = []
    start: Optional[int] = None
    end: Optional[int] = None
    for y, enabled in rows:
        if enabled:
            if start is None:
                start = y
            end = y
        elif start is not None and end is not None:
            blocks.append((start, end))
            start = end = None
    if start is not None and end is not None:
        blocks.append((start, end))
    return blocks


def _photo_region(px, card: Tuple[int, int, int, int]) -> Optional[Tuple[int, int, int, int]]:
    """Select the largest wide image region to exclude page decorations."""
    cx1, cy1, cx2, cy2 = card
    span = max(1, (cx2 - cx1) // 3)
    rows = [
        (
            y,
            sum(1 for x in range(cx1, cx2, 3) if not _nearwhite(px[x, y]))
            > span * 0.5,
        )
        for y in range(cy1, cy2)
    ]
    min_height = max(48, int((cy2 - cy1) * 0.08))
    candidates: List[Tuple[int, Tuple[int, int, int, int]]] = []
    for iy0, iy1 in _row_blocks(rows):
        block_h = iy1 - iy0 + 1
        if block_h < min_height:
            continue
        col_samples = max(1, len(range(iy0, iy1 + 1, 4)))
        col_blocks = _row_blocks(
            [
                (
                    x,
                    sum(
                        1
                        for y in range(iy0, iy1 + 1, 4)
                        if _is_photo_content(px[x, y])
                    )
                    > col_samples * 0.4,
                )
                for x in range(cx1, cx2)
            ]
        )
        if not col_blocks:
            continue
        im_left, im_right = max(col_blocks, key=lambda block: block[1] - block[0])
        block_w = im_right - im_left + 1
        if block_w < max(160, int((cx2 - cx1) * 0.35)):
            continue
        candidates.append((block_w * block_h, (im_left, iy0, im_right, iy1)))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _track_band(
    px,
    card: Tuple[int, int, int, int],
    photo: Tuple[int, int, int, int],
) -> Optional[Tuple[int, int, int, int]]:

    cx1, cy1, cx2, cy2 = card
    im_left, _, im_right, photo_bottom = photo
    sample_width = max(1, (im_right - im_left + 1) // 3)
    rows = [
        (
            y,
            sum(1 for x in range(im_left, im_right + 1, 3) if _is_grey_track(px[x, y]))
            > sample_width * 0.4,
        )
        for y in range(photo_bottom + 1, cy2)
    ]
    min_height = max(24, int((cy2 - cy1) * 0.025))
    for ty0, ty1 in _row_blocks(rows):
        if ty1 - ty0 + 1 < min_height:
            continue
        return im_left, ty0, im_right, ty1
    return None


def _valid_slider_geometry(
    card: Tuple[int, int, int, int],
    photo: Tuple[int, int, int, int],
    track: Tuple[int, int, int, int],
) -> bool:
    cx1, cy1, cx2, cy2 = card
    im_left, iy0, im_right, iy1 = photo
    track_left, ty0, track_right, ty1 = track
    card_w = max(1, cx2 - cx1)
    card_h = max(1, cy2 - cy1)
    photo_w = im_right - im_left + 1
    photo_h = iy1 - iy0 + 1
    track_w = track_right - track_left + 1
    track_h = ty1 - ty0 + 1
    track_inner = track_w - track_h
    return all(
        (
            photo_w >= max(160, int(card_w * 0.35)),
            photo_h >= max(60, int(card_h * 0.08)),
            photo_w >= int(photo_h * 1.2),
            ty0 > iy1,
            20 <= track_h <= max(20, int(photo_h * 0.6)),
            track_w >= int(photo_w * 0.8),
            track_inner >= max(60, int(photo_w * 0.12)),
        )
    )


def _slider_geometry(screenshot_file: str):
    card = locate_captcha_area(screenshot_file)
    if card is None:
        return None
    image = Image.open(screenshot_file).convert("RGB")
    px = image.load()
    photo = _photo_region(px, card)
    if photo is None:
        return None
    track = _track_band(px, card, photo)
    if track is None or not _valid_slider_geometry(card, photo, track):
        return None
    return {"card": card, "photo": photo, "track": track, "image": image}


def execute_locate_slider_handle(action: str, context: ToolContext, match) -> ToolResult:
    geo = _slider_geometry(context.screenshot_file)
    if geo is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "locate_slider_handle", "tool_name": "LocateSliderHandle",
            "read_only": True, "label": "LocateSliderHandle (not found)",
            "prompt_feedback": "Could not locate the slider track/handle from the screenshot.",
            "error": "not_found",
        })
    tL, ty0, tR, ty1 = geo["track"]
    handle_w = ty1 - ty0
    hx = tL + handle_w // 2
    hy = (ty0 + ty1) // 2
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "locate_slider_handle", "tool_name": "LocateSliderHandle",
        "read_only": True,
        "label": f"LocateSliderHandle -> handle≈({hx},{hy}), track=({tL},{tR})",
        "track_bbox": [tL, ty0, tR, ty1], "handle_center": [hx, hy],
        "prompt_feedback": (
            f"The slider handle is at approximately ({hx}, {hy}); the draggable track "
            f"spans x={tL}..{tR} at y≈{hy}. Drag the handle rightward along this track."
        ),
    })


def execute_locate_slider_track(action: str, context: ToolContext, match) -> ToolResult:
    geo = _slider_geometry(context.screenshot_file)
    if geo is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "locate_slider_track", "tool_name": "LocateSliderTrack",
            "read_only": True, "label": "LocateSliderTrack (not found)",
            "prompt_feedback": "Could not locate the slider photo/track from the screenshot.",
            "error": "not_found",
        })
    tL, ty0, tR, ty1 = geo["track"]
    imL, iy0, imR, iy1 = geo["photo"]
    hy = (ty0 + ty1) // 2
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "locate_slider_track", "tool_name": "LocateSliderTrack",
        "read_only": True,
        "label": f"LocateSliderTrack -> track=({tL},{ty0},{tR},{ty1})",
        "track_bbox": [tL, ty0, tR, ty1],
        "track_center_y": hy,
        "photo_bbox": [imL, iy0, imR, iy1],
        "prompt_feedback": (
            f"The slider track is approximately ({tL}, {ty0}, {tR}, {ty1}), with center y≈{hy}. "
            f"The slider image/photo is approximately ({imL}, {iy0}, {imR}, {iy1})."
        ),
    })


def _vlm_gap_fraction(context: ToolContext, crop_path: str) -> Optional[float]:
    cfg = context.env.cfg
    prompt = (
        "This image is the background of a slider puzzle captcha. A puzzle piece must "
        "slide horizontally to fill a notch/gap — a faint darkened square 'hole' in the "
        "image. Ignore the movable piece at the far-left edge. Report ONLY the horizontal "
        "center of the gap as a decimal fraction between 0 and 1 (0=left edge, 1=right "
        "edge). Answer with just the number, e.g. 0.62."
    )
    try:
        chat = init_action_chat()
        chat = add_response("user", prompt, chat, crop_path)
        out = inference_chat(chat, cfg.caption_model, cfg.API_url, cfg.token)
    except Exception:
        return None
    m = re.search(r"(0?\.\d+|0|1(?:\.0+)?)", out or "")
    if not m:
        return None
    try:
        frac = float(m.group(1))
    except ValueError:
        return None
    return max(0.0, min(1.0, frac))


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


def _is_gap_overlay_pixel(pixel: Tuple[int, int, int]) -> bool:
    r, g, b = pixel
    mean = (r + g + b) / 3.0
    return 70 <= mean <= 230 and max(pixel) - min(pixel) <= 46


def _heuristic_gap_fraction(photo: Image.Image) -> Optional[Dict[str, object]]:
    """Accept only confident square gaps; ambiguous images require model fallback."""
    image = photo.convert("RGB")
    width, height = image.size
    if width < 20 or height < 20:
        return None

    window = _heuristic_gap_window(image)

    max_dim = 420
    scale = min(1.0, max_dim / float(max(width, height)))
    scan = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
    pixels = scan.load()
    mask = [
        [_is_gap_overlay_pixel(pixels[x, y]) for x in range(scan.width)]
        for y in range(scan.height)
    ]

    candidates: List[Tuple[float, Tuple[int, int, int, int, int]]] = []
    min_side = max(8, int(min(scan.width, scan.height) * 0.08))
    max_side = max(min_side + 1, int(min(scan.width, scan.height) * 0.42))
    for box in _component_boxes(mask):
        x1, y1, x2, y2, count = box
        box_w = x2 - x1
        box_h = y2 - y1
        if box_w < min_side or box_h < min_side or box_w > max_side or box_h > max_side:
            continue
        if x1 < scan.width * 0.18:
            continue
        ratio = box_w / float(max(1, box_h))
        if not 0.62 <= ratio <= 1.62:
            continue
        fill = count / float(max(1, box_w * box_h))
        if fill < 0.48:
            continue
        area_score = min(box_w * box_h / float(scan.width * scan.height), 0.08) / 0.08
        square_score = 1.0 - min(abs(1.0 - ratio), 0.6)
        score = fill * 2.0 + square_score + area_score
        candidates.append((score, box))

    component_result: Optional[Dict[str, object]] = None
    if candidates:
        score, best = max(candidates, key=lambda item: item[0])
        x1, y1, x2, y2, _ = best
        inv = 1.0 / scale
        bbox = [
            max(0, int(round(x1 * inv))),
            max(0, int(round(y1 * inv))),
            min(width, int(round(x2 * inv))),
            min(height, int(round(y2 * inv))),
        ]
        center_x = (bbox[0] + bbox[2]) / 2.0
        confidence = max(0.0, min(1.0, score / 4.0))
        component_result = {
            "fraction": max(0.0, min(1.0, center_x / float(max(1, width)))),
            "bbox": bbox,
            "confidence": round(confidence, 3),
            "detector": "component",
        }

    if window and component_result:
        return window if float(window["confidence"]) >= float(component_result["confidence"]) else component_result
    return window or component_result


def _heuristic_gap_window(image: Image.Image) -> Optional[Dict[str, object]]:
    width, height = image.size
    gray = image.convert("L")
    best: Optional[Tuple[float, int, int, int, float, float, float]] = None
    for frac in (0.10, 0.12, 0.14, 0.16, 0.18):
        size = max(12, int(width * frac))
        if size >= min(width, height):
            continue
        step = max(8, size // 5)
        margin = max(8, size // 4)
        for y in range(int(height * 0.08), max(int(height * 0.08), height - size - int(height * 0.05)), step):
            for x in range(int(width * 0.18), max(int(width * 0.18), width - size - int(width * 0.04)), step):
                inside = gray.crop((x, y, x + size, y + size))
                ring = gray.crop((
                    max(0, x - margin),
                    max(0, y - margin),
                    min(width, x + size + margin),
                    min(height, y + size + margin),
                ))
                inside_stat = ImageStat.Stat(inside)
                ring_stat = ImageStat.Stat(ring)
                inside_mean = float(inside_stat.mean[0])
                ring_mean = float(ring_stat.mean[0])
                inside_std = float(inside_stat.stddev[0])
                darkness_delta = ring_mean - inside_mean
                if darkness_delta <= 8:
                    continue
                compact_bonus = max(0.0, 40.0 - inside_std) * 0.1
                score = darkness_delta + compact_bonus
                if best is None or score > best[0]:
                    best = (score, x, y, size, inside_mean, ring_mean, inside_std)
    if best is None:
        return None

    score, x, y, size, inside_mean, ring_mean, inside_std = best
    confidence = max(0.0, min(1.0, score / 45.0))
    return {
        "fraction": max(0.0, min(1.0, (x + size / 2.0) / float(max(1, width)))),
        "bbox": [x, y, x + size, y + size],
        "confidence": round(confidence, 3),
        "detector": "window_contrast",
        "inside_mean": round(inside_mean, 2),
        "ring_mean": round(ring_mean, 2),
        "inside_std": round(inside_std, 2),
    }


def _read_gap_fraction(context: ToolContext, crop_path: str) -> Optional[Dict[str, object]]:
    photo = Image.open(crop_path).convert("RGB")
    heuristic = _heuristic_gap_fraction(photo)
    if heuristic is not None and float(heuristic.get("confidence", 0.0)) >= 0.55:
        heuristic["method"] = "local_heuristic"
        return heuristic

    gap_frac = _vlm_gap_fraction(context, crop_path)
    if gap_frac is not None:
        return {"fraction": gap_frac, "method": "vlm", "confidence": None}

    if heuristic is not None:
        heuristic["method"] = "local_heuristic_low_confidence"
        return heuristic
    return None


def _save_gap_overlay(photo: Image.Image, crop_path: str, gap_info: Dict[str, object]) -> str:
    bbox = gap_info.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return crop_path
    overlay = photo.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(tuple(int(v) for v in bbox), outline=(255, 0, 0), width=3)
    path = Path(crop_path).with_name(Path(crop_path).stem + "_gap_overlay.jpg")
    overlay.save(path, "JPEG", quality=95)
    return str(path)


def execute_locate_gap(action: str, context: ToolContext, match) -> ToolResult:
    geo = _slider_geometry(context.screenshot_file)
    if geo is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "locate_gap", "tool_name": "LocateGap",
            "read_only": True, "label": "LocateGap (geometry not found)",
            "prompt_feedback": "Could not locate the slider image/track to find the gap.",
            "error": "geometry_not_found",
        })
    imL, iy0, imR, iy1 = geo["photo"]
    crop_dir = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_path = str(crop_dir / "slider_gap_photo.jpg")
    photo = geo["image"].crop((imL, iy0, imR, iy1))
    photo.save(crop_path, "JPEG", quality=95)
    gap_info = _read_gap_fraction(context, crop_path)
    if gap_info is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "locate_gap", "tool_name": "LocateGap",
            "read_only": True, "label": "LocateGap (gap read failed)",
            "prompt_image": crop_path,
            "prompt_feedback": "Could not read the gap position. Inspect the attached slider image manually.",
            "error": "gap_read_failed",
        })
    gap_frac = float(gap_info["fraction"])
    prompt_image = _save_gap_overlay(photo, crop_path, gap_info)
    gap_x = int(round(imL + gap_frac * max(1, imR - imL)))
    gap_y = int(round((iy0 + iy1) / 2))
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "locate_gap", "tool_name": "LocateGap",
        "read_only": True,
        "label": f"LocateGap -> ({gap_x}, {gap_y}) frac={gap_frac:.2f}",
        "gap_fraction": round(gap_frac, 3),
        "gap_method": gap_info.get("method"),
        "gap_confidence": gap_info.get("confidence"),
        "gap_bbox_in_crop": gap_info.get("bbox"),
        "gap_point": [gap_x, gap_y],
        "photo_bbox": [imL, iy0, imR, iy1],
        "prompt_image": prompt_image,
        "prompt_feedback": (
            f"The visual gap appears around x={gap_x} in the screenshot "
            f"(fraction {gap_frac:.2f} across the slider image). Use EstimateDragOffset() "
            "to convert this into a calibrated handle drag."
        ),
    })


def execute_estimate_drag_offset(action: str, context: ToolContext, match) -> ToolResult:
    geo = _slider_geometry(context.screenshot_file)
    if geo is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "estimate_drag_offset", "tool_name": "EstimateDragOffset",
            "read_only": True, "label": "EstimateDragOffset (not applicable)",
            "not_applicable": True,
            "diagnostic_reason": "geometry_not_found",
            "prompt_feedback": (
                "This tool is not applicable because no continuous slider handle/track "
                "was found. Re-identify the visible interaction affordance."
            ),
            "error": "not_applicable",
        })
    imL, iy0, imR, iy1 = geo["photo"]
    tL, ty0, tR, ty1 = geo["track"]
    handle_w = ty1 - ty0


    crop_dir = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_path = str(crop_dir / "slider_photo.jpg")
    photo = geo["image"].crop((imL, iy0, imR, iy1))
    photo.save(crop_path, "JPEG", quality=95)
    gap_info = _read_gap_fraction(context, crop_path)
    if gap_info is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "estimate_drag_offset", "tool_name": "EstimateDragOffset",
            "read_only": True, "label": "EstimateDragOffset (gap read failed)",
            "prompt_image": crop_path,
            "prompt_feedback": "Could not read the gap position. Inspect the image and drag manually.",
            "error": "gap_read_failed",
        })
    gap_frac = float(gap_info["fraction"])
    prompt_image = _save_gap_overlay(photo, crop_path, gap_info)


    target_x = max(0.0, gap_frac * _NOMINAL_IMAGE_WIDTH - _NOMINAL_SLIDER_SIZE / 2.0)
    handle_frac = max(0.0, min(1.0, target_x / _MAX_PIECE_X))
    track_inner = max(1, (tR - tL) - handle_w)
    handle_dx = int(round(handle_frac * track_inner))
    sx = tL + handle_w // 2
    sy = (ty0 + ty1) // 2
    ex = sx + handle_dx
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "estimate_drag_offset", "tool_name": "EstimateDragOffset",
        "read_only": True,
        "label": f"EstimateDragOffset gap_frac={gap_frac:.2f} -> dx={handle_dx}",
        "gap_fraction": round(gap_frac, 3),
        "gap_method": gap_info.get("method"),
        "gap_confidence": gap_info.get("confidence"),
        "gap_bbox_in_crop": gap_info.get("bbox"),
        "handle_fraction": round(handle_frac, 3),
        "photo_bbox": [imL, iy0, imR, iy1],
        "track_bbox": [tL, ty0, tR, ty1],
        "suggested_drag": [sx, sy, ex, sy],
        "prompt_image": prompt_image,
        "prompt_feedback": (
            f"The gap is at about {gap_frac:.2f} across the slider image. To align the "
            f"piece, drag the handle right by ~{handle_dx}px. Suggested action: "
            f"Drag ({sx}, {sy}), ({ex}, {sy}). After releasing, re-check alignment and "
            "fine-tune if the piece overshoots or falls short."
        ),
    })


def _is_purple(p: Tuple[int, int, int]) -> bool:
    r, g, b = p
    return 55 <= r <= 145 and 40 <= g <= 110 and b >= 195 and b >= r + 70 and b >= g + 90


def _current_handle_x(image: Image.Image, track: Tuple[int, int, int, int]) -> Optional[int]:

    tL, ty0, tR, ty1 = track
    px = image.load()
    ymid = (ty0 + ty1) // 2
    rightmost = None
    for x in range(tL, tR):
        for y in (ymid, ymid - 8, ymid + 8):
            if _is_purple(px[x, y]):
                rightmost = x
                break
    return rightmost


def _vlm_piece_and_gap(context: ToolContext, crop_path: str) -> Optional[Tuple[float, float]]:
    cfg = context.env.cfg
    prompt = (
        "This is the background of a slider puzzle captcha. There is a movable puzzle PIECE "
        "(a bright square tile with a visible border) and a GAP (a faint darkened square "
        "hole) that the piece must fill. Report their horizontal centers as decimal "
        "fractions between 0 and 1. Answer EXACTLY as 'P=<piece> G=<gap>', e.g. 'P=0.05 G=0.62'."
    )
    try:
        chat = init_action_chat()
        chat = add_response("user", prompt, chat, crop_path)
        out = inference_chat(chat, cfg.caption_model, cfg.API_url, cfg.token) or ""
    except Exception:
        return None
    pm = re.search(r"P\s*=\s*(0?\.\d+|0|1(?:\.0+)?)", out)
    gm = re.search(r"G\s*=\s*(0?\.\d+|0|1(?:\.0+)?)", out)
    if not pm or not gm:
        return None
    try:
        p = max(0.0, min(1.0, float(pm.group(1))))
        g = max(0.0, min(1.0, float(gm.group(1))))
    except ValueError:
        return None
    return p, g


def execute_correct_slider_after_failure(action: str, context: ToolContext, match) -> ToolResult:
    """Correct residual displacement from the current piece position, including after a reset."""
    geo = _slider_geometry(context.screenshot_file)
    if geo is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "correct_slider", "tool_name": "CorrectSliderAfterFailure",
            "read_only": True, "label": "CorrectSliderAfterFailure (geometry not found)",
            "prompt_feedback": "Could not locate the slider image/track to correct the drag.",
            "error": "geometry_not_found",
        })
    imL, iy0, imR, iy1 = geo["photo"]
    tL, ty0, tR, ty1 = geo["track"]
    handle_w = ty1 - ty0
    track_inner = max(1, (tR - tL) - handle_w)

    crop_dir = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_path = str(crop_dir / "slider_correct.jpg")
    photo = geo["image"].crop((imL, iy0, imR, iy1))
    photo.save(crop_path, "JPEG", quality=95)
    pg = _vlm_piece_and_gap(context, crop_path)
    if pg is None:
        gap_info = _read_gap_fraction(context, crop_path)
        cur_handle_x = _current_handle_x(geo["image"], geo["track"])
        if gap_info is not None and cur_handle_x is not None:
            gap_frac = float(gap_info["fraction"])
            current_handle_frac = max(
                0.0,
                min(1.0, (cur_handle_x - (tL + handle_w // 2)) / float(track_inner)),
            )
            piece_frac = (
                current_handle_frac * _MAX_PIECE_X + _NOMINAL_SLIDER_SIZE / 2.0
            ) / float(_NOMINAL_IMAGE_WIDTH)
        else:
            prompt_image = _save_gap_overlay(photo, crop_path, gap_info) if gap_info else crop_path
            return ToolResult(handled=True, keep_running=True, exec_info={
                "action_type": "correct_slider", "tool_name": "CorrectSliderAfterFailure",
                "read_only": True, "label": "CorrectSliderAfterFailure (read failed)",
                "prompt_image": prompt_image,
                "gap_method": gap_info.get("method") if gap_info else None,
                "gap_confidence": gap_info.get("confidence") if gap_info else None,
                "prompt_feedback": "Could not read piece/gap positions. Inspect the image and adjust manually.",
                "error": "read_failed",
            })
    else:
        piece_frac, gap_frac = pg

    if pg is None:

        piece_frac = max(0.0, min(1.0, piece_frac))
        gap_frac = max(0.0, min(1.0, gap_frac))
    else:
        piece_frac, gap_frac = pg

    # Convert the remaining image displacement into handle pixels.
    residual_nominal = (gap_frac - piece_frac) * _NOMINAL_IMAGE_WIDTH
    residual_handle = (residual_nominal / _MAX_PIECE_X) * track_inner


    cur_handle_x = _current_handle_x(geo["image"], geo["track"])
    if cur_handle_x is None:
        piece_handle_frac = max(0.0, min(1.0, (piece_frac * _NOMINAL_IMAGE_WIDTH) / _MAX_PIECE_X))
        cur_handle_x = int(tL + handle_w // 2 + piece_handle_frac * track_inner)
    sy = (ty0 + ty1) // 2
    sx = cur_handle_x
    ex = int(round(sx + residual_handle))
    ex = max(tL + handle_w // 2, min(ex, tR - handle_w // 2))
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "correct_slider", "tool_name": "CorrectSliderAfterFailure",
        "read_only": True,
        "label": f"CorrectSlider piece={piece_frac:.2f} gap={gap_frac:.2f} dx={ex - sx}",
        "piece_fraction": round(piece_frac, 3), "gap_fraction": round(gap_frac, 3),
        "photo_bbox": [imL, iy0, imR, iy1],
        "track_bbox": [tL, ty0, tR, ty1],
        "suggested_drag": [sx, sy, ex, sy],
        "prompt_feedback": (
            f"The piece is at ~{piece_frac:.2f} and the gap at ~{gap_frac:.2f} across the "
            f"slider image. Corrective move: Drag ({sx}, {sy}), ({ex}, {sy}). If the piece "
            "already looks aligned, submit instead of dragging again."
        ),
    })


def register_drag_tools(registry: ToolRegistry) -> None:
    registry.register(
        name="DragBy",
        pattern=r"DragBy\s*\(\s*(?P<x>\d+)\s*,\s*(?P<y>\d+)\s*,\s*(?P<dx>-?\d+)\s*,\s*(?P<dy>-?\d+)\s*\)",
        handler=execute_drag_by,
        description=(
            "DragBy(x, y, dx, dy): one calibrated drag starting at (x,y) and moving by "
            "(dx,dy). Use LocateSliderHandle/LocateGrid first to choose the start point."
        ),
    )
    registry.register(
        name="Drag",
        pattern=r"Drag\s*\(\s*(?P<x1>\d+)\s*,\s*(?P<y1>\d+)\s*\)\s*,\s*\(\s*(?P<x2>\d+)\s*,\s*(?P<y2>\d+)\s*\)",
        handler=execute_drag,
        description=(
            "Drag (x1, y1), (x2, y2): one calibrated press-and-drag from start to end "
            "(longer hold than Swipe). Use it for slider/puzzle drags in a single move."
        ),
    )
    registry.register(
        name="CorrectSliderAfterFailure",
        pattern=r"CorrectSliderAfterFailure\s*(?:\(\s*\))?",
        handler=execute_correct_slider_after_failure,
        read_only=True,
        description=(
            "CorrectSliderAfterFailure(): after a slider miss, read the piece and gap "
            "positions and return a corrective Drag. Read-only."
        ),
        affordances=("continuous_slider",),
        preconditions=("visible_handle", "visible_track", "previous_slider_attempt"),
    )
    registry.register(
        name="LocateSliderTrack",
        pattern=r"LocateSliderTrack\s*(?:\(\s*\))?",
        handler=execute_locate_slider_track,
        read_only=True,
        description=(
            "LocateSliderTrack(): locate the slider image/photo and track geometry. Read-only."
        ),
    )
    registry.register(
        name="LocateSliderHandle",
        pattern=r"LocateSliderHandle\s*(?:\(\s*\))?",
        handler=execute_locate_slider_handle,
        read_only=True,
        description=(
            "LocateSliderHandle(): locate the slider track and handle. Read-only; returns "
            "the handle position and draggable track span."
        ),
    )
    registry.register(
        name="LocateGap",
        pattern=r"LocateGap\s*(?:\(\s*\))?",
        handler=execute_locate_gap,
        read_only=True,
        description=(
            "LocateGap(): estimate the visual gap/notch position in a slider image. "
            "Read-only; use EstimateDragOffset() to get the final drag."
        ),
    )
    registry.register(
        name="EstimateDragOffset",
        pattern=r"EstimateDragOffset\s*(?:\(\s*\))?",
        handler=execute_estimate_drag_offset,
        read_only=True,
        description=(
            "EstimateDragOffset(): estimate how far to drag the slider handle to align the "
            "piece with the gap, and return suggested Drag coordinates. Read-only."
        ),
        affordances=("continuous_slider",),
        preconditions=("visible_handle", "visible_track"),
    )
