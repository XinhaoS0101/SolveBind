from __future__ import annotations

import subprocess
from typing import Optional

from hll.tools.base import ToolContext, ToolResult
from hll.tools.registry import ToolRegistry


def _open_url(adb_path: str, url: str) -> bool:

    result = subprocess.run(
        [
            adb_path,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _resolve_captcha_url(context: ToolContext) -> Optional[str]:
    url = (context.captcha_url or "").strip()
    if not url:
        url = (getattr(context.env.cfg, "captcha_url", "") or "").strip()
    return url or None


def execute_refresh_captcha(action: str, context: ToolContext, match) -> ToolResult:
    """Reload through the same /refresh endpoint used by the page controls."""
    url = _resolve_captcha_url(context)
    if not url:
        return ToolResult(
            handled=True,
            keep_running=True,
            exec_info={
                "action_type": "refresh_captcha",
                "tool_name": "RefreshCaptcha",
                "label": "RefreshCaptcha (no captcha_url configured)",
                "error": "captcha_url_missing",
            },
        )

    refresh_url = url.rstrip("/") + "/refresh"
    ok = _open_url(context.env.cfg.adb_path, refresh_url)
    exec_info = {
        "action_type": "refresh_captcha",
        "tool_name": "RefreshCaptcha",
        "label": f"RefreshCaptcha -> open {refresh_url}",
        "refresh_url": refresh_url,
    }
    if not ok:
        exec_info["error"] = "am_start_failed"
    return ToolResult(handled=True, keep_running=True, exec_info=exec_info)


def register_recovery_tools(registry: ToolRegistry) -> None:
    registry.register(
        name="RefreshCaptcha",


        pattern=r"(?:RefreshCaptcha|DismissDialog|TryAgain)\s*(?:\(\s*\))?",
        handler=execute_refresh_captcha,
        description=(
            "RefreshCaptcha(): load a fresh challenge to recover after a failed "
            "submission or a blocking result dialog. Use this instead of guessing "
            "the pixel coordinates of the Refresh / OK / Try Again buttons."
        ),
    )
