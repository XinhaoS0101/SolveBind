from __future__ import annotations

import json
import hashlib
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw

from hll.tools.api import inference_chat
from hll.tools.chat import add_response, init_action_chat
from hll.tools.controller import tap
from hll.tools.base import ToolContext, ToolResult
from hll.tools.crop import locate_captcha_area
from hll.tools.registry import ToolRegistry
from hll.tools.submit import locate_verify_button


PRIMARY_BUTTON_LABELS = ("verify", "submit", "continue", "ok", "done", "next", "try again")
CLEAR_BUTTON_LABELS = ("clear", "reset", "start over", "unselect")
TARGET_ROLES = {"candidate", "control", "reference", "decoy"}
_SQUARE_REFERENCE_SIZE = 1000.0


def _screen_size(context: ToolContext) -> Tuple[int, int]:
    if context.width and context.height:
        return max(int(context.width), 1), max(int(context.height), 1)
    with Image.open(context.screenshot_file) as image:
        return max(image.width, 1), max(image.height, 1)


def _clean_text(text: str) -> str:
    text = (text or "").lower().strip()
    if text.startswith("text:"):
        text = text.split(":", 1)[1].strip()
    if text.startswith("icon:"):
        text = text.split(":", 1)[1].strip()
    return re.sub(r"\s+", " ", text)


def _label_terms(label: str) -> List[str]:
    clean = _clean_text(label)
    return [part.strip() for part in re.split(r"[,/|]", clean) if part.strip()] or [clean]


def _bbox_from_center(x: int, y: int, label: str, width: int, height: int) -> Tuple[int, int, int, int]:
    half_w = max(60, min(220, 18 * max(len(label), 4)))
    half_h = 34
    return (
        max(0, x - half_w),
        max(0, y - half_h),
        min(width - 1, x + half_w),
        min(height - 1, y + half_h),
    )


def locate_button(
    context: ToolContext,
    labels: Iterable[str],
    *,
    allow_primary_fallback: bool = True,
) -> Optional[Dict[str, Any]]:
    width, height = _screen_size(context)
    terms = [term for label in labels for term in _label_terms(label)]

    for info in context.perception_infos or []:
        text = _clean_text(str(info.get("text", "")))
        coords = info.get("coordinates")
        if not text or not isinstance(coords, list) or len(coords) != 2:
            continue
        if any(term and (term == text or term in text or text in term) for term in terms):
            x, y = int(coords[0]), int(coords[1])
            bbox = _bbox_from_center(x, y, text, width, height)
            return {
                "label": text,
                "point": [x, y],
                "bbox": list(bbox),
                "locator": "perception_text",
            }

    snapshot_match = _snapshot_button(context, terms, width, height)
    if snapshot_match is not None:
        return snapshot_match

    accessibility_match = _accessibility_button(context, terms, width, height)
    if accessibility_match is not None:
        return accessibility_match

    if allow_primary_fallback and any(term in PRIMARY_BUTTON_LABELS for term in terms):
        geometry = locate_verify_button(context.screenshot_file)
        if geometry is None:
            return None
        x, y = geometry.center()
        x = max(0, min(x, width - 1))
        y = max(0, min(y, height - 1))
        return {
            "label": "primary",
            "point": [x, y],
            "bbox": list(geometry.bbox),
            "locator": "primary_color_geometry",
        }

    return None


def _snapshot_button(
    context: ToolContext,
    terms: List[str],
    width: int,
    height: int,
) -> Optional[Dict[str, Any]]:
    snapshot = context.click_target_snapshot or {}
    for target in snapshot.get("targets", []):
        if not isinstance(target, dict) or target.get("role") != "control":
            continue
        text = _clean_text(
            f"{target.get('label', '')} {target.get('description', '')}"
        )
        point = target.get("point")
        if not any(term and term in text for term in terms):
            continue
        if not isinstance(point, list) or len(point) != 2:
            continue
        x, y = int(point[0]), int(point[1])
        if not (0 <= x < width and 0 <= y < height):
            continue
        bbox = target.get("bbox") or _bbox_from_center(x, y, text, width, height)
        return {
            "label": text,
            "point": [x, y],
            "bbox": list(bbox),
            "locator": "target_snapshot",
        }
    return None


