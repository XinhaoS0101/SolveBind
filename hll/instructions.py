from __future__ import annotations


CAPTCHA_INSTRUCTIONS: dict[str, str] = {
    "text": """
You are on a captcha verification page. Your task is to:
1. Look at the captcha image displayed on the page
2. Identify the characters shown in the captcha image (they may be distorted)
3. Type the characters into the input field
4. Click the "Verify" button to submit

Important:
- The captcha contains {length} characters (letters and numbers)
- Characters are case-insensitive
- If the captcha image location is unclear, use `locate_captcha_area`, `crop_region`, or `zoom_region` before OCR
- Prefer using the HLL `ocr` action on the captcha image to read the characters accurately instead of guessing from the full screenshot
- Use `input_text` to type the recognized characters; it locates and focuses the input field
- Do not submit until the input field is focused and the typed text is visible or the screen state clearly changed after typing
- If tapping or typing does not visibly change the page, recover by choosing a different input-field coordinate before submitting
- If you see a success message, the task is complete
- If verification fails, use `refresh_captcha` to get a new captcha and try again
""",
    "slider": """
You are on a slider captcha verification page. Your task is to:
1. Look at the image with a dark gap/slot
2. Drag the slider at the bottom to move the puzzle piece
3. Position the puzzle piece exactly over the dark gap
4. Release to verify - the piece should fit into the gap
5. Click the "Verify" button to submit when the page requires an explicit submit

Important:
- The slider is at the bottom of the image
- Drag it horizontally to move the piece above
- Align the piece with the dark rectangular gap in the image
- Prefer calling `estimate_drag_offset` to get the exact handle drag distance, then execute the suggested `drag` in one motion
- After each drag, compare the new screenshot with the previous one; if the piece/handle did not move, change the start point or drag distance instead of repeating the same swipe
- Prefer one calibrated drag from the visible handle toward the gap; avoid many small repeated drags that do not change alignment
- If verification fails, use `refresh_captcha` and try again
""",
    "slider_real": """
You are on a slider captcha verification page with a real image background. Your task is to:
1. Look at the image - there's a dark gap/slot where a piece is missing
2. Drag the slider at the bottom to move the puzzle piece
3. Position the puzzle piece exactly over the dark gap
4. The piece shows part of the original image - match it to the gap
5. Release the drag to submit verification. If it fails, the slider will reset so you can try again

Important:
- The slider is at the bottom of the image
- Drag it horizontally to move the piece above
- Align the piece with the dark rectangular gap in the image
- Prefer calling `estimate_drag_offset` to get the exact handle drag distance, then execute the suggested `drag` in one motion
- After each drag, compare the new screenshot with the previous one; if the piece/handle did not move, change the start point or drag distance instead of repeating the same swipe
- Prefer one calibrated drag from the visible handle toward the gap; avoid many small repeated drags that do not change alignment
- If verification fails, use `refresh_captcha` and try again
""",
    "click": """
You are on a click captcha verification page. Your task is to:
1. Read the instruction at the top showing which characters to click (for example, "Click in order: A -> 5 -> K")
2. Look at the image with scattered characters
3. Click on each character in the exact order specified
4. After clicking all required characters, click "Verify"

Important:
- You must click the characters in the CORRECT ORDER shown in the instruction
- Each character will be marked with a number after you click it
- You need to click exactly {click_count} characters
- Use `read_click_sequence` or `detect_click_targets` when useful
- Use `click_target` when the target index/label is known; use raw `tap` only when no fixed tool fits
- If you make a mistake, use `clear_selection` and start over
- If verification fails, use `refresh_captcha` to get a new captcha
""",
    "click_icon": """
You are on an icon click captcha verification page. Your task is to:
1. Read the instruction at the top showing which icons to click in order
2. Look at the image with scattered icons
3. Click the icons in the exact order shown
4. After clicking all required icons, click "Verify"

Important:
- You must click the icons in the CORRECT ORDER shown in the instruction
- Each click will be marked with a number
- Use `read_click_sequence` or `detect_click_targets` when useful
- Use `click_target` when the target index/label is known; use raw `tap` only when no fixed tool fits
- If you make a mistake, use `clear_selection` and start over
- If verification fails, use `refresh_captcha` to get a new captcha
""",
    "click_real": """
You are on a click captcha verification page with a real image background. Your task is to:
1. Read the instruction at the top showing which characters to click (for example, "Click in order: A -> 5 -> K")
2. Look at the image - characters are displayed on top of a real photo
3. Click on each character in the exact order specified
4. After clicking all required characters, click "Verify"

Important:
- You must click the characters in the CORRECT ORDER shown in the instruction
- Each character will be marked with a number after you click it
- Characters may have a semi-transparent background circle to make them more visible
- You need to click exactly {click_count} characters
- Use `read_click_sequence` or `detect_click_targets` when useful
- Use `click_target` when the target index/label is known; use raw `tap` only when no fixed tool fits
- If you make a mistake, use `clear_selection` and start over
- If verification fails, use `refresh_captcha` to get a new captcha
""",
    "puzzle": """
You are on a puzzle captcha verification page. Your task is to:
1. Look at the image - there's a dark silhouette/gap where a puzzle piece is missing
2. Find the puzzle piece (usually on the left side of the image)
3. Drag the puzzle piece to approximately match the gap position
4. Click "Verify" button to submit and check if correct
5. If wrong, adjust slightly and try again

Important:
- Drag the puzzle piece by clicking and holding it
- Move it both horizontally AND vertically to match the gap position
- The piece should fit precisely into the dark gap
- Use a single deliberate `drag` when possible; avoid repeated tiny drags that do not change alignment
- If verification fails, use `refresh_captcha` and try again
""",
    "puzzle_real": """
You are on a puzzle captcha verification page with a real image. Your task is to:
1. Look at the image - there's a dark silhouette/gap where a puzzle piece is missing
2. Find the puzzle piece (usually on the left side of the image)
3. Drag the puzzle piece to fit exactly into the gap
4. The piece has an irregular shape (with a bump) - match it to the gap
5. Click "Verify" to submit

Important:
- Drag the puzzle piece by clicking and holding it
- Move it both horizontally AND vertically to match the gap position
- The piece should fit precisely into the dark gap
- Use a single deliberate `drag` when possible; avoid repeated tiny drags that do not change alignment
- If verification fails, use `refresh_captcha` and try again
""",
    "pic_puzzle": """
You are on a tile-swap picture puzzle captcha page. Your task is to:
1. Look at the image grid made of small square tiles
2. Identify which two tiles are swapped and make the image look natural again
3. Drag one tile onto another tile, or tap two tiles on mobile, to swap them
4. After restoring the image, click "Verify"

Important:
- Only one pair of tiles needs to be swapped back
- The goal is to restore the original image layout
- Use `locate_grid` if you need labeled cells; then use `tap_grid_cell` or a deliberate `drag`
- If verification fails, use `refresh_captcha` and try again
""",
    "image_grid": """
You are on an image classification captcha page. Your task is to:
1. Read the category label shown at the top (for example, "cats", "cars", "mountains")
2. Look at the 3x3 grid of 9 images below
3. Click on EVERY image that contains the specified category
4. Selected images will show a green border and a checkmark; click again to deselect
5. When you have selected all matching images (and only those), click "Verify"

Important:
- You must select ALL images that match the category; missing one counts as wrong
- Do NOT select images that do NOT contain the category; extra selections also count as wrong
- Treat the grid as row-major indices 0-8: top row 0,1,2; middle row 3,4,5; bottom row 6,7,8
- When selecting an image cell, use `tap_grid_cell` instead of estimating pixel coordinates yourself
- The automation layer maps `tap_grid_cell` to the real screen coordinate; you only need to choose the correct cell index
- Do not repeat a cell that is already selected unless you intentionally need to deselect it
- If a tap does not increase/decrease the selected count or does not add a green border/checkmark, treat that tap as missed and choose the correct `tap_grid_cell` index instead of verifying
- Do not submit until the selected count matches the number of images you believe match the category
- When ready to submit, use `submit_captcha` instead of estimating the Verify button coordinates
- If you are unsure about an image, look carefully at the main subject
- If verification fails or a result dialog appears, use `refresh_captcha` to load a new challenge instead of tapping Refresh/OK/Try Again by coordinates
- The answer format submitted is the comma-separated indices of selected grid cells (0-8)
""",
    "missing_piece": """
You are on a missing-piece captcha page. Your task is to:
1. Look at the main image with one missing square area
2. Compare the candidate pieces shown below
3. Select the piece that correctly completes the missing area
4. Click "Verify" to submit

Important:
- Choose the piece that best matches the missing part of the image
- Only one candidate is correct
- Use `find_match` when useful to compare the candidates
- If verification fails, use `refresh_captcha` and try again
""",
    "logic_arithmetic": """
You are on a logic and arithmetic captcha page. Your task is to:
1. Read the current challenge carefully
2. Solve it using the controls or input field shown on the page
3. If it is a rotation task, use the arrow buttons until the character is upright
4. If it is a selection task, tap the correct letter, symbol, or target area
5. If it is a text or arithmetic task, enter the answer in the input field
6. Click "Verify" to submit

Important:
- Only one challenge is shown at a time
- Read the prompt before acting because the task type can change after refresh
- Use `read_logic_prompt` and `solve_arithmetic` when useful
- For rotation tasks, make deliberate repeated clicks if needed; do not assume one click completes the task
- If verification fails, use `refresh_captcha` to get a new challenge and try again
""",
    "five_line": """
You are on a five-in-a-row style puzzle captcha (5x5 board). Your task is to:
1. Read the instruction on the page
2. Tap one piece that has a stone, then tap an empty cell to move that stone there
3. The goal is to form a straight line of five stones of the same color (horizontal, vertical, or diagonal)
4. Click "Verify" after your move

Important:
- Move a stone to an empty slot
- The final board must contain five identical stones in a row
- Use `detect_board` or `find_winning_move` when useful
- If verification fails, use `refresh_captcha` for a new board
""",
}

