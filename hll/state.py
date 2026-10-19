from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hll.domain import Action


class Phase(str, Enum):
    OBSERVE = "observe"
    GROUND = "ground"
    EXECUTE = "execute"
    SUBMIT_CHECK = "submit_check"
    RECOVER = "recover"
    DONE = "done"


@dataclass
class WorkflowState:
    phase: Phase = Phase.OBSERVE
    phase_steps: int = 0
    grounding_steps: int = 0
    recovery_grounding_steps: int = 0
    pending_action: Action | None = None
    pending_source: str = ""
    ready_to_submit: bool = False
    corrections_used: int = 0
    refreshes_used: int = 0
    submit_attempts: int = 0
    check_attempts: int = 0
    bad_tool_following: int = 0
    selection_actions_since_submit: int = 0
    grid_cell_history: list[int] = field(default_factory=list)
    grid_cell_revisits: int = 0
    unavailable_actions: dict[str, int] = field(default_factory=dict)
    evidence_fingerprints: list[str] = field(default_factory=list)
    new_evidence_steps: int = 0
    repeated_evidence_steps: int = 0
    last_evidence_was_new: bool = False
    interactions_since_submit: list[Action] = field(default_factory=list)
    failed_hypotheses: list[list[dict[str, Any]]] = field(default_factory=list)
    last_action: Action | None = None
    transitions: int = 0
    last_failure: str = ""
    last_failure_class: str = ""
    last_state_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "phase_steps": self.phase_steps,
            "grounding_steps": self.grounding_steps,
            "recovery_grounding_steps": self.recovery_grounding_steps,
            "pending_action": _action_dict(self.pending_action),
            "pending_source": self.pending_source,
            "ready_to_submit": self.ready_to_submit,
            "corrections_used": self.corrections_used,
            "refreshes_used": self.refreshes_used,
            "submit_attempts": self.submit_attempts,
            "check_attempts": self.check_attempts,
            "bad_tool_following": self.bad_tool_following,
            "selection_actions_since_submit": self.selection_actions_since_submit,
            "selection_ledger": {
                "grid_cell_history_since_refresh": list(self.grid_cell_history),
                "revisit_count": self.grid_cell_revisits,
            },
            "unavailable_actions": dict(self.unavailable_actions),
            "information_gain": {
                "new_evidence_steps": self.new_evidence_steps,
                "repeated_evidence_steps": self.repeated_evidence_steps,
                "last_evidence_was_new": self.last_evidence_was_new,
            },
            "failed_hypotheses": list(self.failed_hypotheses),
            "last_action": _action_dict(self.last_action),
            "transitions": self.transitions,
            "last_failure": self.last_failure,
            "last_failure_class": self.last_failure_class,
            "last_state_changed": self.last_state_changed,
        }


def _action_dict(action: Action | None) -> dict[str, Any] | None:
    if action is None:
        return None
    return {"action": action.kind.value, "args": dict(action.args)}
