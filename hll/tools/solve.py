from __future__ import annotations

import ast
import json
import operator
import re
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageStat

from hll.tools.api import inference_chat
from hll.tools.chat import add_response, init_action_chat
from hll.tools.base import ToolContext, ToolResult
from hll.tools.crop import locate_captcha_area
from hll.tools.grid import locate_grid
from hll.tools.registry import ToolRegistry


def _captcha_crop(context: ToolContext, name: str) -> Optional[str]:

    region = locate_captcha_area(context.screenshot_file)
    image = Image.open(context.screenshot_file).convert("RGB")
    if region is not None:
        image = image.crop(tuple(region))
    out = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    out.mkdir(parents=True, exist_ok=True)
    path = str(out / name)
    image.save(path, "JPEG", quality=95)
    return path


def _vlm_read(context: ToolContext, crop_path: str, prompt: str) -> Optional[str]:
    cfg = context.env.cfg
    try:
        chat = init_action_chat()
        chat = add_response("user", prompt, chat, crop_path)
        return (inference_chat(chat, cfg.caption_model, cfg.API_url, cfg.token) or "").strip()
    except Exception:
        return None


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


def _crop_dir(context: ToolContext) -> Path:
    out = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    out.mkdir(parents=True, exist_ok=True)
    return out


def execute_read_click_sequence(action: str, context: ToolContext, match) -> ToolResult:
    crop = _captcha_crop(context, "click_sequence.jpg")
    prompt = (
        "This is a click captcha. At the top it states the order to click targets "
        "(e.g. 'Click in order: A -> 5 -> K'). List that required order as a simple "
        "left-to-right sequence. Answer ONLY the sequence, e.g. 'A, 5, K'."
    )
    seq = _vlm_read(context, crop, prompt)
    if seq is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "read_click_sequence", "tool_name": "ReadClickSequence",
            "read_only": True, "label": "ReadClickSequence (failed)",
            "prompt_feedback": "Could not read the click order; read it from the screenshot.",
            "error": "read_failed",
        })
    seq = seq.strip()
    if not seq:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "read_click_sequence", "tool_name": "ReadClickSequence",
            "read_only": True, "label": "ReadClickSequence (empty)",
            "prompt_feedback": "The click order reader returned empty text; inspect the screenshot or use another visual tool.",
            "error": "empty_sequence",
        })
    suggested = {"action": "detect_click_targets", "args": {}}
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "read_click_sequence", "tool_name": "ReadClickSequence",
        "read_only": True, "label": f"ReadClickSequence -> {seq}",
        "sequence": seq, "prompt_image": crop,
        "suggested_action": suggested,
        "canonical_action": suggested,
        "prompt_feedback": (
            f"Required click order: {seq}. Click these targets in exactly this order, "
            "then Verify. Use Clear/Refresh if you mis-click."
        ),
    })


def _extract_arithmetic_expression(text: str) -> Optional[str]:
    expression = re.search(
        r"[-+]?\d+(?:\.\d+)?(?:\s*(?:[+\-*/×÷]|plus|minus|times)\s*[-+]?\d+(?:\.\d+)?)+",
        text,
        flags=re.IGNORECASE,
    )
    if expression is None:
        return None
    return expression.group(0).strip()


def execute_read_logic_prompt(action: str, context: ToolContext, match) -> ToolResult:
    crop = _captcha_crop(context, "logic_prompt.jpg")
    prompt = (
        "This is a logic/arithmetic captcha. Transcribe the current challenge exactly as "
        "shown (the question or instruction the user must solve). Answer ONLY the challenge text."
    )
    text = _vlm_read(context, crop, prompt)
    if text is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "read_logic_prompt", "tool_name": "ReadLogicPrompt",
            "read_only": True, "label": "ReadLogicPrompt (failed)",
            "prompt_feedback": "Could not read the challenge; read it from the screenshot.",
            "error": "read_failed",
        })
    expression = _extract_arithmetic_expression(text)
    if expression:
        suggested = {"action": "solve_arithmetic", "args": {"expr": expression}}
    else:
        suggested = {"action": "detect_click_targets", "args": {}}
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "read_logic_prompt", "tool_name": "ReadLogicPrompt",
        "read_only": True, "label": f"ReadLogicPrompt -> {text[:60]}",
        "challenge": text, "prompt_image": crop,
        "suggested_action": suggested,
        "canonical_action": suggested,
        "prompt_feedback": (
            f"The current challenge reads: {text}. If it is arithmetic, compute it with "
            "SolveArithmetic <text>(expression)</text> and input the answer. If it is a "
            "visual instruction, locate the requested visible target in the screenshot or "
            "crop, use Zoom/ClassifyRegion/DetectClickTargets if uncertain, tap the target "
            "or target region, then submit."
        ),
    })


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("non-numeric constant")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


