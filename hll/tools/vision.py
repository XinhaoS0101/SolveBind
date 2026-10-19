from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from hll.tools.base import ToolContext, ToolResult
from hll.tools.registry import ToolRegistry


ColorPredicate = Callable[[Tuple[int, int, int]], bool]


def _screen_size(context: ToolContext) -> Tuple[int, int]:
    if context.width and context.height:
        return max(int(context.width), 1), max(int(context.height), 1)
    with Image.open(context.screenshot_file) as image:
        return max(image.width, 1), max(image.height, 1)


def _clamp_region(x1: int, y1: int, x2: int, y2: int, width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
    y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2


def _crop_dir(context: ToolContext) -> Path:
    out = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _mse_similarity(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b)
    pixels = list(diff.getdata())
    if not pixels:
        return 0.0
    mse = sum((p * p if isinstance(p, int) else sum(v * v for v in p) / len(p)) for p in pixels) / len(pixels)
    return max(0.0, min(1.0, 1.0 - mse / float(255 * 255)))


def execute_compare_similarity(action: str, context: ToolContext, match) -> ToolResult:
    width, height = _screen_size(context)
    names = ("a1", "b1", "a2", "b2", "c1", "d1", "c2", "d2")
    values = {name: int(match.group(name)) for name in names}
    r1 = _clamp_region(values["a1"], values["b1"], values["a2"], values["b2"], width, height)
    r2 = _clamp_region(values["c1"], values["d1"], values["c2"], values["d2"], width, height)
    if r1 is None or r2 is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "compare_similarity",
            "tool_name": "CompareSimilarity",
            "read_only": True,
            "label": "CompareSimilarity (invalid region)",
            "error": "invalid_region",
            "prompt_feedback": "One or both regions were invalid; provide two non-empty screen regions.",
        })

    image = Image.open(context.screenshot_file).convert("RGB")
    crop1 = image.crop(r1).resize((96, 96), Image.LANCZOS)
    crop2 = image.crop(r2).resize((96, 96), Image.LANCZOS)
    rgb_similarity = _mse_similarity(crop1, crop2)
    edge1 = crop1.convert("L").filter(ImageFilter.FIND_EDGES)
    edge2 = crop2.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_similarity = _mse_similarity(edge1, edge2)
    similarity = round((rgb_similarity * 0.6 + edge_similarity * 0.4), 4)

    out_dir = _crop_dir(context)
    crop1_path = out_dir / f"compare_a_{r1[0]}_{r1[1]}_{r1[2]}_{r1[3]}.jpg"
    crop2_path = out_dir / f"compare_b_{r2[0]}_{r2[1]}_{r2[2]}_{r2[3]}.jpg"
    crop1.save(crop1_path, "JPEG", quality=95)
    crop2.save(crop2_path, "JPEG", quality=95)
    feedback = (
        f"Similarity between {r1} and {r2}: {similarity:.3f} "
        f"(rgb={rgb_similarity:.3f}, edge={edge_similarity:.3f}). "
        "Higher means the regions look more alike; use this as supporting evidence, not as the only decision."
    )
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "compare_similarity",
        "tool_name": "CompareSimilarity",
        "read_only": True,
        "label": f"CompareSimilarity -> {similarity:.3f}",
        "region_a": list(r1),
        "region_b": list(r2),
        "similarity": similarity,
        "rgb_similarity": round(rgb_similarity, 4),
        "edge_similarity": round(edge_similarity, 4),
        "crop_a": str(crop1_path),
        "crop_b": str(crop2_path),
        "prompt_feedback": feedback,
    })


