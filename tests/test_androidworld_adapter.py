import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from android_world import constants, episode_runner
    from android_world.env import interface, representation_utils

    from hll.benchmarks.androidworld.agent import HllAndroidWorldAgent, SYSTEM_PROMPT
    from hll.benchmarks.androidworld.runner import (
        _build_summary,
        _raise_on_model_backend_error,
    )
    from hll.model import ModelReply, ModelRequestError

    ANDROIDWORLD_AVAILABLE = True
except ImportError:
    ANDROIDWORLD_AVAILABLE = False


@unittest.skipUnless(ANDROIDWORLD_AVAILABLE, "AndroidWorld is an optional dependency")
class AndroidWorldAdapterTests(unittest.TestCase):
    def test_executes_index_click_and_records_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _FakeEnv()
            model = _SequenceModel(
                [
                    ModelReply(
                        '{"action":"click","args":{"index":0},"reason":"open"}',
                        {"total_tokens": 12},
                    )
                ]
            )
            agent = HllAndroidWorldAgent(env, model, artifact_dir=directory)
            agent.reset()
            agent.set_max_steps(10)

            result = agent.step("Open Contacts")

        self.assertFalse(result.done)
        self.assertEqual(env.actions[0].action_type, "click")
        self.assertEqual(env.actions[0].index, 0)
        self.assertEqual(result.data["model_usage"]["total_tokens"], 12)
        self.assertTrue(Path(result.data["screenshot_path"]).name.startswith("screen_"))
        self.assertIn("Contacts", model.messages[-1].text)

    def test_status_completes_without_executing_environment_action(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _FakeEnv()
            agent = HllAndroidWorldAgent(
                env,
                _SequenceModel(
                    [ModelReply('{"action":"status","args":{"goal_status":"complete"}}')]
                ),
                artifact_dir=directory,
            )
            agent.reset()

            result = agent.step("Open Contacts")

        self.assertTrue(result.done)
        self.assertEqual(env.actions, [])

    def test_maps_screenshot_coordinates_to_logical_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _FakeEnv(logical_size=(200, 400))
            agent = HllAndroidWorldAgent(
                env,
                _SequenceModel(
                    [ModelReply('{"action":"click","args":{"x":25,"y":50}}')]
                ),
                artifact_dir=directory,
            )
            agent.reset()

            agent.step("Tap the item")

        self.assertEqual(env.actions[0].x, 50)
        self.assertEqual(env.actions[0].y, 100)

    def test_invalid_index_is_feedback_not_suite_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _FakeEnv()
            agent = HllAndroidWorldAgent(
                env,
                _SequenceModel(
                    [ModelReply('{"action":"click","args":{"index":99}}')]
                ),
                artifact_dir=directory,
            )
            agent.reset()

            result = agent.step("Open Contacts")

        self.assertFalse(result.done)
        self.assertEqual(env.actions, [])
        self.assertIn("outside the current range", result.data["error"])

    def test_retry_failure_preserves_first_response_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _FakeEnv()
            agent = HllAndroidWorldAgent(
                env,
                _SequenceModel(
                    [
                        ModelReply("", {"total_tokens": 5}),
                        RuntimeError("retry failed"),
                    ]
                ),
                artifact_dir=directory,
            )
            agent.reset()

            result = agent.step("Open Contacts")

        self.assertFalse(result.done)
        self.assertEqual(result.data["model_usage"]["total_tokens"], 5)
        self.assertIn("retry failed", result.data["error"])

    def test_model_request_error_is_infrastructure_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _FakeEnv()
            agent = HllAndroidWorldAgent(
                env,
                _SequenceModel([ModelRequestError("invalid API key")]),
                artifact_dir=directory,
            )
            agent.reset()

            with self.assertRaisesRegex(ModelRequestError, "invalid API key"):
                agent.step("Open Contacts")

    def test_general_prompt_has_no_captcha_policy(self):
        self.assertIn("General Android task workflow", SYSTEM_PROMPT)
        self.assertIn("official evaluator independently scores", SYSTEM_PROMPT)
        self.assertNotIn("without an explicit complete status", SYSTEM_PROMPT)
        self.assertNotIn("CAPTCHA", SYSTEM_PROMPT)

    def test_summary_uses_only_final_checkpoint_state(self):
        episode = {
            constants.EpisodeConstants.IS_SUCCESSFUL: 1.0,
            constants.EpisodeConstants.EXCEPTION_INFO: None,
            constants.EpisodeConstants.EPISODE_DATA: {
                "model_usage": [
                    {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    }
                ],
                "model_seconds": [1.25],
            },
        }

        summary = _build_summary([episode])

        self.assertEqual(summary["planned_or_loaded"], 1)
        self.assertEqual(summary["valid_episodes"], 1)
        self.assertEqual(summary["infrastructure_errors"], 0)
        self.assertEqual(summary["accuracy"], 1.0)
        self.assertEqual(summary["model_usage"]["total_tokens"], 12)
        self.assertEqual(summary["model_seconds"], 1.25)
        self.assertEqual(summary["hll_tool_usage"]["total_calls"], 0)

    def test_model_backend_error_stops_batch(self):
        episodes = [
            {
                constants.EpisodeConstants.EXCEPTION_INFO: (
                    "hll.model.ModelRequestError: invalid API key"
                )
            }
        ]

        with self.assertRaises(RuntimeError):
            _raise_on_model_backend_error(episodes)

    def test_official_episode_runner_can_drive_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _FakeEnv()
            agent = HllAndroidWorldAgent(
                env,
                _SequenceModel(
                    [
                        ModelReply('{"action":"click","args":{"index":0}}'),
                        ModelReply(
                            '{"action":"status","args":{"goal_status":"complete"}}'
                        ),
                    ]
                ),
                artifact_dir=directory,
                transition_pause=0,
            )

            result = episode_runner.run_episode(
                goal="Open Contacts",
                agent=agent,
                max_n_steps=3,
                print_fn=lambda _: None,
            )

        self.assertTrue(result.done)
        self.assertEqual(len(result.step_data["step_number"]), 2)
        self.assertEqual(env.actions[0].action_type, "click")


if ANDROIDWORLD_AVAILABLE:

    class _FakeEnv:
        def __init__(self, logical_size=(100, 200)):
            self.logical_size = logical_size
            self.actions = []
            element = representation_utils.UIElement(
                text="Contacts",
                is_clickable=True,
                is_visible=True,
                bbox_pixels=representation_utils.BoundingBox(0, 50, 0, 50),
            )
            self.state = interface.State(
                pixels=np.zeros((200, 100, 3), dtype=np.uint8),
                forest=None,
                ui_elements=[element],
            )

        def reset(self, go_home=False):
            del go_home
            return self.state

        def get_state(self, wait_to_stabilize=False):
            del wait_to_stabilize
            return self.state

        def execute_action(self, action):
            self.actions.append(action)

        def hide_automation_ui(self):
            pass

        @property
        def logical_screen_size(self):
            return self.logical_size


    class _SequenceModel:
        def __init__(self, replies):
            self.replies = list(replies)
            self.messages = []

        def complete(self, messages):
            self.messages = list(messages)
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply


if __name__ == "__main__":
    unittest.main()
