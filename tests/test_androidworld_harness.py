import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import numpy as np
    from PIL import Image
    from android_world.env import interface, representation_utils

    from hll.agent import CaptchaAgent
    from hll.benchmarks.androidworld.harness_adapter import (
        AndroidWorldTaskEnvironment,
        AndroidWorldTaskEvaluator,
        AndroidWorldWorkflowPolicy,
        summarize_hll_tool_usage,
    )
    from hll.benchmarks.androidworld.profile import build_androidworld_system_prompt
    from hll.benchmarks.androidworld.tools import (
        AndroidWorldOcrTool,
        AndroidWorldToolExecutor,
    )
    from hll.domain import (
        Action,
        ActionKind,
        Decision,
        ExecutionResult,
        Observation,
        Task,
    )
    from hll.executor import ToolExecutor
    from hll.harness import Harness, HarnessConfig
    from hll.model import ModelReply
    from hll.workflow import WorkflowConfig, WorkflowPolicy

    ANDROIDWORLD_AVAILABLE = True
except ImportError:
    ANDROIDWORLD_AVAILABLE = False


@unittest.skipUnless(ANDROIDWORLD_AVAILABLE, "AndroidWorld is an optional dependency")
class AndroidWorldHarnessTests(unittest.TestCase):
    def test_full_harness_owns_episode_and_uses_official_evaluator(self):
        with tempfile.TemporaryDirectory() as directory:
            native_env = _FakeEnv()
            task_eval = _FakeTaskEval()
            environment = AndroidWorldTaskEnvironment(
                native_env,
                task_eval,
                adb_path="adb",
                device_serial="emulator-5554",
                max_steps=10,
            )
            agent = CaptchaAgent(
                _SequenceModel(
                    [
                        ModelReply('{"action":"click","args":{"index":0}}'),
                        ModelReply('{"action":"finish","args":{"reason":"done"}}'),
                    ]
                ),
                system_prompt=build_androidworld_system_prompt(),
                ocr_enabled=False,
            )
            harness = Harness(
                agent=agent,
                environment=environment,
                evaluator=AndroidWorldTaskEvaluator(native_env, task_eval),
                executor=ToolExecutor(environment),
                workflow=WorkflowPolicy(
                    WorkflowConfig(completion_mode="external")
                ),
                config=HarnessConfig(max_steps=10, max_read_only_steps=2),
            )
            task = Task("OpenAppTaskEval", "Open Contacts")

            result = harness.run(task, Path(directory))

        self.assertTrue(result.success)
        self.assertEqual([item.action_type for item in native_env.actions], ["click"])
        self.assertTrue(task_eval.initialized_once)
        self.assertTrue(task_eval.torn_down)
        self.assertEqual(
            result.steps[-1].evaluation.signals["official_reward"],
            1.0,
        )
        self.assertEqual(
            result.steps[0].observation.context["ui_elements"][0]["text"],
            "Contacts",
        )

    def test_external_workflow_does_not_force_captcha_submit(self):
        workflow = WorkflowPolicy(WorkflowConfig(completion_mode="external"))
        task = Task("general", "Enter a contact")
        workflow.reset(task)
        before = _observation()
        decision = Decision(Action(ActionKind.INPUT_TEXT, {"text": "Ada"}))
        execution = ExecutionResult(
            True,
            0.0,
            {"ready_to_submit": True},
        )
        from hll.domain import Evaluation, EvaluationStatus

        workflow.update(
            decision=decision,
            execution=execution,
            evaluation=Evaluation(EvaluationStatus.RUNNING),
            before=before,
            after=before,
        )
        next_decision = Decision(
            Action(ActionKind.OPEN_APP, {"app_name": "Contacts"})
        )

        resolved = workflow.resolve(next_decision)

        self.assertEqual(resolved.action.kind, ActionKind.OPEN_APP)
        self.assertFalse(workflow.state.ready_to_submit)

    def test_general_prompt_exposes_native_and_reusable_tools(self):
        prompt = build_androidworld_system_prompt(enable_ocr=True)

        self.assertIn("General Android task workflow", prompt)
        self.assertIn("click args_schema=", prompt)
        self.assertIn("crop_region args_schema=", prompt)
        self.assertIn("normal planning actions", prompt)
        self.assertIn("tool=ReadScreenText", prompt)
        self.assertIn("never alternate apps", prompt)
        self.assertIn("thumbnail grid", prompt)
        self.assertIn("named_inputs", prompt)
        self.assertIn("empty separator line", prompt)
        self.assertIn(r"newline characters (\n\n)", prompt)
        self.assertIn("auto-filled extension", prompt)
        self.assertIn('input_text text=""', prompt)
        self.assertIn("then use its rename", prompt)
        self.assertNotIn("only when the screenshot", prompt)
        self.assertNotIn("distorted characters", prompt)
        self.assertIn("official evaluator", prompt)

    def test_androidworld_ocr_preserves_general_multiline_text(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (100, 80), "white").save(screenshot)
            tool = AndroidWorldOcrTool(
                _SequenceModel([ModelReply("Milk\nTotal: $12.50")])
            )
            observation = Observation(
                step=3,
                screenshot_path=str(screenshot),
                width=100,
                height=80,
                instruction="Transcribe the receipt",
                context={
                    "ui_elements": [
                        {
                            "index": 0,
                            "text": "receipt.md",
                            "bbox": [0, 0, 100, 15],
                        }
                    ]
                },
            )

            result = tool.execute(
                Action(
                    ActionKind.OCR,
                    {"x1": 0, "y1": 20, "x2": 100, "y2": 80},
                ),
                observation,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.details["ocr_text"], "Milk\nTotal: $12.50")
        self.assertEqual(result.details["answer"], "Milk\nTotal: $12.50")
        self.assertNotIn("canonical_action", result.details)
        self.assertEqual(result.details["executor"], "androidworld_tools")
        self.assertEqual(result.details["source_label"], "receipt.md")
        self.assertTrue(result.details["usable_evidence"])

    def test_androidworld_ocr_rejects_highly_repeated_grid_text(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (100, 80), "white").save(screenshot)
            repeated = "\n".join(["Name", "Amount"] * 5)
            tool = AndroidWorldOcrTool(
                _SequenceModel([ModelReply(repeated)])
            )
            observation = Observation(
                1,
                str(screenshot),
                100,
                80,
                "Read one source",
            )

            result = tool.execute(
                Action(
                    ActionKind.OCR,
                    {"x1": 0, "y1": 0, "x2": 100, "y2": 80},
                ),
                observation,
            )

        self.assertTrue(result.ok)
        self.assertFalse(result.details["usable_evidence"])
        self.assertTrue(result.details["ocr_quality"]["high_repetition"])
        self.assertNotIn("answer", result.details)
        self.assertIn("not stored", result.details["prompt_feedback"])

    def test_androidworld_ocr_prefers_exact_structured_ui_text(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (100, 80), "white").save(screenshot)
            tool = AndroidWorldOcrTool(
                _SequenceModel([AssertionError("vision model should not be called")])
            )
            observation = Observation(
                1,
                str(screenshot),
                100,
                80,
                "Read exact text",
                context={
                    "ui_elements": [
                        {
                            "index": 1,
                            "text": "Document title",
                            "bbox": [0, 10, 100, 30],
                            "resource_name": "app:id/title",
                            "editable": False,
                        },
                        {
                            "index": 0,
                            "text": "CaseSensitiveA1b2",
                            "bbox": [0, 20, 100, 70],
                            "resource_name": "app:id/editor",
                            "editable": True,
                        }
                    ]
                },
            )

            result = tool.execute(
                Action(
                    ActionKind.OCR,
                    {"x1": 0, "y1": 20, "x2": 100, "y2": 70},
                ),
                observation,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.details["ocr_text"], "CaseSensitiveA1b2")
        self.assertEqual(result.details["text_source"], "structured_ui")
        self.assertEqual(result.details["usage"], {})

    def test_androidworld_ocr_does_not_trust_noneditable_page_chrome(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            Image.new("RGB", (100, 80), "white").save(screenshot)
            tool = AndroidWorldOcrTool(
                _SequenceModel([ModelReply("Actual document body")])
            )
            observation = Observation(
                1,
                str(screenshot),
                100,
                80,
                "Read exact text",
                context={
                    "ui_elements": [
                        {
                            "index": 0,
                            "text": "Stale app title",
                            "bbox": [0, 10, 100, 35],
                            "editable": False,
                        }
                    ]
                },
            )

            result = tool.execute(
                Action(
                    ActionKind.OCR,
                    {"x1": 0, "y1": 20, "x2": 100, "y2": 70},
                ),
                observation,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.details["ocr_text"], "Actual document body")
        self.assertEqual(result.details["text_source"], "vision")

    def test_tool_executor_uses_native_and_hll_actions_in_one_trajectory(self):
        with tempfile.TemporaryDirectory() as directory:
            native_env = _FakeEnv()
            task_eval = _FakeTaskEval()
            environment = AndroidWorldTaskEnvironment(
                native_env,
                task_eval,
                adb_path="adb",
                device_serial="emulator-5554",
                max_steps=10,
            )
            observation = environment.reset(
                Task("general", "Open Contacts"),
                Path(directory),
            )
            executor = AndroidWorldToolExecutor(
                ToolExecutor(environment),
                environment,
            )
            click = Decision(Action(ActionKind.CLICK, {"index": 0}))
            executor.execute(click, observation)
            after_click = environment.observe(1)

            trajectory = executor.execute(
                Decision(Action(ActionKind.GET_OBSERVATION, {})),
                after_click,
            )
            environment.close()

        summary = trajectory.details["trajectory_summary"]
        self.assertEqual(summary["total_steps"], 1)
        self.assertEqual(summary["recent_actions"][0]["action"], "click")
        self.assertEqual(summary["consecutive_no_effect"], 1)
        self.assertIn("recent native and tool actions", trajectory.details["prompt_feedback"])

    def test_tool_usage_counts_action_tools_and_result_delivery(self):
        read_only = SimpleNamespace(
            decision=Decision(Action(ActionKind.GET_OBSERVATION, {})),
            execution=ExecutionResult(
                True,
                0.0,
                {
                    "executor": "androidworld_tools",
                    "tool_name": "GetObservation",
                    "read_only": True,
                    "tool_dispatch": "direct",
                },
            ),
            after=Observation(
                1,
                "",
                100,
                200,
                "task",
                tool_results={"tool_name": "GetObservation"},
            ),
        )
        drag = SimpleNamespace(
            decision=Decision(
                Action(
                    ActionKind.DRAG,
                    {"x1": 1, "y1": 1, "x2": 20, "y2": 20},
                )
            ),
            execution=ExecutionResult(
                True,
                0.0,
                {"executor": "hll_tools", "tool_name": "Drag"},
            ),
            after=Observation(2, "", 100, 200, "task"),
        )

        summary = summarize_hll_tool_usage(
            SimpleNamespace(steps=(read_only, drag))
        )

        self.assertEqual(summary["total_calls"], 2)
        self.assertEqual(summary["read_only_calls"], 1)
        self.assertEqual(summary["action_calls"], 1)
        self.assertEqual(summary["results_delivered"], 1)
        self.assertEqual(summary["read_only_followed_by_action"], 1)
        self.assertEqual(summary["by_name"], {"GetObservation": 1, "Drag": 1})

    def test_environment_detects_alternating_action_cycle(self):
        environment = AndroidWorldTaskEnvironment(
            _FakeEnv(),
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        execution = ExecutionResult(
            True,
            0.0,
            {"executor": "androidworld_native"},
        )
        for app_name in ("Gallery", "Markor", "Gallery", "Markor"):
            environment.record_execution(
                Decision(
                    Action(ActionKind.OPEN_APP, {"app_name": app_name})
                ),
                execution,
            )

        summary = environment.trajectory_summary()

        self.assertEqual(summary["action_cycle_count"], 2)
        self.assertIn("action cycle", environment._tool_advice([]))
        self.assertEqual(
            environment.cycle_guard_reason(
                Decision(
                    Action(ActionKind.OPEN_APP, {"app_name": "Gallery"})
                )
            ),
            "action_cycle_blocked",
        )

    def test_cycle_guard_does_not_execute_confirmed_repeat(self):
        native_env = _FakeEnv()
        environment = AndroidWorldTaskEnvironment(
            native_env,
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        for app_name in ("Gallery", "Markor", "Gallery", "Markor"):
            environment.record_execution(
                Decision(Action(ActionKind.OPEN_APP, {"app_name": app_name})),
                ExecutionResult(True, 0.0, {"executor": "androidworld_native"}),
            )
        executor = AndroidWorldToolExecutor(ToolExecutor(environment), environment)

        result = executor.execute(
            Decision(Action(ActionKind.OPEN_APP, {"app_name": "Gallery"})),
            _observation(),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "action_cycle_blocked")
        self.assertEqual(native_env.actions, [])

    def test_named_evidence_and_inputs_are_kept_in_trajectory(self):
        environment = AndroidWorldTaskEnvironment(
            _FakeEnv(),
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        observation = Observation(
            1,
            "",
            100,
            200,
            "task",
            context={
                "ui_elements": [
                    {"index": 2, "hint_text": "Playlist name", "bbox": [0, 0, 50, 20]}
                ]
            },
        )
        environment.record_execution(
            Decision(
                Action(ActionKind.INPUT_TEXT, {"index": 2, "text": "Collection"}),
                reason="name destination",
            ),
            ExecutionResult(True, 0.0, {"executor": "androidworld_native"}),
            observation,
        )
        environment.record_execution(
            Decision(Action(ActionKind.OCR, {"x1": 0, "y1": 0, "x2": 10, "y2": 10})),
            ExecutionResult(
                True,
                0.0,
                {
                    "executor": "androidworld_tools",
                    "tool_name": "ReadScreenText",
                    "read_only": True,
                    "ocr_text": "source contents",
                    "source_label": "source.txt",
                    "usable_evidence": True,
                },
            ),
            observation,
        )

        summary = environment.trajectory_summary()

        self.assertEqual(summary["named_inputs"][0]["value"], "Collection")
        self.assertEqual(summary["named_inputs"][0]["field"], "Playlist name")
        self.assertEqual(summary["evidence_memory"][0]["source_label"], "source.txt")

    def test_multi_input_finish_is_verified_once(self):
        environment = AndroidWorldTaskEnvironment(
            _FakeEnv(),
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        for value in ("first", "second"):
            environment.record_execution(
                Decision(Action(ActionKind.INPUT_TEXT, {"text": value})),
                ExecutionResult(True, 0.0, {"executor": "androidworld_native"}),
            )
        workflow = AndroidWorldWorkflowPolicy(
            environment,
            WorkflowConfig(completion_mode="external"),
        )
        workflow.reset(Task("general", "create two objects"))

        guarded = workflow.resolve(
            Decision(Action(ActionKind.FINISH, {"goal_status": "complete"}))
        )
        allowed = workflow.resolve(
            Decision(Action(ActionKind.FINISH, {"goal_status": "complete"}))
        )

        self.assertEqual(guarded.action.kind, ActionKind.GET_OBSERVATION)
        self.assertEqual(guarded.policy["guard"], "androidworld_finish_verification")
        self.assertEqual(allowed.action.kind, ActionKind.FINISH)

    def test_empty_input_text_clears_current_field(self):
        native_env = _FakeEnv()
        native_env.controller = object()
        environment = AndroidWorldTaskEnvironment(
            native_env,
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        environment._current_state = native_env.state
        decision = Decision(
            Action(
                ActionKind.INPUT_TEXT,
                {"index": 0, "text": "", "clear_text": True},
            )
        )

        with (
            mock.patch(
                "hll.benchmarks.androidworld.harness_adapter.adb_utils.issue_generic_request"
            ) as issue,
            mock.patch(
                "hll.benchmarks.androidworld.harness_adapter.adb_utils.check_ok"
            ) as check_ok,
        ):
            response = object()
            issue.return_value = response
            result = environment.execute(decision)

        self.assertTrue(result.ok)
        self.assertTrue(result.details["clear_only"])
        self.assertEqual(native_env.actions[0].action_type, "click")
        self.assertEqual(issue.call_count, 2)
        self.assertEqual(check_ok.call_count, 2)
        check_ok.assert_any_call(
            response, "Failed to clear the focused text field."
        )
        check_ok.assert_any_call(
            response, "Failed to finish clearing the text field."
        )

    def test_confirmation_is_blocked_for_unrequested_auto_extension(self):
        native_env = _FakeEnv()
        environment = AndroidWorldTaskEnvironment(
            native_env,
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        environment.task = Task("general", "Create a new note named Report")
        environment.record_execution(
            Decision(Action(ActionKind.INPUT_TEXT, {"text": "Report"})),
            ExecutionResult(True, 0.0, {"executor": "androidworld_native"}),
        )
        observation = Observation(
            2,
            "",
            100,
            200,
            environment.task.instruction,
            context={
                "ui_elements": [
                    {
                        "index": 1,
                        "text": "Report",
                        "editable": True,
                        "resource_name": "app:id/name",
                    },
                    {
                        "index": 2,
                        "text": ".md",
                        "editable": True,
                        "resource_name": "app:id/extension",
                    },
                    {"index": 3, "text": "OK", "clickable": True},
                ]
            },
        )
        executor = AndroidWorldToolExecutor(ToolExecutor(environment), environment)

        result = executor.execute(
            Decision(Action(ActionKind.CLICK, {"index": 3})),
            observation,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unresolved_auto_suffix")
        self.assertIn("Try clearing that editable", result.details["prompt_feedback"])
        self.assertEqual(native_env.actions, [])
        self.assertEqual(
            environment.action_guard_reason(
                Decision(Action(ActionKind.CLICK, {"index": 3})),
                observation,
            ),
            "",
        )
        self.assertEqual(
            environment.trajectory_summary()["form_constraints"][
                "auto_suffix_conflicts"
            ],
            {"Report": ".md"},
        )

    def test_form_guard_ignores_keyboard_done_key(self):
        environment = AndroidWorldTaskEnvironment(
            _FakeEnv(),
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        environment.task = Task("general", "Create a new note named Report")
        environment.record_execution(
            Decision(Action(ActionKind.INPUT_TEXT, {"text": "Report"})),
            ExecutionResult(True, 0.0, {"executor": "androidworld_native"}),
        )
        observation = Observation(
            2,
            "",
            100,
            200,
            environment.task.instruction,
            context={
                "ui_elements": [
                    {
                        "index": 2,
                        "text": ".md",
                        "editable": True,
                        "resource_name": "app:id/extension",
                    },
                    {
                        "index": 55,
                        "content_description": "Done",
                        "resource_name": "com.google.android.inputmethod.latin:id/key_done",
                    },
                ]
            },
        )

        reason = environment.action_guard_reason(
            Decision(Action(ActionKind.CLICK, {"index": 55})),
            observation,
        )

        self.assertEqual(reason, "")

    def test_form_guard_blocks_coordinate_tap_on_confirmation(self):
        environment = AndroidWorldTaskEnvironment(
            _FakeEnv(),
            _FakeTaskEval(),
            adb_path="adb",
            device_serial="emulator-5554",
            max_steps=10,
        )
        environment.task = Task("general", "Create a new note named Report")
        environment.record_execution(
            Decision(Action(ActionKind.INPUT_TEXT, {"text": "Report"})),
            ExecutionResult(True, 0.0, {"executor": "androidworld_native"}),
        )
        observation = Observation(
            2,
            "",
            100,
            200,
            environment.task.instruction,
            context={
                "ui_elements": [
                    {
                        "index": 2,
                        "text": ".md",
                        "editable": True,
                        "resource_name": "app:id/extension",
                        "bbox": [50, 20, 80, 40],
                    },
                    {
                        "index": 3,
                        "text": "OK",
                        "clickable": True,
                        "bbox": [70, 60, 95, 90],
                    },
                ]
            },
        )

        reason = environment.action_guard_reason(
            Decision(Action(ActionKind.TAP, {"x": 80, "y": 75})),
            observation,
        )

        self.assertEqual(reason, "unresolved_auto_suffix")


if ANDROIDWORLD_AVAILABLE:

    class _FakeTaskEval:
        name = "OpenAppTaskEval"
        goal = "Open Contacts"
        complexity = 1.0
        start_on_home_screen = True
        params = {"seed": 7}

        def __init__(self):
            self.initialized_once = False
            self.torn_down = False

        def initialize_task(self, env):
            del env
            self.initialized_once = True

        def is_successful(self, env):
            return float(any(action.action_type == "click" for action in env.actions))

        def tear_down(self, env):
            del env
            self.torn_down = True


    class _FakeEnv:
        def __init__(self):
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
            return 100, 200


    class _SequenceModel:
        def __init__(self, replies):
            self.replies = list(replies)

        def complete(self, messages):
            del messages
            return self.replies.pop(0)


    def _observation():
        from hll.domain import Observation

        return Observation(0, "", 100, 200, "task")


if __name__ == "__main__":
    unittest.main()