for dynamic_type, base_type in {
    "slider_real_dynamic": "slider_real",
    "click_real_dynamic": "click_real",
    "click_icon_dynamic": "click_icon",
    "puzzle_real_dynamic": "puzzle_real",
    "pic_puzzle_dynamic": "pic_puzzle",
    "image_grid_dynamic": "image_grid",
    "missing_piece_dynamic": "missing_piece",
    "logic_arithmetic_dynamic": "logic_arithmetic",
    "five_line_dynamic": "five_line",
}.items():
    CAPTCHA_INSTRUCTIONS[dynamic_type] = (
        CAPTCHA_INSTRUCTIONS[base_type]
        + """

Additional dynamic requirement:
- Interact with the page in a deliberate, human-like way instead of submitting instantly
"""
    )


DISTRACTION_INSTRUCTION_PREFIX = """
CRITICAL: This page simulates a real webpage with distracting elements.

You must:
1. FIRST identify the REAL captcha verification area on the page
2. IGNORE all fake/decoy elements such as:
   - Fake navigation links (Home, Products, etc.)
   - Fake sidebar menus
   - Fake buttons that say "Submit", "Verify", "Continue" outside the captcha area
   - Fake input fields in form-like sections
   - Content cards (products, posts, articles)
   - Any element that is NOT inside the actual captcha verification box
3. The REAL captcha is usually in a white card/box labeled "Complete Verification"
4. If you click on any decoy element, you will FAIL immediately

After identifying the real captcha area, complete the following task:
"""

