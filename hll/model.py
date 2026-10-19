from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from hll.metrics import intentional_sleep, normalize_usage, record_model_request


@dataclass(frozen=True)
class ModelMessage:
    role: str
    text: str
    image_path: str = ""


@dataclass(frozen=True)
class ModelReply:
    text: str
    usage: Mapping[str, int] = field(default_factory=dict)


class VisionModel(Protocol):
    def complete(self, messages: Sequence[ModelMessage]) -> ModelReply: ...


class ModelRequestError(RuntimeError):
    pass


class OpenAICompatibleVisionModel:


    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 120.0,
        temperature: float | None = None,
        max_tokens: int = 4096,
        billing_category: str = "agent",
        max_attempts: int = 2,
        retry_delay_seconds: float = 0.5,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        self.url = self._chat_completions_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = int(max_tokens)
        self.billing_category = billing_category
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))

    def complete(self, messages: Sequence[ModelMessage]) -> ModelReply:
        body = {
            "model": self.model,
            "messages": [self._serialize_message(message) for message in messages],
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        payload, started, finished = self._request(request)

        finished = time.monotonic()
        raw_usage = (payload.get("usage") or {}) if isinstance(payload, Mapping) else {}

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            record_model_request(
                category=self.billing_category,
                started_at=started,
                finished_at=finished,
                usage=raw_usage,
                success=False,
            )
            raise ModelRequestError(f"invalid model response: {str(payload)[:1000]}") from exc

        if isinstance(content, list):
            content = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, Mapping)
            )
        normalized_usage = normalize_usage(raw_usage)
        usage = {
            "prompt_tokens": normalized_usage["input_tokens"],
            "completion_tokens": normalized_usage["output_tokens"],
            "total_tokens": normalized_usage["total_tokens"],
        }
        record_model_request(
            category=self.billing_category,
            started_at=started,
            finished_at=finished,
            usage=raw_usage,
            success=True,
        )
        return ModelReply(
            text=str(content),
            usage=usage,
        )

    def _request(
        self,
        request: urllib.request.Request,
    ) -> tuple[Mapping[str, Any], float, float]:
        for attempt in range(self.max_attempts):
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                return payload, started, time.monotonic()
            except urllib.error.HTTPError as exc:
                finished = time.monotonic()
                record_model_request(
                    category=self.billing_category,
                    started_at=started,
                    finished_at=finished,
                    usage={},
                    success=False,
                )
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:1000]
                except Exception:
                    detail = str(exc.reason or exc)[:1000]
                if exc.code < 500 or attempt == self.max_attempts - 1:
                    raise ModelRequestError(
                        f"model returned HTTP {exc.code}: {detail}"
                    ) from exc
            except (OSError, ValueError) as exc:
                finished = time.monotonic()
                record_model_request(
                    category=self.billing_category,
                    started_at=started,
                    finished_at=finished,
                    usage={},
                    success=False,
                )
                if attempt == self.max_attempts - 1:
                    raise ModelRequestError(f"model request failed: {exc}") from exc
            intentional_sleep(self.retry_delay_seconds, "model_retry_backoff")
        raise ModelRequestError("model request failed")

    @staticmethod
    def _chat_completions_url(base_url: str) -> str:
        value = base_url.rstrip("/")
        if value.endswith("/chat/completions"):
            return value
        return f"{value}/chat/completions"

    @staticmethod
    def _serialize_message(message: ModelMessage) -> dict[str, Any]:
        if not message.image_path:
            return {"role": message.role, "content": message.text}

        path = Path(message.image_path)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "role": message.role,
            "content": [
                {"type": "text", "text": message.text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                },
            ],
        }