def execute_solve_arithmetic(action: str, context: ToolContext, match) -> ToolResult:
    raw = match.group("expr")

    expr = (raw.replace("×", "*").replace("x", "*").replace("X", "*")
            .replace("÷", "/").replace("plus", "+").replace("minus", "-")
            .replace("times", "*"))
    expr = re.sub(r"[^0-9+\-*/().%\s]", "", expr)
    try:
        value = _safe_eval(ast.parse(expr, mode="eval"))
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        answer = str(value)
        err = None
    except Exception as exc:
        answer, err = None, str(exc)
    if err:
        feedback = f"Could not evaluate '{raw}': {err}. Re-read the expression and try again."
    else:
        feedback = f"{raw.strip()} = {answer}. Enter '{answer}' as the answer."
    exec_info = {
        "action_type": "solve_arithmetic", "tool_name": "SolveArithmetic", "read_only": True,
        "label": f"SolveArithmetic '{raw.strip()}' -> {answer}",
        "answer": answer, "prompt_feedback": feedback,
    }
    if err:
        exec_info["error"] = err
    else:
        suggested = {"action": "input_text", "args": {"text": answer}}
        exec_info["suggested_action"] = suggested
        exec_info["canonical_action"] = suggested
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def _image_like_boxes(screenshot_file: str) -> List[Tuple[int, int, int, int, int]]:
    image = Image.open(screenshot_file).convert("RGB")
    card = locate_captcha_area(screenshot_file) or (0, 0, image.width, image.height)
    cx1, cy1, cx2, cy2 = card
    crop = image.crop(card)
    scale = min(1.0, 520 / float(max(crop.width, crop.height)))
    scan = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))))
    pixels = scan.load()

    def image_pixel(pixel: Tuple[int, int, int]) -> bool:
        mx = max(pixel)
        mn = min(pixel)
        return mx < 246 and mn < 246 and (mx - mn > 12 or mx < 220)

    mask = [
        [image_pixel(pixels[x, y]) for x in range(scan.width)]
        for y in range(scan.height)
    ]
    inv = 1.0 / scale
    boxes: List[Tuple[int, int, int, int, int]] = []
    for x1, y1, x2, y2, count in _component_boxes(mask):
        box_w = x2 - x1
        box_h = y2 - y1
        area = box_w * box_h
        if count < 80 or box_w < 24 or box_h < 24:
            continue
        fill = count / float(max(1, area))
        if fill < 0.55:
            continue
        boxes.append((
            max(0, int(round(cx1 + x1 * inv))),
            max(0, int(round(cy1 + y1 * inv))),
            min(image.width, int(round(cx1 + x2 * inv))),
            min(image.height, int(round(cy1 + y2 * inv))),
            count,
        ))
    return boxes


