from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from hll.domain import EpisodeResult, EvaluationStatus, Task


class EpisodeHarness(Protocol):
    def run(self, task: Task, output_dir: Path) -> EpisodeResult: ...


@dataclass(frozen=True)
class EpisodeSpec:
    sample_id: str
    seed: int
    task: Task


class BatchRunner:
    """Isolate episode state and checkpoint after each task."""

    def __init__(
        self,
        harness_factory: Callable[[], EpisodeHarness],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.harness_factory = harness_factory
        self.metadata = dict(metadata or {})

    def run(self, specs: Iterable[EpisodeSpec], output_dir: Path) -> dict[str, Any]:
        planned = tuple(specs)
        output_dir.mkdir(parents=True, exist_ok=True)
        episodes_dir = output_dir / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        summary: dict[str, Any] = {
            "batch_schema_version": "1.6",
            "output_dir": str(output_dir.resolve()),
            "planned": len(planned),
            "completed": 0,
            "successes": 0,
            "failures": 0,
            "errors": 0,
            "metadata": dict(self.metadata),
            "items": [],
        }
        _update_model_summaries(summary, planned)
        _write_json(output_dir / "run_manifest.json", dict(self.metadata))
        _write_json(output_dir / "batch.json", summary)

        for spec in planned:
            random.seed(spec.seed)
            episode_dir = episodes_dir / spec.sample_id
            try:
                result = self.harness_factory().run(spec.task, episode_dir)
            except Exception as exc:
                result = EpisodeResult(
                    task=spec.task,
                    success=False,
                    status=EvaluationStatus.ERROR,
                    reason=f"batch_episode_setup_failed: {type(exc).__name__}: {exc}",
                    steps=(),
                    elapsed_seconds=0.0,
                    output_dir=str(episode_dir.resolve()),
                    metrics={"sample_id": spec.sample_id, "seed": spec.seed},
                )
                result.write_json(episode_dir / "episode.json")

            item = {
                "sample_id": spec.sample_id,
                "seed": spec.seed,
                "captcha_type": spec.task.captcha_type,
                "success": result.success,
                "status": result.status.value,
                "reason": result.reason,
                "steps": len(result.steps),
                "elapsed_seconds": result.elapsed_seconds,
                "model_accounting": dict(
                    result.metrics.get("model_accounting", {}) or {}
                ),
                "episode_path": str((episode_dir / "episode.json").resolve()),
            }
            summary["items"].append(item)
            summary["completed"] += 1
            if result.success:
                summary["successes"] += 1
            else:
                summary["failures"] += 1
            if result.status is EvaluationStatus.ERROR:
                summary["errors"] += 1
            _update_model_summaries(summary, planned)
            summary["elapsed_seconds"] = round(time.monotonic() - started, 4)
            _write_json(output_dir / "batch.json", summary)

        summary["elapsed_seconds"] = round(time.monotonic() - started, 4)
        _write_json(output_dir / "batch.json", summary)
        return summary


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _update_model_summaries(
    summary: dict[str, Any],
    planned: tuple[EpisodeSpec, ...],
) -> None:
    items = list(summary.get("items", []))
    summary["model_accounting"] = _summarize_accounting(items, len(planned))

    planned_by_type: dict[str, int] = {}
    for spec in planned:
        captcha_type = spec.task.captcha_type
        planned_by_type[captcha_type] = planned_by_type.get(captcha_type, 0) + 1

    completed_by_type: dict[str, list[Mapping[str, Any]]] = {
        captcha_type: [] for captcha_type in planned_by_type
    }
    for item in items:
        completed_by_type.setdefault(str(item.get("captcha_type", "unknown")), []).append(item)

    by_type: dict[str, Any] = {}
    for captcha_type, planned_count in planned_by_type.items():
        completed = completed_by_type.get(captcha_type, [])
        type_summary = _summarize_accounting(completed, planned_count)
        type_summary.update(
            {
                "successes": sum(bool(item.get("success")) for item in completed),
                "failures": sum(not bool(item.get("success")) for item in completed),
            }
        )
        by_type[captcha_type] = type_summary
    summary["captcha_type_summaries"] = by_type


def _summarize_accounting(
    items: list[Mapping[str, Any]],
    planned: int,
) -> dict[str, Any]:
    completed = len(items)
    denominator = completed or 1
    effective_seconds = sum(_accounting_value(item, "timing", "effective_model_window_seconds") for item in items)
    request_seconds = sum(_accounting_value(item, "timing", "model_request_seconds") for item in items)
    wait_seconds = sum(_accounting_value(item, "timing", "intentional_wait_seconds") for item in items)
    total_input = sum(_accounting_value(item, "usage", "total", "input_tokens") for item in items)
    total_output = sum(_accounting_value(item, "usage", "total", "output_tokens") for item in items)
    total_tokens = sum(_accounting_value(item, "usage", "total", "total_tokens") for item in items)
    total_cost = sum(_accounting_value(item, "cost_usd", "total") for item in items)

    by_category: dict[str, Any] = {}
    for category in ("agent", "ocr", "auxiliary_tools"):
        category_input = sum(
            _accounting_value(item, "usage", category, "input_tokens") for item in items
        )
        category_output = sum(
            _accounting_value(item, "usage", category, "output_tokens") for item in items
        )
        category_total = sum(
            _accounting_value(item, "usage", category, "total_tokens") for item in items
        )
        category_cost = sum(
            _accounting_value(item, "cost_usd", category) for item in items
        )
        by_category[category] = {
            "input_tokens": int(category_input),
            "output_tokens": int(category_output),
            "total_tokens": int(category_total),
            "cost_usd": _usd(category_cost),
            "average_cost_usd": _usd(category_cost / denominator) if completed else 0.0,
        }

    return {
        "planned": planned,
        "completed": completed,
        "complete": completed >= planned,
        "total_effective_model_window_seconds": _seconds(effective_seconds),
        "average_effective_model_window_seconds": (
            _seconds(effective_seconds / denominator) if completed else 0.0
        ),
        "total_model_request_seconds": _seconds(request_seconds),
        "average_model_request_seconds": (
            _seconds(request_seconds / denominator) if completed else 0.0
        ),
        "total_intentional_wait_seconds": _seconds(wait_seconds),
        "input_tokens": int(total_input),
        "output_tokens": int(total_output),
        "total_tokens": int(total_tokens),
        "average_input_tokens": round(total_input / denominator, 2) if completed else 0.0,
        "average_output_tokens": round(total_output / denominator, 2) if completed else 0.0,
        "average_total_tokens": round(total_tokens / denominator, 2) if completed else 0.0,
        "total_cost_usd": _usd(total_cost),
        "average_cost_usd": _usd(total_cost / denominator) if completed else 0.0,
        "by_category": by_category,
    }


def _accounting_value(item: Mapping[str, Any], *path: str) -> float:
    value: Any = item.get("model_accounting", {}) or {}
    for key in path:
        if not isinstance(value, Mapping):
            return 0.0
        value = value.get(key, 0)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _seconds(value: float) -> float:
    return round(float(value), 4)


def _usd(value: float) -> float:
    return round(float(value), 8)
