from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw

from hll.tools.controller import tap
from hll.tools.base import ToolContext, ToolResult
from hll.metrics import intentional_sleep
from hll.tools.registry import ToolRegistry


@dataclass
class GridGeometry:
    bbox: Tuple[int, int, int, int]
    rows: int
    cols: int
    detected: bool = True

    def cell_center(self, index: int) -> Tuple[int, int]:
        if index < 0 or index >= self.rows * self.cols:
            raise ValueError(f"Grid cell index out of range: {index}")
        x1, y1, x2, y2 = self.bbox
        row = index // self.cols
        col = index % self.cols
        cell_w = (x2 - x1) / float(self.cols)
        cell_h = (y2 - y1) / float(self.rows)
        return int(round(x1 + (col + 0.5) * cell_w)), int(round(y1 + (row + 0.5) * cell_h))


@dataclass
class GridArtifacts:
    geometry: GridGeometry
    overview_path: str
    cell_paths: List[str]
    selected_cells: List[int]


def _is_grid_background(pixel: Tuple[int, int, int]) -> bool:
    r, g, b = pixel
    if max(pixel) < 170:
        return False
    if min(pixel) > 248:
        return False
    neutral_or_cool = max(pixel) - min(pixel) <= 48 and b >= r - 8 and g >= r - 18
    return neutral_or_cool


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


def _score_grid_candidate(
    box: Tuple[int, int, int, int, int],
    image_width: int,
    image_height: int,
    rows: int,
    cols: int,
) -> float:
    x1, y1, x2, y2, count = box
    box_w = x2 - x1
    box_h = y2 - y1
    if box_w <= 0 or box_h <= 0:
        return 0.0

    min_side = min(image_width, image_height)
    if box_w < min_side * 0.25 or box_h < min_side * 0.20:
        return 0.0

    expected_ratio = cols / float(rows)
    ratio = box_w / float(box_h)
    ratio_penalty = abs(ratio - expected_ratio)
    if ratio_penalty > 0.55:
        return 0.0

    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    center_penalty = abs(center_x - image_width / 2.0) / max(1.0, image_width)
    if center_y < image_height * 0.16:
        return 0.0

    fill = count / float(box_w * box_h)
    if fill < 0.015:
        return 0.0

    square_score = max(0.0, 1.0 - ratio_penalty)
    center_score = max(0.0, 1.0 - center_penalty * 2.0)
    size_score = min(box_w * box_h / float(image_width * image_height), 0.35)
    return count * square_score * center_score * (1.0 + size_score)


def _fallback_grid(image_width: int, image_height: int, rows: int, cols: int) -> GridGeometry:
    size = int(min(image_width * 0.84, image_height * 0.42))
    size = max(size, int(min(image_width, image_height) * 0.45))
    x1 = max(0, int((image_width - size) / 2))
    y1 = max(0, int(image_height * 0.34))
    x2 = min(image_width - 1, x1 + size)
    y2 = min(image_height - 1, y1 + size)
    return GridGeometry((x1, y1, x2, y2), rows=rows, cols=cols, detected=False)


def locate_grid(screenshot_file: str, rows: int = 3, cols: int = 3) -> GridGeometry:
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
            row.append(_is_grid_background(pixels[x, y]))
        mask.append(row)

    boxes = _component_boxes(mask)
    scored = [
        (_score_grid_candidate(box, scan_width, scan_height, rows, cols), box)
        for box in boxes
    ]
    scored = [(score, box) for score, box in scored if score > 0]
    if not scored:
        return _fallback_grid(image_width, image_height, rows, cols)

    _, best = max(scored, key=lambda item: item[0])
    x1, y1, x2, y2, _ = best
    inv = 1.0 / scale
    bbox = (
        max(0, int(round(x1 * inv))),
        max(0, int(round(y1 * inv))),
        min(image_width - 1, int(round(x2 * inv))),
        min(image_height - 1, int(round(y2 * inv))),
    )
    if not _is_plausible_grid_bbox(bbox, image_width, image_height):
        return _fallback_grid(image_width, image_height, rows, cols)
    return GridGeometry(bbox, rows=rows, cols=cols)


