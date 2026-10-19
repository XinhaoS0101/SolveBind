import json
import unittest
import urllib.error
import urllib.request

from hll.cli import build_parser
from hll.metrics import EpisodeModelMeter, activate_model_meter
from hll.model import ModelMessage, OpenAICompatibleVisionModel


class ModelClientTests(unittest.TestCase):
    def test_model_request_default_max_tokens_is_long_horizon_friendly(self):
        captured = self._complete_and_capture_request()
        self.assertEqual(captured["body"]["max_tokens"], 4096)

    def test_model_request_uses_configured_max_tokens(self):
        captured = self._complete_and_capture_request(max_tokens=1234)
        self.assertEqual(captured["body"]["max_tokens"], 1234)

    def test_optional_temperature_is_omitted_by_default(self):
        captured = self._complete_and_capture_request()
        self.assertNotIn("temperature", captured["body"])

    def test_explicit_temperature_is_sent(self):
        captured = self._complete_and_capture_request(temperature=0.2)
        self.assertEqual(captured["body"]["temperature"], 0.2)

    def test_transient_server_error_is_retried_once(self):
        calls = 0
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout):
            nonlocal calls
            del request, timeout
            calls += 1
            if calls == 1:
                raise urllib.error.HTTPError("url", 502, "bad gateway", {}, None)
            return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        urllib.request.urlopen = fake_urlopen
        try:
            model = OpenAICompatibleVisionModel(
                base_url="https://example.test/v1",
                api_key="test-key",
                model="test-model",
                retry_delay_seconds=0,
            )
            reply = model.complete([ModelMessage(role="user", text="hi")])
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertEqual(reply.text, "ok")
        self.assertEqual(calls, 2)

    def test_cli_defaults_to_long_horizon_max_output_tokens(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.max_output_tokens, 4096)

    def test_cli_accepts_max_output_tokens(self):
        args = build_parser().parse_args(["--max-output-tokens", "3456"])
        self.assertEqual(args.max_output_tokens, 3456)

    def test_model_request_records_agent_usage(self):
        meter = EpisodeModelMeter()
        with activate_model_meter(meter):
            self._complete_and_capture_request()

        accounting = meter.snapshot()
        self.assertEqual(accounting["usage"]["agent"]["request_count"], 1)
        self.assertEqual(accounting["usage"]["agent"]["input_tokens"], 1)
        self.assertEqual(accounting["usage"]["agent"]["output_tokens"], 2)

    def _complete_and_capture_request(self, **model_kwargs):
        captured = {}
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout):
            del timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "choices": [{"message": {"content": '{"action":"wait","args":{}}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                }
            )

        urllib.request.urlopen = fake_urlopen
        try:
            model = OpenAICompatibleVisionModel(
                base_url="https://example.test/v1",
                api_key="test-key",
                model="test-model",
                **model_kwargs,
            )
            reply = model.complete([ModelMessage(role="user", text="hi")])
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertEqual(reply.text, '{"action":"wait","args":{}}')
        self.assertEqual(reply.usage["total_tokens"], 3)
        return captured


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
