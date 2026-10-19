from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from hll.tools.api import inference_chat
from hll.tools.chat import add_response, init_action_chat
from hll.tools.base import ToolContext, ToolResult
from hll.tools.registry import ToolRegistry


def _screen_size(context: ToolContext) -> Tuple[int, int]:
    if context.width and context.height:
        return max(int(context.width), 1), max(int(context.height), 1)
    with Image.open(context.screenshot_file) as image:
        w, h = image.size
    return max(w, 1), max(h, 1)


def _clamp_region(x1, y1, x2, y2, width, height) -> Optional[Tuple[int, int, int, int]]:
    x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
    y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2


def execute_classify_region(action: str, context: ToolContext, match) -> ToolResult:
    width, height = _screen_size(context)
    coords = tuple(int(match.group(n)) for n in ("x1", "y1", "x2", "y2"))
    region = _clamp_region(*coords, width=width, height=height)
    if region is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "classify_region", "tool_name": "ClassifyRegion", "read_only": True,
            "label": f"ClassifyRegion {coords} (invalid)",
            "prompt_feedback": (
                f"ClassifyRegion received an invalid region {coords} on a {width}x{height} "
                "screen. Provide x1<x2, y1<y2 within bounds."
            ),
            "error": "invalid_region",
        })

    x1, y1, x2, y2 = region
    out = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    out.mkdir(parents=True, exist_ok=True)
    crop_path = str(out / f"classify_{x1}_{y1}_{x2}_{y2}.jpg")
    Image.open(context.screenshot_file).convert("RGB").crop((x1, y1, x2, y2)).save(
        crop_path, "JPEG", quality=95
    )

    cfg = context.env.cfg
    prompt = (
        "Identify the main subject of this image in 1-3 words (e.g. 'bicycle', 'cat', "
        "'traffic light', 'mountain'). If it clearly shows none of a recognizable object, "
        "say 'background'. Answer with ONLY the subject words."
    )
    try:
        chat = init_action_chat()
        chat = add_response("user", prompt, chat, crop_path)
        raw = (inference_chat(chat, cfg.caption_model, cfg.API_url, cfg.token) or "").strip()
    except Exception as exc:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "classify_region", "tool_name": "ClassifyRegion", "read_only": True,
            "label": "ClassifyRegion (failed)", "prompt_image": crop_path,
            "prompt_feedback": "Classification failed; inspect the attached crop visually.",
            "error": str(exc),
        })

    subject = raw.replace("\n", " ").strip().strip(".").strip()
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "classify_region", "tool_name": "ClassifyRegion", "read_only": True,
        "label": f"ClassifyRegion ({x1},{y1},{x2},{y2}) -> '{subject}'",
        "region": [x1, y1, x2, y2], "subject": subject, "prompt_image": crop_path,
        "prompt_feedback": (
            f"The region ({x1}, {y1}, {x2}, {y2}) mainly shows: '{subject}'. A crop is "
            "attached as the second image. Compare this against the required category to "
            "decide whether to select this cell."
        ),
    })


def register_classify_tools(registry: ToolRegistry) -> None:
    region_args = r"\(\s*(?P<x1>\d+)\s*,\s*(?P<y1>\d+)\s*,\s*(?P<x2>\d+)\s*,\s*(?P<y2>\d+)\s*\)"
    registry.register(
        name="ClassifyRegion",
        pattern=r"ClassifyRegion\s*" + region_args,
        handler=execute_classify_region,
        read_only=True,
        description=(
            "ClassifyRegion(x1, y1, x2, y2): identify the main subject of a screen region. "
            "Read-only; use it to confirm whether an image-grid cell matches the category."
        ),
    )