def _find_missing_hole(image: Image.Image, main_bbox: Tuple[int, int, int, int]) -> Optional[Tuple[int, int, int, int]]:
    crop = image.crop(main_bbox).convert("RGB")
    scale = min(1.0, 420 / float(max(crop.width, crop.height)))
    scan = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))))
    pixels = scan.load()

    def hole_pixel(pixel: Tuple[int, int, int]) -> bool:
        mean = sum(pixel) / 3.0
        return 120 <= mean <= 235 and max(pixel) - min(pixel) <= 42

    mask = [
        [hole_pixel(pixels[x, y]) for x in range(scan.width)]
        for y in range(scan.height)
    ]
    candidates: List[Tuple[float, Tuple[int, int, int, int, int]]] = []
    min_side = max(10, int(min(scan.width, scan.height) * 0.10))
    max_side = max(min_side + 1, int(min(scan.width, scan.height) * 0.38))
    for box in _component_boxes(mask):
        x1, y1, x2, y2, count = box
        box_w = x2 - x1
        box_h = y2 - y1
        if box_w < min_side or box_h < min_side or box_w > max_side or box_h > max_side:
            continue
        ratio = box_w / float(max(1, box_h))
        if not 0.65 <= ratio <= 1.55:
            continue
        fill = count / float(max(1, box_w * box_h))
        if fill < 0.55:
            continue
        score = fill * 2.0 + (1.0 - min(abs(1.0 - ratio), 0.5))
        candidates.append((score, box))
    if not candidates:
        return None

    _, best = max(candidates, key=lambda item: item[0])
    x1, y1, x2, y2, _ = best
    inv = 1.0 / scale
    mx1, my1, _, _ = main_bbox
    return (
        int(round(mx1 + x1 * inv)),
        int(round(my1 + y1 * inv)),
        int(round(mx1 + x2 * inv)),
        int(round(my1 + y2 * inv)),
    )