def _accessibility_button(
    context: ToolContext,
    terms: List[str],
    width: int,
    height: int,
) -> Optional[Dict[str, Any]]:
    adb_path = str(getattr(context.env.cfg, "adb_path", "adb") or "adb")
    remote = "/sdcard/hll_tools_window.xml"
    try:
        subprocess.run(
            [adb_path, "shell", "uiautomator", "dump", remote],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result = subprocess.run(
            [adb_path, "shell", "cat", remote],
            capture_output=True,
            text=True,
            timeout=5,
        )
        root = ET.fromstring(result.stdout)
    except (OSError, subprocess.SubprocessError, ET.ParseError):
        return None

    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for node in root.iter("node"):
        text = _clean_text(
            " ".join(
                (
                    node.attrib.get("text", ""),
                    node.attrib.get("content-desc", ""),
                    node.attrib.get("resource-id", ""),
                )
            )
        )
        if not any(term and term in text for term in terms):
            continue
        numbers = [int(value) for value in re.findall(r"\d+", node.attrib.get("bounds", ""))]
        if len(numbers) != 4:
            continue
        x1, y1, x2, y2 = numbers
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        if not (0 <= x < width and 0 <= y < height and x2 > x1 and y2 > y1):
            continue
        score = int(node.attrib.get("clickable", "false") == "true")
        candidates.append((score, {
            "label": text,
            "point": [x, y],
            "bbox": [x1, y1, x2, y2],
            "locator": "accessibility_text",
        }))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _crop_dir(context: ToolContext) -> Path:
    out = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _captcha_crop(context: ToolContext, name: str) -> Tuple[str, Tuple[int, int, int, int]]:
    image = Image.open(context.screenshot_file).convert("RGB")
    region = locate_captcha_area(context.screenshot_file) or (0, 0, image.width, image.height)
    path = _crop_dir(context) / name
    image.crop(region).save(path, "JPEG", quality=95)
    return str(path), region


def _draw_targets(context: ToolContext, targets: List[Dict[str, Any]], crop_path: str) -> str:
    image = Image.open(crop_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for idx, target in enumerate(targets, start=1):
        x = int(target.get("crop_x", 0))
        y = int(target.get("crop_y", 0))
        label = str(target.get("label", idx))
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), outline=(255, 0, 0), width=4)
        draw.text((x + 16, max(0, y - 10)), f"{idx}: {label}", fill=(255, 0, 0))
    out_path = _crop_dir(context) / "click_targets_overlay.jpg"
    image.save(out_path, "JPEG", quality=95)
    return str(out_path)


def _parse_targets(raw: str, crop_bbox: Tuple[int, int, int, int]) -> List[Dict[str, Any]]:
    payload = _target_payload(raw)
    if payload is None:
        return []
    data, declared_space = payload

    x1, y1, x2, y2 = crop_bbox
    crop_w = max(1, x2 - x1)
    crop_h = max(1, y2 - y1)
    declared_modes = _declared_coordinate_modes(declared_space)
    if declared_space and declared_modes is None:
        return []
    inferred_modes = _infer_square_reference_modes(
        data,
        crop_w,
        crop_h,
    )
    if declared_modes and _coordinate_modes_fit(data, declared_modes, crop_w, crop_h):
        coordinate_modes = declared_modes
    elif declared_modes:
        repaired_modes = _repair_inconsistent_coordinate_modes(
            data,
            declared_modes,
            crop_w,
            crop_h,
        )
        if repaired_modes != (None, None):
            coordinate_modes = repaired_modes
        elif inferred_modes != (None, None):
            coordinate_modes = inferred_modes
        else:
            return []
    elif inferred_modes != (None, None):
        coordinate_modes = inferred_modes
    else:
        coordinate_modes = (None, None)
    targets: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip() or f"target-{len(targets) + 1}"
        try:
            fx = float(item.get("x"))
            fy = float(item.get("y"))
        except Exception:
            continue
        converted = _target_coordinates(
            fx,
            fy,
            crop_w,
            crop_h,
            coordinate_modes=coordinate_modes,
        )
        if converted is None:
            continue
        cx, cy, x_mode, y_mode = converted
        target: Dict[str, Any] = {
            "label": label,
            "crop_x": cx,
            "crop_y": cy,
            "point": [x1 + cx, y1 + cy],
            "coordinate_modes": {"x": x_mode, "y": y_mode},
        }
        bbox = item.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                bx1, by1, bx2, by2 = [float(value) for value in bbox]
                bx1 = _convert_bbox_coordinate(bx1, crop_w, crop_w, x_mode)
                bx2 = _convert_bbox_coordinate(bx2, crop_w, crop_w, x_mode)
                by1 = _convert_bbox_coordinate(by1, crop_h, crop_w, y_mode)
                by2 = _convert_bbox_coordinate(by2, crop_h, crop_w, y_mode)
                full_bbox = [
                    x1 + int(round(min(max(bx1, 0), crop_w))),
                    y1 + int(round(min(max(by1, 0), crop_h))),
                    x1 + int(round(min(max(bx2, 0), crop_w))),
                    y1 + int(round(min(max(by2, 0), crop_h))),
                ]
                target["bbox"] = full_bbox
                target["area"] = max(0, full_bbox[2] - full_bbox[0]) * max(
                    0,
                    full_bbox[3] - full_bbox[1],
                )
                if target["area"] == 0:
                    target.pop("bbox", None)
                    target.pop("area", None)
            except Exception:
                pass
        for key in ("description", "color", "orientation", "size"):
            value = str(item.get(key, "")).strip()
            if value:
                target[key] = value
        target["role"] = _infer_target_role(item, target)
        targets.append(target)
    return targets


