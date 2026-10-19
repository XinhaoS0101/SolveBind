"""Bind tool evidence to pending actions and enforce progress and recovery limits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

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
from hll.state import Phase, WorkflowState


GROUNDING_ACTIONS = {
    ActionKind.OCR,
    ActionKind.LOCATE_CAPTCHA_AREA,
    ActionKind.LOCATE_GRID,
    ActionKind.DETECT_BOARD,
    ActionKind.DETECT_CLICK_TARGETS,
    ActionKind.LOCATE_SLIDER_TRACK,
    ActionKind.LOCATE_SLIDER_HANDLE,
    ActionKind.LOCATE_GAP,
    ActionKind.ESTIMATE_DRAG_OFFSET,
    ActionKind.CORRECT_SLIDER_AFTER_FAILURE,
    ActionKind.CROP_REGION,
    ActionKind.ZOOM_REGION,
    ActionKind.CLASSIFY_REGION,
    ActionKind.NORMALIZE_TEXT,
    ActionKind.READ_CLICK_SEQUENCE,
    ActionKind.READ_LOGIC_PROMPT,
    ActionKind.SOLVE_ARITHMETIC,
    ActionKind.FIND_MATCH,
    ActionKind.FIND_WINNING_MOVE,
    ActionKind.COMPARE_SIMILARITY,
    ActionKind.DETECT_COLOR_MARKERS,
    ActionKind.GET_SCREENSHOT,
    ActionKind.GET_OBSERVATION,
    ActionKind.GET_SERVER_STATS,
    ActionKind.SUMMARIZE_TRAJECTORY,
    ActionKind.WAIT_PAGE_READY,
}
RECOVERY_OBSERVATION_ACTIONS = GROUNDING_ACTIONS | {ActionKind.CHECK, ActionKind.WAIT}
CORRECTION_ACTIONS = {
    ActionKind.TAP,
    ActionKind.TYPE,
    ActionKind.INPUT_TEXT,
    ActionKind.DRAG,
    ActionKind.DRAG_BY,
    ActionKind.KEY,
    ActionKind.TAP_GRID_CELL,
    ActionKind.MOVE_GRID_PIECE,
    ActionKind.TAP_REGION_CENTER,
    ActionKind.CLICK_TARGET,
    ActionKind.CLEAR_SELECTION,
}
SELECTION_ACTIONS = {
    ActionKind.TAP_GRID_CELL,
    ActionKind.TAP_REGION_CENTER,
    ActionKind.CLICK_TARGET,
}
SUBMIT_ACTIONS = {ActionKind.SUBMIT, ActionKind.SUBMIT_CAPTCHA}
REFRESH_ACTIONS = {ActionKind.REFRESH, ActionKind.REFRESH_CAPTCHA}


@dataclass(frozen=True)
class WorkflowConfig:
    max_ground_steps: int = 3
    max_execute_steps: int = 24
    max_submit_check_steps: int = 4
    max_recovery_ground_steps: int = 1
    max_corrections: int = 1
    max_refreshes: int = 1
    selection_submit_threshold: int = 6
    enforce_suggested_action: bool = True
    auto_submit_when_ready: bool = True
    completion_mode: str = "captcha"

    def __post_init__(self) -> None:
        for name in (
            "max_ground_steps",
            "max_execute_steps",
            "max_submit_check_steps",
            "max_recovery_ground_steps",
            "max_corrections",
            "max_refreshes",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be at least 1")
        if int(self.selection_submit_threshold) < 0:
            raise ValueError("selection_submit_threshold must be at least 0")
        if self.completion_mode not in {"captcha", "external"}:
            raise ValueError("completion_mode must be 'captcha' or 'external'")


class WorkflowPolicy:
    def __init__(self, config: WorkflowConfig | None = None) -> None:
        self.config = config or WorkflowConfig()
        self.state = WorkflowState()

    def reset(self, task: Task) -> None:
        del task
        self.state = WorkflowState()

    def context(self) -> dict[str, Any]:
        context = self.state.to_dict()
        context["recommended_recovery"] = recovery_strategy(
            self.state.last_failure_class
        )
        context["local_correction_preferred"] = bool(
            self.state.phase is Phase.RECOVER
            and self.state.failed_hypotheses
            and self.state.corrections_used < self.config.max_corrections
        )
        context["policy"] = {
            "phase_order": [phase.value for phase in Phase],
            "max_corrections": self.config.max_corrections,
            "max_refreshes": self.config.max_refreshes,
            "max_execute_steps": self.config.max_execute_steps,
            "selection_submit_threshold": self.config.selection_submit_threshold,
            "canonical_action_is_binding": self.config.enforce_suggested_action,
            "completion_mode": self.config.completion_mode,
        }
        return context

    def resolve(self, decision: Decision) -> Decision:
        if self.config.completion_mode == "external":
            return self._resolve_external(decision)
        proposed = decision.action
        resolved = proposed
        policy: dict[str, Any] = dict(decision.policy)
        policy.update({
            "phase_before": self.state.phase.value,
            "resolution": "accepted",
            "adherence": "not_applicable",
        })
        if proposed.kind is ActionKind.TAP_GRID_CELL:
            index = proposed.args.get("index")
            if isinstance(index, int) and index in self.state.grid_cell_history:
                policy["selection_revisit"] = index
        if proposed.kind.value in self.state.unavailable_actions:
            policy["previous_non_state_changing_failures"] = (
                self.state.unavailable_actions[proposed.kind.value]
            )

        if self.state.phase is Phase.DONE:
            resolved = Action(ActionKind.FINISH, {"reason": "workflow_done"})
            policy.update(resolution="overridden", guard="workflow_done")
        elif (
            self.state.phase is Phase.RECOVER
            and self.state.corrections_used >= self.config.max_corrections
        ):
            resolved = self._refresh_or_finish("correction_budget_exhausted")
            policy.update(resolution="overridden", guard="correction_budget_exhausted")
        elif (
            proposed.kind in REFRESH_ACTIONS
            and self.state.refreshes_used >= self.config.max_refreshes
        ):
            resolved = Action(ActionKind.FINISH, {"reason": "refresh_budget_exhausted"})
            policy.update(resolution="overridden", guard="refresh_budget_exhausted")
        elif self.state.pending_action is not None:
            # A pending commitment takes precedence over a conflicting proposal.
            canonical = self.state.pending_action
            policy["canonical_action"] = action_to_mapping(canonical)
            policy["canonical_source"] = self.state.pending_source
            if (
                proposed.kind in SUBMIT_ACTIONS
                and self.state.last_action is not None
                and actions_equal(self.state.last_action, canonical)
            ):
                self.state.pending_action = None
                self.state.pending_source = ""
                policy.update(adherence="submit_after_completed_canonical")
            elif self._selection_submit_due(proposed):
                resolved = Action(ActionKind.SUBMIT, {})
                self.state.pending_action = None
                self.state.pending_source = ""
                policy.update(
                    resolution="overridden",
                    guard="selection_submit_convergence",
                    adherence="overridden",
                    canonical_action=action_to_mapping(resolved),
                    canonical_source="selection_submit_threshold",
                )
            elif actions_equal(proposed, canonical):
                policy["adherence"] = "followed"
            elif self.config.enforce_suggested_action:
                resolved = canonical
                self.state.bad_tool_following += 1
                policy.update(resolution="overridden", adherence="overridden")
            else:
                policy["adherence"] = "deviated"
        elif self.state.ready_to_submit and self.config.auto_submit_when_ready:
            resolved = (
                proposed if proposed.kind in SUBMIT_ACTIONS else Action(ActionKind.SUBMIT, {})
            )
            policy.update(
                resolution="overridden" if proposed.kind not in SUBMIT_ACTIONS else "accepted",
                guard="submit_convergence",
                adherence="followed" if proposed.kind in SUBMIT_ACTIONS else "overridden",
                canonical_action=action_to_mapping(resolved),
                canonical_source="ready_to_submit",
            )
        elif self._selection_submit_due(proposed):
            resolved = Action(ActionKind.SUBMIT, {})
            policy.update(
                resolution="overridden",
                guard="selection_submit_convergence",
                canonical_action=action_to_mapping(resolved),
                canonical_source="selection_submit_threshold",
            )
        elif self._recovery_observation_exhausted(proposed):
            resolved = self._refresh_or_finish("recovery_observation_budget_exhausted")
            policy.update(
                resolution="overridden",
                guard="recovery_observation_budget_exhausted",
            )
        elif self._grounding_exhausted(proposed):
            resolved = Action(ActionKind.FINISH, {"reason": "grounding_budget_exhausted"})
            policy.update(resolution="overridden", guard="grounding_budget_exhausted")
        elif self._execute_phase_exhausted(proposed):
            resolved = Action(ActionKind.SUBMIT, {})
            policy.update(
                resolution="overridden",
                guard="execute_phase_convergence",
                canonical_action=action_to_mapping(resolved),
                canonical_source="execute_phase_budget",
            )
        elif self._submit_check_phase_exhausted(proposed):
            resolved = Action(ActionKind.CHECK, {})
            policy.update(
                resolution="overridden",
                guard="submit_check_phase_budget",
                canonical_action=action_to_mapping(resolved),
                canonical_source="submit_check_phase_budget",
            )
        elif (
            self.state.phase is Phase.RECOVER
            and proposed.kind in SUBMIT_ACTIONS
            and not self.state.ready_to_submit
        ):
            resolved = self._refresh_or_finish("submit_without_correction")
            policy.update(resolution="overridden", guard="submit_without_correction")

        if resolved is not proposed or policy.get("canonical_action"):
            proposed_action = proposed
        else:
            proposed_action = decision.proposed_action
        return replace(
            decision,
            action=resolved,
            proposed_action=proposed_action,
            reason=(
                f"workflow:{policy.get('guard')}"
                if resolved is not proposed and policy.get("guard")
                else decision.reason
            ),
            policy=policy,
        )

    def update(
        self,
        *,
        decision: Decision,
        execution: ExecutionResult,
        evaluation: Evaluation,
        before: Observation,
        after: Observation,
    ) -> None:
        if self.config.completion_mode == "external":
            self._update_external(
                decision=decision,
                execution=execution,
                evaluation=evaluation,
                before=before,
                after=after,
            )
            return
        action = decision.action
        phase_before = self.state.phase
        deferred_submit = bool(execution.details.get("deferred_submit"))
        state_changed = bool(execution.details.get("state_changed")) or screenshots_differ(
            before.screenshot_path,
            after.screenshot_path,
        )
        self.state.last_state_changed = state_changed
        self.state.last_action = action
        failure_class = classify_failure(execution, evaluation)
        if failure_class:
            self.state.last_failure_class = failure_class
            if not self.state.last_failure:
                self.state.last_failure = evaluation.reason or execution.error
        if failure_class in {"tool_error", "tool_not_applicable"} and not state_changed:
            action_name = action.kind.value
            self.state.unavailable_actions[action_name] = (
                self.state.unavailable_actions.get(action_name, 0) + 1
            )

        canonical_completed = (
            bool(execution.ok)
            and self.state.pending_action is not None
            and actions_equal(action, self.state.pending_action)
            and action.kind in CORRECTION_ACTIONS
        )
        # Consume dispatched commitments; feedback still determines progress.
        if self.state.pending_action is not None and actions_equal(
            action,
            self.state.pending_action,
        ):
            self.state.pending_action = None
            self.state.pending_source = ""

        if phase_before is Phase.RECOVER and action.kind in CORRECTION_ACTIONS:
            self.state.corrections_used += 1

        if action.kind in SUBMIT_ACTIONS and not deferred_submit:
            self.state.submit_attempts += 1
            self.state.ready_to_submit = False
            self.state.selection_actions_since_submit = 0
        elif action.kind is ActionKind.CHECK:
            self.state.check_attempts += 1
            self.state.selection_actions_since_submit = 0

        if evaluation.status is EvaluationStatus.SUCCESS:
            self.state.ready_to_submit = False
            self.state.pending_action = None
            self.state.selection_actions_since_submit = 0
            self.state.last_failure_class = ""
            self.state.interactions_since_submit.clear()
            self._advance(Phase.DONE)
            return

        if evaluation.done and evaluation.status in {
            EvaluationStatus.ERROR,
            EvaluationStatus.STOPPED,
        }:
            self._advance(Phase.DONE)
            return

        if action.kind is ActionKind.FINISH:
            self._advance(Phase.DONE)
            return

        if action.kind in REFRESH_ACTIONS:
            self.state.refreshes_used += 1
            self.state.ready_to_submit = False
            self.state.pending_action = None
            self.state.pending_source = ""
            self.state.selection_actions_since_submit = 0
            self.state.grid_cell_history.clear()
            self.state.grid_cell_revisits = 0
            self.state.unavailable_actions.clear()
            self.state.evidence_fingerprints.clear()
            self.state.interactions_since_submit.clear()
            self.state.failed_hypotheses.clear()
            self._advance(Phase.OBSERVE)
            return

        if evaluation.status is EvaluationStatus.FAILED_ATTEMPT:
            self.state.last_failure = evaluation.reason
            self.state.ready_to_submit = False
            self.state.pending_action = None
            self.state.pending_source = ""
            self.state.selection_actions_since_submit = 0
            if self.state.interactions_since_submit:
                hypothesis = [
                    action_to_mapping(item)
                    for item in self.state.interactions_since_submit[-6:]
                ]
                self.state.failed_hypotheses.append(hypothesis)
                self.state.failed_hypotheses = self.state.failed_hypotheses[-3:]
            self.state.interactions_since_submit.clear()
            self._advance(Phase.RECOVER)
            return

        read_only = bool(execution.details.get("read_only"))
        if read_only:
            self._record_evidence(execution.details)
            self.state.grounding_steps += 1
            if phase_before is Phase.RECOVER:
                self.state.recovery_grounding_steps += 1
            suggested = parse_suggested_action(execution.details)
            if suggested is not None:
                self._set_pending(suggested, str(execution.details.get("tool_name", "tool")))
            self._advance(Phase.RECOVER if phase_before is Phase.RECOVER else Phase.GROUND)
            return

        if action.kind in SUBMIT_ACTIONS:
            if deferred_submit:
                self.state.ready_to_submit = True
                self._set_pending(Action(ActionKind.SUBMIT, {}), "submit_deferred")
                self._advance(Phase.SUBMIT_CHECK)
                return
            if evaluation.status is EvaluationStatus.RUNNING:
                self._set_pending(Action(ActionKind.CHECK, {}), "submit_followup")
            self._advance(Phase.SUBMIT_CHECK)
            return

        if action.kind is ActionKind.CHECK:
            if evaluation.status is EvaluationStatus.RUNNING and self.state.submit_attempts > 0:
                self.state.last_failure = "verification_not_observed"
                self.state.last_failure_class = "verification_not_observed"
                self.state.pending_action = None
                self.state.pending_source = ""
                self._advance(Phase.RECOVER)
            else:
                self._advance(phase_before)
            return

        if action.kind is ActionKind.CLEAR_SELECTION:
            self.state.grid_cell_history.clear()
        if action.kind is ActionKind.TAP_GRID_CELL:
            index = action.args.get("index")
            if isinstance(index, int):
                self.state.grid_cell_revisits += int(index in self.state.grid_cell_history)
                self.state.grid_cell_history.append(index)
                self.state.grid_cell_history = self.state.grid_cell_history[-12:]
        if action.kind in SELECTION_ACTIONS:
            self.state.selection_actions_since_submit += 1
        if (
            action.kind in CORRECTION_ACTIONS
            and execution.ok
            and not execution.details.get("error")
        ):
            self.state.interactions_since_submit.append(action)
            self.state.interactions_since_submit = self.state.interactions_since_submit[-12:]

        ready = bool(execution.details.get("ready_to_submit")) or action.kind in {
            ActionKind.TYPE,
            ActionKind.INPUT_TEXT,
        } or canonical_completed or (
            phase_before is Phase.RECOVER and action.kind in CORRECTION_ACTIONS
        )
        if ready:
            self.state.ready_to_submit = True
            self._set_pending(Action(ActionKind.SUBMIT, {}), "action_completed")
            self._advance(Phase.SUBMIT_CHECK)
        else:
            suggested = parse_suggested_action(execution.details)
            if suggested is not None:
                self._set_pending(suggested, str(execution.details.get("tool_name", "tool")))
            self._advance(Phase.RECOVER if phase_before is Phase.RECOVER else Phase.EXECUTE)

    def _resolve_external(self, decision: Decision) -> Decision:
        proposed = decision.action
        resolved = proposed
        policy: dict[str, Any] = dict(decision.policy)
        policy.update(
            phase_before=self.state.phase.value,
            resolution="accepted",
            adherence="not_applicable",
        )
        if self.state.phase is Phase.DONE:
            resolved = Action(ActionKind.FINISH, {"reason": "workflow_done"})
            policy.update(resolution="overridden", guard="workflow_done")
        elif self.state.pending_action is not None:
            canonical = self.state.pending_action
            policy["canonical_action"] = action_to_mapping(canonical)
            policy["canonical_source"] = self.state.pending_source
            if actions_equal(proposed, canonical):
                policy["adherence"] = "followed"
            elif self.config.enforce_suggested_action:
                resolved = canonical
                self.state.bad_tool_following += 1
                policy.update(resolution="overridden", adherence="overridden")
            else:
                policy["adherence"] = "deviated"
        return replace(
            decision,
            action=resolved,
            proposed_action=(
                proposed if resolved is not proposed else decision.proposed_action
            ),
            reason=(
                f"workflow:{policy.get('guard')}"
                if resolved is not proposed and policy.get("guard")
                else decision.reason
            ),
            policy=policy,
        )

    def _update_external(
        self,
        *,
        decision: Decision,
        execution: ExecutionResult,
        evaluation: Evaluation,
        before: Observation,
        after: Observation,
    ) -> None:
        action = decision.action
        state_changed = bool(execution.details.get("state_changed")) or screenshots_differ(
            before.screenshot_path,
            after.screenshot_path,
        )
        self.state.last_state_changed = state_changed
        self.state.last_action = action

        failure_class = classify_failure(execution, evaluation)
        if failure_class:
            self.state.last_failure_class = failure_class
            self.state.last_failure = evaluation.reason or execution.error
            if not state_changed:
                name = action.kind.value
                self.state.unavailable_actions[name] = (
                    self.state.unavailable_actions.get(name, 0) + 1
                )

        if self.state.pending_action is not None and actions_equal(
            action,
            self.state.pending_action,
        ):
            self.state.pending_action = None
            self.state.pending_source = ""

        if evaluation.status is EvaluationStatus.SUCCESS or evaluation.done:
            self.state.pending_action = None
            self._advance(Phase.DONE)
            return
        if action.kind is ActionKind.FINISH:
            self._advance(Phase.DONE)
            return

        if bool(execution.details.get("read_only")):
            self._record_evidence(execution.details)
            self.state.grounding_steps += 1
            suggested = parse_suggested_action(execution.details)
            if suggested is not None:
                self._set_pending(
                    suggested,
                    str(execution.details.get("tool_name", "tool")),
                )
            self._advance(Phase.RECOVER if failure_class else Phase.GROUND)
            return

        if execution.ok and not execution.details.get("error"):
            self.state.interactions_since_submit.append(action)
            self.state.interactions_since_submit = self.state.interactions_since_submit[-12:]
            self._advance(Phase.EXECUTE)
        else:
            self._advance(Phase.RECOVER)

    def _refresh_or_finish(self, reason: str) -> Action:
        if self.state.refreshes_used < self.config.max_refreshes:
            return Action(ActionKind.REFRESH, {"reason": reason})
        return Action(ActionKind.FINISH, {"reason": reason})

    def _grounding_exhausted(self, proposed: Action) -> bool:
        return (
            proposed.kind in GROUNDING_ACTIONS
            and self.state.phase is Phase.GROUND
            and self.state.phase_steps >= self.config.max_ground_steps
        )

    def _execute_phase_exhausted(self, proposed: Action) -> bool:
        return (
            proposed.kind in CORRECTION_ACTIONS
            and self.state.phase is Phase.EXECUTE
            and self.state.phase_steps >= self.config.max_execute_steps
        )

    def _selection_submit_due(self, proposed: Action) -> bool:
        return (
            self.config.selection_submit_threshold > 0
            and proposed.kind in SELECTION_ACTIONS
            and self.state.selection_actions_since_submit >= self.config.selection_submit_threshold
        )

    def _recovery_observation_exhausted(self, proposed: Action) -> bool:
        return (
            self.state.phase is Phase.RECOVER
            and proposed.kind in RECOVERY_OBSERVATION_ACTIONS
            and self.state.recovery_grounding_steps >= self.config.max_recovery_ground_steps
        )

    def _submit_check_phase_exhausted(self, proposed: Action) -> bool:
        return (
            self.state.phase is Phase.SUBMIT_CHECK
            and self.state.phase_steps >= self.config.max_submit_check_steps
            and proposed.kind in {ActionKind.SUBMIT, ActionKind.CHECK, ActionKind.WAIT}
        )

    def _set_pending(self, action: Action, source: str) -> None:
        self.state.pending_action = action
        self.state.pending_source = source

    def _record_evidence(self, details: Mapping[str, Any]) -> None:
        fingerprint = evidence_fingerprint(details)
        if fingerprint in self.state.evidence_fingerprints:
            self.state.repeated_evidence_steps += 1
            self.state.last_evidence_was_new = False
            return
        self.state.evidence_fingerprints.append(fingerprint)
        self.state.evidence_fingerprints = self.state.evidence_fingerprints[-12:]
        self.state.new_evidence_steps += 1
        self.state.last_evidence_was_new = True

    def _advance(self, phase: Phase) -> None:
        if phase is self.state.phase:
            self.state.phase_steps += 1
            return
        self.state.phase = phase
        self.state.phase_steps = 1
        self.state.transitions += 1


def parse_suggested_action(details: Mapping[str, Any]) -> Action | None:
    value = details.get("canonical_action") or details.get("suggested_action")
    if not isinstance(value, Mapping):
        return None
    try:
        return Action.from_dict(value)
    except (TypeError, ValueError):
        return None


def classify_failure(execution: ExecutionResult, evaluation: Evaluation) -> str:
    if execution.details.get("not_applicable"):
        return "tool_not_applicable"
    if not execution.ok or execution.details.get("error"):
        return "tool_error"
    if evaluation.reason == "dynamic_behavior_rejected":
        return "behavior_rejected"
    if evaluation.reason == "captcha_rejected":
        return "content_rejected"
    if evaluation.reason == "action_execution_failed":
        return "tool_error"
    return ""


def recovery_strategy(failure_class: str) -> str:
    return {
        "tool_not_applicable": "reidentify_affordance",
        "tool_error": "reground_with_alternative_tool",
        "behavior_rejected": "change_interaction_keep_solution",
        "content_rejected": "correct_in_place_if_reversible_else_refresh",
        "verification_not_observed": "check_or_reground",
    }.get(failure_class, "")


def evidence_fingerprint(details: Mapping[str, Any]) -> str:
    keys = (
        "tool_name",
        "error",
        "not_applicable",
        "answer",
        "sequence",
        "challenge",
        "targets",
        "target_snapshot_id",
        "suggested_action",
        "canonical_action",
        "grid_bbox",
        "grid_rows",
        "grid_cols",
        "crop_bbox",
        "region",
        "point",
        "prompt_feedback",
    )
    payload = {key: details[key] for key in keys if key in details}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def action_to_mapping(action: Action) -> dict[str, Any]:
    return {"action": action.kind.value, "args": dict(action.args)}


def _comparable_action(action: Action) -> dict[str, Any]:
    comparable: dict[str, Any] = {}
    for key, value in sorted(action.args.items()):
        if key == "duration_ms":
            continue
        comparable[key] = value
    return {"action": action.kind.value, "args": comparable}


def actions_equal(left: Action, right: Action) -> bool:
    return _comparable_action(left) == _comparable_action(right)


def screenshots_differ(before_path: str, after_path: str) -> bool:
    if not before_path or not after_path or before_path == after_path:
        return False
    try:
        return _file_digest(Path(before_path)) != _file_digest(Path(after_path))
    except OSError:
        return False


def _file_digest(path: Path) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()
