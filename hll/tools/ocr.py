from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Tuple

from hll.domain import Action, ExecutionResult, Observation
from hll.trace_visual import draw_region_overlay
from hll.model import ModelMessage, VisionModel
from hll.tools.base import ToolContext, ToolResult
from hll.tools.registry import ToolRegistry


DEFAULT_DETECTION_MODEL = "damo/cv_resnet18_ocr-detection-line-level_damo"
DEFAULT_RECOGNITION_MODEL = "damo/cv_convnextTiny_ocr-recognition-document_damo"


@dataclass(frozen=True)
class OcrReading:
    text: str
    raw_text: str
    engine: str
    boxes: tuple[tuple[int, int, int, int], ...] = ()
    usage: Mapping[str, int] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class OcrEngine(Protocol):
    name: str

    def recognize(self, image_path: Path) -> OcrReading: ...


class VlmOcrEngine:
    name = "vlm"

    def __init__(self, model: VisionModel, *, max_text_length: int = 16) -> None:
        self.model = model
        self.max_text_length = max(1, int(max_text_length))

    def recognize(self, image_path: Path) -> OcrReading:
        prompt = (
            "This is a cropped captcha image containing distorted characters (letters and "
            "digits). Read the characters exactly as shown, left to right. Watch for rotation, "
            "noise, and overlap. Respond with ONLY the characters — no spaces, quotes, or "
            "explanation."
        )
        reply = self.model.complete(
            [ModelMessage(role="user", text=prompt, image_path=str(image_path))]
        )
        text, parse_error = parse_vlm_ocr_text(
            reply.text,
            max_text_length=self.max_text_length,
        )
        metadata = {} if not parse_error else {"ocr_parse_error": parse_error}
        return OcrReading(
            text=text,
            raw_text=reply.text,
            engine=self.name,
            usage=reply.usage,
            metadata=metadata,
        )


class ModelScopeOcrEngine:


    name = "modelscope"

    def __init__(
        self,
        *,
        detection_model: str = DEFAULT_DETECTION_MODEL,
        recognition_model: str = DEFAULT_RECOGNITION_MODEL,
    ) -> None:
        self.detection_model = detection_model
        self.recognition_model = recognition_model
        self._detector: Any = None
        self._recognizer: Any = None

    def recognize(self, image_path: Path) -> OcrReading:
        self._load()
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "ModelScope OCR requires modelscope, opencv-python, and numpy"
            ) from exc

        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"cannot read OCR image: {image_path}")
        detected = self._detector(image)
        polygons = detected.get("polygons", [])
        readings: list[tuple[tuple[int, int, int, int], str]] = []

        for polygon in polygons:
            points = _order_points(np.asarray(polygon, dtype="float32").reshape(4, 2), np)
            crop = _perspective_crop(image, points, cv2, np)
            try:
                result = self._recognizer(crop)
                raw = result.get("text", [])
                try:
                    text = str(raw[0])
                except (IndexError, KeyError, TypeError):
                    text = str(raw)
            except Exception:
                continue
            xs = points[:, 0]
            ys = points[:, 1]
            box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            readings.append((box, text))

        readings.sort(key=lambda item: (item[0][1], item[0][0]))
        raw_text = " ".join(text for _, text in readings)
        return OcrReading(
            text=normalize_captcha_text(raw_text),
            raw_text=raw_text,
            engine=self.name,
            boxes=tuple(box for box, _ in readings),
            metadata={
                "detection_model": self.detection_model,
                "recognition_model": self.recognition_model,
            },
        )

    def _load(self) -> None:
        if self._detector is not None and self._recognizer is not None:
            return
        try:
            from modelscope import snapshot_download
            from modelscope.pipelines import pipeline
            from modelscope.utils.constant import Tasks
        except ImportError as exc:
            raise RuntimeError(
                "ModelScope OCR is not installed; install the 'modelscope-ocr' extra"
            ) from exc

        detection_path = _modelscope_model_path(self.detection_model, snapshot_download)
        recognition_path = _modelscope_model_path(self.recognition_model, snapshot_download)
        self._detector = pipeline(Tasks.ocr_detection, model=detection_path)
        self._recognizer = pipeline(Tasks.ocr_recognition, model=recognition_path)