def _is_plausible_grid_bbox(
    bbox: Tuple[int, int, int, int],
    image_width: int,
    image_height: int,
) -> bool:
    x1, y1, x2, y2 = bbox
    box_width = x2 - x1
    box_height = y2 - y1
    if box_width <= 0 or box_height <= 0:
        return False
    if x1 <= 0 or y1 <= 0 or x2 >= image_width - 1 or y2 >= image_height - 1:
        return False
    return box_width < image_width * 0.96 and box_height < image_height * 0.8


def _snapshot_grid_geometry(
    context: ToolContext,
    rows: int,
    cols: int,
) -> GridGeometry | None:
    snapshot = getattr(context, "grid_snapshot", None) or {}
    if int(snapshot.get("rows", 0) or 0) != rows:
        return None
    if int(snapshot.get("cols", 0) or 0) != cols:
        return None
    bbox = snapshot.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        normalized = tuple(int(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    width, height = max(1, int(context.width)), max(1, int(context.height))
    if int(snapshot.get("width", width) or width) != width:
        return None
    if int(snapshot.get("height", height) or height) != height:
        return None
    if not _is_plausible_grid_bbox(normalized, width, height):
        return None
    return GridGeometry(normalized, rows=rows, cols=cols)


def _grid_geometry(context: ToolContext, rows: int, cols: int) -> GridGeometry:
    return _snapshot_grid_geometry(context, rows, cols) or locate_grid(
        context.screenshot_file,
        rows=rows,
        cols=cols,
    )


def _is_selected_pixel(pixel: Tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return r <= 90 and g >= 145 and 80 <= b <= 190 and g >= r + 60 and g >= b + 10


def _cell_selected(cell: Image.Image) -> bool:
    image = cell.convert("RGB")
    width, height = image.size
    if width <= 0 or height <= 0:
        return False
    pixels = image.load()
    selected = 0
    total = width * height
    for y in range(height):
        for x in range(width):
            if _is_selected_pixel(pixels[x, y]):
                selected += 1
    return selected / float(total) >= 0.015


def _draw_label(draw: ImageDraw.ImageDraw, x: int, y: int, label: str) -> None:
    pad = 6

    bbox = draw.textbbox((x, y), label)
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=(0, 0, 0),
        outline=(255, 255, 255),
        width=2,
    )
    draw.text((x, y), label, fill=(255, 255, 255))


def crop_grid_cells(
    screenshot_file: str,
    output_dir: str,
    rows: int = 3,
    cols: int = 3,
) -> GridArtifacts:
    geometry = locate_grid(screenshot_file, rows=rows, cols=cols)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    image = Image.open(screenshot_file).convert("RGB")
    x1, y1, x2, y2 = geometry.bbox
    grid_crop = image.crop((x1, y1, x2, y2))
    draw = ImageDraw.Draw(grid_crop)

    cell_paths: List[str] = []
    selected_cells: List[int] = []
    cell_w = (x2 - x1) / float(cols)
    cell_h = (y2 - y1) / float(rows)

    for index in range(rows * cols):
        row = index // cols
        col = index % cols
        left = int(round(x1 + col * cell_w))
        top = int(round(y1 + row * cell_h))
        right = int(round(x1 + (col + 1) * cell_w))
        bottom = int(round(y1 + (row + 1) * cell_h))
        cell = image.crop((left, top, right, bottom))
        if _cell_selected(cell):
            selected_cells.append(index)
        cell_path = out_dir / f"cell_{index}.jpg"
        cell.save(cell_path, "JPEG", quality=95)
        cell_paths.append(str(cell_path))

        local_x = int(round(col * cell_w)) + 10
        local_y = int(round(row * cell_h)) + 10
        label = f"{index}"
        if index in selected_cells:
            label += " selected"
        _draw_label(draw, local_x, local_y, label)

    overview_path = out_dir / "grid_overview.jpg"
    grid_crop.save(overview_path, "JPEG", quality=95)
    return GridArtifacts(
        geometry=geometry,
        overview_path=str(overview_path),
        cell_paths=cell_paths,
        selected_cells=selected_cells,
    )


def execute_tap_grid_cell(action: str, context: ToolContext, match) -> ToolResult:
    index = int(match.group("index"))
    rows, cols = _rows_cols_from_match(match, 3, 3)
    geometry = _grid_geometry(context, rows, cols)
    if not geometry.detected:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "tap_grid_cell",
            "tool_name": "TapGridCell",
            "read_only": True,
            "label": "TapGridCell (grid geometry uncertain)",
            "grid_bbox": list(geometry.bbox),
            "grid_rows": rows,
            "grid_cols": cols,
            "grid_detected": False,
            "not_applicable": True,
            "error": "grid_not_detected",
            "prompt_feedback": (
                "The visible grid geometry is uncertain, so no cell was tapped. "
                "Use LocateGrid, CropRegion, or another grounding tool before selecting a cell."
            ),
        })
    try:
        x, y = geometry.cell_center(index)
    except ValueError as exc:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "tap",
            "tool_name": "TapGridCell",
            "label": f"TapGridCell ({index}) out of range for {rows}x{cols}",
            "grid_bbox": list(geometry.bbox),
            "grid_rows": geometry.rows,
            "grid_cols": geometry.cols,
            "error": str(exc),
        })

    if context.width and context.height:
        screen_width = int(context.width)
        screen_height = int(context.height)
    else:
        with Image.open(context.screenshot_file) as image:
            screen_width, screen_height = image.size
    screen_width = max(screen_width, 1)
    screen_height = max(screen_height, 1)
    x = max(0, min(x, screen_width - 1))
    y = max(0, min(y, screen_height - 1))

    tap(context.env.cfg.adb_path, x, y)

    exec_info = {
        "action_type": "tap",
        "tool_name": "TapGridCell",
        "label": f"TapGridCell ({index}) -> Tap ({x}, {y})",
        "point": [x, y],
        "cell_index": index,
        "mapped_point": [x, y],
        "grid_bbox": list(geometry.bbox),
        "grid_rows": geometry.rows,
        "grid_cols": geometry.cols,
        "grid_detected": geometry.detected,
    }
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def execute_move_grid_piece(action: str, context: ToolContext, match) -> ToolResult:
    from_index = int(match.group("from_index"))
    to_index = int(match.group("to_index"))
    rows, cols = _rows_cols_from_match(match, 5, 5)
    geometry = _grid_geometry(context, rows, cols)
    if not geometry.detected:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "move_grid_piece",
            "tool_name": "MoveGridPiece",
            "read_only": True,
            "label": "MoveGridPiece (not applicable)",
            "not_applicable": True,
            "diagnostic_reason": "grid_not_detected",
            "prompt_feedback": (
                "This tool is not applicable because a matching grid was not detected. "
                "Re-identify the visible interaction affordance."
            ),
            "error": "not_applicable",
        })
    try:
        start = geometry.cell_center(from_index)
        end = geometry.cell_center(to_index)
    except ValueError as exc:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "move_grid_piece",
            "tool_name": "MoveGridPiece",
            "label": f"MoveGridPiece {from_index}->{to_index} out of range",
            "grid_bbox": list(geometry.bbox),
            "grid_rows": rows,
            "grid_cols": cols,
            "error": str(exc),
        })

    tap(context.env.cfg.adb_path, *start)
    intentional_sleep(0.15, "grid_piece_tap_interval")
    tap(context.env.cfg.adb_path, *end)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "move_grid_piece",
        "tool_name": "MoveGridPiece",
        "label": f"MoveGridPiece {from_index}->{to_index}",
        "from_index": from_index,
        "to_index": to_index,
        "start": list(start),
        "end": list(end),
        "grid_bbox": list(geometry.bbox),
        "grid_rows": rows,
        "grid_cols": cols,
        "grid_detected": geometry.detected,
        "interaction_progress": True,
        "ready_to_submit": True,
    })