def _strip_mse(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    rms = ImageStat.Stat(diff).rms
    if not rms:
        return 0.0
    return sum(value * value for value in rms) / len(rms)


def _candidate_edge_score(
    image: Image.Image,
    main_bbox: Tuple[int, int, int, int],
    hole_bbox: Tuple[int, int, int, int],
    candidate_bbox: Tuple[int, int, int, int],
) -> float:
    hx1, hy1, hx2, hy2 = hole_bbox
    mx1, my1, mx2, my2 = main_bbox
    strip = max(4, min(16, (hx2 - hx1) // 8, (hy2 - hy1) // 8))
    target_w = max(16, hx2 - hx1)
    target_h = max(16, hy2 - hy1)
    candidate = image.crop(candidate_bbox).resize((target_w, target_h), Image.LANCZOS)

    refs = [
        image.crop((max(mx1, hx1 - strip), hy1, hx1, hy2)).resize((strip, 96), Image.LANCZOS),
        image.crop((hx2, hy1, min(mx2, hx2 + strip), hy2)).resize((strip, 96), Image.LANCZOS),
        image.crop((hx1, max(my1, hy1 - strip), hx2, hy1)).resize((96, strip), Image.LANCZOS),
        image.crop((hx1, hy2, hx2, min(my2, hy2 + strip))).resize((96, strip), Image.LANCZOS),
    ]
    edges = [
        candidate.crop((0, 0, strip, target_h)).resize((strip, 96), Image.LANCZOS),
        candidate.crop((target_w - strip, 0, target_w, target_h)).resize((strip, 96), Image.LANCZOS),
        candidate.crop((0, 0, target_w, strip)).resize((96, strip), Image.LANCZOS),
        candidate.crop((0, target_h - strip, target_w, target_h)).resize((96, strip), Image.LANCZOS),
    ]
    return sum(_strip_mse(edge, ref) for edge, ref in zip(edges, refs))


def _draw_match_overlay(
    image: Image.Image,
    output_dir: Path,
    main_bbox: Tuple[int, int, int, int],
    hole_bbox: Tuple[int, int, int, int],
    candidates: List[Tuple[int, int, int, int]],
    scores: List[float],
    best_index: int,
) -> str:
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(main_bbox, outline=(0, 180, 255), width=4)
    draw.rectangle(hole_bbox, outline=(255, 0, 0), width=4)
    for index, bbox in enumerate(candidates):
        color = (0, 200, 0) if index == best_index else (255, 165, 0)
        draw.rectangle(bbox, outline=color, width=4)
        draw.text((bbox[0] + 8, max(0, bbox[1] - 22)), f"{index}: {scores[index]:.0f}", fill=color)
    path = output_dir / "find_match_overlay.jpg"
    overlay.save(path, "JPEG", quality=95)
    return str(path)


def _heuristic_find_match(context: ToolContext) -> Optional[Dict[str, Any]]:
    image = Image.open(context.screenshot_file).convert("RGB")
    boxes = _image_like_boxes(context.screenshot_file)
    if len(boxes) < 3:
        return None

    def box_area(box: Tuple[int, int, int, int, int]) -> int:
        return max(0, box[2] - box[0]) * max(0, box[3] - box[1])

    main_box = max(boxes, key=box_area)
    main_bbox = tuple(main_box[:4])
    main_area = box_area(main_box)
    candidates: List[Tuple[int, int, int, int]] = []
    for box in boxes:
        bbox = tuple(box[:4])
        if bbox == main_bbox:
            continue
        box_w = bbox[2] - bbox[0]
        box_h = bbox[3] - bbox[1]
        area = box_w * box_h
        ratio = box_w / float(max(1, box_h))
        if bbox[1] <= main_bbox[1] or area > main_area * 0.55:
            continue
        if 0.65 <= ratio <= 1.55 and area >= main_area * 0.08:
            candidates.append(bbox)
    candidates = sorted(candidates, key=lambda box: (box[1], box[0]))
    if not candidates:
        return None

    hole_bbox = _find_missing_hole(image, main_bbox)
    if hole_bbox is None:
        return None

    scores = [
        _candidate_edge_score(image, main_bbox, hole_bbox, candidate)
        for candidate in candidates
    ]
    best_index = min(range(len(scores)), key=lambda idx: scores[idx])
    ordered_scores = sorted(scores)
    if len(ordered_scores) >= 2 and ordered_scores[1] > 0:
        confidence = max(0.0, min(1.0, (ordered_scores[1] - ordered_scores[0]) / ordered_scores[1]))
    else:
        confidence = 1.0
    overlay = _draw_match_overlay(
        image,
        _crop_dir(context),
        main_bbox,
        hole_bbox,
        candidates,
        scores,
        best_index,
    )
    return {
        "candidate_index": best_index,
        "candidate_number": best_index + 1,
        "candidate_bbox": list(candidates[best_index]),
        "candidate_bboxes": [list(item) for item in candidates],
        "candidate_scores": [round(score, 2) for score in scores],
        "confidence": round(confidence, 3),
        "main_bbox": list(main_bbox),
        "hole_bbox": list(hole_bbox),
        "prompt_image": overlay,
    }


def _find_match_result_from_index(
    index_zero_based: int,
    *,
    method: str,
    crop: str,
    heuristic: Optional[Dict[str, Any]],
    raw_model_output: str = "",
) -> ToolResult:
    exec_info: Dict[str, Any] = {
        "action_type": "find_match",
        "tool_name": "FindMatch",
        "read_only": True,
        "label": f"FindMatch -> candidate index {index_zero_based}",
        "candidate_index": index_zero_based,
        "candidate_number": index_zero_based + 1,
        "match_method": method,
        "prompt_image": crop,
        "raw_model_output": raw_model_output,
    }
    if heuristic:
        exec_info.update({
            "candidate_bbox": heuristic.get("candidate_bbox"),
            "candidate_bboxes": heuristic.get("candidate_bboxes"),
            "candidate_scores": heuristic.get("candidate_scores"),
            "match_confidence": heuristic.get("confidence"),
            "main_bbox": heuristic.get("main_bbox"),
            "hole_bbox": heuristic.get("hole_bbox"),
            "prompt_image": heuristic.get("prompt_image") or crop,
        })
    bbox = exec_info.get("candidate_bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        suggested = f"TapRegionCenter({bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]})"
    else:
        suggested = f"TapGridCell({index_zero_based})"
    exec_info["suggested_next_actions"] = [suggested]
    exec_info["prompt_feedback"] = (
        f"The best matching candidate is zero-based index {index_zero_based} "
        f"(candidate #{index_zero_based + 1} if counted from 1). Use `{suggested}`, "
        "then submit after visually confirming the selection."
    )
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def execute_find_match(action: str, context: ToolContext, match) -> ToolResult:
    crop = _captcha_crop(context, "find_match.jpg")
    heuristic = _heuristic_find_match(context)
    if heuristic is not None and float(heuristic.get("confidence", 0.0)) >= 0.18:
        return _find_match_result_from_index(
            int(heuristic["candidate_index"]),
            method="local_edge_match",
            crop=crop,
            heuristic=heuristic,
        )

    prompt = (
        "This is a 'missing piece' captcha: a main image has one missing square, and "
        "several candidate patches are shown (numbered left to right starting at 1). "
        "Which candidate correctly completes the missing area? Answer ONLY the index number."
    )
    out = _vlm_read(context, crop, prompt)
    idx = None
    if out:
        m = re.search(r"\d+", out)
        if m:
            idx = int(m.group(0))
    candidate_count = len(heuristic.get("candidate_bboxes", [])) if heuristic else 0
    if idx is not None:
        if candidate_count and 1 <= idx <= candidate_count:
            return _find_match_result_from_index(
                idx - 1,
                method="vlm_1_based",
                crop=crop,
                heuristic=heuristic,
                raw_model_output=out or "",
            )
        if candidate_count and 0 <= idx < candidate_count:
            return _find_match_result_from_index(
                idx,
                method="vlm_0_based",
                crop=crop,
                heuristic=heuristic,
                raw_model_output=out or "",
            )
        if idx > 0:
            return _find_match_result_from_index(
                idx - 1,
                method="vlm_1_based_no_geometry",
                crop=crop,
                heuristic=heuristic,
                raw_model_output=out or "",
            )
    if heuristic is not None:
        return _find_match_result_from_index(
            int(heuristic["candidate_index"]),
            method="local_edge_match_low_confidence",
            crop=crop,
            heuristic=heuristic,
            raw_model_output=out or "",
        )
    if idx is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "find_match", "tool_name": "FindMatch", "read_only": True,
            "label": "FindMatch (failed)", "prompt_image": crop,
            "prompt_feedback": "Could not determine the matching candidate; compare them visually.",
            "error": "read_failed",
        })
    return _find_match_result_from_index(
        idx - 1,
        method="vlm_1_based_no_geometry",
        crop=crop,
        heuristic=heuristic,
        raw_model_output=out or "",
    )


def _all_five_lines() -> List[List[Tuple[int, int]]]:
    lines: List[List[Tuple[int, int]]] = []
    for r in range(5):
        lines.append([(r, c) for c in range(5)])
    for c in range(5):
        lines.append([(r, c) for r in range(5)])
    lines.append([(i, i) for i in range(5)])
    lines.append([(i, 4 - i) for i in range(5)])
    return lines


def _classify_board_cell(mean: List[float]) -> Optional[str]:
    r, g, b = mean
    avg = (r + g + b) / 3.0
    spread = max(mean) - min(mean)
    if b > r + 25 and b > g + 5:
        return "blue"
    if r > 185 and g > 160 and b < 190 and r >= g - 5:
        return "yellow"
    if avg < 175 and spread < 75:
        return "black"
    if avg > 220 and spread < 38:
        return "white"
    if spread < 30 and 145 < avg < 232:
        return None
    return "unknown"


def _detect_colored_board(
    image: Image.Image,
    geometry,
) -> List[List[Optional[str]]]:
    x1, y1, x2, y2 = geometry.bbox
    rows, cols = geometry.rows, geometry.cols
    cell_w = (x2 - x1) / float(cols)
    cell_h = (y2 - y1) / float(rows)
    board: List[List[Optional[str]]] = []
    for r in range(rows):
        row: List[Optional[str]] = []
        for c in range(cols):
            left = int(round(x1 + (c + 0.18) * cell_w))
            top = int(round(y1 + (r + 0.18) * cell_h))
            right = int(round(x1 + (c + 0.82) * cell_w))
            bottom = int(round(y1 + (r + 0.82) * cell_h))
            crop = image.crop((left, top, right, bottom)).convert("RGB")
            row.append(_classify_board_cell(ImageStat.Stat(crop).mean))
        board.append(row)
    return board


def _find_one_line_move(board: List[List[Optional[str]]]) -> Optional[Tuple[int, int, str]]:
    if len(board) != 5 or any(len(row) != 5 for row in board):
        return None
    lines = _all_five_lines()
    for line in lines:
        values = [board[r][c] for r, c in line]
        for color in ("blue", "yellow", "black", "white"):
            if values.count(color) != 4 or values.count(None) != 1:
                continue
            dst_r, dst_c = line[values.index(None)]
            for r in range(5):
                for c in range(5):
                    if (r, c) not in line and board[r][c] == color:
                        return r * 5 + c, dst_r * 5 + dst_c, color
    return None


def _draw_board_overlay(
    image: Image.Image,
    geometry,
    board: List[List[Optional[str]]],
    output_dir: Path,
    src: int,
    dst: int,
) -> str:
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    x1, y1, x2, y2 = geometry.bbox
    rows, cols = geometry.rows, geometry.cols
    cell_w = (x2 - x1) / float(cols)
    cell_h = (y2 - y1) / float(rows)
    draw.rectangle((x1, y1, x2, y2), outline=(0, 180, 255), width=4)
    for index in range(rows * cols):
        r = index // cols
        c = index % cols
        left = int(round(x1 + c * cell_w))
        top = int(round(y1 + r * cell_h))
        right = int(round(x1 + (c + 1) * cell_w))
        bottom = int(round(y1 + (r + 1) * cell_h))
        color = (0, 220, 0) if index in {src, dst} else (255, 165, 0)
        draw.rectangle((left, top, right, bottom), outline=color, width=3)
        label = f"{index}:{board[r][c] or '-'}"
        draw.text((left + 4, top + 4), label, fill=color)
    path = output_dir / "winning_move_overlay.jpg"
    overlay.save(path, "JPEG", quality=95)
    return str(path)


def _heuristic_find_winning_move(context: ToolContext, geometry=None) -> Optional[Dict[str, Any]]:
    image = Image.open(context.screenshot_file).convert("RGB")
    geometry = geometry or locate_grid(context.screenshot_file, rows=5, cols=5)
    if geometry.rows != 5 or geometry.cols != 5:
        return None
    board = _detect_colored_board(image, geometry)
    move = _find_one_line_move(board)
    if move is None:
        return None
    src, dst, color = move
    sx, sy = geometry.cell_center(src)
    tx, ty = geometry.cell_center(dst)
    suggested = {
        "action": "move_grid_piece",
        "args": {"from_index": src, "to_index": dst, "rows": 5, "cols": 5},
    }
    overlay = _draw_board_overlay(image, geometry, board, _crop_dir(context), src, dst)
    return {
        "action_type": "find_winning_move",
        "tool_name": "FindWinningMove",
        "read_only": True,
        "label": f"FindWinningMove {src}->{dst} ({color}, local)",
        "from_cell": src,
        "to_cell": dst,
        "from_point": [sx, sy],
        "to_point": [tx, ty],
        "grid_bbox": list(geometry.bbox),
        "board_state": board,
        "move_color": color,
        "match_method": "local_color_line_solver",
        "suggested_action": suggested,
        "canonical_action": suggested,
        "prompt_image": overlay,
        "prompt_feedback": (
            f"Local board analysis found four {color} pieces plus one empty cell. "
            f"Suggested move: {src} -> {dst}. Use MoveGridPiece({src}, {dst}, 5, 5), "
            "then submit if the row/column/diagonal shows five in a row."
        ),
    }


def _parse_move(raw: str) -> Tuple[Optional[int], Optional[int]]:
    if not raw:
        return None, None
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        data = json.loads(raw[start:end])
        src = data.get("from")
        dst = data.get("to")
        if isinstance(src, int) and isinstance(dst, int):
            return src, dst
    except Exception:
        pass
    numbers = [int(item) for item in re.findall(r"\d+", raw)]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    return None, None


def execute_find_winning_move(action: str, context: ToolContext, match) -> ToolResult:
    geometry = locate_grid(context.screenshot_file, rows=5, cols=5)
    if not geometry.detected:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "find_winning_move",
            "tool_name": "FindWinningMove",
            "read_only": True,
            "label": "FindWinningMove (not applicable)",
            "not_applicable": True,
            "diagnostic_reason": "five_by_five_board_not_detected",
            "prompt_feedback": (
                "This tool is not applicable because no visible 5x5 board was detected. "
                "Use a tool matching the actual grid or interaction affordance."
            ),
            "error": "not_applicable",
        })
    local = _heuristic_find_winning_move(context, geometry)
    if local is not None:
        return ToolResult(handled=True, keep_running=True, exec_info=local)

    crop = _captcha_crop(context, "winning_move_board.jpg")
    prompt = (
        "This is a board/grid puzzle. Cells are indexed row-major from 0 at the top-left. "
        "Find one move that best completes a line or solves the current board. Return ONLY "
        "JSON like {\"from\": 12, \"to\": 7}. If the puzzle requires a single tap instead "
        "of moving a piece, use the same index for from and to."
    )
    out = _vlm_read(context, crop, prompt) or ""
    src, dst = _parse_move(out)
    if src is None or dst is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "find_winning_move", "tool_name": "FindWinningMove",
            "read_only": True, "label": "FindWinningMove (failed)",
            "prompt_image": crop,
            "raw_model_output": out,
            "prompt_feedback": "Could not identify a winning board move. Use DetectBoard() and inspect the labeled cells manually.",
            "error": "move_not_found",
        })

    max_index = geometry.rows * geometry.cols - 1
    if not (0 <= src <= max_index and 0 <= dst <= max_index):
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "find_winning_move", "tool_name": "FindWinningMove",
            "read_only": True, "label": f"FindWinningMove invalid {src}->{dst}",
            "prompt_image": crop,
            "raw_model_output": out,
            "prompt_feedback": f"The suggested move {src}->{dst} is outside the detected 5x5 board. Re-check with DetectBoard().",
            "error": "move_out_of_range",
        })
    sx, sy = geometry.cell_center(src)
    tx, ty = geometry.cell_center(dst)
    suggested = {
        "action": "move_grid_piece",
        "args": {"from_index": src, "to_index": dst, "rows": 5, "cols": 5},
    }
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "find_winning_move", "tool_name": "FindWinningMove",
        "read_only": True,
        "label": f"FindWinningMove {src}->{dst}",
        "from_cell": src,
        "to_cell": dst,
        "from_point": [sx, sy],
        "to_point": [tx, ty],
        "grid_bbox": list(geometry.bbox),
        "suggested_action": suggested,
        "canonical_action": suggested,
        "prompt_image": crop,
        "raw_model_output": out,
        "prompt_feedback": (
            f"Suggested board move: {src} -> {dst}. Use MoveGridPiece({src}, {dst}, 5, 5). "
            "Then submit if the board visibly shows the solved line."
        ),
    })