def _target_payload(raw: str) -> Tuple[List[Dict[str, Any]], str] | None:
    if not raw:
        return None
    decoder = json.JSONDecoder()
    for start, char in enumerate(raw):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(raw[start:])
        except ValueError:
            continue
        if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            return payload, ""
        if not isinstance(payload, dict):
            continue
        targets = payload.get("targets")
        if not isinstance(targets, list) or not all(isinstance(item, dict) for item in targets):
            continue
        return targets, str(payload.get("coordinate_space", "") or "").strip()
    return None


def _declared_coordinate_modes(value: str) -> Tuple[str, str] | None:
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
    modes = {
        "fraction": ("fraction", "fraction"),
        "fractions": ("fraction", "fraction"),
        "normalized": ("fraction", "fraction"),
        "originalpixels": ("pixel", "pixel"),
        "pixels": ("pixel", "pixel"),
        "pixel": ("pixel", "pixel"),
        "square1000": ("square_1000", "square_1000"),
        "normalized1000": ("square_1000", "square_1000"),
    }
    return modes.get(normalized)


def _infer_square_reference_modes(
    data: List[Dict[str, Any]],
    width: int,
    height: int,
) -> Tuple[str | None, str | None]:


    if height < width * 1.25:
        return None, None
    coordinates: List[Tuple[float, float]] = []
    for item in data:
        try:
            coordinates.append((float(item.get("x")), float(item.get("y"))))
        except (TypeError, ValueError):
            continue
    if not coordinates:
        return None, None
    y_pixels = [y for _, y in coordinates if y > 1]
    if not y_pixels:
        return None, None

    # Require lower-page evidence before interpreting pixels as a 1000x1000 canvas.


    if max(y_pixels) < _SQUARE_REFERENCE_SIZE * 0.85 or max(y_pixels) > _SQUARE_REFERENCE_SIZE:
        return None, None

    x_pixels = [x for x, _ in coordinates if x > 1]
    x_mode = (
        "square_1000"
        if x_pixels and max(x_pixels) <= _SQUARE_REFERENCE_SIZE
        else None
    )
    return x_mode, "square_1000"


def _coordinate_modes_fit(
    data: List[Dict[str, Any]],
    modes: Tuple[str | None, str | None],
    width: int,
    height: int,
) -> bool:
    x_mode, y_mode = modes
    saw_coordinate = False
    for item in data:
        try:
            x = float(item.get("x"))
            y = float(item.get("y"))
        except (TypeError, ValueError):
            continue
        saw_coordinate = True
        if _target_axis_coordinate(x, width, coordinate_mode=x_mode) is None:
            return False
        if _target_axis_coordinate(
            y,
            height,
            width_fraction_base=width,
            coordinate_mode=y_mode,
        ) is None:
            return False
    return saw_coordinate


