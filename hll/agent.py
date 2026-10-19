from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from hll.domain import Action, Decision, Observation, StepRecord, Task
from hll.model import ModelMessage, VisionModel


class InvalidModelAction(ValueError):


    def __init__(
        self,
        message: str,
        *,
        raw_response: str = "",
        usage: Mapping[str, int] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.usage = dict(usage or {})


_PROMPT_HEADER = """You control an Android browser to complete one CAPTCHA.
Use only the screenshot and task instruction. Never request or infer hidden server answers.
Return exactly one JSON object and no markdown:
{"action":"...","args":{...},"reason":"short reason"}

Choose one action from the MCP-style tool schema catalog below. The `action` field
must be the snake_case action name, and `args` must match that action's schema.
Legacy aliases such as `ocr_region`, `input_captcha_text`, `submit`, and
`refresh` are accepted, but prefer the listed action names when possible."""


_WORKFLOW_GUIDE = """### Universal CAPTCHA solving workflow ###
1. Observe the visible task, instruction, latest tool result, and workflow state before acting.
2. Identify the interaction affordance: text entry, selection, dragging, ordering, matching, arithmetic, or another visible control pattern.
3. If coordinates, text, target order, or match identity are uncertain, choose one useful perception tool before using raw coordinates.
4. If a read-only tool returns actionable evidence such as an answer, target list, sequence, suggested_action, or canonical_action, convert it into the next concrete action before replacing it with another read-only result.
5. If a tool returns suggested_action or canonical_action, execute that exact action next unless the workflow state already requires submit/check.
6. After the final required interaction appears complete, submit or check instead of inspecting repeatedly.
7. Treat workflow_state.unavailable_actions as unavailable until the page is refreshed; do not repeat the same ineffective action/tool call or another non-state-changing tool failure.
8. If a submit is rejected and the visible state is still reversible, change the failed hypothesis and correct in place once before refreshing.
9. Repeated read-only evidence without information gain must lead to a concrete action, a different evidence source, or a bounded stop."""


_CORE_ACTIONS = """### Core control actions ###
- key args_schema={"properties":{"key":{"enum":["ENTER","BACK"],"type":"string"}},"required":["key"],"type":"object"} tool=environment read_only=False: press a small set of Android keys.
- wait args_schema={"properties":{"seconds":{"type":"number"}},"required":[],"type":"object"} tool=environment read_only=True: wait briefly when the screen is changing.
- check args_schema={"properties":{},"required":[],"type":"object"} tool=evaluator read_only=True: check whether a recent submit was accepted or rejected.
- finish args_schema={"properties":{"reason":{"type":"string"}},"required":["reason"],"type":"object"} tool=workflow read_only=False: stop only when further action cannot help."""


_PROMPT_FOOTER = """Tool use policy:
- Prefer fixed tools over raw coordinates whenever they fit.
- slider: call estimate_drag_offset first, then execute the returned canonical drag.
- image_grid: use locate_grid if needed, then tap_grid_cell(index), then submit_captcha.
- ordered click targets: read the required order, detect target centers, then click each target in that exact order; prefer indexed/labeled target tools over raw taps.
- arithmetic or text-answer prompts: read the visible challenge, solve the expression if needed, then input_text with the answer and submit; do not raw-tap random answer areas unless the screen clearly presents multiple-choice buttons.
- visual logic instructions: if the page asks for logic, arithmetic, comparison, ordering, attribute matching, or marker placement, call read_logic_prompt before any tap or submit; after reading the instruction, locate the requested visible target by attribute (letter, icon, color, orientation, position, marker, or shape), use zoom/crop/classify/detect tools if uncertain, then tap the target or target region before submitting.
- text: if the character image location is uncertain, call locate_captcha_area, crop_region, or zoom_region first; then use ocr on the distorted character image.
- OCR crop guidance: crop only the full short text/string you want transcribed, including its visible border when present, not page headings, instructions, labels, or buttons.
- OCR recovery: if OCR returns empty, refusal, or likely wrong-region feedback, crop a tighter region that fully encloses the visible short character/string image, or read from the screenshot directly; never type page headings or instruction text as the answer.
- submit/recovery: use submit_captcha and refresh_captcha instead of button coordinates.
- selection state: workflow_state.selection_ledger records grid-cell action history since refresh; a repeated index may toggle an existing selection, so revisit it only for an explicit correction.
- failure-aware recovery: for tool_not_applicable re-identify the affordance; for tool_error use another available tool; for behavior_rejected keep the solution but change the interaction; for content_rejected change the failed hypothesis in place when the state is reversible, otherwise refresh.

Coordinates are absolute pixels in the attached full screenshot, matching Android input coordinates.
When acting from an attached crop or zoom, map crop-local positions back to full-screen coordinates
before tapping, dragging, or OCR-cropping. Perform one grounded action at a time. After completing
the challenge, submit/verify it. Do not request or infer hidden server answers. Use finish
only when further action cannot help. The workflow state and pending canonical action are
binding; when a tool returns suggested_action/canonical_action, execute that exact action next
without reinterpreting coordinates. Set complete=true only on the final tap or drag required
by the challenge; keep it false when more interactions remain."""


def build_tool_schema_prompt() -> str:
    from hll.tools import build_default_registry

    return build_default_registry().prompt_block()


def build_system_prompt() -> str:
    return "\n\n".join(
        [
            _PROMPT_HEADER,
            _WORKFLOW_GUIDE,
            build_tool_schema_prompt(),
            _CORE_ACTIONS,
            _PROMPT_FOOTER,
        ]
    )


SYSTEM_PROMPT = build_system_prompt()


def _history_tool_evidence(details: Mapping[str, Any]) -> dict[str, Any]:
    tool_name = str(details.get("tool_name", "") or "")
    evidence: dict[str, Any] = {}
    for key in (
        "sequence",
        "challenge",
        "target_snapshot_id",
        "answer",
        "error",
    ):
        value = details.get(key)
        if value not in (None, "", [], {}):
            evidence[key] = value
    if tool_name == "DetectClickTargets":
        targets = details.get("targets")
        if isinstance(targets, list):
            evidence["targets"] = [
                {
                    key: target[key]
                    for key in (
                        "target_id",
                        "label",
                        "role",
                        "point",
                        "bbox",
                        "description",
                        "color",
                        "orientation",
                        "size",
                    )
                    if key in target
                }
                for target in targets
                if isinstance(target, Mapping)
            ]
    elif tool_name == "ClickTarget" and isinstance(details.get("target"), Mapping):
        target = details["target"]
        evidence["clicked_target"] = {
            key: target[key]
            for key in ("target_id", "label", "role", "point")
            if key in target
        }
    feedback = str(details.get("prompt_feedback", "") or "")
    if feedback and not evidence:
        evidence["feedback"] = feedback[:1200]
    return evidence


class CaptchaAgent:
    def __init__(
        self,
        model: VisionModel,
        *,
        history_limit: int = 4,
        ocr_enabled: bool = True,
        system_prompt: str | None = None,
    ) -> None:
        self.model = model
        self.history_limit = max(0, history_limit)
        self.ocr_enabled = ocr_enabled
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.task: Task | None = None
        self.history: list[dict[str, Any]] = []

    def reset(self, task: Task) -> None:
        self.task = task
        self.history.clear()

    def decide(self, observation: Observation) -> Decision:
        history = self.history[-self.history_limit :]
        context_line = (
            f"Observation context: "
            f"{json.dumps(dict(observation.context), ensure_ascii=False)}\n"
            if observation.context
            else ""
        )
        prompt = (
            f"Task: {observation.instruction}\n"
            f"Screenshot: {observation.width}x{observation.height}\n"
            f"Step: {observation.step}\n"
            f"Last feedback: {observation.last_feedback or 'none'}\n"
            f"Latest tool result: {json.dumps(dict(observation.tool_results), ensure_ascii=False)}\n"
            f"Workflow state: {json.dumps(dict(observation.workflow_state), ensure_ascii=False)}\n"
            f"{context_line}"
            f"Recent steps: {json.dumps(history, ensure_ascii=False)}\n"
            "Choose the single best next action."
        )
        system_prompt = self.system_prompt
        if not self.ocr_enabled:
            system_prompt += "\nOCR is disabled. Do not emit the ocr action."
        messages = [ModelMessage(role="system", text=system_prompt)]
        tool_crop = str(observation.tool_results.get("crop_path", ""))
        if tool_crop:
            messages.append(
                ModelMessage(
                    role="user",
                    text=(
                        "This is the latest OCR crop. Verify the reported characters "
                        "against it before typing."
                    ),
                    image_path=tool_crop,
                )
            )
        tool_image = str(observation.tool_results.get("prompt_image", "") or "")
        if tool_image and tool_image != tool_crop and Path(tool_image).is_file():
            messages.append(
                ModelMessage(
                    role="user",
                    text=(
                        "This is the latest visual tool result. Treat its labels and "
                        "annotations as current grounded evidence for the next action."
                    ),
                    image_path=tool_image,
                )
            )
        messages.append(
            ModelMessage(
                role="user",
                text=prompt,
                image_path=observation.screenshot_path,
            )
        )
        reply = self.model.complete(messages)
        usage = dict(reply.usage)
        empty_response_retries = 0
        if not reply.text.strip():
            retry = self.model.complete(messages)
            usage = _merge_usage(usage, retry.usage)
            reply = retry
            empty_response_retries = 1
        if not reply.text.strip():
            raise InvalidModelAction(
                "model returned an empty response after one retry",
                raw_response=reply.text,
                usage=usage,
            )
        try:
            payload = extract_json_object(reply.text)
            action = Action.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise InvalidModelAction(
                str(exc),
                raw_response=reply.text,
                usage=usage,
            ) from exc
        return Decision(
            action=action,
            reason=str(payload.get("reason", payload.get("rationale", ""))),
            raw_response=reply.text,
            usage=usage,
            policy=(
                {"empty_response_retries": empty_response_retries}
                if empty_response_retries
                else {}
            ),
        )

    def update(self, record: StepRecord) -> None:
        item = {
            "step": record.step,
            "action": record.decision.action.kind.value,
            "args": dict(record.decision.action.args),
            "evaluation": record.evaluation.status.value,
            "feedback": record.evaluation.reason,
        }
        evidence = _history_tool_evidence(record.execution.details)
        if evidence:
            item["tool_evidence"] = evidence
        self.history.append(item)


def _merge_usage(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    keys = set(left) | set(right)
    return {key: int(left.get(key, 0) or 0) + int(right.get(key, 0) or 0) for key in keys}


def extract_json_object(text: str) -> Mapping[str, Any]:


    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise ValueError(f"model did not return a JSON action: {text[:500]!r}")
