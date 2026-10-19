from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Optional

from hll.tools.base import ToolContext, ToolResult
from hll.metrics import intentional_sleep
from hll.tools.registry import ToolRegistry


# Only allowlisted public statistics may reach the agent.
_ALLOWED_STAT_KEYS = ("page_views", "total_verifications", "successful_verifications")


def _resolve_captcha_url(context: ToolContext) -> Optional[str]:
    url = (context.captcha_url or "").strip()
    if not url:
        url = (getattr(context.env.cfg, "captcha_url", "") or "").strip()
    return url or None


def _stats_from_safe_state(context: ToolContext) -> dict[str, int]:
    raw = context.safe_state or {}
    stats: dict[str, int] = {}
    for key in _ALLOWED_STAT_KEYS:
        if key not in raw:
            continue
        try:
            stats[key] = int(raw.get(key, 0) or 0)
        except Exception:
            stats[key] = 0
    return stats


def _read_safe_server_stats(context: ToolContext) -> tuple[dict[str, int], str]:
    stats = _stats_from_safe_state(context)
    if stats:
        return stats, ""

    url = _resolve_captcha_url(context)
    if not url:
        return {}, "captcha_url_missing"

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/stats", timeout=3) as response:
            raw = json.loads(response.read().decode("utf-8"))

        return {k: int(raw.get(k, 0) or 0) for k in _ALLOWED_STAT_KEYS if k in raw}, ""
    except Exception as exc:
        return {}, str(exc)


def execute_get_server_stats(action: str, context: ToolContext, match) -> ToolResult:
    stats, err = _read_safe_server_stats(context)
    if err == "captcha_url_missing":
        return ToolResult(handled=True, keep_running=True, exec_info={
            "action_type": "get_server_stats",
            "tool_name": "GetServerStats",
            "read_only": True,
            "label": "GetServerStats (no captcha_url)",
            "prompt_feedback": "Server stats are unavailable (captcha URL not configured).",
            "error": "captcha_url_missing",
        })

    if err:
        feedback = f"Could not read server stats: {err}"
    else:
        feedback = (
            "Current verification stats — "
            f"page_views={stats.get('page_views')}, "
            f"total_verifications={stats.get('total_verifications')}, "
            f"successful_verifications={stats.get('successful_verifications')}. "
            "If successful_verifications is 0 and total_verifications increased, your "
            "last submission was rejected; recover with RefreshCaptcha() before retrying."
        )
    exec_info = {
        "action_type": "get_server_stats",
        "tool_name": "GetServerStats",
        "read_only": True,
        "label": "GetServerStats",
        "server_stats": stats,
        "prompt_feedback": feedback,
    }
    if err:
        exec_info["error"] = err
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def execute_summarize_trajectory(action: str, context: ToolContext, match) -> ToolResult:
    summary = context.trajectory_summary or {}
    recent = summary.get("recent_actions") or []
    recent_lines = [
        f"  step {r.get('iter')}: {r.get('action')}"
        + ("  [no effect]" if r.get("no_effect") else "")
        + ("  [repeated]" if r.get("repeated_action") else "")
        for r in recent
    ]
    feedback = "\n".join([
        "Trajectory so far — "
        f"total_steps={summary.get('total_steps', 0)}, "
        f"no_effect_count={summary.get('no_effect_count', 0)}, "
        f"repeated_action_count={summary.get('repeated_action_count', 0)}.",
        "Recent actions:" if recent_lines else "Recent actions: (none)",
        *recent_lines,
        "Avoid repeating actions that had no effect; choose a different target or recover.",
    ])
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "summarize_trajectory",
        "tool_name": "SummarizeTrajectory",
        "read_only": True,
        "label": "SummarizeTrajectory",
        "prompt_feedback": feedback,
    })


def execute_get_observation(action: str, context: ToolContext, match) -> ToolResult:

    stats, _ = _read_safe_server_stats(context)
    summary = context.trajectory_summary or {}
    feedback = "\n".join([
        "Current observation —",
        f"  task: {context.instruction.strip()[:200]}" if context.instruction else "  task: (none)",
        f"  server_stats: {stats}",
        f"  steps_taken: {summary.get('total_steps', 0)}, "
        f"no_effect: {summary.get('no_effect_count', 0)}, "
        f"repeated: {summary.get('repeated_action_count', 0)}, "
        f"refreshes: {summary.get('refresh_count', 0)}",
        "The current screenshot is the attached image. Decide the next concrete action.",
    ])
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "get_observation",
        "tool_name": "GetObservation",
        "read_only": True,
        "label": "GetObservation",
        "server_stats": stats,
        "prompt_feedback": feedback,
    })


