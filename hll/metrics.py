from __future__ import annotations

import math
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Mapping


TOKEN_UNIT = 1_000_000
MODEL_CATEGORIES = ("agent", "ocr", "auxiliary_tools")


@dataclass(frozen=True)
class PricingConfig:


    agent_input_per_1m_tokens_usd: float = 0.0
    agent_output_per_1m_tokens_usd: float = 0.0

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> PricingConfig:
        values = os.environ if environ is None else environ
        return cls(
            agent_input_per_1m_tokens_usd=_price(
                values, "AGENT_INPUT_COST_PER_1M_TOKENS"
            ),
            agent_output_per_1m_tokens_usd=_price(
                values, "AGENT_OUTPUT_COST_PER_1M_TOKENS"
            ),
        )

    def rates_for(self, category: str) -> tuple[float, float]:


        if category not in MODEL_CATEGORIES:
            raise ValueError(f"unknown model request category: {category}")
        return (
            self.agent_input_per_1m_tokens_usd,
            self.agent_output_per_1m_tokens_usd,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": "USD",
            "token_unit": TOKEN_UNIT,
            "agent": {
                "input_per_1m_tokens": self.agent_input_per_1m_tokens_usd,
                "output_per_1m_tokens": self.agent_output_per_1m_tokens_usd,
            },
            "applies_to": list(MODEL_CATEGORIES),
        }


class EpisodeModelMeter:


    def __init__(self, pricing: PricingConfig | None = None) -> None:
        self.pricing = pricing or PricingConfig()
        self._first_request_started: float | None = None
        self._last_request_finished: float | None = None
        self._waits: list[tuple[float, float, str]] = []
        self._categories = {name: _empty_category() for name in MODEL_CATEGORIES}

    def record_request(
        self,
        *,
        category: str,
        started_at: float,
        finished_at: float,
        usage: Mapping[str, Any] | None,
        success: bool,
    ) -> None:
        category = category if category in MODEL_CATEGORIES else "auxiliary_tools"
        finished_at = max(started_at, finished_at)
        self._first_request_started = (
            started_at
            if self._first_request_started is None
            else min(self._first_request_started, started_at)
        )
        self._last_request_finished = (
            finished_at
            if self._last_request_finished is None
            else max(self._last_request_finished, finished_at)
        )

        item = self._categories[category]
        item["request_count"] += 1
        item["successful_requests" if success else "failed_requests"] += 1
        item["request_seconds"] += finished_at - started_at
        supplied = _usage_supplied(usage)
        item["metered_requests" if supplied else "unmetered_requests"] += 1
        normalized = normalize_usage(usage)
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            item[key] += normalized[key]

    def record_wait(self, started_at: float, finished_at: float, reason: str) -> None:
        if finished_at > started_at:
            self._waits.append((started_at, finished_at, reason or "unspecified"))

    def snapshot(self) -> dict[str, Any]:
        first = self._first_request_started
        last = self._last_request_finished
        wall_window = max(0.0, (last - first)) if first is not None and last is not None else 0.0
        clipped_waits = _clipped_waits(self._waits, first, last)
        intentional_wait = _merged_duration((start, end) for start, end, _ in clipped_waits)
        waits_by_reason: dict[str, float] = {}
        for start, end, reason in clipped_waits:
            waits_by_reason[reason] = waits_by_reason.get(reason, 0.0) + end - start

        categories: dict[str, dict[str, Any]] = {}
        costs: dict[str, float] = {}
        for name in MODEL_CATEGORIES:
            item = dict(self._categories[name])
            item["request_seconds"] = _seconds(item["request_seconds"])
            categories[name] = item
            input_rate, output_rate = self.pricing.rates_for(name)
            costs[name] = _usd(
                item["input_tokens"] * input_rate / TOKEN_UNIT
                + item["output_tokens"] * output_rate / TOKEN_UNIT
            )

        total_usage = _sum_categories(categories)
        total_request_seconds = sum(
            float(item["request_seconds"]) for item in categories.values()
        )
        costs["total"] = _usd(sum(costs.values()))
        return {
            "timing": {
                "effective_model_window_seconds": _seconds(
                    max(0.0, wall_window - intentional_wait)
                ),
                "model_window_wall_seconds": _seconds(wall_window),
                "intentional_wait_seconds": _seconds(intentional_wait),
                "model_request_seconds": _seconds(total_request_seconds),
                "intentional_waits_by_reason": {
                    key: _seconds(value) for key, value in sorted(waits_by_reason.items())
                },
            },
            "usage": {**categories, "total": total_usage},
            "cost_usd": costs,
        }


_CURRENT_METER: ContextVar[EpisodeModelMeter | None] = ContextVar(
    "hll_episode_model_meter",
    default=None,
)


@contextmanager
def activate_model_meter(meter: EpisodeModelMeter) -> Iterator[None]:
    token = _CURRENT_METER.set(meter)
    try:
        yield
    finally:
        _CURRENT_METER.reset(token)


def record_model_request(
    *,
    category: str,
    started_at: float,
    finished_at: float,
    usage: Mapping[str, Any] | None,
    success: bool,
) -> None:
    meter = _CURRENT_METER.get()
    if meter is not None:
        meter.record_request(
            category=category,
            started_at=started_at,
            finished_at=finished_at,
            usage=usage,
            success=success,
        )


def intentional_sleep(seconds: float, reason: str) -> float:
    """Exclude intentional waits from effective model time."""

    duration = max(0.0, float(seconds))
    started = time.monotonic()
    time.sleep(duration)
    finished = time.monotonic()
    meter = _CURRENT_METER.get()
    if meter is not None:
        meter.record_wait(started, finished, reason)
    return finished - started


def normalize_usage(usage: Mapping[str, Any] | None) -> dict[str, int]:
    source = usage or {}
    input_tokens = _token_value(source, "prompt_tokens", "input_tokens")
    output_tokens = _token_value(source, "completion_tokens", "output_tokens")
    total_tokens = _token_value(source, "total_tokens")
    if total_tokens <= 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _price(values: Mapping[str, str], name: str) -> float:
    raw = str(values.get(name, "") or "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative number") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


def _empty_category() -> dict[str, Any]:
    return {
        "request_count": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "metered_requests": 0,
        "unmetered_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "request_seconds": 0.0,
    }


def _sum_categories(categories: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    total = _empty_category()
    for item in categories.values():
        for key in total:
            total[key] += item.get(key, 0)
    total["request_seconds"] = _seconds(total["request_seconds"])
    return total


def _usage_supplied(usage: Mapping[str, Any] | None) -> bool:
    if not isinstance(usage, Mapping):
        return False
    return any(
        key in usage
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        )
    )


def _token_value(source: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        if key not in source:
            continue
        try:
            return max(0, int(source.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _clipped_waits(
    waits: list[tuple[float, float, str]],
    first: float | None,
    last: float | None,
) -> list[tuple[float, float, str]]:
    if first is None or last is None or last <= first:
        return []
    clipped = []
    for start, end, reason in waits:
        clipped_start = max(first, start)
        clipped_end = min(last, end)
        if clipped_end > clipped_start:
            clipped.append((clipped_start, clipped_end, reason))
    return clipped


def _merged_duration(intervals: Any) -> float:
    ordered = sorted(intervals)
    if not ordered:
        return 0.0
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += current_end - current_start
        current_start, current_end = start, end
    return total + current_end - current_start


def _seconds(value: float) -> float:
    return round(float(value), 4)


def _usd(value: float) -> float:
    return round(float(value), 8)
