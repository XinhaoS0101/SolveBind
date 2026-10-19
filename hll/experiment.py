from __future__ import annotations

import hashlib
import json
from importlib import metadata
from typing import Any

from hll.agent import SYSTEM_PROMPT
from hll.tools import build_default_registry


WORKFLOW_VERSION = "0.6-dev"
TOOL_SCHEMA_VERSION = "1.1"


def build_reproducibility_manifest() -> dict[str, Any]:


    schema_entries = build_default_registry().schema_entries()
    return {
        "framework_version": _package_version(),
        "workflow": {
            "version": WORKFLOW_VERSION,
            "prompt_sha256": _sha256_text(SYSTEM_PROMPT),
        },
        "tool_schema": {
            "version": TOOL_SCHEMA_VERSION,
            "sha256": _sha256_json(schema_entries),
            "action_count": len(schema_entries),
        },
    }


def _package_version() -> str:
    try:
        return metadata.version("solvebind")
    except metadata.PackageNotFoundError:
        return "0.1.0"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(canonical)