def _repair_inconsistent_coordinate_modes(
    data: List[Dict[str, Any]],
    declared_modes: Tuple[str | None, str | None],
    width: int,
    height: int,
) -> Tuple[str | None, str | None]:


    if declared_modes != ("fraction", "fraction") or height < width * 1.25:
        return None, None
    coordinates: List[Tuple[float, float]] = []
    for item in data:
        try:
            coordinates.append((float(item.get("x")), float(item.get("y"))))
        except (TypeError, ValueError):
            continue
    if not coordinates:
        return None, None
    x_values = [x for x, _ in coordinates]
    y_values = [y for _, y in coordinates]
    if not all(0 <= x <= 1 for x in x_values):
        return None, None
    if not all(0 <= y <= _SQUARE_REFERENCE_SIZE for y in y_values):
        return None, None
    if not any(y > 1 for y in y_values):
        return None, None
    return "fraction", "square_1000"


def _target_coordinates(
    x: float,
    y: float,
    width: int,
    height: int,
    *,
    coordinate_modes: Tuple[str | None, str | None] = (None, None),
) -> Tuple[int, int, str, str] | None:
    x_mode, y_mode = coordinate_modes
    x_axis = _target_axis_coordinate(x, width, coordinate_mode=x_mode)
    y_axis = _target_axis_coordinate(
        y,
        height,
        width_fraction_base=width,
        coordinate_mode=y_mode,
    )
    if x_axis is None or y_axis is None:
        return None
    cx, x_mode = x_axis
    cy, y_mode = y_axis
    return cx, cy, x_mode, y_mode


def _target_axis_coordinate(
    value: float,
    size: int,
    *,
    width_fraction_base: int | None = None,
    coordinate_mode: str | None = None,
) -> Tuple[int, str] | None:
    if coordinate_mode == "fraction":
        coordinate, mode = round(value * size), "fraction"
    elif coordinate_mode == "pixel":
        coordinate, mode = round(value), "pixel"
    elif coordinate_mode == "square_1000":
        coordinate, mode = round(value * size / _SQUARE_REFERENCE_SIZE), "square_1000"
    elif 0 <= value <= 1:
        coordinate, mode = round(value * size), "fraction"
    elif width_fraction_base and value <= size / max(width_fraction_base, 1):
        coordinate, mode = round(value * width_fraction_base), "width_fraction"
    elif 0 <= value < size:
        coordinate, mode = round(value), "pixel"
    else:
        return None
    if not 0 <= coordinate < size:
        return None
    return int(coordinate), mode


def _convert_bbox_coordinate(value: float, size: int, width: int, mode: str) -> float:
    if mode == "fraction":
        return value * size
    if mode == "width_fraction":
        return value * width
    if mode == "square_1000":
        return value * size / _SQUARE_REFERENCE_SIZE
    return value


def _infer_target_role(item: Dict[str, Any], target: Dict[str, Any]) -> str:
    explicit = str(item.get("role", "")).strip().lower()
    if explicit in TARGET_ROLES:
        return explicit
    label = _clean_text(str(target.get("label", "")))
    description = _clean_text(str(target.get("description", "")))
    combined = f"{label} {description}"
    reference_markers = (
        "instruction",
        "order prompt",
        "shown in the order",
        "shown above",
        "reference",
        "target icon",
        "match this icon",
    )
    if any(marker in combined for marker in reference_markers):
        return "reference"
    control_markers = (
        "verify",
        "refresh",
        "clear",
        "previous arrow",
        "next arrow",
        "arrow button",
        "rotate left",
        "rotate right",
        "rotate clockwise",
        "rotate counterclockwise",
    )
    if any(marker in combined for marker in control_markers):
        return "control"
    return "candidate"


