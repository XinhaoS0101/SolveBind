import unittest

from hll.agent import extract_json_object
from hll.domain import Action, ActionKind


class ActionTests(unittest.TestCase):
    def test_ocr_action_is_structured(self):
        action = Action.from_dict(
            {"action": "ocr", "args": {"x1": 1, "y1": 2, "x2": 30, "y2": 40}}
        )
        self.assertEqual(action.kind, ActionKind.OCR)
        self.assertEqual(action.args["x2"], 30)

    def test_flat_action_is_normalized(self):
        action = Action.from_dict({"action": "tap", "x": 12, "y": 34})
        self.assertEqual(action.kind, ActionKind.TAP)
        self.assertEqual(action.args, {"x": 12, "y": 34})

    def test_invalid_action_is_trace_only_action(self):
        action = Action.from_dict({"action": "invalid_action", "args": {"message": "bad json"}})
        self.assertEqual(action.kind, ActionKind.INVALID)
        self.assertEqual(action.args["message"], "bad json")

    def test_missing_arguments_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing arguments"):
            Action.from_dict({"action": "drag", "args": {"x1": 1}})

    def test_json_can_be_extracted_from_code_fence(self):
        value = extract_json_object('```json\n{"action":"wait","args":{}}\n```')
        self.assertEqual(value["action"], "wait")

    def test_hll_tool_names_are_normalized(self):
        self.assertEqual(
            Action.from_dict({"action": "SubmitCaptcha", "args": {}}).kind,
            ActionKind.SUBMIT_CAPTCHA,
        )
        self.assertEqual(
            Action.from_dict({"action": "TapGridCell", "args": {"index": 4}}).kind,
            ActionKind.TAP_GRID_CELL,
        )
        self.assertEqual(
            Action.from_dict({"action": "InputCaptchaText", "args": {"text": "M9YA"}}).kind,
            ActionKind.INPUT_TEXT,
        )
        self.assertEqual(
            Action.from_dict(
                {"action": "MoveGridPiece", "args": {"from_index": 4, "to_index": 9}}
            ).kind,
            ActionKind.MOVE_GRID_PIECE,
        )


if __name__ == "__main__":
    unittest.main()
