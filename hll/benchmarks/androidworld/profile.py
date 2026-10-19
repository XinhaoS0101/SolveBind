from __future__ import annotations

import json

from hll.domain import ActionKind
from hll.tools import build_default_registry


_HEADER = """You control an Android device to complete one general user task.
Use the screenshot, task instruction, visible UI elements, tool results, and workflow state.
Return exactly one JSON object and no markdown:
{"action":"...","args":{...},"reason":"short reason"}

Choose exactly one action from the schema catalog. The action name is snake_case and
args must match its schema. AndroidWorld's official evaluator, not the model, judges
whether the final device state is correct."""


_WORKFLOW = """### General Android task workflow ###
1. Inspect the current screenshot and structured UI elements before acting.
2. Open the required app, navigate to the requested object, then make the smallest
   state-changing action that advances the task.
3. Prefer a current UI-element index when it identifies the target unambiguously;
   otherwise use absolute screenshot coordinates.
4. Treat perception tools as normal planning actions, not last-resort fallbacks. Before
   interacting with dense text, a canvas, a small visual target, or evidence needed in
   another app, proactively choose the single tool that best grounds the next action.
5. Before OCR, open the intended single source item. Do not treat a list, thumbnail grid,
   or repeated-card overview as one document. If OCR reports unusable repeated evidence,
   open the source item or tighten the crop before continuing.
6. Act on a useful tool result immediately. Do not replace actionable text, coordinates,
   or target evidence with another inspection, and do not repeat an equivalent tool call.
7. When a task transfers visible content between apps, capture the source facts with OCR,
   crop, zoom, or classification before opening the destination app. If the destination
   was opened without the needed evidence, return once to capture it; never alternate apps.
   Use each evidence_memory source_label to keep facts bound to the source that produced them.
8. For multi-object work, consult named_inputs and evidence_memory before acting. Reuse an
   existing destination object when required instead of recreating or renaming it per item.
9. For text transfer or transformation, preserve the requested order, capitalization, and
   whitespace exactly. When the instruction asks for a new line between the content of
   separate items, insert an empty separator line: encode every boundary as two consecutive
   newline characters (\\n\\n). One newline only starts the immediately following line.
10. In creation forms, inspect every editable name, extension, and suffix field and match the
    complete requested name exactly. If the requested name has no extension, clear an
    auto-filled extension with input_text text="" and clear_text=true before confirming. If
    the app enforces and restores that suffix, create the object and then use its rename
    operation to set and verify the exact full requested name.
11. After typing, verify the visible value and continue only if another operation is needed.
12. For information-retrieval tasks, emit answer with the requested text, then emit finish.
13. Before finish, visibly verify every requested object and its membership/content. Emit
   finish only after the requested state is achieved. Use
   {"goal_status":"infeasible"} only after bounded recovery shows the task cannot proceed.
14. If an action produces no visible state change, use the trajectory context to re-ground
    with a relevant perception tool, a different UI target, or Back."""


_CORE_ACTIONS = (
    ("click", '{"oneOf":[{"required":["index"]},{"required":["x","y"]}],"type":"object"}', "tap an element by current UI index or screenshot coordinates"),
    ("long_press", '{"oneOf":[{"required":["index"]},{"required":["x","y"]}],"type":"object"}', "long-press an element"),
    ("double_tap", '{"oneOf":[{"required":["index"]},{"required":["x","y"]}],"type":"object"}', "double-tap an element"),
    ("input_text", '{"properties":{"text":{"type":"string"},"index":{"type":"integer"},"x":{"type":"integer"},"y":{"type":"integer"},"clear_text":{"type":"boolean"}},"required":["text"],"type":"object"}', "focus an optional field and replace or clear its text; non-empty input presses Enter"),
    ("scroll", '{"properties":{"direction":{"enum":["up","down","left","right"]},"index":{"type":"integer"}},"required":["direction"],"type":"object"}', "reveal content; direction names the content direction"),
    ("open_app", '{"properties":{"app_name":{"type":"string"}},"required":["app_name"],"type":"object"}', "open an installed app by human-readable name"),
    ("navigate_back", '{"type":"object"}', "press Android Back"),
    ("navigate_home", '{"type":"object"}', "go to the Android home screen"),
    ("keyboard_enter", '{"type":"object"}', "press keyboard Enter"),
    ("answer", '{"properties":{"text":{"type":"string"}},"required":["text"],"type":"object"}', "record an answer for an information-retrieval task"),
    ("wait", '{"properties":{"seconds":{"type":"number"}},"type":"object"}', "wait briefly for a changing screen"),
    ("finish", '{"properties":{"reason":{"type":"string"},"goal_status":{"enum":["complete","infeasible"]}},"type":"object"}', "stop and ask the official evaluator to score the final state"),
)