def execute_get_screenshot(action: str, context: ToolContext, match) -> ToolResult:
    out_dir = Path(getattr(context.env.cfg, "judgement_dir", "judgement")) / "tool_crops"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "current_screenshot.jpg"
    try:
        shutil.copy2(context.screenshot_file, out_path)
        err = None
    except Exception as exc:
        err = str(exc)
    exec_info = {
        "action_type": "get_screenshot",
        "tool_name": "GetScreenshot",
        "read_only": True,
        "label": "GetScreenshot",
        "screenshot_path": context.screenshot_file,
        "prompt_feedback": (
            "The current screenshot is already attached to the prompt. A copy is attached "
            "as the second image for explicit reference."
        ),
    }
    if err:
        exec_info["error"] = err
        exec_info["prompt_feedback"] = f"Could not copy the current screenshot: {err}"
    else:
        exec_info["prompt_image"] = str(out_path)
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def _screencap_signature(adb_path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [adb_path, "exec-out", "screencap", "-p"],
            capture_output=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return hashlib.blake2b(result.stdout, digest_size=12).hexdigest()


def execute_wait_page_ready(action: str, context: ToolContext, match) -> ToolResult:

    adb_path = context.env.cfg.adb_path
    interval = max(0.1, float(getattr(context.env.cfg, "post_action_poll_interval_sec", 0.2)))
    max_checks = 8
    start = time.perf_counter()
    prev = _screencap_signature(adb_path)
    stable = False
    intentional_wait = 0.0
    for _ in range(max_checks):
        intentional_wait += intentional_sleep(interval, "wait_page_ready_poll")
        cur = _screencap_signature(adb_path)
        if cur is not None and cur == prev:
            stable = True
            break
        prev = cur
    waited = round(time.perf_counter() - start, 2)
    feedback = (
        f"Waited {waited}s for the page to settle; it is now "
        + ("stable and ready." if stable else "still changing — it may need more time.")
    )
    return ToolResult(handled=True, keep_running=True, exec_info={
        "action_type": "wait_page_ready",
        "tool_name": "WaitPageReady",
        "read_only": True,
        "label": f"WaitPageReady ({waited}s, stable={stable})",
        "waited_sec": waited,
        "intentional_wait_seconds": round(intentional_wait, 4),
        "stable": stable,
        "prompt_feedback": feedback,
    })


def register_observation_tools(registry: ToolRegistry) -> None:
    registry.register(
        name="GetScreenshot",
        pattern=r"GetScreenshot\s*(?:\(\s*\))?",
        handler=execute_get_screenshot,
        read_only=True,
        description=(
            "GetScreenshot(): attach an explicit copy of the current screenshot. "
            "Read-only; usually unnecessary because the screenshot is already shown."
        ),
    )
    registry.register(
        name="GetObservation",
        pattern=r"GetObservation\s*(?:\(\s*\))?",
        handler=execute_get_observation,
        read_only=True,
        description=(
            "GetObservation(): get a structured snapshot — task, non-answer server stats, "
            "and trajectory summary. Read-only; the current screenshot is the attached image."
        ),
    )
    registry.register(
        name="GetServerStats",
        pattern=r"GetServerStats\s*(?:\(\s*\))?",
        handler=execute_get_server_stats,
        read_only=True,
        description=(
            "GetServerStats(): read non-answer verification stats (page_views, "
            "total/successful verifications). Read-only; use it to check if a "
            "submission was accepted or rejected."
        ),
    )
    registry.register(
        name="SummarizeTrajectory",
        pattern=r"SummarizeTrajectory\s*(?:\(\s*\))?",
        handler=execute_summarize_trajectory,
        read_only=True,
        description=(
            "SummarizeTrajectory(): get a summary of actions so far, including "
            "no-effect and repeated actions. Read-only; use it to avoid repeating "
            "ineffective actions."
        ),
    )
    registry.register(
        name="WaitPageReady",
        pattern=r"WaitPageReady\s*(?:\(\s*\))?",
        handler=execute_wait_page_ready,
        read_only=True,
        description=(
            "WaitPageReady(): wait until the page stops changing before acting. "
            "Use it after navigation/refresh instead of guessing with fixed waits."
        ),
    )
