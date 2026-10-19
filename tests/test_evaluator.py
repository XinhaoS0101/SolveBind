import unittest

from hll.captcha.evaluator import CaptchaEvaluator
from hll.domain import Action, ActionKind, Decision, EvaluationStatus, ExecutionResult


class Source:
    def __init__(self):
        self.stats = {"page_views": 1, "total_verifications": 0, "successful_verifications": 0}

    def get_stats(self):
        return dict(self.stats)

    def get_verification_feedback(self):
        return {
            "attempt": 1,
            "success": False,
            "reason_code": "dynamic_behavior_rejected",
            "answer_exposed": False,
            "details": {"telemetry_events": 4},
        }


class EvaluatorTests(unittest.TestCase):
    def test_semantic_locator_failure_enters_recovery(self):
        source = Source()
        evaluator = CaptchaEvaluator(source, poll_seconds=0)
        evaluator.reset()
        feedback = evaluator.evaluate(
            Decision(Action(ActionKind.SUBMIT, {})),
            ExecutionResult(
                ok=False,
                elapsed_seconds=0,
                details={"recoverable": True},
                error="no primary submit control",
            ),
        )
        self.assertEqual(feedback.status, EvaluationStatus.FAILED_ATTEMPT)
        self.assertFalse(feedback.done)
        self.assertEqual(feedback.reason, "action_execution_failed")

    def test_ocr_failure_is_recoverable(self):
        source = Source()
        evaluator = CaptchaEvaluator(source, poll_seconds=0)
        evaluator.reset()
        feedback = evaluator.evaluate(
            Decision(Action(ActionKind.OCR, {"x1": 1, "y1": 1, "x2": 10, "y2": 10})),
            ExecutionResult(
                ok=False,
                elapsed_seconds=0,
                details={"read_only": True, "tool_name": "OCRRegion"},
                error="temporary OCR error",
            ),
        )
        self.assertEqual(feedback.status, EvaluationStatus.RUNNING)
        self.assertEqual(feedback.reason, "tool_failed")
        self.assertFalse(feedback.done)

    def test_read_only_ocr_does_not_poll_or_change_oracle_state(self):
        source = Source()
        evaluator = CaptchaEvaluator(source, poll_seconds=10)
        evaluator.reset()
        feedback = evaluator.evaluate(
            Decision(Action(ActionKind.OCR, {"x1": 1, "y1": 1, "x2": 10, "y2": 10})),
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={"read_only": True, "tool_name": "OCRRegion", "ocr_text": "A7"},
            ),
        )
        self.assertEqual(feedback.status, EvaluationStatus.RUNNING)
        self.assertEqual(feedback.reason, "tool_completed")

    def test_rejection_does_not_end_episode_or_expose_answer(self):
        source = Source()
        evaluator = CaptchaEvaluator(source, poll_seconds=0)
        evaluator.reset()
        source.stats["total_verifications"] = 1
        feedback = evaluator.evaluate(
            Decision(Action(ActionKind.TAP, {"x": 1, "y": 1})),
            ExecutionResult(ok=True, elapsed_seconds=0),
        )
        self.assertEqual(feedback.status, EvaluationStatus.FAILED_ATTEMPT)
        self.assertFalse(feedback.done)
        self.assertEqual(feedback.reason, "dynamic_behavior_rejected")
        self.assertFalse(feedback.signals["answer_exposed"])
        self.assertNotIn("answer", feedback.signals)
        self.assertEqual(
            feedback.signals["verification_feedback"]["reason_code"],
            "dynamic_behavior_rejected",
        )

    def test_submit_records_when_verification_was_not_observed(self):
        source = Source()
        evaluator = CaptchaEvaluator(source, poll_seconds=0)
        evaluator.reset()
        feedback = evaluator.evaluate(
            Decision(Action(ActionKind.SUBMIT_CAPTCHA, {})),
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={"verification_action": True},
            ),
        )
        self.assertEqual(feedback.status, EvaluationStatus.RUNNING)
        observation = feedback.signals["submit_observation"]
        self.assertTrue(observation["verification_action"])
        self.assertFalse(observation["verification_observed"])
        self.assertEqual(observation["total_verifications_before"], 0)
        self.assertEqual(observation["total_verifications_after"], 0)
        self.assertEqual(observation["total_verifications_delta"], 0)

    def test_submit_records_when_verification_was_observed(self):
        source = Source()
        evaluator = CaptchaEvaluator(source, poll_seconds=0)
        evaluator.reset()
        source.stats["total_verifications"] = 1
        feedback = evaluator.evaluate(
            Decision(Action(ActionKind.SUBMIT, {})),
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={"verification_action": True},
            ),
        )
        observation = feedback.signals["submit_observation"]
        self.assertTrue(observation["verification_observed"])
        self.assertEqual(observation["total_verifications_before"], 0)
        self.assertEqual(observation["total_verifications_after"], 1)
        self.assertEqual(observation["total_verifications_delta"], 1)


if __name__ == "__main__":
    unittest.main()
