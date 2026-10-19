import unittest

from hll.metrics import EpisodeModelMeter, PricingConfig


class ModelAccountingTests(unittest.TestCase):
    def test_effective_window_excludes_waits_and_costs_each_category(self):
        meter = EpisodeModelMeter(
            PricingConfig(
                agent_input_per_1m_tokens_usd=2.0,
                agent_output_per_1m_tokens_usd=6.0,
            )
        )
        meter.record_request(
            category="agent",
            started_at=10.0,
            finished_at=12.0,
            usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            success=True,
        )
        meter.record_wait(12.0, 15.0, "post_action_settle")
        meter.record_request(
            category="ocr",
            started_at=15.0,
            finished_at=16.0,
            usage={"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
            success=True,
        )
        meter.record_request(
            category="auxiliary_tools",
            started_at=19.0,
            finished_at=20.0,
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            success=True,
        )

        result = meter.snapshot()

        self.assertEqual(result["timing"]["model_window_wall_seconds"], 10.0)
        self.assertEqual(result["timing"]["intentional_wait_seconds"], 3.0)
        self.assertEqual(result["timing"]["effective_model_window_seconds"], 7.0)
        self.assertEqual(result["timing"]["model_request_seconds"], 4.0)
        self.assertEqual(result["usage"]["total"]["input_tokens"], 1300)
        self.assertEqual(result["usage"]["total"]["output_tokens"], 650)
        self.assertEqual(result["cost_usd"]["agent"], 0.005)
        self.assertEqual(result["cost_usd"]["ocr"], 0.001)
        self.assertEqual(result["cost_usd"]["auxiliary_tools"], 0.0005)
        self.assertEqual(result["cost_usd"]["total"], 0.0065)

    def test_missing_usage_is_reported_as_unmetered(self):
        meter = EpisodeModelMeter()
        meter.record_request(
            category="agent",
            started_at=1.0,
            finished_at=2.0,
            usage={},
            success=False,
        )

        agent = meter.snapshot()["usage"]["agent"]

        self.assertEqual(agent["request_count"], 1)
        self.assertEqual(agent["failed_requests"], 1)
        self.assertEqual(agent["unmetered_requests"], 1)
        self.assertEqual(agent["total_tokens"], 0)

    def test_pricing_reads_per_million_environment_names(self):
        pricing = PricingConfig.from_environment(
            {
                "AGENT_INPUT_COST_PER_1M_TOKENS": "1.25",
                "AGENT_OUTPUT_COST_PER_1M_TOKENS": "5",
            }
        )

        self.assertEqual(pricing.agent_input_per_1m_tokens_usd, 1.25)
        self.assertEqual(pricing.agent_output_per_1m_tokens_usd, 5.0)


if __name__ == "__main__":
    unittest.main()
