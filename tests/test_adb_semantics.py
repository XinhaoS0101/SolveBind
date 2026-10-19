import unittest

from hll.domain import Action, ActionKind, Decision
from hll.captcha.adb_environment import (
    AdbCaptchaEnvironment,
    _bounds_center,
    _expected_url_markers,
    _is_primary_button_color,
)


class SemanticEnvironment(AdbCaptchaEnvironment):
    def __init__(self, nodes):
        super().__init__()
        self.nodes = nodes

    def _ui_nodes(self):
        return self.nodes


class ExecutingEnvironment(AdbCaptchaEnvironment):
    def __init__(self):
        super().__init__(settle_seconds=0)
        self.last_size = (1080, 1920)
        self.commands = []

    def _adb(self, *args):
        self.commands.append(args)
        return "mInputShown=false"

    def _find_editable_text_field(self):
        return (200, 800)

    def _find_primary_submit_control(self):
        return (540, 1200), "accessibility"


class BrowserEnvironment(AdbCaptchaEnvironment):
    def __init__(self, texts, page_views):
        super().__init__(
            page_ready_timeout=0.05,
            page_load_retries=0,
            page_retry_interval=0,
            settle_seconds=0,
        )
        self.texts = texts
        self.page_views = list(page_views)
        self.commands = []

    def get_stats(self):
        if len(self.page_views) > 1:
            page_views = self.page_views.pop(0)
        else:
            page_views = self.page_views[0]
        return {
            "page_views": page_views,
            "total_verifications": 0,
            "successful_verifications": 0,
        }

    def _adb(self, *args):
        self.commands.append(args)
        return ""

    def _ui_nodes(self):
        return [{"text": text, "content-desc": ""} for text in self.texts]


class AdbSemanticTests(unittest.TestCase):
    def test_input_text_is_semantic_and_marks_submit_ready(self):
        env = ExecutingEnvironment()
        result = env.execute(
            Decision(Action(ActionKind.INPUT_TEXT, {"text": "M9YA"}))
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.details["ready_to_submit"])
        self.assertEqual(result.details["mapped_point"], [200, 800])
        self.assertIn(("shell", "input", "text", "M9YA"), env.commands)

    def test_submit_is_semantic_and_records_verification_action(self):
        env = ExecutingEnvironment()
        result = env.execute(Decision(Action(ActionKind.SUBMIT, {})))
        self.assertTrue(result.ok)
        self.assertTrue(result.details["verification_action"])
        self.assertEqual(result.details["mapped_point"], [540, 1200])

    def test_multistep_tap_and_drag_require_explicit_completion(self):
        env = ExecutingEnvironment()
        tap = env.execute(Decision(Action(ActionKind.TAP, {"x": 100, "y": 200})))
        drag = env.execute(
            Decision(
                Action(
                    ActionKind.DRAG,
                    {"x1": 100, "y1": 200, "x2": 300, "y2": 200},
                )
            )
        )
        final_drag = env.execute(
            Decision(
                Action(
                    ActionKind.DRAG,
                    {"x1": 100, "y1": 200, "x2": 300, "y2": 200, "complete": True},
                )
            )
        )
        self.assertTrue(tap.details["interaction_progress"])
        self.assertNotIn("ready_to_submit", tap.details)
        self.assertNotIn("ready_to_submit", drag.details)
        self.assertTrue(final_drag.details["ready_to_submit"])

    def test_bounds_center(self):
        self.assertEqual(_bounds_center("[10,20][110,80]"), (60, 50))
        self.assertIsNone(_bounds_center("invalid"))

    def test_editable_field_is_located_without_family_knowledge(self):
        env = SemanticEnvironment(
            [
                {
                    "class": "android.widget.EditText",
                    "editable": "true",
                    "resource-id": "captcha-input",
                    "bounds": "[20,100][220,160]",
                }
            ]
        )
        self.assertEqual(env._find_editable_text_field(), (120, 130))

    def test_submit_control_uses_semantic_label(self):
        env = SemanticEnvironment(
            [
                {
                    "class": "android.widget.Button",
                    "text": "Verify",
                    "content-desc": "",
                    "resource-id": "verify-button",
                    "clickable": "true",
                    "bounds": "[30,200][230,260]",
                }
            ]
        )
        self.assertEqual(env._find_primary_submit_control(), ((130, 230), "accessibility"))

    def test_primary_color_filter(self):
        self.assertTrue(_is_primary_button_color((79, 70, 229)))
        self.assertFalse(_is_primary_button_color((255, 255, 255)))

    def test_browser_open_waits_for_page_and_checks_foreground_url(self):
        env = BrowserEnvironment(["127.0.0.1:8000"], [0, 1])
        env._open_browser_until_ready("http://127.0.0.1:8000/")

        self.assertTrue(
            any(command[:3] == ("shell", "am", "force-stop") for command in env.commands)
        )
        self.assertIn(
            (
                "shell",
                "am",
                "start",
                "-W",
                "--activity-clear-top",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                "http://127.0.0.1:8000/",
            ),
            env.commands,
        )

    def test_foreground_check_rejects_search_or_error_page(self):
        env = BrowserEnvironment(["Search or type URL"], [1])
        result = env._check_browser_foreground_for_url("http://127.0.0.1:8000/")
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "browser_not_on_expected_url")

    def test_expected_url_markers_include_host_and_display_url(self):
        markers = _expected_url_markers("http://127.0.0.1:8000/path")
        self.assertIn("127.0.0.1", markers)
        self.assertIn("127.0.0.1:8000/path", markers)


if __name__ == "__main__":
    unittest.main()