def _target_snapshot_id(targets: List[Dict[str, Any]]) -> str:
    payload = json.dumps(targets, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _attach_target_ids(targets: List[Dict[str, Any]]) -> str:
    snapshot_id = _target_snapshot_id(targets)
    for index, target in enumerate(targets, start=1):
        target["target_id"] = f"{snapshot_id}:{index}"
    return snapshot_id


def detect_click_targets(
    context: ToolContext,
) -> Tuple[List[Dict[str, Any]], str, str, str]:
    crop_path, crop_bbox = _captcha_crop(context, "click_targets.jpg")
    crop_width, crop_height = crop_bbox[2] - crop_bbox[0], crop_bbox[3] - crop_bbox[1]
    prompt = (
        "Find visible click targets in this captcha/card crop. Targets may be letters, "
        "digits, icons, or selectable candidates. Include all candidates that may matter "
        "for attributes such as color, hue, upright/sideways orientation, visual size, or "
        "shape. Distinguish actual selectable candidates from instruction/reference examples, "
        "buttons/controls, and decoys. The original crop is "
        f"{crop_width}x{crop_height} pixels. Return ONLY one JSON object: "
        "{\"coordinate_space\": \"fraction\"|\"original_pixels\"|\"square_1000\", "
        "\"targets\": [{\"label\": string, \"x\": number, \"y\": number, \"role\": "
        "\"candidate\"|\"control\"|\"reference\"|\"decoy\"}]}. Use exactly one "
        "coordinate_space for every target: fraction means x,y are 0..1 within this crop; "
        "original_pixels means x is 0.."
        f"{crop_width} and y is 0..{crop_height}; square_1000 means both x,y are "
        "0..1000 on a square reference canvas. When possible also include \"bbox\" as "
        "[x1,y1,x2,y2] in the same coordinate_space and short \"description\", \"color\", "
        "\"orientation\", or \"size\" fields. If no targets are clear, return "
        "{\"coordinate_space\":\"fraction\",\"targets\":[]}."
    )
    raw = ""
    detection_error = ""
    targets: List[Dict[str, Any]] = []
    for _ in range(2):
        try:
            chat = init_action_chat()
            chat = add_response("user", prompt, chat, crop_path)
            raw = inference_chat(
                chat,
                context.env.cfg.caption_model,
                context.env.cfg.API_url,
                context.env.cfg.token,
            ) or ""
        except Exception as exc:
            raw = ""
            detection_error = f"inference_error:{type(exc).__name__}"
            continue
        if not raw.strip():
            detection_error = "empty_response"
            continue
        targets = _parse_targets(raw, crop_bbox)
        parsed_payload = _target_payload(raw)
        if targets or (parsed_payload is not None and not parsed_payload[0]):
            detection_error = "" if targets else "no_targets_detected"
            break
        detection_error = "parse_error"
    overlay = _draw_targets(context, targets, crop_path) if targets else crop_path
    return targets, overlay, raw, detection_error


def _extract_label(match) -> str:
    return (match.groupdict().get("label_text") or match.groupdict().get("label_arg") or "").strip()


def execute_locate_button(action: str, context: ToolContext, match) -> ToolResult:
    label = _extract_label(match)
    result = locate_button(context, [label])
    if result is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "locate_button",
            "tool_name": "LocateButton",
            "read_only": True,
            "label": f"LocateButton '{label}' (not found)",
            "prompt_feedback": f"Could not locate a button labeled '{label}'. Inspect the screenshot and use a different label or TapPoint.",
            "error": "not_found",
        })
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "locate_button",
        "tool_name": "LocateButton",
        "read_only": True,
        "label": f"LocateButton '{label}' -> {result['point']}",
        "button_label": result["label"],
        "button_bbox": result["bbox"],
        "point": result["point"],
        "locator": result["locator"],
        "prompt_feedback": (
            f"Located a '{label}' button near {result['point']} using {result['locator']}. "
            f"To press it, use TapPoint({result['point'][0]}, {result['point'][1]}) or SubmitPrimary if it is the main action."
        ),
    })


def execute_submit_primary(action: str, context: ToolContext, match) -> ToolResult:
    result = locate_button(context, PRIMARY_BUTTON_LABELS, allow_primary_fallback=True)
    if result is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "submit_primary",
            "tool_name": "SubmitPrimary",
            "read_only": True,
            "label": "SubmitPrimary (not found)",
            "prompt_feedback": "Could not locate a primary submit/verify/continue button. Use LocateButton(label) or inspect the screenshot before tapping.",
            "error": "not_found",
        })
    x, y = result["point"]
    tap(context.env.cfg.adb_path, x, y)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "tap",
        "tool_name": "SubmitPrimary",
        "label": f"SubmitPrimary -> Tap ({x}, {y})",
        "point": [x, y],
        "button_label": result["label"],
        "button_bbox": result["bbox"],
        "locator": result["locator"],
    })


