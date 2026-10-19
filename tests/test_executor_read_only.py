import unittest

from hll.domain import Action, ActionKind, Decision
from hll.executor import HllToolExecutor, READ_ONLY_ACTIONS


class ExecutorReadOnlyTests(unittest.TestCase):
    def test_exported_read_only_actions_include_ocr_and_hll_tools(self):
        self.assertIn(ActionKind.OCR, READ_ONLY_ACTIONS)
        self.assertIn(ActionKind.LOCATE_GRID, READ_ONLY_ACTIONS)
        self.assertIn(ActionKind.ESTIMATE_DRAG_OFFSET, READ_ONLY_ACTIONS)
        self.assertNotIn(ActionKind.TAP, READ_ONLY_ACTIONS)

    def test_hll_read_only_action_is_forced_read_only_in_details(self):
        executor = HllToolExecutor(_FakeEnvironment())
        details = {"tool_name": "LocateGrid"}

        executor._annotate_details(
            Decision(Action(ActionKind.LOCATE_GRID, {})),
            details,
            previous_page_views=0,
        )

        self.assertTrue(details["read_only"])


class _FakeEnvironment:
    adb_path = "adb"
    device_serial = ""
    captcha_url = "http://127.0.0.1:8000"

    def get_stats(self):
        return {"page_views": 1}


if __name__ == "__main__":
    unittest.main()
