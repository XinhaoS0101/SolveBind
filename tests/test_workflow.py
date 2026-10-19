import tempfile
import unittest
from pathlib import Path

from hll.domain import (
    Action,
    ActionKind,
    Decision,
    Evaluation,
    EvaluationStatus,
    ExecutionResult,
    Observation,
    Task,
)
from hll.state import Phase
from hll.workflow import WorkflowConfig, WorkflowPolicy


def observation(path: str = ""):
    return Observation(
        step=0,
        screenshot_path=path,
        width=100,
        height=200,
        instruction="solve",
    )


def running(reason="no_verification_yet"):
    return Evaluation(EvaluationStatus.RUNNING, reason=reason)


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = WorkflowPolicy(
            WorkflowConfig(
                max_ground_steps=2,
                max_execute_steps=3,
                max_corrections=1,
                max_refreshes=1,
            )
        )
        self.policy.reset(Task("text", "solve"))
        self.obs = observation()

    def update(self, decision, execution, evaluation=None):
        self.policy.update(
            decision=decision,
            execution=execution,
            evaluation=evaluation or running(),
            before=self.obs,
            after=self.obs,
        )

    def test_tool_suggested_action_is_binding(self):
        ocr = Decision(Action(ActionKind.OCR, {"x1": 1, "y1": 2, "x2": 30, "y2": 40}))
        self.update(
            ocr,
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={
                    "read_only": True,
                    "tool_name": "OCRRegion",
                    "suggested_action": {
                        "action": "input_text",
                        "args": {"text": "M9YA"},
                    },
                },
            ),
        )

        model_decision = Decision(Action(ActionKind.TAP, {"x": 99, "y": 99}))
        resolved = self.policy.resolve(model_decision)
        self.assertEqual(resolved.action.kind, ActionKind.INPUT_TEXT)
        self.assertEqual(resolved.action.args["text"], "M9YA")
        self.assertEqual(resolved.proposed_action, model_decision.action)
        self.assertEqual(resolved.policy["adherence"], "overridden")
        self.assertEqual(self.policy.state.bad_tool_following, 1)

    def test_agent_retry_diagnostic_survives_policy_resolution(self):
        resolved = self.policy.resolve(
            Decision(
                Action(ActionKind.WAIT, {}),
                policy={"empty_response_retries": 1},
            )
        )
        self.assertEqual(resolved.policy["empty_response_retries"], 1)

    def test_grid_selection_ledger_records_revisits_without_blocking(self):
        first = Decision(Action(ActionKind.TAP_GRID_CELL, {"index": 2}))
        self.update(first, ExecutionResult(ok=True, elapsed_seconds=0))

        second = self.policy.resolve(
            Decision(Action(ActionKind.TAP_GRID_CELL, {"index": 2}))
        )
        self.assertEqual(second.action.kind, ActionKind.TAP_GRID_CELL)
        self.assertEqual(second.policy["selection_revisit"], 2)
        self.update(second, ExecutionResult(ok=True, elapsed_seconds=0))

        ledger = self.policy.context()["selection_ledger"]
        self.assertEqual(ledger["grid_cell_history_since_refresh"], [2, 2])
        self.assertEqual(ledger["revisit_count"], 1)

    def test_failure_class_distinguishes_behavior_and_tool_applicability(self):
        submit = Decision(Action(ActionKind.SUBMIT, {}))
        self.update(
            submit,
            ExecutionResult(ok=True, elapsed_seconds=0),
            Evaluation(
                EvaluationStatus.FAILED_ATTEMPT,
                reason="dynamic_behavior_rejected",
            ),
        )
        self.assertEqual(self.policy.state.last_failure_class, "behavior_rejected")

        policy = WorkflowPolicy()
        policy.reset(Task("generic", "solve"))
        policy.update(
            decision=Decision(Action(ActionKind.ESTIMATE_DRAG_OFFSET, {})),
            execution=ExecutionResult(
                ok=False,
                elapsed_seconds=0,
                details={"read_only": True, "not_applicable": True, "error": "not_applicable"},
                error="not_applicable",
            ),
            evaluation=running("tool_failed"),
            before=self.obs,
            after=self.obs,
        )
        self.assertEqual(policy.state.last_failure_class, "tool_not_applicable")
        self.assertEqual(
            policy.context()["recommended_recovery"],
            "reidentify_affordance",
        )

    def test_non_state_changing_tool_failure_is_remembered_until_refresh(self):
        clear = Decision(Action(ActionKind.CLEAR_SELECTION, {}))
        self.update(
            clear,
            ExecutionResult(
                ok=False,
                elapsed_seconds=0,
                details={"error": "not_found", "tool_name": "ClearSelection"},
                error="not_found",
            ),
        )

        self.assertEqual(self.policy.context()["unavailable_actions"], {"clear_selection": 1})
        resolved = self.policy.resolve(clear)
        self.assertEqual(resolved.policy["previous_non_state_changing_failures"], 1)

        refresh = Decision(Action(ActionKind.REFRESH, {}))
        self.update(refresh, ExecutionResult(ok=True, elapsed_seconds=0))
        self.assertEqual(self.policy.context()["unavailable_actions"], {})

    def test_repeated_read_only_evidence_is_counted(self):
        locate = Decision(Action(ActionKind.LOCATE_GRID, {}))
        result = ExecutionResult(
            ok=True,
            elapsed_seconds=0,
            details={"read_only": True, "tool_name": "LocateGrid", "grid_rows": 3},
        )
        self.update(locate, result)
        self.update(locate, result)

        gain = self.policy.context()["information_gain"]
        self.assertEqual(gain["new_evidence_steps"], 1)
        self.assertEqual(gain["repeated_evidence_steps"], 1)
        self.assertFalse(gain["last_evidence_was_new"])

    def test_failed_interactions_are_exposed_as_recovery_hypothesis(self):
        tap = Decision(Action(ActionKind.TAP_GRID_CELL, {"index": 2}))
        self.update(tap, ExecutionResult(ok=True, elapsed_seconds=0))
        submit = Decision(Action(ActionKind.SUBMIT, {}))
        self.update(
            submit,
            ExecutionResult(ok=True, elapsed_seconds=0),
            Evaluation(EvaluationStatus.FAILED_ATTEMPT, reason="captcha_rejected"),
        )

        context = self.policy.context()
        self.assertEqual(
            context["failed_hypotheses"],
            [[{"action": "tap_grid_cell", "args": {"index": 2}}]],
        )
        self.assertTrue(context["local_correction_preferred"])
        self.assertEqual(
            context["recommended_recovery"],
            "correct_in_place_if_reversible_else_refresh",
        )

    def test_nearby_coordinate_does_not_replace_exact_canonical_coordinate(self):
        self.policy.state.pending_action = Action(ActionKind.TAP, {"x": 100, "y": 200})
        self.policy.state.pending_source = "tool"
        resolved = self.policy.resolve(
            Decision(Action(ActionKind.TAP, {"x": 101, "y": 201}))
        )
        self.assertEqual(resolved.action.args, {"x": 100, "y": 200})
        self.assertEqual(resolved.policy["adherence"], "overridden")

    def test_submit_can_follow_completed_canonical_action(self):
        canonical = Action(ActionKind.TAP_REGION_CENTER, {"region_id": "candidate"})
        self.policy.state.pending_action = canonical
        self.policy.state.pending_source = "FindMatch"
        self.policy.state.last_action = canonical

        resolved = self.policy.resolve(Decision(Action(ActionKind.SUBMIT_CAPTCHA, {})))

        self.assertEqual(resolved.action.kind, ActionKind.SUBMIT_CAPTCHA)
        self.assertEqual(resolved.policy["adherence"], "submit_after_completed_canonical")
        self.assertIsNone(self.policy.state.pending_action)

    def test_selection_convergence_submits_after_threshold(self):
        policy = WorkflowPolicy(WorkflowConfig(selection_submit_threshold=2))
        policy.reset(Task("image", "select matching images"))
        policy.state.selection_actions_since_submit = 2
        policy.state.pending_action = Action(ActionKind.TAP_GRID_CELL, {"index": 5})
        policy.state.pending_source = "FindMatch"

        resolved = policy.resolve(
            Decision(Action(ActionKind.TAP_GRID_CELL, {"index": 5}))
        )

        self.assertEqual(resolved.action.kind, ActionKind.SUBMIT)
        self.assertEqual(resolved.policy["guard"], "selection_submit_convergence")
        self.assertIsNone(policy.state.pending_action)

    def test_completed_action_forces_submit_then_check(self):
        typed = Decision(Action(ActionKind.INPUT_TEXT, {"text": "M9YA"}))
        self.update(
            typed,
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={"ready_to_submit": True},
            ),
        )
        self.assertEqual(self.policy.state.phase, Phase.SUBMIT_CHECK)

        resolved_submit = self.policy.resolve(
            Decision(Action(ActionKind.TAP, {"x": 5, "y": 5}))
        )
        self.assertEqual(resolved_submit.action.kind, ActionKind.SUBMIT)
        self.update(
            resolved_submit,
            ExecutionResult(ok=True, elapsed_seconds=0),
        )

        resolved_check = self.policy.resolve(
            Decision(Action(ActionKind.TAP, {"x": 6, "y": 6}))
        )
        self.assertEqual(resolved_check.action.kind, ActionKind.CHECK)
        self.update(
            resolved_check,
            ExecutionResult(ok=True, elapsed_seconds=0),
        )
        self.assertEqual(self.policy.state.phase, Phase.RECOVER)

    def test_multistep_drag_does_not_submit_until_completion_signal(self):
        first_drag = Decision(
            Action(ActionKind.DRAG, {"x1": 1, "y1": 2, "x2": 40, "y2": 2})
        )
        self.update(
            first_drag,
            ExecutionResult(ok=True, elapsed_seconds=0, details={"interaction_progress": True}),
        )
        self.assertEqual(self.policy.state.phase, Phase.EXECUTE)
        self.assertFalse(self.policy.state.ready_to_submit)

        final_drag = Decision(
            Action(
                ActionKind.DRAG,
                {"x1": 2, "y1": 2, "x2": 50, "y2": 2, "complete": True},
            )
        )
        self.update(
            final_drag,
            ExecutionResult(ok=True, elapsed_seconds=0, details={"ready_to_submit": True}),
        )
        self.assertEqual(self.policy.state.phase, Phase.SUBMIT_CHECK)
        self.assertEqual(
            self.policy.resolve(Decision(Action(ActionKind.TAP, {"x": 8, "y": 8}))).action.kind,
            ActionKind.SUBMIT,
        )

    def test_fixed_submit_tool_counts_as_submit_phase_action(self):
        submit = Decision(Action(ActionKind.SUBMIT_CAPTCHA, {}))
        self.update(submit, ExecutionResult(ok=True, elapsed_seconds=0))
        self.assertEqual(self.policy.state.submit_attempts, 1)
        self.assertEqual(self.policy.state.phase, Phase.SUBMIT_CHECK)

    def test_deferred_submit_keeps_submit_pending_without_counting_attempt(self):
        submit = Decision(Action(ActionKind.SUBMIT_CAPTCHA, {}))
        self.update(
            submit,
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={"deferred_submit": True, "state_changed": True},
            ),
            running("verify_button_not_visible_scrolled"),
        )

        self.assertEqual(self.policy.state.submit_attempts, 0)
        self.assertTrue(self.policy.state.ready_to_submit)
        self.assertEqual(self.policy.state.pending_action.kind, ActionKind.SUBMIT)
        resolved = self.policy.resolve(Decision(Action(ActionKind.CHECK, {})))
        self.assertEqual(resolved.action.kind, ActionKind.SUBMIT)

    def test_hll_read_only_tool_suggested_drag_is_binding(self):
        estimate = Decision(Action(ActionKind.ESTIMATE_DRAG_OFFSET, {}))
        self.update(
            estimate,
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={
                    "read_only": True,
                    "tool_name": "EstimateDragOffset",
                    "suggested_action": {
                        "action": "drag",
                        "args": {
                            "x1": 10,
                            "y1": 20,
                            "x2": 120,
                            "y2": 20,
                            "complete": True,
                        },
                    },
                },
            ),
        )

        resolved = self.policy.resolve(
            Decision(Action(ActionKind.DRAG, {"x1": 1, "y1": 2, "x2": 3, "y2": 4}))
        )
        self.assertEqual(resolved.action.args["x1"], 10)
        self.assertEqual(resolved.action.args["complete"], True)
        self.assertEqual(resolved.policy["adherence"], "overridden")

    def test_completed_tool_canonical_action_converges_to_submit(self):
        find_move = Decision(Action(ActionKind.FIND_WINNING_MOVE, {}))
        canonical_drag = {
            "action": "drag",
            "args": {"x1": 10, "y1": 20, "x2": 40, "y2": 20},
        }
        self.update(
            find_move,
            ExecutionResult(
                ok=True,
                elapsed_seconds=0,
                details={
                    "read_only": True,
                    "tool_name": "FindWinningMove",
                    "suggested_action": canonical_drag,
                },
            ),
        )

        drag = self.policy.resolve(
            Decision(Action(ActionKind.DRAG, {"x1": 1, "y1": 2, "x2": 3, "y2": 4}))
        )
        self.assertEqual(drag.action.args["x1"], 10)
        self.update(drag, ExecutionResult(ok=True, elapsed_seconds=0))

        self.assertTrue(self.policy.state.ready_to_submit)
        self.assertEqual(self.policy.state.phase, Phase.SUBMIT_CHECK)
        submit = self.policy.resolve(Decision(Action(ActionKind.FIND_WINNING_MOVE, {})))
        self.assertEqual(submit.action.kind, ActionKind.SUBMIT)
        self.assertEqual(submit.policy["canonical_source"], "action_completed")

    def test_one_correction_then_refresh_then_finish(self):
        failed = Evaluation(
            EvaluationStatus.FAILED_ATTEMPT,
            reason="captcha_rejected",
        )
        submit = Decision(Action(ActionKind.SUBMIT, {}))
        self.update(submit, ExecutionResult(ok=True, elapsed_seconds=0), failed)
        self.assertEqual(self.policy.state.phase, Phase.RECOVER)

        correction = self.policy.resolve(
            Decision(Action(ActionKind.DRAG, {"x1": 1, "y1": 2, "x2": 50, "y2": 2}))
        )
        self.update(
            correction,
            ExecutionResult(ok=True, elapsed_seconds=0, details={"ready_to_submit": True}),
        )
        self.assertEqual(self.policy.state.corrections_used, 1)

        retry_submit = self.policy.resolve(Decision(Action(ActionKind.SUBMIT, {})))
        self.update(retry_submit, ExecutionResult(ok=True, elapsed_seconds=0), failed)
        recovery = self.policy.resolve(
            Decision(Action(ActionKind.DRAG, {"x1": 2, "y1": 2, "x2": 40, "y2": 2}))
        )
        self.assertEqual(recovery.action.kind, ActionKind.REFRESH)
        self.update(recovery, ExecutionResult(ok=True, elapsed_seconds=0))
        self.assertEqual(self.policy.state.refreshes_used, 1)

        self.update(submit, ExecutionResult(ok=True, elapsed_seconds=0), failed)
        terminal = self.policy.resolve(
            Decision(Action(ActionKind.DRAG, {"x1": 3, "y1": 2, "x2": 30, "y2": 2}))
        )
        self.assertEqual(terminal.action.kind, ActionKind.FINISH)

    def test_execute_phase_converges_to_submit(self):
        for index in range(3):
            tap = Decision(Action(ActionKind.TAP, {"x": 32 + index * 64, "y": 96}))
            resolved = self.policy.resolve(tap)
            self.update(resolved, ExecutionResult(ok=True, elapsed_seconds=0))
        forced = self.policy.resolve(
            Decision(Action(ActionKind.TAP, {"x": 300, "y": 96}))
        )
        self.assertEqual(forced.action.kind, ActionKind.SUBMIT)
        self.assertEqual(forced.policy["guard"], "execute_phase_convergence")

    def test_explicit_refresh_cannot_exceed_budget(self):
        refresh = Decision(Action(ActionKind.REFRESH, {}))
        first = self.policy.resolve(refresh)
        self.assertEqual(first.action.kind, ActionKind.REFRESH)
        self.update(first, ExecutionResult(ok=True, elapsed_seconds=0))
        second = self.policy.resolve(refresh)
        self.assertEqual(second.action.kind, ActionKind.FINISH)
        self.assertEqual(second.policy["guard"], "refresh_budget_exhausted")

    def test_grounding_phase_has_a_hard_limit(self):
        ocr = Decision(Action(ActionKind.OCR, {"x1": 1, "y1": 2, "x2": 30, "y2": 40}))
        result = ExecutionResult(
            ok=True,
            elapsed_seconds=0,
            details={"read_only": True, "tool_name": "OCRRegion"},
        )
        for _ in range(2):
            resolved = self.policy.resolve(ocr)
            self.assertEqual(resolved.action.kind, ActionKind.OCR)
            self.update(resolved, result)
        blocked = self.policy.resolve(ocr)
        self.assertEqual(blocked.action.kind, ActionKind.FINISH)
        self.assertEqual(blocked.policy["guard"], "grounding_budget_exhausted")

    def test_screenshot_change_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            before_path = Path(directory) / "before.png"
            after_path = Path(directory) / "after.png"
            before_path.write_bytes(b"before")
            after_path.write_bytes(b"after")
            before = observation(str(before_path))
            after = observation(str(after_path))
            tap = Decision(Action(ActionKind.TAP, {"x": 1, "y": 2}))
            self.policy.update(
                decision=tap,
                execution=ExecutionResult(ok=True, elapsed_seconds=0),
                evaluation=running(),
                before=before,
                after=after,
            )
        self.assertTrue(self.policy.state.last_state_changed)


if __name__ == "__main__":
    unittest.main()