def _rows_cols_from_match(match, default_rows: int, default_cols: int) -> Tuple[int, int]:
    rows = match.groupdict().get("rows")
    cols = match.groupdict().get("cols")
    if rows and cols:
        return max(1, int(rows)), max(1, int(cols))
    return default_rows, default_cols


def _grid_feedback(name: str, geometry: GridGeometry, artifacts: GridArtifacts) -> str:
    x1, y1, x2, y2 = geometry.bbox
    lines = [
        f"{name} located a {geometry.rows}x{geometry.cols} grid/board at ({x1}, {y1}, {x2}, {y2}).",
        f"Selected/marked cells detected: {artifacts.selected_cells}.",
        "The attached overview labels each cell by row-major index.",
        "For selection grids use TapGridCell(index). For source-to-destination boards use MoveGridPiece(from_index, to_index, rows, cols).",
    ]
    return "\n".join(lines)


def execute_locate_grid(action: str, context: ToolContext, match) -> ToolResult:
    rows, cols = _rows_cols_from_match(match, 3, 3)
    out_dir = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops" / f"grid_{rows}x{cols}"
    artifacts = crop_grid_cells(context.screenshot_file, str(out_dir), rows=rows, cols=cols)
    geometry = artifacts.geometry
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "locate_grid",
        "tool_name": "LocateGrid",
        "read_only": True,
        "label": f"LocateGrid -> {rows}x{cols} {geometry.bbox}",
        "grid_bbox": list(geometry.bbox),
        "grid_rows": rows,
        "grid_cols": cols,
        "selected_cells": artifacts.selected_cells,
        "grid_detected": geometry.detected,
        "cell_paths": artifacts.cell_paths,
        "prompt_image": artifacts.overview_path,
        "prompt_feedback": _grid_feedback("LocateGrid", geometry, artifacts),
    })


