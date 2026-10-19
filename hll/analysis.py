from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ANALYSIS_SCHEMA_VERSION = "1.1"
SUMMARY_FILES = {"batch.json", "results.json", "agent_trace.json"}


def analyze_paths(inputs: Iterable[Path]) -> dict[str, Any]:


    sources = _discover_sources(inputs)
    episodes: list[dict[str, Any]] = []
    source_metadata: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for source in sources:
        loaded, metadata = _load_source(source)
        source_metadata.append(
            {
                "path": str(source.resolve()),
                "kind": source.name,
                "metadata": metadata,
            }
        )
        for episode in loaded:
            key = (str(source.resolve()), str(episode.get("sample_id", "")))
            if key in seen:
                continue
            seen.add(key)
            episodes.append(episode)

    return {
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": source_metadata,
        "summary": _aggregate(episodes),
        "by_captcha_type": _group_by_captcha_type(episodes),
        "issues": _issue_summary(episodes),
        "episodes": episodes,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# Trajectory Analysis",
        "",
        f"- Episodes: {summary.get('episodes', 0)}",
        f"- Successes: {summary.get('successes', 0)}",
        f"- Success rate: {summary.get('success_rate', 0):.1%}",
        f"- Average steps: {summary.get('average_steps', 0)}",
        f"- Average elapsed seconds: {summary.get('average_elapsed_seconds', 0)}",
        f"- Average effective model seconds: {summary.get('average_effective_model_window_seconds', 0)}",
        f"- Total input/output tokens: {summary.get('input_tokens', 0)} / {summary.get('output_tokens', 0)}",
        f"- Total model cost (USD): {summary.get('total_cost_usd', 0):.8f}",
        "",
        "## Reproducibility",
        "",
        "| Source | Commit | Workflow | Tool schema | Model |",
        "|---|---|---|---|---|",
    ]
    for source in report.get("sources", []):
        metadata = source.get("metadata", {}) or {}
        workflow = metadata.get("workflow", {}) or {}
        tools = metadata.get("tool_schema", {}) or {}
        lines.append(
            "| "
            + " | ".join(
                _md(value)
                for value in (
                    Path(str(source.get("path", ""))).name,
                    metadata.get("commit", ""),
                    workflow.get("version", ""),
                    str(tools.get("sha256", ""))[:12],
                    metadata.get("model", ""),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## By CAPTCHA Type",
            "",
            "| CAPTCHA | Episodes | Success | Rate | Avg model sec | Avg cost USD | Tool errors |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for captcha_type, item in sorted((report.get("by_captcha_type") or {}).items()):
        lines.append(
            f"| {_md(captcha_type)} | {item['episodes']} | {item['successes']} | "
            f"{item['success_rate']:.1%} | "
            f"{item['average_effective_model_window_seconds']} | "
            f"{item['average_cost_usd']:.8f} | {item['tool_errors']} |"
        )

    lines.extend(
        [
            "",
            "## Tool Reliability",
            "",
            "| Tool | Calls | Errors | Success rate |",
            "|---|---:|---:|---:|",
        ]
    )
    for tool, item in (summary.get("tool_metrics") or {}).items():
        lines.append(
            f"| {_md(tool)} | {item['calls']} | {item['errors']} | {item['success_rate']:.1%} |"
        )

    lines.extend(
        [
            "",
            "## Diagnostic Issues",
            "",
            "| Issue | Count | Affected episodes |",
            "|---|---:|---:|",
        ]
    )
    for issue in report.get("issues", []):
        lines.append(
            f"| {_md(issue['issue'])} | {issue['count']} | {issue['affected_episodes']} |"
        )

    lines.extend(
        [
            "",
            "## Failure Ownership Hints",
            "",
            "| Hint | Count |",
            "|---|---:|",
        ]
    )
    for hint, count in (summary.get("failure_owner_hints") or {}).items():
        lines.append(f"| {_md(hint)} | {count} |")

    failures = [episode for episode in report.get("episodes", []) if not episode.get("success")]
    lines.extend(
        [
            "",
            "## Failed Episodes",
            "",
            "| Sample | CAPTCHA | Reason | Owner hint | Failure phase |",
            "|---|---|---|---|---|",
        ]
    )
    for episode in failures:
        lines.append(
            "| "
            + " | ".join(
                _md(episode.get(key, ""))
                for key in (
                    "sample_id",
                    "captcha_type",
                    "reason",
                    "failure_owner_hint",
                    "failure_phase",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_report(report: Mapping[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "trajectory_analysis.json"
    markdown_path = output_dir / "trajectory_analysis.md"
    _write_json(json_path, report)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _discover_sources(inputs: Iterable[Path]) -> list[Path]:
    discovered: list[Path] = []
    for raw in inputs:
        path = raw.expanduser()
        if not path.exists():
            raise FileNotFoundError(f"analysis input not found: {path}")
        if path.is_file():
            if path.name not in SUMMARY_FILES:
                raise ValueError(f"unsupported analysis file: {path}")
            discovered.append(path)
            continue

        direct = [path / name for name in ("batch.json", "results.json") if (path / name).is_file()]
        if direct:
            discovered.extend(direct)
            continue
        summaries = sorted(path.rglob("batch.json")) + sorted(path.rglob("results.json"))
        if summaries:
            discovered.extend(summaries)
        else:
            discovered.extend(sorted(path.rglob("agent_trace.json")))
    return list(dict.fromkeys(discovered))


def _load_source(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = _read_json(path)
    if path.name == "batch.json":
        return _load_batch(path, payload), dict(payload.get("metadata", {}) or {})
    if path.name == "results.json":
        return _load_legacy_results(path, payload), _legacy_run_metadata(payload)
    return [_load_legacy_trace(path, payload)], {}


def _load_batch(path: Path, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    metadata = dict(payload.get("metadata", {}) or {})
    for item in payload.get("items", []) or []:
        episode_path = _resolve_episode_path(path, item)
        if episode_path is not None:
            episode = _analyze_hll_episode(_read_json(episode_path), str(episode_path.resolve()))
        else:
            episode = _episode_from_summary(item, str(path.resolve()))
        episode["run_metadata"] = metadata
        episodes.append(episode)
    return episodes


def _load_legacy_results(path: Path, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for item in payload.get("results", []) or []:
        artifact_dir = _resolve_artifact_dir(path, item)
        trace_path = artifact_dir / "agent_trace.json" if artifact_dir else None
        if trace_path and trace_path.is_file():
            episode = _load_legacy_trace(trace_path, _read_json(trace_path), context=item)
        else:
            episode = _episode_from_summary(item, str(path.resolve()))
        episode["run_metadata"] = _legacy_run_metadata(payload)
        episodes.append(episode)
    return episodes


def _analyze_hll_episode(payload: Mapping[str, Any], source: str) -> dict[str, Any]:
    metrics = payload.get("metrics", {}) or {}
    actions: list[str] = []
    tools: list[str] = []
    phases: Counter[str] = Counter()
    tool_errors: list[dict[str, Any]] = []
    repeated_actions = 0
    no_effect_actions = 0
    click_without_effect = 0
    deferred_submits = 0
    failed_submits = 0
    previous_signature = ""

    for step in payload.get("steps", []) or []:
        decision = step.get("decision", {}) or {}
        action_payload = decision.get("action", {}) or {}
        action = _action_name(action_payload.get("action", ""))
        args = action_payload.get("args", {}) or {}
        execution = step.get("execution", {}) or {}
        details = execution.get("details", {}) or {}
        evaluation = step.get("evaluation", {}) or {}
        workflow = step.get("workflow_before", {}) or {}
        phase = str(workflow.get("phase", "") or "")
        if phase:
            phases[phase] += 1
        actions.append(action)
        tool_name = str(details.get("tool_name", "") or "")
        if tool_name:
            tools.append(tool_name)

        signature = json.dumps([action, args], sort_keys=True, default=str)
        if signature == previous_signature:
            repeated_actions += 1
        previous_signature = signature

        read_only = bool(details.get("read_only", False))
        no_effect = bool(details.get("no_effect", False)) or (
            details.get("state_changed") is False
            and not read_only
            and _compact(action) not in {"check", "wait", "waitpageready"}
        )
        if no_effect:
            no_effect_actions += 1
        if _compact(action) == "clicktarget" and no_effect:
            click_without_effect += 1
        if details.get("deferred_submit"):
            deferred_submits += 1
        if "rejected" in str(evaluation.get("reason", "")).lower():
            failed_submits += 1
        error = details.get("error") or execution.get("error")
        if not execution.get("ok", True) or error:
            tool_errors.append(
                {
                    "step": step.get("step"),
                    "tool_name": tool_name,
                    "error": str(error or "execution_failed"),
                }
            )

    diagnostics = metrics.get("trajectory_diagnostics", {}) or {}
    if not actions:
        actions = [_action_name(value) for value in diagnostics.get("action_sequence", [])]
    if not tools:
        tools = [str(value) for value in diagnostics.get("tool_sequence", [])]
    if not tool_errors:
        tool_errors = list(diagnostics.get("tool_error_steps", []) or [])

    task = payload.get("task", {}) or {}
    accounting = metrics.get("model_accounting", {}) or {}
    timing = accounting.get("timing", {}) or {}
    accounting_usage = (accounting.get("usage", {}) or {}).get("total", {}) or {}
    accounting_cost = accounting.get("cost_usd", {}) or {}
    success = bool(payload.get("success", False))
    reason = str(payload.get("reason", "") or "")
    status = str(payload.get("status", "") or "")
    refreshes = _count_actions(actions, {"refresh", "refreshcaptcha"})
    episode = {
        "source": source,
        "format": "hll_episode",
        "sample_id": str(metrics.get("sample_id") or (task.get("config", {}) or {}).get("sample_id", "")),
        "captcha_type": str(task.get("captcha_type", "") or "unknown"),
        "model": str((metrics.get("run", {}) or {}).get("model", "")),
        "success": success,
        "status": status,
        "reason": reason,
        "steps": int(metrics.get("steps", len(actions)) or len(actions)),
        "elapsed_seconds": float(payload.get("elapsed_seconds", 0) or 0),
        "effective_model_window_seconds": float(
            timing.get("effective_model_window_seconds", 0) or 0
        ),
        "input_tokens": int(accounting_usage.get("input_tokens", 0) or 0),
        "output_tokens": int(accounting_usage.get("output_tokens", 0) or 0),
        "cost_usd": float(accounting_cost.get("total", 0) or 0),
        "total_tokens": int((metrics.get("model_usage", {}) or {}).get("total_tokens", 0) or 0),
        "action_sequence": actions,
        "tool_sequence": tools,
        "phase_counts": dict(phases),
        "failure_phase": _failure_phase(payload.get("steps", []), success),
        "tool_errors": tool_errors,
        "invalid_actions": int(metrics.get("invalid_action_steps", 0) or 0),
        "repeated_actions": repeated_actions,
        "read_only_repeats": int(diagnostics.get("read_only_repeats", 0) or 0),
        "no_effect_actions": no_effect_actions,
        "target_detection_without_click": _detections_without_click(actions),
        "click_without_effect": click_without_effect,
        "submit_attempts": _count_actions(actions, {"submit", "submitcaptcha"}),
        "failed_submits": failed_submits,
        "deferred_submits": deferred_submits,
        "refreshes": refreshes,
        "recovery_succeeded": bool(success and refreshes),
        "model_wait_ratio": float(diagnostics.get("model_wait_ratio", 0) or 0),
    }
    episode["failure_owner_hint"] = _failure_owner_hint(episode)
    return episode


def _load_legacy_trace(
    path: Path,
    payload: Mapping[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(context or {})
    companion_result = path.parent / "result.json"
    if companion_result.is_file():
        context = {**_read_json(companion_result), **context}
    companion_meta = path.parent / "sample_meta.json"
    if companion_meta.is_file():
        context = {**_read_json(companion_meta), **context}

    actions: list[str] = []
    tools: list[str] = []
    phases: Counter[str] = Counter()
    tool_errors: list[dict[str, Any]] = []
    repeated_actions = 0
    no_effect_actions = 0
    click_without_effect = 0
    failed_submits = 0
    previous_signature = ""
    refreshes = 0

    attempts = payload.get("attempts", []) or []
    for attempt in attempts:
        failed_submits += int(attempt.get("failed_verification_count", 0) or 0)
        for error in attempt.get("step_errors", []) or []:
            tool_errors.append({"step": "", "tool_name": "", "error": str(error)})
        for step in attempt.get("step_records", []) or []:
            action = _action_name(step.get("action", ""))
            actions.append(action)
            executed = step.get("executed_action", {}) or {}
            tool_name = str(executed.get("tool_name", "") or "")
            if tool_name:
                tools.append(tool_name)
            workflow = step.get("workflow", {}) or {}
            phase = str(workflow.get("phase", "") or "")
            if phase:
                phases[phase] += 1
            trajectory = step.get("trajectory", {}) or {}
            signature = str(trajectory.get("action_key", "") or action)
            repeated = bool(trajectory.get("repeated_action", False)) or signature == previous_signature
            previous_signature = signature
            repeated_actions += int(repeated)
            no_effect = bool(trajectory.get("no_effect", False))
            no_effect_actions += int(no_effect)
            click_without_effect += int(_compact(action) == "clicktarget" and no_effect)
            error = executed.get("error") or step.get("error")
            if error:
                tool_errors.append(
                    {"step": step.get("iter"), "tool_name": tool_name, "error": str(error)}
                )

    refreshes = _count_actions(actions, {"refresh", "refreshcaptcha"})
    success = bool(context.get("success", _legacy_success(attempts)))
    reason = str(context.get("error") or ("captcha_verified" if success else "unsolved"))
    episode = {
        "source": str(path.resolve()),
        "format": "legacy_agent_trace",
        "sample_id": str(context.get("sample_id", path.parent.name)),
        "captcha_type": str(context.get("captcha_type", path.parent.parent.name)),
        "model": str(context.get("model", "")),
        "success": success,
        "status": "success" if success else ("error" if context.get("error") else "stopped"),
        "reason": reason,
        "steps": len(actions),
        "elapsed_seconds": float(context.get("duration_sec", 0) or 0),
        "effective_model_window_seconds": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "total_tokens": _legacy_total_tokens(context),
        "action_sequence": actions,
        "tool_sequence": tools,
        "phase_counts": dict(phases),
        "failure_phase": "" if success else (next(reversed(phases), "") if phases else ""),
        "tool_errors": tool_errors,
        "invalid_actions": sum(1 for action in actions if _compact(action) == "invalid"),
        "repeated_actions": repeated_actions,
        "read_only_repeats": 0,
        "no_effect_actions": no_effect_actions,
        "target_detection_without_click": _detections_without_click(actions),
        "click_without_effect": click_without_effect,
        "submit_attempts": _count_actions(actions, {"submit", "submitcaptcha"}),
        "failed_submits": failed_submits,
        "deferred_submits": 0,
        "refreshes": refreshes,
        "recovery_succeeded": bool(success and refreshes),
        "model_wait_ratio": 0.0,
    }
    episode["failure_owner_hint"] = _failure_owner_hint(episode)
    return episode


def _episode_from_summary(item: Mapping[str, Any], source: str) -> dict[str, Any]:
    success = bool(item.get("success", False))
    accounting = item.get("model_accounting", {}) or {}
    timing = accounting.get("timing", {}) or {}
    accounting_usage = (accounting.get("usage", {}) or {}).get("total", {}) or {}
    accounting_cost = accounting.get("cost_usd", {}) or {}
    episode = {
        "source": source,
        "format": "summary_only",
        "sample_id": str(item.get("sample_id", "")),
        "captcha_type": str(item.get("captcha_type", "unknown")),
        "model": str(item.get("model", "")),
        "success": success,
        "status": str(item.get("status", "success" if success else "stopped")),
        "reason": str(item.get("reason") or item.get("error") or ("success" if success else "unsolved")),
        "steps": int(item.get("steps", item.get("attempts_used", 0)) or 0),
        "elapsed_seconds": float(item.get("elapsed_seconds", item.get("duration_sec", 0)) or 0),
        "effective_model_window_seconds": float(
            timing.get("effective_model_window_seconds", 0) or 0
        ),
        "input_tokens": int(accounting_usage.get("input_tokens", 0) or 0),
        "output_tokens": int(accounting_usage.get("output_tokens", 0) or 0),
        "cost_usd": float(accounting_cost.get("total", 0) or 0),
        "total_tokens": int(accounting_usage.get("total_tokens", 0) or 0)
        or _legacy_total_tokens(item),
        "action_sequence": [],
        "tool_sequence": [],
        "phase_counts": {},
        "failure_phase": "",
        "tool_errors": [],
        "invalid_actions": 0,
        "repeated_actions": 0,
        "read_only_repeats": 0,
        "no_effect_actions": 0,
        "target_detection_without_click": 0,
        "click_without_effect": 0,
        "submit_attempts": 0,
        "failed_submits": 0,
        "deferred_submits": 0,
        "refreshes": 0,
        "recovery_succeeded": False,
        "model_wait_ratio": 0.0,
    }
    episode["failure_owner_hint"] = _failure_owner_hint(episode)
    return episode


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(episodes)
    successes = sum(1 for item in episodes if item.get("success"))
    tool_error_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    owners: Counter[str] = Counter()
    failure_phases: Counter[str] = Counter()
    phase_steps: Counter[str] = Counter()
    for item in episodes:
        action_counts.update(item.get("action_sequence", []))
        tool_counts.update(item.get("tool_sequence", []))
        phase_steps.update(item.get("phase_counts", {}))
        if not item.get("success"):
            reasons[str(item.get("reason", "unknown"))] += 1
            owners[str(item.get("failure_owner_hint", "unknown"))] += 1
            if item.get("failure_phase"):
                failure_phases[str(item["failure_phase"])] += 1
        for error in item.get("tool_errors", []):
            tool_error_counts[str(error.get("tool_name") or "unknown")] += 1
    tool_metrics = {
        tool: {
            "calls": calls,
            "errors": tool_error_counts.get(tool, 0),
            "success_rate": round(
                max(0, calls - tool_error_counts.get(tool, 0)) / calls,
                4,
            ),
        }
        for tool, calls in tool_counts.most_common()
    }
    total_actions = sum(action_counts.values())
    return {
        "episodes": total,
        "successes": successes,
        "failures": total - successes,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "average_steps": _average(episodes, "steps"),
        "average_elapsed_seconds": _average(episodes, "elapsed_seconds"),
        "average_effective_model_window_seconds": _average(
            episodes, "effective_model_window_seconds"
        ),
        "average_model_wait_ratio": _average(episodes, "model_wait_ratio"),
        "total_tokens": sum(int(item.get("total_tokens", 0) or 0) for item in episodes),
        "input_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in episodes),
        "output_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in episodes),
        "total_cost_usd": round(
            sum(float(item.get("cost_usd", 0) or 0) for item in episodes), 8
        ),
        "average_cost_usd": round(
            sum(float(item.get("cost_usd", 0) or 0) for item in episodes) / total,
            8,
        )
        if total
        else 0.0,
        "tool_errors": sum(len(item.get("tool_errors", [])) for item in episodes),
        "invalid_actions": _sum(episodes, "invalid_actions"),
        "repeated_actions": _sum(episodes, "repeated_actions"),
        "action_retry_rate": round(
            _sum(episodes, "repeated_actions") / total_actions,
            4,
        )
        if total_actions
        else 0.0,
        "read_only_repeats": _sum(episodes, "read_only_repeats"),
        "no_effect_actions": _sum(episodes, "no_effect_actions"),
        "target_detection_without_click": _sum(episodes, "target_detection_without_click"),
        "click_without_effect": _sum(episodes, "click_without_effect"),
        "submit_attempts": _sum(episodes, "submit_attempts"),
        "failed_submits": _sum(episodes, "failed_submits"),
        "deferred_submits": _sum(episodes, "deferred_submits"),
        "refreshes": _sum(episodes, "refreshes"),
        "recovery_successes": sum(1 for item in episodes if item.get("recovery_succeeded")),
        "failure_reasons": dict(reasons.most_common()),
        "failure_owner_hints": dict(owners.most_common()),
        "failure_phases": dict(failure_phases.most_common()),
        "phase_step_counts": dict(phase_steps.most_common()),
        "tool_error_counts": dict(tool_error_counts.most_common()),
        "tool_metrics": tool_metrics,
        "action_counts": dict(action_counts.most_common()),
        "tool_counts": dict(tool_counts.most_common()),
    }


def _group_by_captcha_type(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for episode in episodes:
        grouped.setdefault(str(episode.get("captcha_type", "unknown")), []).append(episode)
    return {name: _aggregate(items) for name, items in grouped.items()}


def _issue_summary(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        ("tool_errors", "tool_errors", True),
        ("invalid_actions", "invalid_actions", False),
        ("repeated_actions", "repeated_actions", False),
        ("read_only_repeats", "read_only_repeats", False),
        ("no_effect_actions", "no_effect_actions", False),
        ("target_detection_without_click", "target_detection_without_click", False),
        ("click_without_effect", "click_without_effect", False),
        ("failed_submits", "failed_submits", False),
        ("deferred_submits", "deferred_submits", False),
    )
    issues: list[dict[str, Any]] = []
    for label, field, is_list in fields:
        values = [len(item.get(field, [])) if is_list else int(item.get(field, 0) or 0) for item in episodes]
        count = sum(values)
        if count:
            issues.append(
                {"issue": label, "count": count, "affected_episodes": sum(value > 0 for value in values)}
            )
    return sorted(issues, key=lambda item: (-item["count"], item["issue"]))


def _failure_owner_hint(episode: Mapping[str, Any]) -> str:
    if episode.get("success"):
        return "none"
    reason = str(episode.get("reason", "")).lower()
    status = str(episode.get("status", "")).lower()
    infrastructure_terms = (
        "adb",
        "browser",
        "cleanup_failed",
        "connection",
        "page_ready",
        "server_failed",
        "setup_failed",
    )
    if status == "error" or any(term in reason for term in infrastructure_terms):
        return "framework_or_environment"
    if int(episode.get("invalid_actions", 0) or 0):
        return "model_protocol"
    if episode.get("tool_errors"):
        return "tool_or_framework"
    if int(episode.get("deferred_submits", 0) or 0) > 1:
        return "workflow_or_layout"
    if int(episode.get("no_effect_actions", 0) or 0) > 1 or int(
        episode.get("repeated_actions", 0) or 0
    ) > 2:
        return "workflow_or_model"
    if "timeout" in reason or "budget_exhausted" in reason:
        return "workflow_or_model"
    if "rejected" in reason or "unsolved" in reason:
        return "model_or_task"
    return "unknown"


def _failure_phase(steps: Any, success: bool) -> str:
    if success or not isinstance(steps, list):
        return ""
    for step in reversed(steps):
        workflow = step.get("workflow_before", {}) or {}
        phase = str(workflow.get("phase", "") or "")
        if phase:
            return phase
    return ""


def _detections_without_click(actions: list[str]) -> int:
    pending = False
    missed = 0
    for action in actions:
        compact = _compact(action)
        if compact == "detectclicktargets":
            missed += int(pending)
            pending = True
        elif compact in {"clicktarget", "tap", "tappoint", "refresh", "refreshcaptcha"}:
            pending = False
        elif compact in {"submit", "submitcaptcha", "finish"} and pending:
            missed += 1
            pending = False
    return missed + int(pending)


def _resolve_episode_path(batch_path: Path, item: Mapping[str, Any]) -> Path | None:
    raw = str(item.get("episode_path", "") or "")
    candidates = []
    if raw:
        candidate = Path(raw).expanduser()
        candidates.extend([candidate, batch_path.parent / candidate])
    sample_id = str(item.get("sample_id", "") or "")
    if sample_id:
        candidates.append(batch_path.parent / "episodes" / sample_id / "episode.json")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _resolve_artifact_dir(results_path: Path, item: Mapping[str, Any]) -> Path | None:
    raw = str(item.get("artifact_dir", "") or "")
    candidates: list[Path] = []
    if raw:
        candidate = Path(raw).expanduser()
        candidates.extend([candidate, results_path.parent / candidate])
    model = str(item.get("model", "") or "")
    captcha = str(item.get("captcha_type", "") or "")
    sample = str(item.get("sample_id", "") or "")
    if model and captcha and sample:
        candidates.append(results_path.parent / model / captcha / sample)
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def _legacy_run_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": payload.get("run_id", ""),
        "models": list(payload.get("models", []) or []),
        "captcha_types": list(payload.get("captcha_types", []) or []),
        "samples_per_type": payload.get("samples_per_type", 0),
    }


def _legacy_success(attempts: Any) -> bool:
    for attempt in attempts or []:
        start = attempt.get("stats_start", {}) or {}
        end = attempt.get("stats_end", {}) or {}
        if int(end.get("successful_verifications", 0) or 0) > int(
            start.get("successful_verifications", 0) or 0
        ):
            return True
    return False


def _legacy_total_tokens(context: Mapping[str, Any]) -> int:
    runtime = context.get("runtime_metrics", {}) or {}
    tokens = runtime.get("tokens", {}) or {}
    if isinstance(tokens, Mapping):
        return int(sum(value for value in tokens.values() if isinstance(value, (int, float))))
    return 0


def _action_name(value: Any) -> str:
    raw = str(value or "").strip()
    return re.split(r"[<(]", raw, maxsplit=1)[0].strip() or "unknown"


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _count_actions(actions: Iterable[str], names: set[str]) -> int:
    normalized = {_compact(name) for name in names}
    return sum(1 for action in actions if _compact(action) in normalized)


def _sum(items: Iterable[Mapping[str, Any]], key: str) -> int:
    return sum(int(item.get(key, 0) or 0) for item in items)


def _average(items: list[Mapping[str, Any]], key: str) -> float:
    if not items:
        return 0.0
    return round(sum(float(item.get(key, 0) or 0) for item in items) / len(items), 4)


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze HLL batches and legacy agent traces")
    parser.add_argument("inputs", nargs="+", type=Path, help="run directories or trajectory JSON files")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = analyze_paths(args.inputs)
    if args.output_dir is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    json_path, markdown_path = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "episodes": report["summary"]["episodes"],
                "success_rate": report["summary"]["success_rate"],
                "json_path": str(json_path.resolve()),
                "markdown_path": str(markdown_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
