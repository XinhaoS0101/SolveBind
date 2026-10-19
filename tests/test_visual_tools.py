import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from hll.tools import build_default_registry
from hll.tools.drag import _heuristic_gap_fraction, _slider_geometry, execute_estimate_drag_offset
from hll.tools.elements import (
    _parse_targets,
    execute_clear_selection,
    execute_click_target,
    execute_detect_click_targets,
)
from hll.tools.submit import execute_submit_captcha, locate_verify_button
from hll.tools.solve import (
    _classify_board_cell,
    execute_find_match,
    execute_find_winning_move,
    execute_read_click_sequence,
    execute_read_logic_prompt,
    execute_solve_arithmetic,
)
from hll.domain import Action, ActionKind, Decision, Observation
from hll.executor import HllToolExecutor, _tool_call_candidates


def _context(path: Path):
    with Image.open(path) as image:
        width, height = image.size
    cfg = SimpleNamespace(
        adb_path="adb",
        API_url="",
        token="",
        caption_model="",
        screenshot_dir=str(path.parent),
        judgement_dir=str(path.parent),
        captcha_url="http://127.0.0.1:8000",
        post_action_poll_interval_sec=0.0,
    )
    return SimpleNamespace(
        env=SimpleNamespace(cfg=cfg),
        screenshot_file=str(path),
        width=width,
        height=height,
        perception_infos=[],
        instruction="solve",
        action_history=[],
        task_profile=None,
        captcha_url=cfg.captcha_url,
        trajectory_summary={},
        click_target_snapshot=None,
    )