DISTRACTION_INSTRUCTION_SUFFIX = """

Remember: Focus ONLY on the real captcha area. Clicking anywhere outside of it (on decoy elements) will cause immediate failure!
"""

HLL_ACTION_SUFFIX = """

HLL action interface reminder:
- Return exactly one JSON action object, not raw tool-call text or prose.
- Use the HLL action names from the system prompt, such as `ocr`, `input_text`, `estimate_drag_offset`, `tap_grid_cell`, `click_target`, `find_match`, `find_winning_move`, `submit_captcha`, and `refresh_captcha`.
"""


TASK_ACTION_GUIDANCE: dict[str, tuple[tuple[str, ...], str]] = {
    "text": (
        (
            "locate_captcha_area",
            "crop_region",
            "zoom_region",
            "ocr",
            "input_text",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `locate_captcha_area`, `crop_region`, or `zoom_region` if the character image location is unclear, then `ocr` on the character image, then `input_text`, then `submit_captcha`; after a failed verification, use `refresh_captcha`.",
    ),
    "slider": (
        (
            "estimate_drag_offset",
            "drag",
            "correct_slider_after_failure",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `estimate_drag_offset` first, execute the returned canonical `drag`, use `submit_captcha` only when the page requires explicit verification, and use `correct_slider_after_failure` or `refresh_captcha` after failure.",
    ),
    "slider_real": (
        (
            "estimate_drag_offset",
            "drag",
            "correct_slider_after_failure",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `estimate_drag_offset` first, execute the returned canonical `drag`, use `submit_captcha` only when the page requires explicit verification, and use `correct_slider_after_failure` or `refresh_captcha` after failure.",
    ),
    "click": (
        (
            "read_click_sequence",
            "detect_click_targets",
            "click_target",
            "tap",
            "clear_selection",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `read_click_sequence` or `detect_click_targets` when useful, select targets with `click_target` when available, use `tap` only when no fixed target tool fits, then `submit_captcha`; use `clear_selection` or `refresh_captcha` for recovery.",
    ),
    "click_icon": (
        (
            "read_click_sequence",
            "detect_click_targets",
            "click_target",
            "tap",
            "clear_selection",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `read_click_sequence` or `detect_click_targets` when useful, select targets with `click_target` when available, use `tap` only when no fixed target tool fits, then `submit_captcha`; use `clear_selection` or `refresh_captcha` for recovery.",
    ),
    "click_real": (
        (
            "read_click_sequence",
            "detect_click_targets",
            "click_target",
            "tap",
            "clear_selection",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `read_click_sequence` or `detect_click_targets` when useful, select targets with `click_target` when available, use `tap` only when no fixed target tool fits, then `submit_captcha`; use `clear_selection` or `refresh_captcha` for recovery.",
    ),
    "puzzle": (
        ("drag", "submit_captcha", "refresh_captcha"),
        "Use a deliberate `drag` to move the piece into the gap, then `submit_captcha`; after a failed verification, adjust with another `drag` or use `refresh_captcha`.",
    ),
    "puzzle_real": (
        ("drag", "submit_captcha", "refresh_captcha"),
        "Use a deliberate `drag` to move the piece into the gap, then `submit_captcha`; after a failed verification, adjust with another `drag` or use `refresh_captcha`.",
    ),
    "pic_puzzle": (
        ("locate_grid", "tap_grid_cell", "drag", "submit_captcha", "refresh_captcha"),
        "Use `locate_grid` if cell geometry is unclear, use `tap_grid_cell` or `drag` to swap the selected pair, then `submit_captcha`; after a failed verification, use `refresh_captcha`.",
    ),
    "image_grid": (
        ("locate_grid", "tap_grid_cell", "submit_captcha", "refresh_captcha"),
        "Use `locate_grid` if grid geometry is unclear, use `tap_grid_cell` for selected cells, then `submit_captcha`; after a failed verification or unusable page state, use `refresh_captcha`.",
    ),
    "missing_piece": (
        ("find_match", "click_target", "tap_region_center", "submit_captcha", "refresh_captcha"),
        "Use `find_match` when useful, choose the matching candidate with `click_target` or `tap_region_center`, then `submit_captcha`; after a failed verification, use `refresh_captcha`.",
    ),
    "logic_arithmetic": (
        (
            "read_logic_prompt",
            "solve_arithmetic",
            "tap",
            "click_target",
            "input_text",
            "drag",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `read_logic_prompt` to understand the visible challenge when useful, `solve_arithmetic` only for arithmetic expressions, then solve with `tap`, `click_target`, `input_text`, or `drag` as the visible control requires; use `submit_captcha` after the challenge appears solved and `refresh_captcha` after failure.",
    ),
    "five_line": (
        (
            "detect_board",
            "find_winning_move",
            "tap_grid_cell",
            "tap_region_center",
            "submit_captcha",
            "refresh_captcha",
        ),
        "Use `detect_board` or `find_winning_move` when useful, move the stone with `tap_grid_cell` or `tap_region_center`, then `submit_captcha`; after a failed verification, use `refresh_captcha`.",
    ),
}

RECOVERY_ACTIONS = (
    "check",
    "wait",
    "get_observation",
    "get_server_stats",
    "summarize_trajectory",
    "refresh_captcha",
    "finish",
)


def _task_action_suffix(captcha_type: str) -> str:
    task_type = captcha_type.removesuffix("_dynamic")
    if task_type not in TASK_ACTION_GUIDANCE:
        if task_type.startswith("slider"):
            task_type = "slider"
        elif task_type.startswith("click"):
            task_type = "click"
        elif task_type in {"puzzle_real", "pic_puzzle"}:
            task_type = "puzzle"
    guidance = TASK_ACTION_GUIDANCE.get(task_type)
    if guidance is None:
        return ""
    preferred_actions, suggested_flow = guidance
    preferred = ", ".join(f"`{name}`" for name in preferred_actions)
    recovery = ", ".join(f"`{name}`" for name in RECOVERY_ACTIONS)
    return f"""

Task-relevant action routing:
- Prefer this action subset for this CAPTCHA: {preferred}.
- Suggested flow: {suggested_flow}
- Use the exact action names, schemas, and meanings from the system prompt. This list is guidance, not a hard whitelist.
- General recovery and diagnostic actions remain available when needed: {recovery}.
- Avoid unrelated CAPTCHA-family actions unless the visible page clearly changes to that task type or recovery requires it.
"""


def instruction_for(
    captcha_type: str,
    *,
    length: int = 4,
    click_count: int = 3,
    distraction_level: int = 0,
) -> str:
    base_type = captcha_type.removesuffix("_dynamic")
    if base_type not in CAPTCHA_INSTRUCTIONS:
        if base_type.startswith("slider"):
            base_type = "slider"
        elif base_type.startswith("click"):
            base_type = "click"
        elif base_type in {"puzzle_real", "pic_puzzle"}:
            base_type = "puzzle"
    template = CAPTCHA_INSTRUCTIONS.get(captcha_type, CAPTCHA_INSTRUCTIONS.get(base_type, CAPTCHA_INSTRUCTIONS["text"]))
    instruction = template.format(length=int(length), click_count=int(click_count)).strip()
    if distraction_level > 0:
        instruction = (
            DISTRACTION_INSTRUCTION_PREFIX.strip()
            + "\n"
            + instruction
            + "\n"
            + DISTRACTION_INSTRUCTION_SUFFIX.strip()
        )
    return instruction + _task_action_suffix(captcha_type) + HLL_ACTION_SUFFIX
