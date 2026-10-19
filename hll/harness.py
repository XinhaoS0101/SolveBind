"""The harness owns dispatch, budgets, evaluation, tracing, and cleanup."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Protocol

from hll.agent import InvalidModelAction
from hll.domain import (
    Action,
    ActionKind,
    Decision,
    EpisodeResult,
    Evaluation,
    EvaluationStatus,
    ExecutionResult,
    Observation,
    StepRecord,
    Task,
)
from hll.executor import READ_ONLY_ACTIONS
from hll.metrics import (
    EpisodeModelMeter,
    PricingConfig,
    activate_model_meter,
)
from hll.workflow import WorkflowPolicy, actions_equal, parse_suggested_action


class Agent(Protocol):
    def reset(self, task: Task) -> None: ...

    def decide(self, observation: Observation) -> Decision: ...

    def update(self, record: StepRecord) -> None: ...


class Environment(Protocol):
    def reset(self, task: Task, output_dir: Path) -> Observation: ...

    def observe(self, step: int) -> Observation: ...

    def execute(self, decision: Decision) -> ExecutionResult: ...

    def close(self) -> None: ...


class Evaluator(Protocol):
    def reset(self) -> None: ...

    def evaluate(
        self,
        decision: Decision,
        execution: ExecutionResult,
    ) -> Evaluation: ...


class Executor(Protocol):
    def execute(
        self,
        decision: Decision,
        observation: Observation,
    ) -> ExecutionResult: ...


class EnvironmentExecutor:
    def __init__(self, environment: Environment) -> None:
        self.environment = environment

    def execute(
        self,
        decision: Decision,
        observation: Observation,
    ) -> ExecutionResult:
        return self.environment.execute(decision)


@dataclass(frozen=True)
class HarnessConfig:
    max_steps: int = 32
    max_read_only_steps: int = 32
    max_total_steps: int | None = None
    max_invalid_actions: int = 10
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if self.max_read_only_steps < 0:
            raise ValueError("max_read_only_steps cannot be negative")
        if self.max_total_steps is not None and self.max_total_steps < 1:
            raise ValueError("max_total_steps must be at least 1")
        if self.max_invalid_actions < 0:
            raise ValueError("max_invalid_actions cannot be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class Harness:
    def __init__(
        self,
        *,
        agent: Agent,
        environment: Environment,
        evaluator: Evaluator,
        executor: Executor | None = None,
        workflow: WorkflowPolicy | None = None,
        config: HarnessConfig | None = None,
        metadata: Mapping[str, Any] | None = None,
        pricing: PricingConfig | None = None,
    ) -> None:
        self.agent = agent
        self.environment = environment
        self.evaluator = evaluator
        self.executor = executor or EnvironmentExecutor(environment)
        self.workflow = workflow or WorkflowPolicy()
        self.config = config or HarnessConfig()
        self.metadata = dict(metadata or {})
        self.pricing = pricing or PricingConfig()

    def run(self, task: Task, output_dir: Path) -> EpisodeResult:
        meter = EpisodeModelMeter(self.pricing)
        with activate_model_meter(meter):
            return self._run(task, output_dir, meter)

    def _run(
        self,
        task: Task,
        output_dir: Path,
        meter: EpisodeModelMeter,
    ) -> EpisodeResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        partial_path = output_dir / "episode.partial.json"
        started = time.monotonic()
        records: list[StepRecord] = []
        status = EvaluationStatus.STOPPED
        reason = "step_budget_exhausted"
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        action_steps = 0
        read_only_steps = 0
        invalid_action_steps = 0
        tool_calls: dict[str, int] = {}
        tool_errors = 0

        def build_result(
            current_status: EvaluationStatus,
            current_reason: str,
        ) -> EpisodeResult:
            elapsed_seconds = round(time.monotonic() - started, 4)
            model_accounting = meter.snapshot()
            model_usage = _compatible_model_usage(model_accounting, usage)
            return EpisodeResult(
                task=task,
                success=current_status is EvaluationStatus.SUCCESS,
                status=current_status,
                reason=current_reason,
                steps=tuple(records),
                elapsed_seconds=elapsed_seconds,
                output_dir=str(output_dir.resolve()),
                metrics={
                    "sample_id": str(task.config.get("sample_id", "")),
                    "seed": task.config.get("seed"),
                    "model_usage": model_usage,
                    "model_accounting": model_accounting,
                    "steps": len(records),
                    "action_steps": action_steps,
                    "read_only_steps": read_only_steps,
                    "invalid_action_steps": invalid_action_steps,
                    "tool_calls": dict(tool_calls),
                    "tool_errors": tool_errors,
                    "workflow": self.workflow.context(),
                    "trajectory_diagnostics": _trajectory_diagnostics(
                        records,
                        elapsed_seconds=elapsed_seconds,
                        model_usage=model_usage,
                        model_accounting=model_accounting,
                    ),
                    "run": dict(self.metadata),
                },
            )

        try:
            self.agent.reset(task)
            self.workflow.reset(task)
            build_result(EvaluationStatus.RUNNING, "episode_starting").write_json(partial_path)
            observation = self.environment.reset(task, output_dir)
            self.evaluator.reset()
            observation = replace(
                observation,
                workflow_state=self.workflow.context(),
            )

            total_step_limit = self.config.max_total_steps or (
                self.config.max_steps + self.config.max_read_only_steps
            )
            for step in range(1, total_step_limit + 1):
                if time.monotonic() - started >= self.config.timeout_seconds:
                    reason = "episode_timeout"
                    break

                workflow_before = self.workflow.context()
                try:
                    proposed_decision = self.agent.decide(observation)
                except InvalidModelAction as exc:
                    invalid_action_steps += 1
                    raw_response = getattr(exc, "raw_response", "")
                    invalid_usage = getattr(exc, "usage", {})
                    if isinstance(invalid_usage, Mapping):
                        for key in usage:
                            usage[key] += int(invalid_usage.get(key, 0) or 0)
                    stop_for_invalid = invalid_action_steps >= self.config.max_invalid_actions
                    invalid_reason = (
                        "invalid_model_action_budget_exhausted"
                        if stop_for_invalid
                        else "invalid_model_action"
                    )
                    decision = Decision(
                        Action(ActionKind.INVALID, {"message": str(exc)}),
                        reason=invalid_reason,
                        raw_response=str(raw_response),
                        usage=invalid_usage if isinstance(invalid_usage, Mapping) else {},
                    )
                    execution = ExecutionResult(
                        ok=False,
                        elapsed_seconds=0.0,
                        details={
                            "invalid_model_action": True,
                            "raw_response": str(raw_response),
                            "error": str(exc),
                        },
                        error=str(exc),
                    )
                    evaluation = Evaluation(
                        status=EvaluationStatus.STOPPED if stop_for_invalid else EvaluationStatus.FAILED_ATTEMPT,
                        reward=-0.25,
                        reason=invalid_reason,
                        done=stop_for_invalid,
                        signals={
                            "answer_exposed": False,
                            "invalid_model_action": True,
                            "raw_response": str(raw_response),
                        },
                    )
                    record = StepRecord(
                        step=step,
                        observation=observation,
                        decision=decision,
                        execution=execution,
                        after=observation,
                        evaluation=evaluation,
                        workflow_before=workflow_before,
                        workflow_after=self.workflow.context(),
                    )
                    records.append(record)
                    self.agent.update(record)
                    build_result(
                        evaluation.status if evaluation.done else EvaluationStatus.RUNNING,
                        evaluation.reason if evaluation.done else "episode_running",
                    ).write_json(partial_path)
                    if stop_for_invalid:
                        status = evaluation.status
                        reason = evaluation.reason
                        break
                    observation = replace(
                        observation,
                        last_feedback=(
                            "The previous model response was not one valid JSON action. "
                            "Return exactly one JSON object matching the allowed action schema."
                        ),
                        tool_results={},
                        workflow_state=self.workflow.context(),
                    )
                    continue
                # Mediate every model proposal before any operation is dispatched.
                decision = self.workflow.resolve(proposed_decision)
                action_is_read_only = decision.action.kind in READ_ONLY_ACTIONS
                if action_is_read_only:
                    if read_only_steps >= self.config.max_read_only_steps:
                        status = EvaluationStatus.STOPPED
                        reason = "read_only_step_budget_exhausted"
                        break
                elif action_steps >= self.config.max_steps:
                    status = EvaluationStatus.STOPPED
                    reason = "action_step_budget_exhausted"
                    break
                for key in usage:
                    usage[key] += int(decision.usage.get(key, 0) or 0)

                execution = self.executor.execute(decision, observation)
                read_only = action_is_read_only or bool(execution.details.get("read_only", False))
                if read_only:
                    read_only_steps += 1
                    tool_name = str(execution.details.get("tool_name", decision.action.kind.value))
                    tool_calls[tool_name] = tool_calls.get(tool_name, 0) + 1
                    if not execution.ok:
                        tool_errors += 1
                    tool_usage = execution.details.get("usage", {})
                    if isinstance(tool_usage, dict):
                        for key in usage:
                            usage[key] += int(tool_usage.get(key, 0) or 0)
                else:
                    action_steps += 1
                after = self.environment.observe(step)
                evaluation = self.evaluator.evaluate(decision, execution)

                if read_only:
                    after = replace(after, tool_results=dict(execution.details))

                if decision.action.kind is ActionKind.FINISH and not evaluation.done:
                    evaluation = Evaluation(
                        status=EvaluationStatus.STOPPED,
                        reason=str(decision.action.args.get("reason", "agent_finished")),
                        done=True,
                        signals=evaluation.signals,
                    )

                self.workflow.update(
                    decision=decision,
                    execution=execution,
                    evaluation=evaluation,
                    before=observation,
                    after=after,
                )
                workflow_after = self.workflow.context()

                record = StepRecord(
                    step=step,
                    observation=observation,
                    decision=decision,
                    execution=execution,
                    after=after,
                    evaluation=evaluation,
                    workflow_before=workflow_before,
                    workflow_after=workflow_after,
                )
                records.append(record)
                self.agent.update(record)
                checkpoint_status = evaluation.status if evaluation.done else EvaluationStatus.RUNNING
                checkpoint_reason = evaluation.reason if evaluation.done else "episode_running"
                build_result(checkpoint_status, checkpoint_reason).write_json(partial_path)

                if evaluation.done:
                    status = evaluation.status
                    reason = evaluation.reason
                    break

                observation = replace(
                    after,
                    last_feedback=evaluation.reason,
                    tool_results=dict(execution.details) if read_only else {},
                    workflow_state=workflow_after,
                )
            else:
                status = EvaluationStatus.STOPPED

        except Exception as exc:
            status = EvaluationStatus.ERROR
            reason = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self.environment.close()
            except Exception as exc:
                if status is not EvaluationStatus.ERROR:
                    status = EvaluationStatus.ERROR
                    reason = f"cleanup_failed: {type(exc).__name__}: {exc}"

        result = build_result(status, reason)
        result.write_json(output_dir / "episode.json")
        partial_path.unlink(missing_ok=True)
        return result


def _trajectory_diagnostics(
    records: list[StepRecord],
    *,
    elapsed_seconds: float,
    model_usage: Mapping[str, Any],
    model_accounting: Mapping[str, Any],
) -> dict[str, Any]:
    action_sequence: list[str] = []
    tool_sequence: list[str] = []
    tool_error_steps: list[dict[str, Any]] = []
    submit_steps: list[int] = []
    check_steps: list[int] = []
    suggested_actions = 0
    suggested_actions_followed = 0
    suggested_actions_overridden = 0
    read_only_repeats = 0
    previous_read_only_tool = ""
    pending_suggestion: Action | None = None
    total_tool_elapsed = 0.0

    for record in records:
        action = record.decision.action
        details = record.execution.details or {}
        action_sequence.append(action.kind.value)
        total_tool_elapsed += float(record.execution.elapsed_seconds or 0.0)

        tool_name = str(details.get("tool_name", "") or "")
        if tool_name:
            tool_sequence.append(tool_name)

        read_only = bool(details.get("read_only", False))
        if read_only and tool_name and tool_name == previous_read_only_tool:
            read_only_repeats += 1
        previous_read_only_tool = tool_name if read_only else ""

        if not record.execution.ok or details.get("error"):
            tool_error_steps.append(
                {
                    "step": record.step,
                    "action": action.kind.value,
                    "tool_name": tool_name,
                    "error": str(details.get("error") or record.execution.error or ""),
                }
            )

        if action.kind in {ActionKind.SUBMIT, ActionKind.SUBMIT_CAPTCHA} or details.get(
            "verification_action"
        ):
            submit_steps.append(record.step)
        if action.kind is ActionKind.CHECK:
            check_steps.append(record.step)

        if pending_suggestion is not None:
            if actions_equal(action, pending_suggestion):
                suggested_actions_followed += 1
            if record.decision.policy.get("adherence") == "overridden":
                suggested_actions_overridden += 1
            pending_suggestion = None

        suggested = parse_suggested_action(details)
        if suggested is not None:
            suggested_actions += 1
            pending_suggestion = suggested

    timing = model_accounting.get("timing", {}) or {}
    model_wait_seconds = float(timing.get("model_request_seconds", 0) or 0)
    effective_window = float(
        timing.get("effective_model_window_seconds", 0) or 0
    )
    total_tokens = int(model_usage.get("total_tokens", 0) or 0)
    step_count = max(1, len(records))
    return {
        "action_sequence": action_sequence,
        "tool_sequence": tool_sequence,
        "tool_error_steps": tool_error_steps,
        "submitted": bool(submit_steps),
        "submit_steps": submit_steps,
        "check_steps": check_steps,
        "suggested_actions": suggested_actions,
        "suggested_actions_followed": suggested_actions_followed,
        "suggested_actions_overridden": suggested_actions_overridden,
        "read_only_repeats": read_only_repeats,
        "tool_elapsed_seconds": round(total_tool_elapsed, 4),
        "model_wait_seconds": round(model_wait_seconds, 4),
        "model_wait_ratio": round(model_wait_seconds / effective_window, 4)
        if effective_window > 0
        else 0.0,
        "effective_model_window_seconds": round(effective_window, 4),
        "intentional_wait_seconds": float(
            timing.get("intentional_wait_seconds", 0) or 0
        ),
        "tokens_per_step": round(total_tokens / step_count, 2),
    }


def _compatible_model_usage(
    model_accounting: Mapping[str, Any],
    fallback: Mapping[str, int],
) -> dict[str, int]:
    tracked = (model_accounting.get("usage", {}) or {}).get("total", {}) or {}
    if int(tracked.get("request_count", 0) or 0) <= 0:
        return {key: int(value or 0) for key, value in fallback.items()}
    return {
        "prompt_tokens": int(tracked.get("input_tokens", 0) or 0),
        "completion_tokens": int(tracked.get("output_tokens", 0) or 0),
        "total_tokens": int(tracked.get("total_tokens", 0) or 0),
    }