def register_solve_tools(registry: ToolRegistry) -> None:
    registry.register(
        name="ReadClickSequence",
        pattern=r"ReadClickSequence\s*(?:\(\s*\))?",
        handler=execute_read_click_sequence,
        read_only=True,
        description=(
            "ReadClickSequence(): read the required click order. After this, detect or "
            "click the listed targets in the exact order. Read-only."
        ),
    )
    registry.register(
        name="ReadLogicPrompt",
        pattern=r"ReadLogicPrompt\s*(?:\(\s*\))?",
        handler=execute_read_logic_prompt,
        read_only=True,
        description=(
            "ReadLogicPrompt(): transcribe the current logic/arithmetic or text-answer "
            "challenge. After this, solve/input text answers or locate and tap the requested "
            "visual target; do not submit before the requested action is done. Read-only."
        ),
    )
    registry.register(
        name="SolveArithmetic",
        pattern=r"SolveArithmetic\s*<text>(?P<expr>.*?)</text>",
        handler=execute_solve_arithmetic,
        read_only=True,
        description=(
            "SolveArithmetic <text>(expression)</text>: evaluate an arithmetic expression "
            "exactly (e.g. '7 * 8 + 3'). After this, use input_text with the returned "
            "answer, then submit. Read-only."
        ),
    )
    registry.register(
        name="FindMatch",
        pattern=r"FindMatch\s*(?:\(\s*\))?",
        handler=execute_find_match,
        read_only=True,
        description=(
            "FindMatch(): for a missing-piece captcha, pick the candidate index that "
            "completes the image. Read-only."
        ),
    )
    registry.register(
        name="FindWinningMove",
        pattern=r"FindWinningMove\s*(?:\(\s*\))?",
        handler=execute_find_winning_move,
        read_only=True,
        description=(
            "FindWinningMove(): on a visible 5x5 line-completion board, find a row-major "
            "source/destination move and return a canonical MoveGridPiece action. Read-only."
        ),
        affordances=("grid_piece_move", "line_completion"),
        preconditions=("visible_5x5_board",),
    )
