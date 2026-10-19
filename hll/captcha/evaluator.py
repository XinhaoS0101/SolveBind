from __future__ import annotations

import time
from typing import Protocol

from hll.domain import (
    ActionKind,
    Decision,
    Evaluation,
    EvaluationStatus,
    ExecutionResult,
)
from hll.metrics import intentional_sleep


class StatsSource(Protocol):
    def get_stats(self) -> dict[str, int]: ...


class CaptchaEvaluator:
    def __init__(
        self,
        source: StatsSource,
        *,
        poll_seconds: float = 1.5,
        poll_interval: float = 0.1,
    ) -> None:
        self.source = source
        self.poll_seconds = max(0.0, poll_seconds)
        self.poll_interval = max(0.02, poll_interval)
        self.before: dict[str, int] = {}

    def reset(self) -> None:
        self.before = self._safe_stats()

    def evaluate(
        self,
        decision: Decision,
        execution: ExecutionResult,
    ) -> Evaluation:
        if execution.details.get("read_only"):
            return Evaluation(
                status=EvaluationStatus.RUNNING,
                reason="tool_completed" if execution.ok else "tool_failed",
                signals={
                    "answer_exposed": False,
                    "tool_name": execution.details.get("tool_name", ""),
                    "tool_error": execution.error,
                },
            )

        if decision.action.kind is ActionKind.FINISH:
            return Evaluation(
                status=EvaluationStatus.RUNNING,
                reason="agent_finished",
                signals={"answer_exposed": False},
            )

        if not execution.ok:
            if execution.details.get("recoverable"):
                return Evaluation(
                    status=EvaluationStatus.FAILED_ATTEMPT,
                    reward=-0.25,
                    reason="action_execution_failed",
                    done=False,
                    signals={
                        "answer_exposed": False,
                        "action": decision.action.kind.value,
                        "error": execution.error,
                    },
                )
            return Evaluation(
                status=EvaluationStatus.ERROR,
                reward=-1.0,
                reason=execution.error or "action_execution_failed",
                done=True,
                signals={"answer_exposed": False},
            )

        deadline = time.monotonic() + self.poll_seconds
        current = self._safe_stats()
        while time.monotonic() < deadline:
            if self._changed(current):
                break
            intentional_sleep(self.poll_interval, "evaluator_poll")
            current = self._safe_stats()

        delta = {
            key: current[key] - self.before.get(key, 0)
            for key in current
        }
        submit_like = _is_submit_like(decision, execution)
        signals = {
            "answer_exposed": False,
            "stats": current,
            "stats_delta": delta,
            "action": decision.action.kind.value,
        }
        if submit_like:
            signals["submit_observation"] = {
                "verification_action": bool(execution.details.get("verification_action", False)),
                "verification_observed": delta["total_verifications"] > 0,
                "total_verifications_before": int(self.before.get("total_verifications", 0) or 0),
                "total_verifications_after": current["total_verifications"],
                "total_verifications_delta": delta["total_verifications"],
                "successful_verifications_before": int(
                    self.before.get("successful_verifications", 0) or 0
                ),
                "successful_verifications_after": current["successful_verifications"],
                "successful_verifications_delta": delta["successful_verifications"],
                "poll_seconds": self.poll_seconds,
                "poll_interval": self.poll_interval,
            }
        if delta["total_verifications"] > 0:
            feedback_reader = getattr(self.source, "get_verification_feedback", None)
            if callable(feedback_reader):
                feedback = feedback_reader()
                if isinstance(feedback, dict) and not feedback.get("answer_exposed", False):
                    signals["verification_feedback"] = feedback
        self.before = current

        if current["successful_verifications"] > 0 or delta["successful_verifications"] > 0:
            return Evaluation(
                status=EvaluationStatus.SUCCESS,
                reward=1.0,
                reason="captcha_verified",
                done=True,
                signals=signals,
            )
        if delta["total_verifications"] > 0:
            feedback = signals.get("verification_feedback", {})
            rejection_reason = (
                "dynamic_behavior_rejected"
                if isinstance(feedback, dict)
                and feedback.get("reason_code") == "dynamic_behavior_rejected"
                else "captcha_rejected"
            )
            return Evaluation(
                status=EvaluationStatus.FAILED_ATTEMPT,
                reward=-0.25,
                reason=rejection_reason,
                done=False,
                signals=signals,
            )
        return Evaluation(
            status=EvaluationStatus.RUNNING,
            reason=str(execution.details.get("deferred_reason", "no_verification_yet")),
            signals=signals,
        )

    def _safe_stats(self) -> dict[str, int]:
        stats = self.source.get_stats()
        return {
            "page_views": int(stats.get("page_views", 0) or 0),
            "total_verifications": int(stats.get("total_verifications", 0) or 0),
            "successful_verifications": int(stats.get("successful_verifications", 0) or 0),
        }

    def _changed(self, current: dict[str, int]) -> bool:
        return (
            current["total_verifications"] > self.before.get("total_verifications", 0)
            or current["successful_verifications"]
            > self.before.get("successful_verifications", 0)
        )


def _is_submit_like(decision: Decision, execution: ExecutionResult) -> bool:
    return decision.action.kind in {
        ActionKind.SUBMIT,
        ActionKind.SUBMIT_CAPTCHA,
    } or bool(execution.details.get("verification_action", False))
