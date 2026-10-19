import json
import tempfile
import unittest
from pathlib import Path

from hll.analysis import analyze_paths, render_markdown, write_report


class TrajectoryAnalysisTests(unittest.TestCase):
    def test_hll_batch_aggregates_diagnostics_and_failure_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episode_dir = root / "episodes" / "sample_1"
            episode_dir.mkdir(parents=True)
            episode = {
                "task": {"captcha_type": "click_real_dynamic", "config": {"sample_id": "sample_1"}},
                "success": False,
                "status": "stopped",
                "reason": "action_step_budget_exhausted",
                "elapsed_seconds": 12.5,
                "metrics": {
                    "sample_id": "sample_1",
                    "steps": 3,
                    "invalid_action_steps": 0,
                    "model_usage": {"total_tokens": 100},
                    "model_accounting": {
                        "timing": {"effective_model_window_seconds": 9.5},
                        "usage": {
                            "total": {
                                "input_tokens": 80,
                                "output_tokens": 20,
                                "total_tokens": 100,
                            }
                        },
                        "cost_usd": {"total": 0.00125},
                    },
                    "trajectory_diagnostics": {"read_only_repeats": 0, "model_wait_ratio": 0.5},
                    "run": {"model": "test-model"},
                },
                "steps": [
                    _hll_step(1, "detect_click_targets", "DetectClickTargets", read_only=True),
                    _hll_step(2, "submit_captcha", "SubmitCaptcha", deferred=True),
                    _hll_step(3, "submit_captcha", "SubmitCaptcha", error="not_found"),
                ],
            }
            episode_path = episode_dir / "episode.json"
            episode_path.write_text(json.dumps(episode), encoding="utf-8")
            batch = {
                "metadata": {"commit": "abc", "model": "test-model"},
                "items": [
                    {
                        "sample_id": "sample_1",
                        "captcha_type": "click_real_dynamic",
                        "success": False,
                        "episode_path": str(episode_path),
                    }
                ],
            }
            (root / "batch.json").write_text(json.dumps(batch), encoding="utf-8")

            report = analyze_paths([root])

        self.assertEqual(report["summary"]["episodes"], 1)
        self.assertEqual(report["summary"]["tool_errors"], 1)
        self.assertEqual(report["summary"]["target_detection_without_click"], 1)
        self.assertEqual(report["summary"]["deferred_submits"], 1)
        self.assertEqual(report["summary"]["average_effective_model_window_seconds"], 9.5)
        self.assertEqual(report["summary"]["input_tokens"], 80)
        self.assertEqual(report["summary"]["output_tokens"], 20)
        self.assertEqual(report["summary"]["total_cost_usd"], 0.00125)
        self.assertEqual(report["summary"]["phase_step_counts"], {"execute": 3})
        self.assertEqual(report["summary"]["tool_metrics"]["SubmitCaptcha"]["errors"], 1)
        self.assertEqual(report["episodes"][0]["failure_owner_hint"], "tool_or_framework")
        self.assertIn("click_real_dynamic", render_markdown(report))

    def test_legacy_trace_reads_steps_and_success_from_companion_result(self):
        with tempfile.TemporaryDirectory() as directory:
            sample_dir = Path(directory) / "model" / "click_icon_dynamic" / "sample_1"
            sample_dir.mkdir(parents=True)
            trace = {
                "attempts": [
                    {
                        "failed_verification_count": 0,
                        "step_errors": [],
                        "step_records": [
                            {
                                "iter": 1,
                                "action": "DetectClickTargets()",
                                "workflow": {"phase": "locate_challenge"},
                                "executed_action": {"tool_name": "DetectClickTargets"},
                                "trajectory": {"action_key": "detect_click_targets"},
                            },
                            {
                                "iter": 2,
                                "action": "ClickTarget(1)",
                                "workflow": {"phase": "execute"},
                                "executed_action": {"tool_name": "ClickTarget"},
                                "trajectory": {"action_key": "click_target"},
                            },
                        ],
                    }
                ]
            }
            trace_path = sample_dir / "agent_trace.json"
            trace_path.write_text(json.dumps(trace), encoding="utf-8")
            (sample_dir / "result.json").write_text(
                json.dumps(
                    {
                        "sample_id": "sample_1",
                        "captcha_type": "click_icon_dynamic",
                        "model": "test-model",
                        "success": True,
                    }
                ),
                encoding="utf-8",
            )

            report = analyze_paths([trace_path])
            json_path, markdown_path = write_report(report, Path(directory) / "analysis")

        self.assertEqual(report["summary"]["successes"], 1)
        self.assertEqual(report["summary"]["target_detection_without_click"], 0)
        self.assertEqual(report["episodes"][0]["tool_sequence"], ["DetectClickTargets", "ClickTarget"])
        self.assertTrue(json_path.name.endswith(".json"))
        self.assertTrue(markdown_path.name.endswith(".md"))


def _hll_step(
    step: int,
    action: str,
    tool_name: str,
    *,
    read_only: bool = False,
    deferred: bool = False,
    error: str = "",
) -> dict:
    details = {"tool_name": tool_name, "read_only": read_only}
    if deferred:
        details["deferred_submit"] = True
    if error:
        details["error"] = error
    return {
        "step": step,
        "decision": {"action": {"action": action, "args": {}}},
        "execution": {"ok": not error, "details": details, "error": error},
        "evaluation": {"reason": "tool_completed"},
        "workflow_before": {"phase": "execute"},
    }


if __name__ == "__main__":
    unittest.main()
