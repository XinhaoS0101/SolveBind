from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContext:
    env: Any
    screenshot_file: str
    width: int
    height: int
    perception_infos: list[dict[str, Any]]
    instruction: str
    action_history: list[str]
    task_profile: dict[str, Any] | None = None
    captcha_url: str = ""
    trajectory_summary: dict[str, Any] | None = None
    safe_state: dict[str, Any] | None = None
    click_target_snapshot: dict[str, Any] | None = None
    grid_snapshot: dict[str, Any] | None = None


@dataclass
class ToolResult:
    handled: bool
    keep_running: bool = True
    exec_info: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