def execute_clear_selection(action: str, context: ToolContext, match) -> ToolResult:
    result = locate_button(context, CLEAR_BUTTON_LABELS, allow_primary_fallback=False)
    if result is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "clear_selection",
            "tool_name": "ClearSelection",
            "read_only": True,
            "label": "ClearSelection (button not found)",
            "prompt_feedback": "Could not locate a Clear/Reset button. Use LocateButton(label) or recover with RefreshCaptcha() if needed.",
            "error": "not_found",
        })
    x, y = result["point"]
    tap(context.env.cfg.adb_path, x, y)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "tap",
        "tool_name": "ClearSelection",
        "label": f"ClearSelection -> Tap ({x}, {y})",
        "point": [x, y],
        "button_label": result["label"],
        "button_bbox": result["bbox"],
        "locator": result["locator"],
    })


def execute_detect_click_targets(action: str, context: ToolContext, match) -> ToolResult:
    targets, overlay, raw, detection_error = detect_click_targets(context)
    snapshot_id = _attach_target_ids(targets) if targets else ""
    feedback_lines = [f"Detected {len(targets)} possible click targets."]
    for idx, target in enumerate(targets, start=1):
        attrs = []
        for key in ("description", "color", "orientation", "size"):
            if target.get(key):
                attrs.append(f"{key}={target[key]}")
        if target.get("area"):
            attrs.append(f"area={target['area']}")
        attr_text = f" ({'; '.join(attrs)})" if attrs else ""
        feedback_lines.append(
            f"- {idx}: [{target.get('role', 'candidate')}] {target['label']} "
            f"at {target['point']}{attr_text}"
        )
    if targets:
        feedback_lines.append(
            "This indexed snapshot remains stable across subsequent ClickTarget calls. "
            "Select candidate/control targets; do not click reference or decoy targets."
        )
    else:
        feedback_lines.append("No reliable target was detected; inspect the screenshot or use another visual tool.")
    exec_info = {
        "action_type": "detect_click_targets",
        "tool_name": "DetectClickTargets",
        "read_only": True,
        "label": f"DetectClickTargets -> {len(targets)} targets",
        "targets": targets,
        "target_snapshot_id": snapshot_id,
        "raw_model_output": raw,
        "prompt_image": overlay,
        "prompt_feedback": "\n".join(feedback_lines),
    }
    coordinate_modes = sorted({
        f"x={target.get('coordinate_modes', {}).get('x', 'unknown')},"
        f"y={target.get('coordinate_modes', {}).get('y', 'unknown')}"
        for target in targets
    })
    if coordinate_modes:
        exec_info["coordinate_modes"] = coordinate_modes
    if not targets:
        exec_info["error"] = detection_error or "no_targets_detected"
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def _target_role_rank(target: Dict[str, Any]) -> int:
    return {"candidate": 0, "control": 1, "reference": 2, "decoy": 3}.get(
        str(target.get("role", "candidate")),
        3,
    )


def _safe_target_point(
    target: Dict[str, Any],
    click_count: int,
    width: int,
    height: int,
) -> Tuple[int, int, List[int]]:
    x, y = (int(value) for value in target["point"])
    offsets = ((-12, -6), (8, -12), (14, 8), (-6, 14))
    dx, dy = offsets[click_count % len(offsets)]
    bbox = target.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        bx1, by1, bx2, by2 = (int(value) for value in bbox)
        margin = 3
        if bx2 - bx1 > margin * 2:
            x = max(bx1 + margin, min(x + dx, bx2 - margin))
        if by2 - by1 > margin * 2:
            y = max(by1 + margin, min(y + dy, by2 - margin))
    else:
        x += dx
        y += dy
    x = max(0, min(x, max(0, width - 1)))
    y = max(0, min(y, max(0, height - 1)))
    return x, y, [x - int(target["point"][0]), y - int(target["point"][1])]


