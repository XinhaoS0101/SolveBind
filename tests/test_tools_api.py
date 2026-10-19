import unittest
from unittest.mock import patch

from hll.metrics import EpisodeModelMeter, activate_model_meter
from hll.tools.api import inference_chat


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        }


class ToolApiTests(unittest.TestCase):
    def test_visual_tool_default_completion_budget_is_4096(self):
        with patch("hll.tools.api.requests.post", return_value=_Response()) as post:
            result = inference_chat(
                [("user", "inspect")],
                "test-model",
                "http://127.0.0.1:9999/v1",
                "token",
            )

        self.assertEqual(result, "ok")
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 4096)
        self.assertNotIn("temperature", post.call_args.kwargs["json"])
        self.assertNotIn("seed", post.call_args.kwargs["json"])

    def test_visual_tool_sends_explicit_sampling_options(self):
        with patch("hll.tools.api.requests.post", return_value=_Response()) as post:
            inference_chat(
                [("user", "inspect")],
                "test-model",
                "http://127.0.0.1:9999/v1",
                "token",
                temperature=0.1,
                seed=7,
            )

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["temperature"], 0.1)
        self.assertEqual(body["seed"], 7)

    def test_visual_tool_request_records_auxiliary_usage(self):
        meter = EpisodeModelMeter()
        with patch("hll.tools.api.requests.post", return_value=_Response()):
            with activate_model_meter(meter):
                inference_chat(
                    [("user", "inspect")],
                    "test-model",
                    "http://127.0.0.1:9999/v1",
                    "token",
                )

        usage = meter.snapshot()["usage"]["auxiliary_tools"]
        self.assertEqual(usage["request_count"], 1)
        self.assertEqual(usage["input_tokens"], 4)
        self.assertEqual(usage["output_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
