import unittest

from hll.benchmarks.androidworld.actions import (
    build_action_schema_prompt,
    parse_androidworld_action,
)


class AndroidWorldActionTests(unittest.TestCase):
    def test_schema_prompt_contains_general_android_actions(self):
        prompt = build_action_schema_prompt()

        self.assertIn("MCP-style Android action catalog", prompt)
        self.assertIn("open_app args_schema=", prompt)
        self.assertIn("status args_schema=", prompt)
        self.assertNotIn("captcha", prompt.lower())

    def test_parses_structured_click_and_normalizes_numeric_coordinates(self):
        action = parse_androidworld_action(
            'Reasoning before JSON {"action":"click","args":{"x":"25","y":40.0},'
            '"reason":"open item"}'
        )

        self.assertEqual(action.kind, "click")
        self.assertEqual(action.args, {"x": 25, "y": 40})
        self.assertEqual(action.reason, "open item")

    def test_accepts_native_androidworld_shape(self):
        action = parse_androidworld_action(
            '{"action_type":"open_app","app_name":"Contacts","reason":"start"}'
        )

        self.assertEqual(action.kind, "open_app")
        self.assertEqual(action.args["app_name"], "Contacts")

    def test_normalizes_existing_hll_key_alias(self):
        action = parse_androidworld_action(
            '{"action":"key","args":{"key":"BACK"}}'
        )

        self.assertEqual(action.kind, "navigate_back")
        self.assertEqual(action.args, {})

    def test_skips_unrelated_json_before_action(self):
        action = parse_androidworld_action(
            'Schema example: {"type":"object"}\n'
            'Actual action: {"action":"click","args":{"index":2}}'
        )

        self.assertEqual(action.kind, "click")
        self.assertEqual(action.args, {"index": 2})

    def test_rejects_ambiguous_click_target(self):
        with self.assertRaisesRegex(ValueError, "either index or x/y"):
            parse_androidworld_action(
                '{"action":"click","args":{"index":1,"x":2,"y":3}}'
            )

    def test_rejects_unknown_action(self):
        with self.assertRaisesRegex(ValueError, "unknown AndroidWorld action"):
            parse_androidworld_action('{"action":"submit_captcha","args":{}}')


if __name__ == "__main__":
    unittest.main()