def execute_click_target(action: str, context: ToolContext, match) -> ToolResult:
    label = _extract_label(match)
    index_text = match.groupdict().get("index")
    snapshot = context.click_target_snapshot or {}
    targets = [dict(target) for target in snapshot.get("targets", []) if isinstance(target, dict)]
    snapshot_id = str(snapshot.get("snapshot_id", ""))
    raw = ""
    detection_error = ""
    if targets:
        overlay = _draw_targets(context, targets, _captcha_crop(context, "click_targets.jpg")[0])
    else:
        targets, overlay, raw, detection_error = detect_click_targets(context)
        snapshot_id = _attach_target_ids(targets) if targets else ""
    selected: Optional[Dict[str, Any]] = None
    if index_text:
        idx = int(index_text)
        if 1 <= idx <= len(targets):
            selected = targets[idx - 1]
    elif label:
        clean_label = _clean_text(label)
        for target in sorted(targets, key=_target_role_rank):
            target_label = _clean_text(str(target.get("label", "")))
            if clean_label == target_label or clean_label in target_label or target_label in clean_label:
                selected = target
                break

    if selected is None and label:
        button = locate_button(context, [label], allow_primary_fallback=False)
        if button:
            selected = {"label": button["label"], "point": button["point"]}

    if selected is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "click_target",
            "tool_name": "ClickTarget",
            "label": "ClickTarget (target not found)",
            "read_only": True,
            "targets": targets,
            "target_snapshot_id": snapshot_id,
            "raw_model_output": raw,
            "prompt_image": overlay,
            "prompt_feedback": "Could not find the requested click target. Inspect the attached target overlay and use ClickTarget(index) or TapPoint(x, y).",
            "error": detection_error or "not_found",
        })

    role = str(selected.get("role", "candidate"))
    if role not in {"candidate", "control"}:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "click_target",
            "tool_name": "ClickTarget",
            "label": f"ClickTarget blocked non-clickable {role} target",
            "read_only": True,
            "target": selected,
            "target_snapshot_id": snapshot_id,
            "prompt_image": overlay,
            "prompt_feedback": (
                f"The requested target is classified as {role}, not a selectable candidate "
                "or control. Choose a candidate/control target from the stable snapshot."
            ),
            "error": "non_clickable_target_role",
        })

    click_count = int(snapshot.get("click_count", 0) or 0)
    x, y, click_offset = _safe_target_point(
        selected,
        click_count,
        max(1, int(context.width)),
        max(1, int(context.height)),
    )
    if isinstance(context.click_target_snapshot, dict):
        context.click_target_snapshot["click_count"] = click_count + 1
    tap(context.env.cfg.adb_path, int(x), int(y))
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "tap",
        "tool_name": "ClickTarget",
        "label": f"ClickTarget '{selected.get('label')}' -> Tap ({x}, {y})",
        "point": [int(x), int(y)],
        "target_point": list(selected["point"]),
        "click_offset": click_offset,
        "target": selected,
        "target_snapshot_id": snapshot_id,
        "detected_targets": targets,
    })


def register_element_tools(registry: ToolRegistry) -> None:
    label_arg = r"(?:\(\s*(?P<label_arg>[^)]*?)\s*\)|<text>(?P<label_text>.*?)</text>)"
    registry.register(
        name="LocateButton",
        pattern=r"LocateButton\s*" + label_arg,
        handler=execute_locate_button,
        read_only=True,
        description=(
            "LocateButton(label): find a visible button by text label and return its point/bbox. "
            "Read-only; useful for Verify, Submit, Continue, Clear, OK, and Try Again."
        ),
    )
    registry.register(
        name="SubmitPrimary",
        pattern=r"SubmitPrimary\s*(?:\(\s*\))?",
        handler=execute_submit_primary,
        description=(
            "SubmitPrimary(): tap the page's primary submit/verify/continue button. "
            "Use it instead of estimating final submit coordinates."
        ),
    )
    registry.register(
        name="ClearSelection",
        pattern=r"ClearSelection\s*(?:\(\s*\))?",
        handler=execute_clear_selection,
        description=(
            "ClearSelection(): tap a visible Clear/Reset control to recover from wrong selections."
        ),
    )
    registry.register(
        name="DetectClickTargets",
        pattern=r"DetectClickTargets\s*(?:\(\s*\))?",
        handler=execute_detect_click_targets,
        read_only=True,
        description=(
            "DetectClickTargets(): detect visible clickable targets such as letters, icons, "
            "or candidate pieces and return indexed centers plus useful attributes such as "
            "color, orientation, size, and bbox when available. Read-only."
        ),
    )
    registry.register(
        name="ClickTarget",
        pattern=r"ClickTarget\s*(?:\(\s*(?P<index>\d+)\s*\)|<text>(?P<label_text>.*?)</text>)",
        handler=execute_click_target,
        description=(
            "ClickTarget(index or <text>label</text>): use the latest stable target snapshot "
            "and tap an indexed or labeled candidate/control inside its safe bounds."
        ),
    )