class OcrTool:
    name = "OCRRegion"

    def __init__(
        self,
        engine: OcrEngine,
        *,
        minimum_crop_width: int = 400,
        max_suggested_text_length: int = 16,
    ) -> None:
        self.engine = engine
        self.minimum_crop_width = max(1, minimum_crop_width)
        self.max_suggested_text_length = max(1, int(max_suggested_text_length))

    def execute(self, action: Action, observation: Observation) -> ExecutionResult:
        started = time.monotonic()
        details: dict[str, Any] = {
            "action": "ocr",
            "tool_name": self.name,
            "read_only": True,
            "ocr_engine": self.engine.name,
        }
        try:
            region = clamp_region(action.args, observation.width, observation.height)
            x1, y1, x2, y2 = region
            details["region"] = list(region)
            crop_dir = Path(observation.screenshot_path).parent / "tool_crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            crop_path = crop_dir / f"ocr_{observation.step:03d}_{x1}_{y1}_{x2}_{y2}.png"

            Image = _image_module()
            with Image.open(observation.screenshot_path) as source:
                crop = source.convert("RGB").crop(region)
            scale = 1
            if crop.width < self.minimum_crop_width:
                scale = min(8, max(1, round(self.minimum_crop_width / max(1, crop.width))))
                crop = crop.resize(
                    (crop.width * scale, crop.height * scale),
                    _lanczos_filter(Image),
                )
            crop.save(crop_path, "PNG")
            details["crop_path"] = str(crop_path.resolve())
            details["crop_scale"] = scale
            overlay_path = draw_region_overlay(
                observation.screenshot_path,
                region,
                label="ocr",
                output_name=f"ocr_{observation.step:03d}_{x1}_{y1}_{x2}_{y2}_overlay.png",
            )
            if overlay_path:
                details["crop_overlay_path"] = overlay_path
            details["coordinate_space"] = "absolute_screen_pixels"
            details["screenshot_size"] = [observation.width, observation.height]

            reading = self.engine.recognize(crop_path)
            metadata = dict(reading.metadata)
            ocr_text = reading.text
            if ocr_text and len(ocr_text) > self.max_suggested_text_length:
                metadata.setdefault("ocr_parse_error", "implausible_length")
                ocr_text = ""
            details.update(
                {
                    "ocr_text": ocr_text,
                    "raw_text": reading.raw_text,
                    "boxes_in_crop": [list(box) for box in reading.boxes],
                    "usage": dict(reading.usage),
                    "engine_metadata": metadata,
                    "confusable_note": (
                        "Double-check O/0, I/1, S/5, B/8, Z/2, and G/6 against the crop."
                    ),
                }
            )
            if metadata.get("ocr_parse_error"):
                details["ocr_parse_error"] = str(metadata["ocr_parse_error"])
                details["prompt_feedback"] = _ocr_prompt_feedback(
                    str(metadata["ocr_parse_error"])
                )
            if ocr_text:
                canonical = {
                    "action": "input_text",
                    "args": {"text": ocr_text},
                }
                details["suggested_action"] = canonical
                details["canonical_action"] = canonical
            elif reading.text:
                details["suggested_action_suppressed"] = "ocr_text_too_long"
                details["max_suggested_text_length"] = self.max_suggested_text_length
            return ExecutionResult(
                ok=True,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
            )
        except Exception as exc:
            details["error"] = f"{type(exc).__name__}: {exc}"
            return ExecutionResult(
                ok=False,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
                error=details["error"],
            )


def normalize_captcha_text(value: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9]", value))


OCR_REFUSAL_MARKERS = (
    "can't help",
    "cannot help",
    "cant help",
    "i'm sorry",
    "i am sorry",
    "bypass",
    "verification challenge",
    "accessibility option",
    "contact support",
    "site support",
)

OCR_WRONG_REGION_MARKERS = (
    "captchaverification",
    "pleasecompletetheverification",
    "entercharactersshownabove",
    "verifyrefresh",
    "verificationbelow",
)


def parse_vlm_ocr_text(value: str, *, max_text_length: int = 16) -> tuple[str, str]:
    """Return (text, "") on success or ("", reason) when the reading is unusable."""

    raw = str(value or "").strip()
    if not raw:
        return "", "empty"
    if raw.lower() == "empty":
        return "", "empty"

    compact_raw = normalize_captcha_text(raw).lower()
    lower_raw = raw.lower()
    if any(marker in lower_raw for marker in OCR_REFUSAL_MARKERS):
        return "", "model_refusal"
    if any(marker in compact_raw for marker in OCR_WRONG_REGION_MARKERS):
        return "", "wrong_region_likely"

    boxed = extract_boxed_captcha_text(raw)
    text = boxed or _extract_short_ocr_candidate(raw) or normalize_captcha_text(raw)
    if not text:
        return "", "empty"
    if len(text) > max(1, int(max_text_length)):
        return "", "implausible_length"
    if any(marker in text.lower() for marker in OCR_WRONG_REGION_MARKERS):
        return "", "wrong_region_likely"
    return text, ""


