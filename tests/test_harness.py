import tempfile
import unittest
from pathlib import Path

from hll.agent import InvalidModelAction
from hll.captcha.evaluator import CaptchaEvaluator
from hll.domain import (
    Action,
    ActionKind,
    Decision,
    ExecutionResult,
    Observation,
    Task,
)
from hll.harness import Harness, HarnessConfig


class FakeAgent:
    def reset(self, task):
        self.records = []

    def decide(self, observation):
        return Decision(Action(ActionKind.TAP, {"x": 1, "y": 2}), reason="test")

    def update(self, record):
        self.records.append(record)


class FakeEnvironment:
    def __init__(self):
        self.stats = {
            "page_views": 1,
            "total_verifications": 0,
            "successful_verifications": 0,
        }
        self.closed = False
        self.output_dir = None
        self.task = None

    def reset(self, task, output_dir):
        self.task = task
        self.output_dir = output_dir
        return self.observe(0)

    def observe(self, step):
        image = self.output_dir / f"fake_{step}.png"
        image.write_bytes(b"fake")
        return Observation(
            step=step,
            screenshot_path=str(image),
            width=100,
            height=200,
            instruction=self.task.instruction,
            safe_state=dict(self.stats),
        )

    def execute(self, decision):
        self.stats["total_verifications"] += 1
        self.stats["successful_verifications"] += 1
        return ExecutionResult(ok=True, elapsed_seconds=0.01)

    def get_stats(self):
        return dict(self.stats)

    def close(self):
        self.closed = True


class OcrThenTapAgent(FakeAgent):
    def reset(self, task):
        super().reset(task)
        self.calls = 0

    def decide(self, observation):
        self.calls += 1
        if self.calls == 1:
            return Decision(
                Action(ActionKind.OCR, {"x1": 1, "y1": 2, "x2": 30, "y2": 40})
            )
        assert observation.tool_results["ocr_text"] == "M9YA"
        return super().decide(observation)


class LocateGridThenTapAgent(FakeAgent):
    def reset(self, task):
        super().reset(task)
        self.calls = 0

    def decide(self, observation):
        self.calls += 1
        if self.calls == 1:
            return Decision(Action(ActionKind.LOCATE_GRID, {}))
        return super().decide(observation)


class LocateGridOnlyAgent(FakeAgent):
    def decide(self, observation):
        return Decision(Action(ActionKind.LOCATE_GRID, {}))


class FakeToolExecutor:
    def __init__(self, environment):
        self.environment = environment

    def execute(self, decision, observation):
        if decision.action.kind is ActionKind.OCR:
            return ExecutionResult(
                ok=True,
                elapsed_seconds=0.02,
                details={
                    "read_only": True,
                    "tool_name": "OCRRegion",
                    "ocr_engine": "fake",
                    "ocr_text": "M9YA",
                    "usage": {"total_tokens": 3},
                },
            )
        return self.environment.execute(decision)


class UnmarkedReadOnlyExecutor:
    def __init__(self, environment):
        self.environment = environment
        self.executed = []

    def execute(self, decision, observation):
        self.executed.append(decision.action.kind)
        if decision.action.kind is ActionKind.LOCATE_GRID:
            return ExecutionResult(
                ok=True,
                elapsed_seconds=0.01,
                details={"tool_name": "LocateGrid"},
            )
        return self.environment.execute(decision)


class DeviatingAgent(FakeAgent):
    def reset(self, task):
        super().reset(task)
        self.calls = 0

    def decide(self, observation):
        self.calls += 1
        if self.calls == 1:
            return Decision(
                Action(ActionKind.OCR, {"x1": 1, "y1": 2, "x2": 30, "y2": 40})
            )
        return Decision(Action(ActionKind.TAP, {"x": 99, "y": 99}))


class CanonicalExecutor:
    def __init__(self, environment):
        self.environment = environment

    def execute(self, decision, observation):
        if decision.action.kind is ActionKind.OCR:
            return ExecutionResult(
                ok=True,
                elapsed_seconds=0.01,
                details={
                    "read_only": True,
                    "tool_name": "OCRRegion",
                    "ocr_text": "M9YA",
                    "suggested_action": {
                        "action": "input_text",
                        "args": {"text": "M9YA"},
                    },
                },
            )
        if decision.action.kind is ActionKind.INPUT_TEXT:
            return ExecutionResult(
                ok=True,
                elapsed_seconds=0.01,
                details={"ready_to_submit": True},
            )
        if decision.action.kind is ActionKind.SUBMIT:
            self.environment.stats["total_verifications"] += 1
            self.environment.stats["successful_verifications"] += 1
            return ExecutionResult(ok=True, elapsed_seconds=0.01)
        raise AssertionError(f"unexpected resolved action: {decision.action.kind}")