class VisualToolTests(unittest.TestCase):
    def test_empty_parentheses_have_registry_candidate(self):
        self.assertEqual(_tool_call_candidates("LocateGrid()"), ["LocateGrid()", "LocateGrid"])
        self.assertEqual(_tool_call_candidates("DetectBoard()"), ["DetectBoard()", "DetectBoard"])

    def test_no_arg_locate_grid_executes_without_unknown_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (320, 480), "white").save(screenshot)
            executor = HllToolExecutor(_FakeEnvironment())

            result = executor.execute(
                Decision(Action(ActionKind.LOCATE_GRID, {})),
                Observation(
                    step=0,
                    screenshot_path=str(screenshot),
                    width=320,
                    height=480,
                    instruction="select matching images",
                ),
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.details["tool_name"], "LocateGrid")
        self.assertNotEqual(result.details.get("tool_name"), "UnknownHllTool")

    def test_tap_grid_cell_accepts_rows_and_cols(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "board.png"
            image = Image.new("RGB", (600, 600), "white")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((90, 90, 510, 510), radius=16, fill=(229, 234, 240))
            image.save(screenshot)
            registry = build_default_registry()

            with patch("hll.tools.grid.tap") as tap:
                result = registry.try_execute("TapGridCell(23, 5, 5)", _context(screenshot))

        self.assertTrue(result.handled)
        self.assertFalse(result.exec_info.get("error"))
        self.assertEqual(result.exec_info["tool_name"], "TapGridCell")
        self.assertEqual(result.exec_info["grid_rows"], 5)
        self.assertEqual(result.exec_info["grid_cols"], 5)
        self.assertEqual(result.exec_info["cell_index"], 23)
        tap.assert_called_once()

    def test_tap_grid_cell_reuses_verified_grid_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (600, 600), "white").save(screenshot)
            context = _context(screenshot)
            context.grid_snapshot = {"bbox": [90, 90, 510, 510], "rows": 3, "cols": 3}
            registry = build_default_registry()

            with patch("hll.tools.grid.tap") as tap:
                result = registry.try_execute("TapGridCell(0)", context)

        self.assertTrue(result.handled)
        self.assertTrue(result.exec_info["grid_detected"])
        tap.assert_called_once_with("adb", 160, 160)

    def test_tap_grid_cell_blocks_uncertain_grid_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (600, 600), "white").save(screenshot)
            registry = build_default_registry()

            with patch("hll.tools.grid.tap") as tap:
                result = registry.try_execute("TapGridCell(0)", _context(screenshot))

        self.assertTrue(result.handled)
        self.assertEqual(result.exec_info["error"], "grid_not_detected")
        tap.assert_not_called()

    def test_slider_gap_heuristic_finds_dark_square(self):
        image = Image.new("RGB", (300, 160), (160, 190, 210))
        draw = ImageDraw.Draw(image)
        for y in range(160):
            draw.line((0, y, 300, y), fill=(120 + y // 4, 170 - y // 8, 210 - y // 6))
        draw.rectangle((190, 50, 230, 90), fill=(95, 95, 95))

        result = _heuristic_gap_fraction(image)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["fraction"], 0.7, delta=0.12)
        self.assertGreaterEqual(result["confidence"], 0.5)

    def test_find_match_converts_vlm_one_based_to_zero_based(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            with patch("hll.tools.solve._heuristic_find_match", return_value=None):
                with patch("hll.tools.solve._vlm_read", return_value="Candidate 3"):
                    result = execute_find_match("FindMatch()", _context(screenshot), None)

        self.assertTrue(result.handled)
        self.assertEqual(result.exec_info["candidate_number"], 3)
        self.assertEqual(result.exec_info["candidate_index"], 2)
        self.assertEqual(result.exec_info["suggested_next_actions"], ["TapGridCell(2)"])

    def test_empty_click_target_detection_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            with patch(
                "hll.tools.elements.detect_click_targets",
                return_value=([], str(screenshot), "", "no_targets_detected"),
            ):
                result = execute_detect_click_targets(
                    "DetectClickTargets()", _context(screenshot), None
                )

        self.assertTrue(result.handled)
        self.assertEqual(result.exec_info["error"], "no_targets_detected")
        self.assertEqual(result.exec_info["targets"], [])

    def test_click_target_parser_preserves_visual_attributes(self):
        raw = (
            '[{"label":"F","x":0.5,"y":0.25,"bbox":[0.4,0.2,0.6,0.4],'
            '"color":"green","orientation":"sideways","size":"large"}]'
        )

        targets = _parse_targets(raw, (100, 200, 500, 600))

        self.assertEqual(targets[0]["point"], [300, 300])
        self.assertEqual(targets[0]["color"], "green")
        self.assertEqual(targets[0]["orientation"], "sideways")
        self.assertEqual(targets[0]["size"], "large")
        self.assertGreater(targets[0]["area"], 0)
        self.assertEqual(targets[0]["role"], "candidate")

    def test_click_target_parser_accepts_width_normalized_y(self):
        raw = (
            '[{"label":"Clear","x":0.746,"y":1.288,'
            '"bbox":[0.685,1.258,0.808,1.318],"role":"control"}]'
        )

        targets = _parse_targets(raw, (0, 0, 1080, 1831))

        self.assertEqual(targets[0]["point"], [806, 1391])
        self.assertGreater(targets[0]["area"], 0)

    def test_click_target_parser_accepts_mixed_fraction_and_pixel_axes(self):
        raw = (
            '[{"label":"peace sign","x":0.672,"y":626,'
            '"bbox":[0.647,608,0.698,644],"role":"candidate"}]'
        )

        targets = _parse_targets(raw, (0, 0, 1080, 1831))

        self.assertEqual(targets[0]["point"], [726, 626])
        self.assertEqual(targets[0]["bbox"], [699, 608, 754, 644])
        self.assertEqual(
            targets[0]["coordinate_modes"], {"x": "fraction", "y": "pixel"}
        )

    def test_click_target_parser_scales_legacy_square_reference_coordinates(self):
        raw = (
            '[{"label":"peace","x":673.5,"y":625.5,"role":"candidate"},'
            '{"label":"Verify","x":499.5,"y":849,"role":"control"},'
            '{"label":"Refresh","x":499.5,"y":938,"role":"control"}]'
        )

        targets = _parse_targets(raw, (0, 0, 1080, 1833))

        self.assertEqual(targets[0]["point"], [727, 1147])
        self.assertEqual(targets[1]["point"], [539, 1556])
        self.assertEqual(
            targets[0]["coordinate_modes"],
            {"x": "square_1000", "y": "square_1000"},
        )

    def test_click_target_parser_honors_declared_coordinate_space(self):
        raw = (
            '{"coordinate_space":"square_1000","targets":'
            '[{"label":"target","x":250,"y":750,"role":"candidate"}]}'
        )

        targets = _parse_targets(raw, (100, 200, 1100, 2200))

        self.assertEqual(targets[0]["point"], [350, 1700])
        self.assertEqual(
            targets[0]["coordinate_modes"],
            {"x": "square_1000", "y": "square_1000"},
        )

    def test_click_target_parser_recovers_from_inconsistent_space_declaration(self):
        raw = (
            '{"coordinate_space":"fraction","targets":['
            '{"label":"umbrella","x":0.267,"y":481,"role":"candidate"},'
            '{"label":"peace","x":0.672,"y":626,"role":"candidate"}]}'
        )

        targets = _parse_targets(raw, (0, 0, 1080, 1833))

        self.assertEqual(targets[0]["point"], [288, 882])
        self.assertEqual(targets[1]["point"], [726, 1147])
        self.assertEqual(
            targets[1]["coordinate_modes"],
            {"x": "fraction", "y": "square_1000"},
        )

    def test_click_target_parser_drops_out_of_bounds_target(self):
        targets = _parse_targets('[{"label":"bad","x":2,"y":3000}]', (0, 0, 1080, 1831))
        self.assertEqual(targets, [])

    def test_clear_selection_reuses_control_target_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)
            context = _context(screenshot)
            context.click_target_snapshot = {
                "targets": [{
                    "label": "Clear",
                    "description": "clear selection button",
                    "role": "control",
                    "point": [500, 700],
                    "bbox": [460, 670, 540, 730],
                }],
            }

            with patch("hll.tools.elements.tap") as tap:
                result = execute_clear_selection("ClearSelection()", context, None)

        tap.assert_called_once_with("adb", 500, 700)
        self.assertEqual(result.exec_info["locator"], "target_snapshot")

    def test_slider_geometry_ignores_wide_logo_above_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "slider.png"
            image = Image.new("RGB", (1080, 1580), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 210, 1079, 260), fill=(92, 65, 220))
            draw.rectangle((147, 535, 934, 937), fill=(35, 110, 175))
            draw.rectangle((147, 977, 934, 1085), fill=(242, 243, 245))
            image.save(screenshot)

            with patch(
                "hll.tools.drag.locate_captcha_area",
                return_value=(0, 0, 1080, 1580),
            ):
                geometry = _slider_geometry(str(screenshot))
                with patch(
                    "hll.tools.drag._read_gap_fraction",
                    return_value={"fraction": 0.62, "method": "test", "confidence": 1.0},
                ):
                    estimate = execute_estimate_drag_offset(
                        "EstimateDragOffset()",
                        _context(screenshot),
                        None,
                    )

        self.assertIsNotNone(geometry)
        self.assertEqual(geometry["photo"], (147, 535, 934, 937))
        self.assertEqual(geometry["track"], (147, 977, 934, 1085))
        drag = estimate.exec_info["suggested_drag"]
        self.assertGreater(drag[2] - drag[0], 200)

    def test_click_target_reuses_snapshot_and_prefers_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)
            context = _context(screenshot)
            context.click_target_snapshot = {
                "snapshot_id": "snapshot-1",
                "click_count": 0,
                "targets": [
                    {
                        "label": "star",
                        "role": "reference",
                        "point": [100, 100],
                        "crop_x": 100,
                        "crop_y": 100,
                    },
                    {
                        "label": "star",
                        "role": "candidate",
                        "point": [300, 400],
                        "bbox": [280, 380, 320, 420],
                        "crop_x": 300,
                        "crop_y": 400,
                    },
                ],
            }
            match = _FakeMatch({"index": None, "label_text": "star", "label_arg": None})

            with patch("hll.tools.elements.detect_click_targets") as detect:
                with patch("hll.tools.elements.tap") as tap:
                    result = execute_click_target("ClickTarget <text>star</text>", context, match)

        detect.assert_not_called()
        tap.assert_called_once()
        self.assertEqual(result.exec_info["target"]["role"], "candidate")
        self.assertEqual(result.exec_info["target_snapshot_id"], "snapshot-1")
        self.assertNotEqual(result.exec_info["point"], [300, 400])
        self.assertGreaterEqual(abs(result.exec_info["click_offset"][0]), 8)
        self.assertEqual(context.click_target_snapshot["click_count"], 1)

    def test_click_target_blocks_reference_index(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)
            context = _context(screenshot)
            context.click_target_snapshot = {
                "snapshot_id": "snapshot-2",
                "click_count": 0,
                "targets": [{
                    "label": "instruction star",
                    "role": "reference",
                    "point": [100, 100],
                    "crop_x": 100,
                    "crop_y": 100,
                }],
            }
            match = _FakeMatch({"index": "1", "label_text": None, "label_arg": None})

            with patch("hll.tools.elements.tap") as tap:
                result = execute_click_target("ClickTarget(1)", context, match)

        tap.assert_not_called()
        self.assertEqual(result.exec_info["error"], "non_clickable_target_role")

    def test_submit_scrolls_instead_of_tapping_fixed_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            self.assertIsNone(locate_verify_button(str(screenshot)))
            with patch("hll.tools.submit.swipe", return_value=True) as swipe:
                with patch("hll.tools.submit.tap") as tap:
                    result = execute_submit_captcha(
                        "SubmitCaptcha()",
                        _context(screenshot),
                        None,
                    )

        swipe.assert_called_once()
        tap.assert_not_called()
        self.assertTrue(result.exec_info["deferred_submit"])
        self.assertFalse(result.exec_info["verification_action"])

    def test_empty_click_sequence_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            with patch("hll.tools.solve._vlm_read", return_value="   "):
                result = execute_read_click_sequence("ReadClickSequence()", _context(screenshot), None)

        self.assertTrue(result.handled)
        self.assertEqual(result.exec_info["error"], "empty_sequence")

    def test_click_sequence_suggests_target_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            with patch("hll.tools.solve._vlm_read", return_value="A, 5, K"):
                result = execute_read_click_sequence("ReadClickSequence()", _context(screenshot), None)

        self.assertTrue(result.handled)
        self.assertEqual(
            result.exec_info["canonical_action"],
            {"action": "detect_click_targets", "args": {}},
        )

    def test_logic_prompt_suggests_visual_target_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            with patch(
                "hll.tools.solve._vlm_read",
                return_value="Place the marker on the sideways uppercase E.",
            ):
                result = execute_read_logic_prompt("ReadLogicPrompt()", _context(screenshot), None)

        self.assertTrue(result.handled)
        self.assertEqual(
            result.exec_info["canonical_action"],
            {"action": "detect_click_targets", "args": {}},
        )

    def test_logic_prompt_suggests_arithmetic_solver(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            with patch("hll.tools.solve._vlm_read", return_value="What is 7 * 8 + 3?"):
                result = execute_read_logic_prompt("ReadLogicPrompt()", _context(screenshot), None)

        self.assertTrue(result.handled)
        self.assertEqual(
            result.exec_info["canonical_action"],
            {"action": "solve_arithmetic", "args": {"expr": "7 * 8 + 3"}},
        )

    def test_solve_arithmetic_suggests_input_text(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            result = execute_solve_arithmetic(
                "SolveArithmetic <text>7 * 8 + 3</text>",
                _context(screenshot),
                _FakeMatch({"expr": "7 * 8 + 3"}),
            )

        self.assertTrue(result.handled)
        self.assertEqual(result.exec_info["answer"], "59")
        self.assertEqual(
            result.exec_info["canonical_action"],
            {"action": "input_text", "args": {"text": "59"}},
        )

    def test_find_winning_move_uses_local_color_solver(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "five_line.png"
            _draw_five_line_board(screenshot)

            result = execute_find_winning_move("FindWinningMove()", _context(screenshot), None)

        self.assertTrue(result.handled)
        self.assertEqual(result.exec_info["match_method"], "local_color_line_solver")
        self.assertEqual(result.exec_info["from_cell"], 14)
        self.assertEqual(result.exec_info["to_cell"], 23)
        self.assertEqual(
            result.exec_info["canonical_action"],
            {
                "action": "move_grid_piece",
                "args": {"from_index": 14, "to_index": 23, "rows": 5, "cols": 5},
            },
        )

    def test_find_winning_move_rejects_grid_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            with patch("hll.tools.solve._vlm_read") as vlm:
                result = execute_find_winning_move(
                    "FindWinningMove()", _context(screenshot), None
                )

        vlm.assert_not_called()
        self.assertEqual(result.exec_info["error"], "not_applicable")
        self.assertEqual(
            result.exec_info["diagnostic_reason"],
            "five_by_five_board_not_detected",
        )

    def test_slider_estimator_reports_not_applicable_without_slider_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (640, 960), "white").save(screenshot)

            result = execute_estimate_drag_offset(
                "EstimateDragOffset()", _context(screenshot), None
            )

        self.assertTrue(result.exec_info["not_applicable"])
        self.assertEqual(result.exec_info["error"], "not_applicable")

    def test_board_classifier_handles_highlighted_black_pieces(self):
        self.assertEqual(_classify_board_cell([160.4, 162.4, 168.5]), "black")
        self.assertIsNone(_classify_board_cell([202.8, 209.2, 218.2]))


class _FakeEnvironment:
    adb_path = "adb"
    device_serial = ""
    captcha_url = "http://127.0.0.1:8000"

    def get_stats(self):
        return {"page_views": 1}


class _FakeMatch:
    def __init__(self, groups):
        self._groups = groups

    def group(self, name):
        return self._groups[name]

    def groupdict(self):
        return self._groups


def _draw_five_line_board(path: Path) -> None:
    image = Image.new("RGB", (720, 1080), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    bbox = (110, 260, 610, 760)
    draw.rounded_rectangle(bbox, radius=18, fill=(229, 234, 240))
    grid = [
        [None, "w", "b", "y", None],
        [None, None, "w", "y", None],
        [None, "w", "w", "y", "y"],
        [None, "k", "k", "y", None],
        ["b", "b", "k", None, "b"],
    ]
    colors = {
        "b": (42, 164, 230),
        "y": (235, 190, 45),
        "k": (45, 45, 50),
        "w": (244, 244, 246),
    }
    cell = (bbox[2] - bbox[0]) / 5.0
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            cx = int(round(bbox[0] + (c + 0.5) * cell))
            cy = int(round(bbox[1] + (r + 0.5) * cell))
            radius = 38
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(205, 213, 222))
            if value:
                draw.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), fill=colors[value])
    image.save(path)


if __name__ == "__main__":
    unittest.main()