_GENERAL_TOOL_ACTIONS = {
    ActionKind.TAP,
    ActionKind.TYPE,
    ActionKind.DRAG,
    ActionKind.DRAG_BY,
    ActionKind.CLICK_TARGET,
    ActionKind.DETECT_CLICK_TARGETS,
    ActionKind.CROP_REGION,
    ActionKind.ZOOM_REGION,
    ActionKind.CLASSIFY_REGION,
    ActionKind.GET_SCREENSHOT,
    ActionKind.GET_OBSERVATION,
    ActionKind.SUMMARIZE_TRAJECTORY,
    ActionKind.WAIT_PAGE_READY,
}


_TOOL_DESCRIPTIONS = {
    ActionKind.TAP: ("TapPoint", "tap one absolute screenshot coordinate"),
    ActionKind.TYPE: ("TypeText", "type text into the currently focused field"),
    ActionKind.DRAG: ("Drag", "drag between two absolute screenshot coordinates"),
    ActionKind.DRAG_BY: ("DragBy", "drag from a point by a relative pixel offset"),
    ActionKind.CLICK_TARGET: (
        "ClickTarget",
        "click a previously detected visual target by index or label",
    ),
    ActionKind.DETECT_CLICK_TARGETS: (
        "DetectClickTargets",
        "detect and index visible targets when UI elements do not expose them",
    ),
    ActionKind.CROP_REGION: (
        "CropRegion",
        "extract a focused screenshot region for closer visual inspection",
    ),
    ActionKind.ZOOM_REGION: (
        "Zoom",
        "enlarge a small or dense screenshot region while retaining screen coordinates",
    ),
    ActionKind.CLASSIFY_REGION: (
        "ClassifyRegion",
        "describe the visible content or affordance inside a screenshot region",
    ),
    ActionKind.GET_SCREENSHOT: (
        "GetScreenshot",
        "return the current full screenshot as grounded visual evidence",
    ),
    ActionKind.GET_OBSERVATION: (
        "GetObservation",
        "return current screen metadata plus recent native and tool actions",
    ),
    ActionKind.SUMMARIZE_TRAJECTORY: (
        "SummarizeTrajectory",
        "summarize recent native and tool actions, repeats, and no-effect actions",
    ),
    ActionKind.WAIT_PAGE_READY: (
        "WaitPageReady",
        "wait for a changing page to stabilize before the next grounded action",
    ),
    ActionKind.OCR: (
        "ReadScreenText",
        "transcribe ordinary app text in a screenshot region while preserving line breaks",
    ),
}


def build_androidworld_system_prompt(*, enable_ocr: bool = False) -> str:
    selected = set(_GENERAL_TOOL_ACTIONS)
    if enable_ocr:
        selected.add(ActionKind.OCR)

    core_lines = ["### Native Android actions ###"]
    core_lines.extend(
        f"- {name} args_schema={schema} read_only=False: {description}"
        for name, schema, description in _CORE_ACTIONS
    )

    tool_lines = ["### HLL reusable action and perception tools ###"]
    for entry in build_default_registry().schema_entries():
        try:
            kind = ActionKind(str(entry["action"]))
        except (KeyError, ValueError):
            continue
        if kind not in selected:
            continue
        schema = json.dumps(
            entry["input_schema"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        tool_name, description = _TOOL_DESCRIPTIONS.get(
            kind,
            (str(entry["tool"]), str(entry["description"])),
        )
        tool_lines.append(
            f"- {entry['action']} args_schema={schema} "
            f"tool={tool_name} read_only={str(entry['read_only']).lower()}: "
            f"{description}"
        )

    footer = (
        "Coordinates are absolute pixels in the attached full screenshot. UI indexes are "
        "valid only for the current observation. A read-only tool result appears on the "
        "next step and should normally be converted into a concrete action immediately. "
        "Execute one grounded action at a time."
    )
    return "\n\n".join(
        (_HEADER, _WORKFLOW, "\n".join(core_lines), "\n".join(tool_lines), footer)
    )


__all__ = ["build_androidworld_system_prompt"]