class HarnessTests(unittest.TestCase):
    def test_harness_enforces_ocr_then_input_then_submit(self):
        environment = FakeEnvironment()
        harness = Harness(
            agent=DeviatingAgent(),
            environment=environment,
            evaluator=CaptchaEvaluator(environment, poll_seconds=0),
            executor=CanonicalExecutor(environment),
            config=HarnessConfig(max_steps=3, max_read_only_steps=1, timeout_seconds=2),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = harness.run(Task("text", "solve"), Path(directory))
        self.assertTrue(result.success)
        self.assertEqual(
            [record.decision.action.kind for record in result.steps],
            [ActionKind.OCR, ActionKind.INPUT_TEXT, ActionKind.SUBMIT],
        )
        self.assertEqual(result.steps[1].decision.proposed_action.kind, ActionKind.TAP)
        self.assertEqual(result.steps[2].decision.proposed_action.kind, ActionKind.TAP)
        self.assertEqual(result.metrics["workflow"]["bad_tool_following"], 2)
        self.assertEqual(result.metrics["workflow"]["phase"], "done")
        diagnostics = result.metrics["trajectory_diagnostics"]
        self.assertEqual(diagnostics["action_sequence"], ["ocr", "input_text", "submit"])
        self.assertEqual(diagnostics["tool_sequence"], ["OCRRegion"])
        self.assertEqual(diagnostics["tool_error_steps"], [])
        self.assertTrue(diagnostics["submitted"])
        self.assertEqual(diagnostics["submit_steps"], [3])
        self.assertEqual(diagnostics["suggested_actions"], 1)
        self.assertEqual(diagnostics["suggested_actions_followed"], 1)
        self.assertEqual(diagnostics["suggested_actions_overridden"], 1)

    def test_ocr_is_budget_free_and_reaches_next_observation(self):
        environment = FakeEnvironment()
        harness = Harness(
            agent=OcrThenTapAgent(),
            environment=environment,
            evaluator=CaptchaEvaluator(environment, poll_seconds=0),
            executor=FakeToolExecutor(environment),
            config=HarnessConfig(max_steps=1, max_read_only_steps=1, timeout_seconds=2),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = harness.run(Task("text", "solve"), Path(directory))
        self.assertTrue(result.success)
        self.assertEqual(result.metrics["action_steps"], 1)
        self.assertEqual(result.metrics["read_only_steps"], 1)
        self.assertEqual(result.metrics["tool_calls"], {"OCRRegion": 1})
        self.assertEqual(result.metrics["model_usage"]["total_tokens"], 3)

    def test_hll_read_only_action_is_budget_free_even_without_executor_flag(self):
        environment = FakeEnvironment()
        executor = UnmarkedReadOnlyExecutor(environment)
        harness = Harness(
            agent=LocateGridThenTapAgent(),
            environment=environment,
            evaluator=CaptchaEvaluator(environment, poll_seconds=0),
            executor=executor,
            config=HarnessConfig(max_steps=1, max_read_only_steps=1, timeout_seconds=2),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = harness.run(Task("image_grid_dynamic", "solve"), Path(directory))
        self.assertTrue(result.success)
        self.assertEqual(result.metrics["action_steps"], 1)
        self.assertEqual(result.metrics["read_only_steps"], 1)
        self.assertEqual(result.metrics["tool_calls"], {"LocateGrid": 1})
        self.assertEqual(executor.executed, [ActionKind.LOCATE_GRID, ActionKind.TAP])

    def test_hll_read_only_action_budget_is_checked_before_execution(self):
        environment = FakeEnvironment()
        executor = UnmarkedReadOnlyExecutor(environment)
        harness = Harness(
            agent=LocateGridOnlyAgent(),
            environment=environment,
            evaluator=CaptchaEvaluator(environment, poll_seconds=0),
            executor=executor,
            config=HarnessConfig(max_steps=1, max_read_only_steps=0, timeout_seconds=2),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = harness.run(Task("image_grid_dynamic", "solve"), Path(directory))
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "read_only_step_budget_exhausted")
        self.assertEqual(len(result.steps), 0)
        self.assertEqual(executor.executed, [])

    def test_successful_episode_is_traced_and_closed(self):
        environment = FakeEnvironment()
        harness = Harness(
            agent=FakeAgent(),
            environment=environment,
            evaluator=CaptchaEvaluator(environment, poll_seconds=0),
            config=HarnessConfig(max_steps=2, timeout_seconds=2),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = harness.run(Task("text", "solve"), Path(directory))
            self.assertTrue(result.success)
            self.assertEqual(len(result.steps), 1)
            self.assertTrue((Path(directory) / "episode.json").exists())
            self.assertFalse((Path(directory) / "episode.partial.json").exists())
            self.assertEqual(result.trace_schema_version, "1.7")
        self.assertTrue(environment.closed)


if __name__ == "__main__":
    unittest.main()