def _predicate_for_color(name: str) -> ColorPredicate:
    color = (name or "").lower().strip()

    def green(p: Tuple[int, int, int]) -> bool:
        r, g, b = p
        return r <= 120 and g >= 130 and g >= r + 40 and g >= b + 10

    def red(p: Tuple[int, int, int]) -> bool:
        r, g, b = p
        return r >= 150 and g <= 110 and b <= 120 and r >= g + 45

    def blue(p: Tuple[int, int, int]) -> bool:
        r, g, b = p
        return b >= 140 and r <= 130 and g <= 160 and b >= r + 40

    def purple(p: Tuple[int, int, int]) -> bool:
        r, g, b = p
        return 55 <= r <= 160 and 30 <= g <= 130 and b >= 145 and b >= g + 45

    def yellow(p: Tuple[int, int, int]) -> bool:
        r, g, b = p
        return r >= 170 and g >= 145 and b <= 120 and abs(r - g) <= 90

    mapping: Dict[str, ColorPredicate] = {
        "green": green,
        "selected": green,
        "red": red,
        "blue": blue,
        "purple": purple,
        "primary": purple,
        "yellow": yellow,
    }
    return mapping.get(color, green)


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


def execute_detect_color_markers(action: str, context: ToolContext, match) -> ToolResult:
    color = (match.group("color") or "green").strip()
    predicate = _predicate_for_color(color)
    image = Image.open(context.screenshot_file).convert("RGB")
    max_dim = 480
    scale = min(1.0, max_dim / float(max(image.width, image.height)))
    scan = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    pixels = scan.load()
    mask = [[predicate(pixels[x, y]) for x in range(scan.width)] for y in range(scan.height)]
    inv = 1.0 / scale
    markers = []
    for box in _component_boxes(mask):
        x1, y1, x2, y2, count = box
        area = (x2 - x1) * (y2 - y1)
        if area < 16 or count < 8:
            continue
        bbox = [
            int(round(x1 * inv)),
            int(round(y1 * inv)),
            int(round(x2 * inv)),
            int(round(y2 * inv)),
        ]
        markers.append({
            "bbox": bbox,
            "center": [(bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2],
            "pixel_count": count,
        })
    markers = sorted(markers, key=lambda item: item["pixel_count"], reverse=True)[:20]

    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for idx, marker in enumerate(markers, start=1):
        x1, y1, x2, y2 = marker["bbox"]
        draw.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=3)
        draw.text((x1, max(0, y1 - 14)), str(idx), fill=(255, 0, 0))
    out_path = _crop_dir(context) / f"markers_{color.lower()}.jpg"
    overlay.save(out_path, "JPEG", quality=95)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "detect_color_markers",
        "tool_name": "DetectColorMarkers",
        "read_only": True,
        "label": f"DetectColorMarkers {color} -> {len(markers)}",
        "color": color,
        "markers": markers,
        "prompt_image": str(out_path),
        "prompt_feedback": (
            f"Detected {len(markers)} {color} marker components. The overlay image labels "
            "the largest components. Use centers/bboxes to identify selected cells, error marks, or active controls."
        ),
    })


def register_vision_tools(registry: ToolRegistry) -> None:
    region_pair = (
        r"\(\s*(?P<a1>\d+)\s*,\s*(?P<b1>\d+)\s*,\s*(?P<a2>\d+)\s*,\s*(?P<b2>\d+)\s*\)"
        r"\s*,\s*"
        r"\(\s*(?P<c1>\d+)\s*,\s*(?P<d1>\d+)\s*,\s*(?P<c2>\d+)\s*,\s*(?P<d2>\d+)\s*\)"
    )
    registry.register(
        name="CompareSimilarity",
        pattern=r"CompareSimilarity\s*" + region_pair,
        handler=execute_compare_similarity,
        read_only=True,
        description=(
            "CompareSimilarity(region_a, region_b): compare two screen regions using color "
            "and edge similarity. Read-only; useful for candidate matching."
        ),
    )
    registry.register(
        name="DetectColorMarkers",
        pattern=r"DetectColorMarkers\s*\(\s*(?P<color>[A-Za-z_ -]+)\s*\)",
        handler=execute_detect_color_markers,
        read_only=True,
        description=(
            "DetectColorMarkers(color): find colored marker components such as green "
            "selected-cell borders/checkmarks or red error markers. Read-only."
        ),
    )