def extract_boxed_captcha_text(value: str) -> str:


    for match in re.finditer(r"\\+\s*box(?:ed)?\s*\{\s*([^{}]*?)\s*\}", str(value or "")):
        text = normalize_captcha_text(match.group(1))
        if text:
            return text
    return ""


def clamp_region(args: Mapping[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    x1, x2 = sorted((max(0, min(width, int(args["x1"]))), max(0, min(width, int(args["x2"])))))
    y1, y2 = sorted((max(0, min(height, int(args["y1"]))), max(0, min(height, int(args["y2"])))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        raise ValueError(f"invalid OCR region {(x1, y1, x2, y2)} for {width}x{height}")
    return x1, y1, x2, y2


def _extract_short_ocr_candidate(value: str) -> str:
    ignored = {
        "a",
        "an",
        "and",
        "answer",
        "be",
        "captcha",
        "characters",
        "code",
        "empty",
        "is",
        "no",
        "none",
        "read",
        "reads",
        "shown",
        "string",
        "text",
        "the",
        "to",
        "visible",
    }
    candidates = [
        normalize_captcha_text(token)
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", str(value or ""))
    ]
    candidates = [
        token
        for token in candidates
        if 2 <= len(token) <= 16 and token.lower() not in ignored
    ]
    if len(candidates) == 1:
        return candidates[0]
    return ""


def _ocr_prompt_feedback(parse_error: str) -> str:
    if parse_error == "empty":
        return (
            "OCR crop did not contain a visible short alphanumeric string; select a "
            "new box that fully encloses the characters, including their border if "
            "visible, or input directly from the screenshot if readable."
        )
    if parse_error == "wrong_region_likely":
        return (
            "OCR crop likely captured page heading/instructions instead of the short "
            "character image; choose a tighter crop around the distorted characters."
        )
    if parse_error == "model_refusal":
        return (
            "OCR model did not return a transcription; use the screenshot directly or "
            "retry with a tighter crop around the short character image."
        )
    if parse_error == "implausible_length":
        return (
            "OCR output was not a short alphanumeric string; avoid headings, labels, "
            "and instruction text when selecting the crop."
        )
    return "OCR did not return a usable short alphanumeric string."


def _modelscope_model_path(model_id: str, downloader: Any) -> str:
    local = Path.home() / ".cache" / "modelscope" / "hub" / Path(*model_id.split("/"))
    return str(local) if local.is_dir() else str(downloader(model_id))


def _order_points(points: Any, np: Any) -> Any:
    centroid = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - centroid[1], points[:, 0] - centroid[0])
    ordered = points[np.argsort(angles)]
    start = int(np.argmin(ordered[:, 0] + ordered[:, 1]))
    return np.concatenate((ordered[start:], ordered[:start])).astype("float32")


def _perspective_crop(image: Any, points: Any, cv2: Any, np: Any) -> Any:
    top_left, top_right, bottom_right, bottom_left = points
    width = max(
        int(math.dist(bottom_right, bottom_left)),
        int(math.dist(top_right, top_left)),
        1,
    )
    height = max(
        int(math.dist(top_right, bottom_right)),
        int(math.dist(top_left, bottom_left)),
        1,
    )
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(points, target)
    return cv2.warpPerspective(image, matrix, (width, height))


def _image_module() -> Any:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("OCR image operations require Pillow") from exc
    return Image


def _lanczos_filter(Image: Any) -> Any:
    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def _screen_size(context: ToolContext) -> Tuple[int, int]:
    if context.width and context.height:
        return max(int(context.width), 1), max(int(context.height), 1)
    Image = _image_module()
    with Image.open(context.screenshot_file) as image:
        w, h = image.size
    return max(w, 1), max(h, 1)


def _clamp_region(x1, y1, x2, y2, width, height) -> Optional[Tuple[int, int, int, int]]:
    x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
    y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2


def _crop_dir(context: ToolContext) -> Path:
    out = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    out.mkdir(parents=True, exist_ok=True)
    return out


def execute_ocr_region(action: str, context: ToolContext, match) -> ToolResult:
    width, height = _screen_size(context)
    coords = tuple(int(match.group(n)) for n in ("x1", "y1", "x2", "y2"))
    region = _clamp_region(*coords, width=width, height=height)
    if region is None:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "ocr_region", "tool_name": "OCRRegion", "read_only": True,
            "label": f"OCRRegion {coords} (invalid)",
            "prompt_feedback": (
                f"OCRRegion received an invalid region {coords} on a {width}x{height} "
                "screen. Provide x1<x2, y1<y2 within bounds."
            ),
            "error": "invalid_region",
        })

    x1, y1, x2, y2 = region
    crop_path = str(_crop_dir(context) / f"ocr_{x1}_{y1}_{x2}_{y2}.jpg")
    Image = _image_module()
    with Image.open(context.screenshot_file) as source:
        crop = source.convert("RGB").crop((x1, y1, x2, y2))
    if crop.width < 400:
        scale = max(1, int(round(400 / max(1, crop.width))))
        crop = crop.resize((crop.width * scale, crop.height * scale), _lanczos_filter(Image))
    crop.save(crop_path, "JPEG", quality=95)

    cfg = context.env.cfg
    prompt = (
        "This is a cropped captcha image containing distorted characters (letters and "
        "digits). Read the characters exactly as shown, left to right. Watch for rotation, "
        "noise, and overlap. Respond with ONLY the characters — no spaces, quotes, or "
        "explanation."
    )
    try:
        from hll.tools.api import inference_chat
        from hll.tools.chat import add_response, init_action_chat

        chat = init_action_chat()
        chat = add_response("user", prompt, chat, crop_path)
        raw = inference_chat(
            chat,
            cfg.caption_model,
            cfg.API_url,
            cfg.token,
            billing_category="ocr",
        ) or ""
    except Exception as exc:
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "ocr_region", "tool_name": "OCRRegion", "read_only": True,
            "label": "OCRRegion (read failed)",
            "prompt_image": crop_path,
            "prompt_feedback": "OCR read failed; inspect the attached crop and read it visually.",
            "error": str(exc),
        })

    text = normalize_captcha_text(raw)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "ocr_region", "tool_name": "OCRRegion", "read_only": True,
        "label": f"OCRRegion ({x1},{y1},{x2},{y2}) -> '{text}'",
        "region": [x1, y1, x2, y2], "ocr_text": text, "prompt_image": crop_path,
        "prompt_feedback": (
            f"OCR of region ({x1}, {y1}, {x2}, {y2}) reads: '{text}'. A crop is attached "
            "as the second image — verify it before typing. Captcha matching is usually "
            "case-insensitive."
        ),
    })


