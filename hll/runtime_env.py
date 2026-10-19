from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_for_cli(cwd: Path | None = None) -> tuple[Path, ...]:
    """Prefer nonempty shell values, then the working-directory .env, then the project .env."""

    start = (cwd or Path.cwd()).expanduser().resolve()
    project_root = Path(__file__).resolve().parents[1]
    candidates = [start / ".env"]
    project_env = project_root / ".env"
    if project_env != candidates[0]:
        candidates.append(project_env)

    loaded: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        _load_dotenv_file(path)
        loaded.append(path)
    return tuple(loaded)


def _load_dotenv_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_dotenv_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if not os.environ.get(key):
            os.environ[key] = value


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        return None
    return key, _parse_dotenv_value(value)


def _parse_dotenv_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""

    quote = value[0]
    if quote in {"'", '"'}:
        return _parse_quoted_value(value, quote)
    return value.split(" #", 1)[0].strip()


def _parse_quoted_value(value: str, quote: str) -> str:
    escaped = False
    chars: list[str] = []
    for char in value[1:]:
        if escaped:
            chars.append(_unescape_double_quoted(char) if quote == '"' else char)
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char == quote:
            break
        chars.append(char)
    if escaped:
        chars.append("\\")
    return "".join(chars)


def _unescape_double_quoted(char: str) -> str:
    return {"n": "\n", "r": "\r", "t": "\t"}.get(char, char)
