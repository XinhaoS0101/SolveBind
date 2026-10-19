from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def draw_region_overlay(
    screenshot_path: str,
    region: Sequence[int],
    *,
    label: str = "region",
    output_name: str = "",
) -> str:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""

    try:
        path = Path(screenshot_path)
        image = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(image)
        x1, y1, x2, y2 = _coerce_region(region)
        _draw_region(draw, (x1, y1, x2, y2), label)
        out_dir = path.parent / "debug_overlays"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (output_name or f"{path.stem}_{_slug(label)}_region.png")
        image.save(out_path, "PNG")
        return str(out_path.resolve())
    except Exception:
        return ""


def draw_action_overlay(
    screenshot_path: str,
    details: Mapping[str, Any],
    *,
    label: str = "",
) -> str:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""

    try:
        path = Path(screenshot_path)
        image = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(image)
        action_label = label or str(details.get("label") or details.get("tool_name") or "action")

        region = _first_sequence(details, ("region", "grid_bbox", "button_bbox", "input_bbox"))
        if region and len(region) >= 4:
            _draw_region(draw, _coerce_region(region[:4]), action_label)

        path_values = _first_sequence(details, ("mapped_path",))
        if path_values and len(path_values) >= 4:
            x1, y1, x2, y2 = [int(round(float(value))) for value in path_values[:4]]
            _draw_path(draw, (x1, y1), (x2, y2), action_label)
        else:
            start = _first_sequence(details, ("start",))
            end = _first_sequence(details, ("end",))
            if start and end and len(start) >= 2 and len(end) >= 2:
                _draw_path(
                    draw,
                    (int(round(float(start[0]))), int(round(float(start[1])))),
                    (int(round(float(end[0]))), int(round(float(end[1])))),
                    action_label,
                )

        point = _first_sequence(details, ("mapped_point", "point"))
        if point and len(point) >= 2:
            _draw_point(
                draw,
                (int(round(float(point[0]))), int(round(float(point[1])))),
                action_label,
            )

        out_dir = path.parent / "debug_overlays"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{path.stem}_{_slug(action_label)}_action.png"
        image.save(out_path, "PNG")
        return str(out_path.resolve())
    except Exception:
        return ""


def _coerce_region(values: Sequence[Any]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [int(round(float(value))) for value in values[:4]]
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def _first_sequence(details: Mapping[str, Any], keys: Iterable[str]) -> Sequence[Any] | None:
    for key in keys:
        value = details.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return value
    return None


def _draw_region(draw: Any, region: tuple[int, int, int, int], label: str) -> None:
    x1, y1, x2, y2 = region
    color = (255, 80, 0)
    for offset in range(4):
        draw.rectangle((x1 - offset, y1 - offset, x2 + offset, y2 + offset), outline=color)
    draw.text((x1 + 6, max(0, y1 - 22)), f"{label} [{x1},{y1},{x2},{y2}]", fill=color)


def _draw_point(draw: Any, point: tuple[int, int], label: str) -> None:
    x, y = point
    color = (0, 150, 255)
    radius = 18
    for offset in range(4):
        draw.ellipse(
            (x - radius - offset, y - radius - offset, x + radius + offset, y + radius + offset),
            outline=color,
        )
    draw.line((x - radius, y, x + radius, y), fill=color, width=3)
    draw.line((x, y - radius, x, y + radius), fill=color, width=3)
    draw.text((x + radius + 6, max(0, y - radius)), f"{label} ({x},{y})", fill=color)


def _draw_path(draw: Any, start: tuple[int, int], end: tuple[int, int], label: str) -> None:
    color = (20, 190, 80)
    draw.line((start[0], start[1], end[0], end[1]), fill=color, width=7)
    _draw_point(draw, start, f"{label} start")
    _draw_point(draw, end, f"{label} end")


def _slug(value: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in value.lower())
    return "_".join(part for part in safe.split("_") if part)[:80] or "trace"