def execute_detect_board(action: str, context: ToolContext, match) -> ToolResult:
    rows, cols = _rows_cols_from_match(match, 5, 5)
    out_dir = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops" / f"board_{rows}x{cols}"
    artifacts = crop_grid_cells(context.screenshot_file, str(out_dir), rows=rows, cols=cols)
    geometry = artifacts.geometry
    x1, y1, x2, y2 = geometry.bbox
    cell_bboxes = []
    cell_w = (x2 - x1) / float(cols)
    cell_h = (y2 - y1) / float(rows)
    for index in range(rows * cols):
        row = index // cols
        col = index % cols
        cell_bboxes.append([
            int(round(x1 + col * cell_w)),
            int(round(y1 + row * cell_h)),
            int(round(x1 + (col + 1) * cell_w)),
            int(round(y1 + (row + 1) * cell_h)),
        ])
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "detect_board",
        "tool_name": "DetectBoard",
        "read_only": True,
        "label": f"DetectBoard -> {rows}x{cols} {geometry.bbox}",
        "board_bbox": list(geometry.bbox),
        "rows": rows,
        "cols": cols,
        "cell_bboxes": cell_bboxes,
        "selected_cells": artifacts.selected_cells,
        "grid_detected": geometry.detected,
        "prompt_image": artifacts.overview_path,
        "prompt_feedback": _grid_feedback("DetectBoard", geometry, artifacts),
    })


def register_grid_tools(registry: ToolRegistry) -> None:
    rows_cols = r"(?:\(\s*(?:(?P<rows>\d+)\s*,\s*(?P<cols>\d+))?\s*\))?"
    registry.register(
        name="LocateGrid",
        pattern=r"LocateGrid\s*" + rows_cols,
        handler=execute_locate_grid,
        read_only=True,
        description=(
            "LocateGrid(rows, cols): locate a generic grid and attach a labeled overview. "
            "Read-only; defaults to 3x3."
        ),
    )
    registry.register(
        name="DetectBoard",
        pattern=r"DetectBoard\s*" + rows_cols,
        handler=execute_detect_board,
        read_only=True,
        description=(
            "DetectBoard(rows, cols): locate a board/grid, return cell bboxes, and attach "
            "a labeled overview. Read-only; defaults to 5x5."
        ),
    )
    registry.register(
        name="TapGridCell",
        pattern=(
            r"TapGridCell\s*\(\s*(?P<index>\d+)"
            r"(?:\s*,\s*(?P<rows>\d+)\s*,\s*(?P<cols>\d+))?\s*\)"
        ),
        handler=execute_tap_grid_cell,
        description=(
            "TapGridCell(index[, rows, cols]): click one grid cell by zero-based row-major "
            "index. Defaults to a 3x3 image grid."
        ),
    )
    registry.register(
        name="MoveGridPiece",
        pattern=(
            r"MoveGridPiece\s*\(\s*(?P<from_index>\d+)\s*,\s*(?P<to_index>\d+)"
            r"(?:\s*,\s*(?P<rows>\d+)\s*,\s*(?P<cols>\d+))?\s*\)"
        ),
        handler=execute_move_grid_piece,
        description=(
            "MoveGridPiece(from_index, to_index[, rows, cols]): move one board piece "
            "using the common select-source then select-destination interaction."
        ),
        affordances=("grid_piece_move",),
        preconditions=("visible_grid", "occupied_source", "empty_destination"),
    )
