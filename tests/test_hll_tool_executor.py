import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from hll.domain import Action, ActionKind, Decision, Observation
from hll.executor import _tool_call_to_hll_action
from hll.executor import HllToolExecutor


class HllToolExecutorTests(unittest.TestCase):
    def test_tool_suggested_drag_converts_to_hll_action(self):
        converted = _tool_call_to_hll_action("Drag (10, 20), (110, 20)")
        self.assertEqual(converted["action"], "drag")
        self.assertEqual(converted["args"]["x1"], 10)
        self.assertEqual(converted["args"]["x2"], 110)

    def test_tool_submit_converts_to_hll_submit(self):
        converted = _tool_call_to_hll_action("SubmitCaptcha()")
        self.assertEqual(converted["action"], "submit")
        self.assertEqual(converted["args"]["raw"], "SubmitCaptcha()")

    def test_read_only_hll_tool_executes_through_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (320, 480), "white").save(screenshot)
            env = _FakeEnvironment()
            executor = HllToolExecutor(env)

            result = executor.execute(
                Decision(Action(ActionKind.LOCATE_GRID, {"rows": 3, "cols": 3})),
                Observation(
                    step=0,
                    screenshot_path=str(screenshot),
                    width=320,
                    height=480,
                    instruction="select matching images",
                ),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.details["read_only"])
        self.assertEqual(result.details["tool_name"], "LocateGrid")
        self.assertEqual(result.details["tool_call"], "LocateGrid(3, 3)")
        self.assertEqual(result.details["tool_dispatch"], "direct")

    def test_tap_grid_cell_reuses_last_located_grid_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            image = Image.new("RGB", (480, 720), "white")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((70, 180, 410, 520), radius=12, fill=(229, 234, 240))
            image.save(screenshot)
            env = _FakeEnvironment()
            executor = HllToolExecutor(env)
            observation = Observation(
                step=0,
                screenshot_path=str(screenshot),
                width=480,
                height=720,
                instruction="select matching images",
            )

            locate = executor.execute(
                Decision(Action(ActionKind.LOCATE_GRID, {"rows": 4, "cols": 4})),
                observation,
            )
            with patch("hll.tools.grid.tap") as tap:
                tap_result = executor.execute(
                    Decision(Action(ActionKind.TAP_GRID_CELL, {"index": 10})),
                    observation,
                )

        self.assertTrue(locate.ok)
        self.assertTrue(tap_result.ok)
        self.assertEqual(tap_result.details["tool_dispatch"], "direct")
        self.assertEqual(tap_result.details["tool_call"], "TapGridCell(10, 4, 4)")
        self.assertEqual(tap_result.details["grid_rows"], 4)
        self.assertEqual(tap_result.details["grid_cols"], 4)
        self.assertEqual(tap_result.details["cell_index"], 10)
        tap.assert_called_once()

    def test_move_grid_piece_dispatches_two_cell_taps(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "board.png"
            image = Image.new("RGB", (600, 600), "white")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((90, 90, 510, 510), radius=16, fill=(229, 234, 240))
            image.save(screenshot)
            executor = HllToolExecutor(_FakeEnvironment())
            observation = Observation(
                step=0,
                screenshot_path=str(screenshot),
                width=600,
                height=600,
                instruction="move one piece",
            )

            with patch("hll.tools.grid.tap") as tap:
                with patch("hll.tools.grid.intentional_sleep"):
                    result = executor.execute(
                        Decision(
                            Action(
                                ActionKind.MOVE_GRID_PIECE,
                                {"from_index": 4, "to_index": 9, "rows": 5, "cols": 5},
                            )
                        ),
                        observation,
                    )

        self.assertTrue(result.ok)
        self.assertEqual(result.details["tool_name"], "MoveGridPiece")
        self.assertEqual(result.details["tool_call"], "MoveGridPiece(4, 9, 5, 5)")
        self.assertTrue(result.details["ready_to_submit"])
        self.assertEqual(tap.call_count, 2)


class _FakeEnvironment:
    adb_path = "adb"
    device_serial = ""
    captcha_url = "http://127.0.0.1:8000"

    def get_stats(self):
        return {"page_views": 1}


if __name__ == "__main__":
    unittest.main()
