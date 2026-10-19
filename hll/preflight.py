from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from hll.captcha.task_config import required_asset_directories


def run_preflight(
    captcha_types: Iterable[str],
    *,
    adb_path: str,
    device_serial: str,
    api_key: str,
    ocr_engine: str,
    asset_root: Path,
    expected_dynamic_types: int | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    _record(
        checks,
        errors,
        "api_key",
        bool(api_key),
        "OPENAI_API_KEY is not set; pass --api-key, export it, or put it in .env",
    )
    _record(
        checks,
        errors,
        "pillow",
        importlib.util.find_spec("PIL") is not None,
        "Pillow is not installed; run: pip install -e .",
    )
    if ocr_engine == "modelscope":
        _record(
            checks,
            errors,
            "modelscope_ocr",
            importlib.util.find_spec("modelscope") is not None,
            "ModelScope OCR is not installed; run: pip install -e '.[modelscope-ocr]'",
        )

    if expected_dynamic_types is not None:
        actual_count = len(tuple(captcha_types))
        _record(
            checks,
            errors,
            "dynamic_type_count",
            actual_count == int(expected_dynamic_types),
            f"expected {expected_dynamic_types} dynamic task types, got {actual_count}",
            expected=int(expected_dynamic_types),
            actual=actual_count,
        )

    for captcha_type, directory in required_asset_directories(
        captcha_types,
        asset_root=asset_root,
    ).items():
        available = directory.is_dir() and any(path.is_file() for path in directory.rglob("*"))
        _record(
            checks,
            errors,
            f"assets:{captcha_type}",
            available,
            f"asset directory is missing or empty: {directory}",
            path=str(directory.resolve()),
        )

    resolved_adb = _resolve_executable(adb_path)
    _record(
        checks,
        errors,
        "adb_executable",
        resolved_adb is not None,
        f"ADB executable was not found: {adb_path}",
        path=resolved_adb or adb_path,
    )
    if resolved_adb:
        device_check = _check_devices(resolved_adb, device_serial)
        checks.append(device_check)
        if not device_check["ok"]:
            errors.append(str(device_check["message"]))

    return {"ok": not errors, "checks": checks, "errors": errors}


def _record(
    checks: list[dict[str, Any]],
    errors: list[str],
    name: str,
    ok: bool,
    error: str,
    **metadata: Any,
) -> None:
    checks.append({"name": name, "ok": ok, **metadata})
    if not ok:
        errors.append(error)


def _resolve_executable(value: str) -> str | None:
    path = Path(value).expanduser()
    if path.parent != Path("."):
        return str(path.resolve()) if path.is_file() else None
    return shutil.which(value)


def _check_devices(adb: str, requested_serial: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [adb, "devices"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": "adb_device", "ok": False, "message": str(exc)}
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "adb devices failed"
        return {"name": "adb_device", "ok": False, "message": message}

    devices: dict[str, str] = {}
    for line in completed.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            devices[parts[0]] = parts[1]
    if requested_serial:
        state = devices.get(requested_serial, "missing")
        ok = state == "device"
        return {
            "name": "adb_device",
            "ok": ok,
            "serial": requested_serial,
            "state": state,
            "message": "selected Android device is ready" if ok else f"device {requested_serial} is {state}",
        }

    ready = [serial for serial, state in devices.items() if state == "device"]
    if len(ready) == 1:
        return {
            "name": "adb_device",
            "ok": True,
            "serial": ready[0],
            "state": "device",
            "message": "Android device is ready",
        }
    if not ready:
        return {
            "name": "adb_device",
            "ok": False,
            "message": "no authorized Android device is connected",
            "devices": devices,
        }
    return {
        "name": "adb_device",
        "ok": False,
        "message": "multiple Android devices are connected; pass --device-serial",
        "devices": devices,
    }
