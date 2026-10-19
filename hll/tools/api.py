from __future__ import annotations

import base64
import time
from typing import Any, Sequence

import requests

from hll.metrics import intentional_sleep, record_model_request


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def _normalize_api_url(api_url: str) -> str:
    endpoint = str(api_url or "").strip()
    if not endpoint:
        raise ValueError("API URL must be provided.")
    endpoint = endpoint.rstrip("/")
    lowered = endpoint.lower()
    suffixes = ("/chat/completions", "/completions", "/responses")
    if any(lowered.endswith(suffix) for suffix in suffixes):
        return endpoint
    if lowered.endswith("/v1"):
        return f"{endpoint}/chat/completions"
    return f"{endpoint}/v1/chat/completions"


def inference_chat(
    chat: Sequence[tuple[str, Any]],
    model: str,
    api_url: str,
    token: str,
    *,
    max_tokens: int = 4096,
    temperature: float | None = None,
    seed: int | None = None,
    max_attempts: int = 3,
    retry_delay_seconds: float = 0.5,
    billing_category: str = "auxiliary_tools",
) -> str:
    normalized_url = _normalize_api_url(api_url)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = {
        "model": model,
        "messages": [],
        "max_tokens": max(1, int(max_tokens)),
    }
    if temperature is not None:
        data["temperature"] = temperature
    if seed is not None:
        data["seed"] = seed
    for role, content in chat:
        data["messages"].append({"role": role, "content": content})

    last_error: Exception | None = None
    attempts = max(1, int(max_attempts))
    for attempt in range(attempts):
        payload: Any = {}
        started = time.monotonic()
        try:
            response = requests.post(normalized_url, headers=headers, json=data, timeout=120)
            response.raise_for_status()
            payload = response.json()
            finished = time.monotonic()
            content = payload["choices"][0]["message"]["content"]
            record_model_request(
                category=billing_category,
                started_at=started,
                finished_at=finished,
                usage=payload.get("usage") or {},
                success=True,
            )
            return str(content or "")
        except requests.exceptions.RequestException as exc:
            record_model_request(
                category=billing_category,
                started_at=started,
                finished_at=time.monotonic(),
                usage={},
                success=False,
            )
            response = getattr(exc, "response", None)
            body = f"; response={response.text}" if response is not None else ""
            last_error = RuntimeError(f"model request failed for {normalized_url}: {exc}{body}")
        except (KeyError, IndexError, TypeError) as exc:
            record_model_request(
                category=billing_category,
                started_at=started,
                finished_at=time.monotonic(),
                usage=(payload.get("usage") or {}) if isinstance(payload, dict) else {},
                success=False,
            )
            last_error = RuntimeError(f"unexpected model response format: {exc}")
        except Exception as exc:
            record_model_request(
                category=billing_category,
                started_at=started,
                finished_at=time.monotonic(),
                usage={},
                success=False,
            )
            last_error = exc
        if attempt < attempts - 1:
            intentional_sleep(retry_delay_seconds, "model_retry_backoff")
    raise RuntimeError(str(last_error or "model request failed"))