_CONFUSABLE_NOTE = (
    "Common confusions to double-check against the image: O/0, l/I/1, S/5, B/8, Z/2, G/6."
)


def execute_normalize_text(action: str, context: ToolContext, match) -> ToolResult:
    raw = match.group("text")
    normalized = normalize_captcha_text(raw)
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "normalize_text", "tool_name": "NormalizeText", "read_only": True,
        "label": f"NormalizeText '{raw}' -> '{normalized}'",
        "normalized_text": normalized,
        "prompt_feedback": (
            f"Normalized text: '{normalized}' (whitespace/punctuation removed). "
            f"{_CONFUSABLE_NOTE} Type this with the Type action when the input is focused."
        ),
    })


def register_ocr_tools(registry: ToolRegistry) -> None:
    region_args = r"\(\s*(?P<x1>\d+)\s*,\s*(?P<y1>\d+)\s*,\s*(?P<x2>\d+)\s*,\s*(?P<y2>\d+)\s*\)"
    registry.register(
        name="OCRRegion",
        pattern=r"OCRRegion\s*" + region_args,
        handler=execute_ocr_region,
        read_only=True,
        description=(
            "OCRRegion(x1, y1, x2, y2): read the characters in a screen region (crops and "
            "reads it closely). Read-only; use it for text captchas instead of guessing."
        ),
    )
    registry.register(
        name="NormalizeText",
        pattern=r"NormalizeText\s*<text>(?P<text>.*?)</text>",
        handler=execute_normalize_text,
        read_only=True,
        description=(
            "NormalizeText <text>(value)</text>: strip spaces/punctuation from a captcha "
            "reading and flag confusable characters. Read-only."
        ),
    )
