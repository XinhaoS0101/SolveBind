from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from hll.domain import Action, ActionKind, Decision, ExecutionResult, Observation
from hll.model import ModelMessage, VisionModel
from hll.tools.ocr import clamp_region


class AndroidWorldOcrTool:
    """Preserve multiline app text without CAPTCHA normalization."""

    name = "ReadScreenText"

    def __init__(self, model: VisionModel) -> None:
        self.model = model

    def execute(self, action: Action, observation: Observation) -> ExecutionResult:
        started = time.monotonic()
        details: dict[str, Any] = {
            "action": ActionKind.OCR.value,
            "tool_name": self.name,
            "executor": "androidworld_tools",
            "tool_dispatch": "direct",
            "read_only": True,
        }
        try:
            region = clamp_region(action.args, observation.width, observation.height)
            x1, y1, x2, y2 = region
            crop_dir = Path(observation.screenshot_path).parent / "tool_crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            crop_path = crop_dir / (
                f"screen_text_{observation.step:03d}_{x1}_{y1}_{x2}_{y2}.png"
            )
            with Image.open(observation.screenshot_path) as source:
                source.convert("RGB").crop(region).save(crop_path, "PNG")

            structured_text = _structured_text(observation, region)
            if structured_text:
                text = structured_text
                raw_text = structured_text
                usage: Mapping[str, int] = {}
                text_source = "structured_ui"
            else:
                reply = self.model.complete(
                    [
                        ModelMessage(
                            role="user",
                            text=(
                                "Transcribe all ordinary app text visible in this image "
                                "exactly. Preserve reading order and line breaks. Return "
                                "only the text, or EMPTY when no text is visible."
                            ),
                            image_path=str(crop_path.resolve()),
                        )
                    ]
                )
                text = _clean_transcription(reply.text)
                raw_text = reply.text
                usage = reply.usage
                text_source = "vision"
            quality = _text_quality(text)
            source_label = _source_label(observation, region)
            usable_evidence = bool(text) and not quality["high_repetition"]
            details.update(
                {
                    "region": list(region),
                    "ocr_text": text,
                    "raw_text": raw_text,
                    "usage": dict(usage),
                    "text_source": text_source,
                    "prompt_image": str(crop_path.resolve()),
                    "ocr_crop_path": str(crop_path.resolve()),
                    "coordinate_space": "absolute_screen_pixels",
                    "source_label": source_label,
                    "ocr_quality": quality,
                    "usable_evidence": usable_evidence,
                }
            )
            if usable_evidence:
                details["answer"] = text
                details["prompt_feedback"] = (
                    f"Store this transcription under source {source_label!r} and use it "
                    "in the next relevant state-changing action."
                    if source_label
                    else "Preserve this transcription as evidence and use it in the next "
                    "relevant state-changing action."
                )
            elif quality["high_repetition"]:
                details["prompt_feedback"] = (
                    "This transcription has a high duplicate-line ratio and is not stored "
                    "as durable evidence. The screen may show repeated cards or thumbnails; "
                    "open the intended single source item or use a tighter crop, then read it."
                )
            else:
                details["prompt_feedback"] = (
                    "No text was found; choose a different visual region or act from other "
                    "grounded evidence."
                )
            return ExecutionResult(
                ok=True,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            details["error"] = error
            return ExecutionResult(
                ok=False,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
                error=error,
            )


class AndroidWorldToolExecutor:


    def __init__(self, executor: Any, environment: Any) -> None:
        self.executor = executor
        self.environment = environment

    def execute(
        self,
        decision: Decision,
        observation: Observation,
    ) -> ExecutionResult:
        guard_reason = self.environment.action_guard_reason(decision, observation)
        if guard_reason:
            if guard_reason == "unresolved_auto_suffix":
                feedback = (
                    "The creation form still has a separate non-empty extension or suffix, "
                    "but the requested name does not include it. Try clearing that editable "
                    "field with input_text text=\"\" and clear_text=true. If the app restores "
                    "the suffix, confirm creation once and then rename the created object to "
                    "the exact full requested name."
                )
            else:
                feedback = (
                    "This action would continue a confirmed repetition cycle and was not "
                    "executed. Capture the missing evidence or choose a different "
                    "object-level action."
                )
            result = ExecutionResult(
                ok=False,
                elapsed_seconds=0.0,
                details={
                    "action": decision.action.kind.value,
                    "args": dict(decision.action.args),
                    "executor": "androidworld_guard",
                    "recoverable": True,
                    "guard": guard_reason,
                    "error": guard_reason,
                    "prompt_feedback": feedback,
                },
                error=guard_reason,
            )
        elif decision.action.kind in {
            ActionKind.GET_OBSERVATION,
            ActionKind.SUMMARIZE_TRAJECTORY,
        }:
            result = self._trajectory_result(decision, observation)
        else:
            result = self.executor.execute(decision, observation)
        self.environment.record_execution(decision, result, observation)
        return result

    def _trajectory_result(
        self,
        decision: Decision,
        observation: Observation,
    ) -> ExecutionResult:
        started = time.monotonic()
        summary = self.environment.trajectory_summary()
        details: dict[str, Any] = {
            "action": decision.action.kind.value,
            "args": dict(decision.action.args),
            "executor": "androidworld_tools",
            "tool_dispatch": "direct",
            "read_only": True,
            "tool_name": (
                "GetObservation"
                if decision.action.kind is ActionKind.GET_OBSERVATION
                else "SummarizeTrajectory"
            ),
            "trajectory_summary": summary,
            "prompt_feedback": (
                "Use the recent native and tool actions to choose a different grounded "
                "action; do not repeat a no-effect action."
            ),
        }
        if decision.action.kind is ActionKind.GET_OBSERVATION:
            details["screen"] = {
                "path": observation.screenshot_path,
                "width": observation.width,
                "height": observation.height,
            }
            details["observation_context"] = dict(observation.context)
        return ExecutionResult(
            ok=True,
            elapsed_seconds=round(time.monotonic() - started, 4),
            details=details,
        )


def _clean_transcription(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            lines = lines[1:-1]
            text = "\n".join(lines).strip()
    return "" if text.upper() == "EMPTY" else text


def _text_quality(value: str) -> dict[str, Any]:
    lines = [" ".join(line.lower().split()) for line in value.splitlines()]
    lines = [line for line in lines if len(line) >= 3]
    counts = Counter(lines)
    duplicate_lines = sum(count - 1 for count in counts.values())
    duplicate_ratio = duplicate_lines / len(lines) if lines else 0.0
    return {
        "line_count": len(lines),
        "unique_line_count": len(counts),
        "duplicate_line_ratio": round(duplicate_ratio, 4),
        "high_repetition": len(lines) >= 8 and duplicate_ratio >= 0.5,
    }


def _source_label(
    observation: Observation,
    region: tuple[int, int, int, int],
) -> str:
    ui_elements = observation.context.get("ui_elements", [])
    if isinstance(ui_elements, list):
        candidates: list[tuple[int, str]] = []
        for item in ui_elements:
            if not isinstance(item, Mapping):
                continue
            resource = str(item.get("resource_name", ""))
            if "systemui" in resource:
                continue
            text = str(item.get("text", "") or "").strip()
            bbox = item.get("bbox")
            if not text or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            try:
                bottom = int(bbox[3])
            except (TypeError, ValueError):
                continue
            if bottom <= region[1] + 8:
                candidates.append((bottom, text[:240]))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]

    recent = observation.context.get("recent_interactions", [])
    if isinstance(recent, list):
        for item in reversed(recent):
            if isinstance(item, Mapping) and item.get("target_label"):
                return str(item["target_label"])[:240]
    return ""


def _structured_text(
    observation: Observation,
    region: tuple[int, int, int, int],
) -> str:
    ui_elements = observation.context.get("ui_elements", [])
    if not isinstance(ui_elements, list):
        return ""
    values: list[tuple[int, int, str, bool]] = []
    for item in ui_elements:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text", "") or "").strip()
        bbox = item.get("bbox")
        if (
            not text
            or "systemui" in str(item.get("resource_name", ""))
            or not isinstance(bbox, list)
            or len(bbox) != 4
        ):
            continue
        try:
            x1, y1, x2, y2 = (int(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        if x2 <= region[0] or x1 >= region[2] or y2 <= region[1] or y1 >= region[3]:
            continue
        values.append((y1, x1, text, bool(item.get("editable"))))
    if not any(editable for _, _, _, editable in values):
        return ""
    values = [item for item in values if item[3]]
    values.sort()
    ordered: list[str] = []
    for _, _, text, _ in values:
        if text not in ordered:
            ordered.append(text)
    return "\n".join(ordered)


__all__ = ["AndroidWorldOcrTool", "AndroidWorldToolExecutor"]
