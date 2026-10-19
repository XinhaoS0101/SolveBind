import unittest
import tempfile
from pathlib import Path

from PIL import Image

from hll.agent import CaptchaAgent, InvalidModelAction, SYSTEM_PROMPT, _history_tool_evidence
from hll.domain import ActionKind, Observation, Task
from hll.model import ModelReply


class AgentPromptTests(unittest.TestCase):
    def test_ocr_region_guidance_discourages_heading_crops(self):
        self.assertIn("crop only the full short text/string", SYSTEM_PROMPT)
        self.assertIn("not page headings", SYSTEM_PROMPT)
        self.assertIn("OCR recovery", SYSTEM_PROMPT)

    def test_prompt_contains_schema_driven_tool_catalog(self):
        self.assertIn("MCP-style tool schema catalog", SYSTEM_PROMPT)
        self.assertIn("tap_grid_cell args_schema=", SYSTEM_PROMPT)
        self.assertIn('"required":["index"]', SYSTEM_PROMPT)
        self.assertIn("tool=TapGridCell", SYSTEM_PROMPT)

    def test_prompt_contains_universal_workflow_guide_before_tools(self):
        guide_index = SYSTEM_PROMPT.index("Universal CAPTCHA solving workflow")
        tools_index = SYSTEM_PROMPT.index("Captcha action tools")

        self.assertLess(guide_index, tools_index)
        self.assertIn("Identify the interaction affordance", SYSTEM_PROMPT)
        self.assertIn("suggested_action or canonical_action", SYSTEM_PROMPT)
        self.assertIn("do not repeat the same ineffective action/tool call", SYSTEM_PROMPT)

    def test_prompt_contains_actionable_tool_result_policy(self):
        self.assertIn("convert it into the next concrete action", SYSTEM_PROMPT)
        self.assertIn("ordered click targets", SYSTEM_PROMPT)
        self.assertIn("arithmetic or text-answer prompts", SYSTEM_PROMPT)
        self.assertIn("input_text with the answer", SYSTEM_PROMPT)
        self.assertIn("visual logic instructions", SYSTEM_PROMPT)
        self.assertIn("locate the requested visible target", SYSTEM_PROMPT)
        self.assertIn("call read_logic_prompt before any tap or submit", SYSTEM_PROMPT)

    def test_click_target_snapshot_is_preserved_as_history_evidence(self):
        evidence = _history_tool_evidence(
            {
                "tool_name": "DetectClickTargets",
                "target_snapshot_id": "snapshot-1",
                "targets": [
                    {
                        "target_id": "snapshot-1:1",
                        "label": "star",
                        "role": "candidate",
                        "point": [100, 200],
                    }
                ],
            }
        )

        self.assertEqual(evidence["target_snapshot_id"], "snapshot-1")
        self.assertEqual(evidence["targets"][0]["role"], "candidate")
        self.assertEqual(evidence["targets"][0]["point"], [100, 200])

    def test_empty_model_response_is_retried_once(self):
        model = _SequenceModel(
            [
                ModelReply("", {"total_tokens": 2}),
                ModelReply('{"action":"wait","args":{}}', {"total_tokens": 3}),
            ]
        )
        agent = CaptchaAgent(model)
        agent.reset(Task("generic", "solve"))

        decision = agent.decide(_observation())

        self.assertEqual(decision.action.kind, ActionKind.WAIT)
        self.assertEqual(decision.usage["total_tokens"], 5)
        self.assertEqual(decision.policy["empty_response_retries"], 1)
        self.assertEqual(model.calls, 2)

    def test_two_empty_model_responses_raise_one_invalid_action(self):
        model = _SequenceModel([ModelReply(""), ModelReply("   ")])
        agent = CaptchaAgent(model)
        agent.reset(Task("generic", "solve"))

        with self.assertRaisesRegex(InvalidModelAction, "after one retry"):
            agent.decide(_observation())
        self.assertEqual(model.calls, 2)

    def test_prompt_image_is_forwarded_as_grounded_visual_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt_image = Path(directory) / "grid_overview.jpg"
            Image.new("RGB", (20, 20), "white").save(prompt_image)
            model = _SequenceModel([ModelReply('{"action":"wait","args":{}}')])
            agent = CaptchaAgent(model)
            agent.reset(Task("generic", "solve"))

            agent.decide(
                Observation(
                    step=0,
                    screenshot_path="",
                    width=100,
                    height=200,
                    instruction="solve",
                    tool_results={"prompt_image": str(prompt_image)},
                )
            )

        self.assertEqual(model.messages[1].image_path, str(prompt_image))
        self.assertIn("latest visual tool result", model.messages[1].text)


class _SequenceModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.messages = []

    def complete(self, messages):
        self.messages = list(messages)
        self.calls += 1
        return self.replies.pop(0)


def _observation():
    return Observation(
        step=0,
        screenshot_path="",
        width=100,
        height=200,
        instruction="solve",
    )


if __name__ == "__main__":
    unittest.main()
