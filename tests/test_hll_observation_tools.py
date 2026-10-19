import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hll.domain import Action, ActionKind, Decision, Observation
from hll.executor import HllToolExecutor
from hll.tools import build_observation_registry
from hll.tools.base import ToolContext


class HllObservationToolTests(unittest.TestCase):
    def test_get_server_stats_reads_hll_safe_state_without_url(self):
        registry = build_observation_registry()
        context = _tool_context(
            safe_state={
                "page_views": 3,
                "total_verifications": 2,
                "successful_verifications": 1,
                "captcha_answer_at_start": "hidden",
            },
            captcha_url="",
        )

        result = registry.try_execute("GetServerStats()", context)

        self.assertTrue(result.handled)
        self.assertEqual(result.exec_info["tool_name"], "GetServerStats")
        self.assertTrue(result.exec_info["read_only"])
        self.assertEqual(
            result.exec_info["server_stats"],
            {
                "page_views": 3,
                "total_verifications": 2,
                "successful_verifications": 1,
            },
        )
        self.assertNotIn("captcha_answer_at_start", result.exec_info["server_stats"])

    def test_executor_dispatches_get_observation_through_hll_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            screenshot.write_bytes(b"not-a-real-image")
            executor = HllToolExecutor(_FakeEnvironment())

            result = executor.execute(
                Decision(Action(ActionKind.GET_OBSERVATION, {})),
                Observation(
                    step=0,
                    screenshot_path=str(screenshot),
                    width=320,
                    height=480,
                    instruction="select matching images",
                    safe_state={
                        "page_views": 1,
                        "total_verifications": 0,
                        "successful_verifications": 0,
                    },
                ),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.details["read_only"])
        self.assertEqual(result.details["tool_name"], "GetObservation")
        self.assertEqual(result.details["tool_call"], "GetObservation()")
        self.assertEqual(result.details["server_stats"]["page_views"], 1)


class _FakeEnvironment:
    adb_path = "adb"
    device_serial = ""
    captcha_url = ""

    def get_stats(self):
        return {"page_views": 1}


def _tool_context(
    *,
    safe_state: dict,
    captcha_url: str = "",
) -> ToolContext:
    cfg = SimpleNamespace(
        adb_path="adb",
        API_url="",
        token="",
        caption_model="",
        screenshot_dir="",
        judgement_dir="",
        captcha_url=captcha_url,
        post_action_poll_interval_sec=0.0,
    )
    return ToolContext(
        env=SimpleNamespace(cfg=cfg),
        screenshot_file="screen.png",
        width=320,
        height=480,
        perception_infos=[],
        instruction="solve",
        action_history=[],
        captcha_url=captcha_url,
        trajectory_summary={"total_steps": 0},
        safe_state=safe_state,
    )


if __name__ == "__main__":
    unittest.main()
