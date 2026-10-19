from __future__ import annotations

import struct
import subprocess
import time
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from hll.domain import (
    ActionKind,
    Decision,
    ExecutionResult,
    Observation,
    Task,
)
from hll.metrics import intentional_sleep


SAFE_STAT_KEYS = ("page_views", "total_verifications", "successful_verifications")
DEFAULT_BROWSER_PACKAGES = (
    "com.android.chrome",
    "com.google.android.apps.chrome",
    "org.chromium.chrome",
    "com.android.browser",
)


class AdbError(RuntimeError):
    pass


class AdbCaptchaEnvironment:


    def __init__(
        self,
        *,
        adb_path: str = "adb",
        device_serial: str = "",
        host: str = "127.0.0.1",
        port: int = 8000,
        page_ready_timeout: float = 20.0,
        page_load_retries: int = 2,
        page_retry_interval: float = 1.0,
        force_stop_browser_on_open: bool = True,
        foreground_url_check: bool = True,
        browser_packages: tuple[str, ...] = DEFAULT_BROWSER_PACKAGES,
        settle_seconds: float = 1.0,
    ) -> None:
        self.adb_path = adb_path
        self.device_serial = device_serial
        self.host = host
        self.port = port
        self.page_ready_timeout = page_ready_timeout
        self.page_load_retries = max(0, int(page_load_retries))
        self.page_retry_interval = max(0.0, float(page_retry_interval))
        self.force_stop_browser_on_open = bool(force_stop_browser_on_open)
        self.foreground_url_check = bool(foreground_url_check)
        self.browser_packages = tuple(browser_packages)
        self.settle_seconds = settle_seconds
        self.task: Task | None = None
        self.output_dir: Path | None = None
        self.server: Any = None
        self.session: Any = None
        self.last_size = (0, 0)
        self.last_screenshot_path = ""
        self.captcha_url = ""

    def reset(self, task: Task, output_dir: Path) -> Observation:
        self.close()
        self.task = task
        self.output_dir = output_dir


        try:
            from web.captcha_page import start_captcha_server_in_thread
        except ImportError as exc:
            raise RuntimeError(
                "CAPTCHA server dependencies are missing; install requirements-server.txt"
            ) from exc

        self.server, _, self.session = start_captcha_server_in_thread(
            captcha_type=task.captcha_type,
            captcha_config=dict(task.config),
            host=self.host,
            port=self.port,
            debug=False,
        )
        self._adb("reverse", f"tcp:{self.port}", f"tcp:{self.port}")
        url = f"http://127.0.0.1:{self.port}/"
        self.captcha_url = url.rstrip("/")
        self._open_browser_until_ready(url)
        return self.observe(step=0)

    def observe(self, step: int) -> Observation:
        if self.task is None or self.output_dir is None:
            raise RuntimeError("environment has not been reset")
        image = self._adb_bytes("exec-out", "screencap", "-p")
        width, height = _png_size(image)
        self.last_size = (width, height)
        screenshot = self.output_dir / f"screen_{step:03d}.png"
        screenshot.write_bytes(image)
        self.last_screenshot_path = str(screenshot.resolve())
        return Observation(
            step=step,
            screenshot_path=str(screenshot.resolve()),
            width=width,
            height=height,
            instruction=self.task.instruction,
            safe_state=self.get_stats(),
        )

    def execute(self, decision: Decision) -> ExecutionResult:
        started = time.monotonic()
        action = decision.action
        details: dict[str, Any] = {
            "action": action.kind.value,
            "args": dict(action.args),
        }
        try:
            if action.kind is ActionKind.TAP:
                x, y = self._point(action.args["x"], action.args["y"])
                self._adb("shell", "input", "tap", str(x), str(y))
                details["mapped_point"] = [x, y]
                details["interaction_progress"] = True
                if bool(action.args.get("complete", False)):
                    details["ready_to_submit"] = True
            elif action.kind is ActionKind.TYPE:
                self._type_text(str(action.args["text"]))
                details["ready_to_submit"] = True
            elif action.kind is ActionKind.INPUT_TEXT:
                text = str(action.args["text"])
                if "x" in action.args and "y" in action.args:
                    point = self._point(action.args["x"], action.args["y"])
                    source = "provided_point"
                else:
                    point = self._find_editable_text_field()
                    source = "accessibility"
                if point is None:
                    details["recoverable"] = True
                    raise RuntimeError("no editable text field found")
                self._adb("shell", "input", "tap", str(point[0]), str(point[1]))
                intentional_sleep(0.2, "input_focus_settle")
                if bool(action.args.get("clear_existing", True)):
                    self._clear_focused_text()
                self._type_text(text)
                keyboard_dismissed = self._dismiss_keyboard_if_shown()
                details.update(
                    {
                        "mapped_point": list(point),
                        "input_locator": source,
                        "keyboard_dismissed": keyboard_dismissed,
                        "ready_to_submit": True,
                    }
                )
            elif action.kind is ActionKind.DRAG:
                x1, y1 = self._point(action.args["x1"], action.args["y1"])
                x2, y2 = self._point(action.args["x2"], action.args["y2"])
                duration = max(100, min(5000, int(action.args.get("duration_ms", 800))))
                self._adb(
                    "shell",
                    "input",
                    "swipe",
                    str(x1),
                    str(y1),
                    str(x2),
                    str(y2),
                    str(duration),
                )
                details["mapped_path"] = [x1, y1, x2, y2]
                details["duration_ms"] = duration
                details["interaction_progress"] = True
                if bool(action.args.get("complete", False)):
                    details["ready_to_submit"] = True
            elif action.kind is ActionKind.KEY:
                key = str(action.args["key"]).upper()
                keycode = {"ENTER": "KEYCODE_ENTER", "BACK": "KEYCODE_BACK"}.get(key)
                if keycode is None:
                    raise ValueError("key must be ENTER or BACK")
                self._adb("shell", "input", "keyevent", keycode)
            elif action.kind is ActionKind.WAIT:
                seconds = max(0.0, min(10.0, float(action.args.get("seconds", 1.0))))
                intentional_sleep(seconds, "agent_wait_action")
                details["seconds"] = seconds
                details["intentional_wait_seconds"] = seconds
            elif action.kind is ActionKind.SUBMIT:
                point, source = self._find_primary_submit_control()
                if point is None:
                    details["recoverable"] = True
                    raise RuntimeError("no primary submit/check control found")
                self._adb("shell", "input", "tap", str(point[0]), str(point[1]))
                details.update(
                    {
                        "mapped_point": list(point),
                        "control_locator": source,
                        "verification_action": True,
                    }
                )
            elif action.kind is ActionKind.CHECK:
                seconds = max(0.0, min(5.0, float(action.args.get("seconds", 0.5))))
                intentional_sleep(seconds, "verification_check_wait")
                details["seconds"] = seconds
                details["intentional_wait_seconds"] = seconds
                details["verification_check"] = True
            elif action.kind is ActionKind.REFRESH:
                if not self.captcha_url:
                    raise RuntimeError("captcha URL is unavailable")
                before_views = self.get_stats()["page_views"]
                self._adb(
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    f"{self.captcha_url}/refresh",
                )
                self._wait_for_page_view_after(before_views)
                if self.foreground_url_check:
                    foreground = self._check_browser_foreground_for_url(self.captcha_url)
                    if not foreground.get("ready"):
                        details["foreground"] = foreground
                        raise RuntimeError(
                            "refreshed CAPTCHA page is not foreground: "
                            f"{foreground.get('reason', 'unknown')}"
                        )
                details["state_changed"] = True
                details["refresh_url"] = f"{self.captcha_url}/refresh"
            elif action.kind is ActionKind.FINISH:
                pass

            if action.kind not in {
                ActionKind.WAIT,
                ActionKind.CHECK,
                ActionKind.REFRESH,
                ActionKind.FINISH,
            }:
                intentional_sleep(self.settle_seconds, "post_action_settle")
            return ExecutionResult(
                ok=True,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
            )
        except Exception as exc:
            return ExecutionResult(
                ok=False,
                elapsed_seconds=round(time.monotonic() - started, 4),
                details=details,
                error=f"{type(exc).__name__}: {exc}",
            )

    def get_stats(self) -> dict[str, int]:
        raw: Mapping[str, Any] = self.session.get_stats() if self.session else {}
        return {key: int(raw.get(key, 0) or 0) for key in SAFE_STAT_KEYS}

    def get_verification_feedback(self) -> dict[str, Any]:
        if self.session is None or not hasattr(self.session, "get_verification_feedback"):
            return {}
        raw = self.session.get_verification_feedback()
        return dict(raw) if isinstance(raw, Mapping) else {}

    def close(self) -> None:
        server, self.server = self.server, None
        self.session = None
        if server is not None:
            server.shutdown()
            server.server_close()

    def _open_browser_until_ready(self, url: str) -> None:
        last_error = ""
        last_foreground: Mapping[str, Any] = {}

        if self.force_stop_browser_on_open:
            self._force_stop_browsers()

        for attempt in range(self.page_load_retries + 1):
            baseline_views = self.get_stats()["page_views"]
            self._open_browser_to_url(url)
            try:
                self._wait_for_page_view_after(baseline_views)
            except TimeoutError as exc:
                last_error = str(exc)
            else:
                if not self.foreground_url_check:
                    return
                foreground = self._check_browser_foreground_for_url(url)
                if foreground.get("ready"):
                    return
                last_foreground = foreground
                last_error = str(foreground.get("reason", "foreground_check_failed"))

            if attempt < self.page_load_retries:
                if self.force_stop_browser_on_open:
                    self._force_stop_browsers()
                if self.page_retry_interval > 0:
                    intentional_sleep(self.page_retry_interval, "page_load_retry")

        detail = f"; foreground={dict(last_foreground)}" if last_foreground else ""
        raise TimeoutError(
            f"browser did not open CAPTCHA page within {self.page_ready_timeout:.1f}s "
            f"after {self.page_load_retries + 1} attempt(s): {last_error}{detail}"
        )

    def _open_browser_to_url(self, url: str) -> None:
        self._adb(
            "shell",
            "am",
            "start",
            "-W",
            "--activity-clear-top",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
        )

    def _force_stop_browsers(self) -> None:
        for package in self.browser_packages:
            try:
                self._adb("shell", "am", "force-stop", package)
            except AdbError:
                continue

    def _check_browser_foreground_for_url(self, expected_url: str) -> dict[str, Any]:
        texts = self._window_texts()
        lower_texts = [text.lower() for text in texts]
        joined = " ".join(lower_texts)
        markers = _expected_url_markers(expected_url)

        fatal_bad_phrases = (
            "google.com/search",
            "google.com.hk/search",
            "search?q=",
            "this site can't be reached",
            "this site can’t be reached",
            "err_connection",
            "err_address",
            "err_name",
        )
        for phrase in fatal_bad_phrases:
            if phrase in joined:
                return {
                    "ready": False,
                    "reason": "browser_not_on_expected_url",
                    "matched_bad_phrase": phrase,
                    "expected_markers": markers,
                    "texts": texts[:30],
                }

        for marker in markers:
            if any(marker in text for text in lower_texts):
                return {
                    "ready": True,
                    "reason": "expected_url_visible",
                    "matched_marker": marker,
                    "texts": texts[:30],
                }

        if "search or type url" in joined:
            return {
                "ready": False,
                "reason": "browser_not_on_expected_url",
                "matched_bad_phrase": "search or type url",
                "expected_markers": markers,
                "texts": texts[:30],
            }

        return {
            "ready": False,
            "reason": "expected_url_not_visible",
            "expected_markers": markers,
            "texts": texts[:30],
        }

    def _window_texts(self) -> list[str]:
        try:
            nodes = self._ui_nodes()
        except Exception:
            return []
        texts: list[str] = []
        for node in nodes:
            for attr in ("text", "content-desc"):
                value = str(node.get(attr, "") or "").strip()
                if value:
                    texts.append(value)
        return texts

    def _wait_page_ready(self) -> None:
        deadline = time.monotonic() + self.page_ready_timeout
        while time.monotonic() < deadline:
            if self.get_stats()["page_views"] > 0:
                return
            intentional_sleep(0.2, "page_ready_poll")
        raise TimeoutError(
            f"browser did not open CAPTCHA page within {self.page_ready_timeout:.1f}s"
        )

    def _wait_for_page_view_after(self, previous: int) -> None:
        deadline = time.monotonic() + self.page_ready_timeout
        while time.monotonic() < deadline:
            if self.get_stats()["page_views"] > previous:
                return
            intentional_sleep(0.2, "page_view_poll")
        raise TimeoutError("refreshed CAPTCHA page did not become ready")

    def _type_text(self, text: str) -> None:
        if "\n" in text or "\r" in text:
            raise ValueError("input text cannot contain newlines")
        self._adb("shell", "input", "text", _encode_adb_text(text))

    def _clear_focused_text(self) -> None:
        keys = ["KEYCODE_MOVE_END"] + ["KEYCODE_DEL"] * 32
        self._adb("shell", "input", "keyevent", *keys)

    def _dismiss_keyboard_if_shown(self) -> bool:
        output = self._adb("shell", "dumpsys", "input_method")
        shown = any(
            marker in output
            for marker in ("mInputShown=true", "mInputViewShown=true", "isInputViewShown=true")
        )
        if shown:
            self._adb("shell", "input", "keyevent", "KEYCODE_BACK")
        return shown

    def _find_editable_text_field(self) -> tuple[int, int] | None:
        nodes = self._ui_nodes()
        candidates: list[tuple[int, tuple[int, int]]] = []
        for node in nodes:
            class_name = node.get("class", "").lower()
            resource_id = node.get("resource-id", "").lower()
            editable = node.get("editable", "false") == "true"
            if not (editable or "edittext" in class_name or "input" in resource_id):
                continue
            point = _bounds_center(node.get("bounds", ""))
            if point is None:
                continue
            score = 10 + (10 if editable else 0) + (5 if "edittext" in class_name else 0)
            candidates.append((score, point))
        return max(candidates, default=(0, None), key=lambda item: item[0])[1]

    def _find_primary_submit_control(self) -> tuple[tuple[int, int] | None, str]:
        labels = ("verify", "submit", "check", "confirm", "continue", "done")
        candidates: list[tuple[int, tuple[int, int]]] = []
        for node in self._ui_nodes():
            text = " ".join(
                (node.get("text", ""), node.get("content-desc", ""), node.get("resource-id", ""))
            ).lower()
            matches = [label for label in labels if label in text]
            if not matches:
                continue
            point = _bounds_center(node.get("bounds", ""))
            if point is None:
                continue
            score = 50
            if text.strip() in labels:
                score += 50
            if node.get("clickable", "false") == "true":
                score += 20
            if "button" in node.get("class", "").lower():
                score += 10
            candidates.append((score, point))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1], "accessibility"
        point = self._find_primary_button_visual()
        return point, "visual_primary_color" if point is not None else "not_found"

    def _ui_nodes(self) -> list[Mapping[str, str]]:
        remote = "/sdcard/hll_window.xml"
        self._adb("shell", "uiautomator", "dump", remote)
        raw = self._adb("shell", "cat", remote)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return []
        return [node.attrib for node in root.iter("node")]

    def _find_primary_button_visual(self) -> tuple[int, int] | None:
        if not self.last_screenshot_path:
            return None
        try:
            from PIL import Image
        except ImportError:
            return None
        with Image.open(self.last_screenshot_path) as source:
            image = source.convert("RGB")
            scale = 4
            small = image.resize(
                (max(1, image.width // scale), max(1, image.height // scale))
            )
        width, height = small.size
        pixels = small.load()
        mask = {
            (x, y)
            for y in range(height)
            for x in range(width)
            if _is_primary_button_color(pixels[x, y])
        }
        best: tuple[float, tuple[int, int]] | None = None
        while mask:
            seed = mask.pop()
            stack = [seed]
            xs = [seed[0]]
            ys = [seed[1]]
            while stack:
                x, y = stack.pop()
                for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if neighbor in mask:
                        mask.remove(neighbor)
                        stack.append(neighbor)
                        xs.append(neighbor[0])
                        ys.append(neighbor[1])
            box_width = (max(xs) - min(xs) + 1) * scale
            box_height = (max(ys) - min(ys) + 1) * scale
            if box_width < 80 or not 24 <= box_height <= 180:
                continue
            center = (
                int((min(xs) + max(xs) + 1) * scale / 2),
                int((min(ys) + max(ys) + 1) * scale / 2),
            )
            score = box_width + center[1] / max(1, image.height)
            if best is None or score > best[0]:
                best = (score, center)
        return best[1] if best else None

    def _point(self, raw_x: Any, raw_y: Any) -> tuple[int, int]:
        width, height = self.last_size
        if width <= 0 or height <= 0:
            raise RuntimeError("screen size is unavailable")
        x = max(0, min(width - 1, int(raw_x)))
        y = max(0, min(height - 1, int(raw_y)))
        return x, y

    def _command(self, *args: str) -> list[str]:
        command = [self.adb_path]
        if self.device_serial:
            command.extend(["-s", self.device_serial])
        command.extend(args)
        return command

    def _adb(self, *args: str) -> str:
        try:
            completed = subprocess.run(
                self._command(*args),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(str(exc)) from exc
        if completed.returncode != 0:
            raise AdbError(completed.stderr.strip() or completed.stdout.strip())
        return completed.stdout

    def _adb_bytes(self, *args: str) -> bytes:
        try:
            completed = subprocess.run(
                self._command(*args),
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(str(exc)) from exc
        if completed.returncode != 0:
            raise AdbError(completed.stderr.decode("utf-8", errors="replace").strip())
        return completed.stdout


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("ADB screencap did not return a PNG image")
    return struct.unpack(">II", data[16:24])


def _encode_adb_text(value: str) -> str:
    return value.replace("%", "\\%").replace(" ", "%s")


def _expected_url_markers(url: str) -> list[str]:
    parsed = urlparse(url)
    markers = []
    if parsed.netloc:
        markers.append(parsed.netloc)
    if parsed.hostname:
        markers.append(parsed.hostname)
    display_url = url.replace("http://", "").replace("https://", "").rstrip("/")
    if display_url:
        markers.append(display_url)
    return sorted({marker.lower() for marker in markers if marker}, key=len, reverse=True)


_BOUNDS_RE = re.compile(r"\[(?P<x1>\d+),(?P<y1>\d+)\]\[(?P<x2>\d+),(?P<y2>\d+)\]")


def _bounds_center(value: str) -> tuple[int, int] | None:
    match = _BOUNDS_RE.fullmatch(value)
    if match is None:
        return None
    x1, y1, x2, y2 = (int(match.group(name)) for name in ("x1", "y1", "x2", "y2"))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1 + x2) // 2, (y1 + y2) // 2


def _is_primary_button_color(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return 45 <= red <= 120 and 35 <= green <= 110 and 165 <= blue <= 255
