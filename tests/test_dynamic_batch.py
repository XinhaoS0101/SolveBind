import tempfile
import unittest
from pathlib import Path

from hll.batch import BatchRunner, EpisodeSpec
from hll.captcha.task_config import DYNAMIC_CAPTCHA_TYPES, build_task_config
from hll.cli import build_episode_specs
from hll.domain import EpisodeResult, EvaluationStatus, Task
from hll.instructions import instruction_for
from hll.preflight import run_preflight
from web.captcha_feedback import safe_verification_feedback
from web.captcha.logic_arithmetic_dynamic_captcha import LogicArithmeticDynamicCaptcha
from web.captcha.slider_real_dynamic_captcha import SliderRealDynamicCaptcha
from web.captcha import create_distraction_captcha
from web.captcha.click_icon_captcha import ClickIconCaptcha


class Result:
    def __init__(self, success, message, extra):
        self.success = success
        self.message = message
        self.extra = extra
        self.expected = "SECRET"
        self.received = "guess"


class StubHarness:
    def run(self, task, output_dir):
        result = EpisodeResult(
            task=task,
            success=True,
            status=EvaluationStatus.SUCCESS,
            reason="captcha_verified",
            steps=(),
            elapsed_seconds=0.01,
            output_dir=str(output_dir),
            metrics={"seed": task.config["seed"]},
        )
        result.write_json(output_dir / "episode.json")
        return result


class AccountingHarness:
    def run(self, task, output_dir):
        seed = int(task.config["seed"])
        accounting = {
            "timing": {
                "effective_model_window_seconds": float(seed),
                "model_request_seconds": float(seed) / 2,
                "intentional_wait_seconds": 0.25,
            },
            "usage": {
                "agent": {
                    "input_tokens": seed * 10,
                    "output_tokens": seed * 5,
                    "total_tokens": seed * 15,
                },
                "ocr": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "auxiliary_tools": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "total": {
                    "input_tokens": seed * 10,
                    "output_tokens": seed * 5,
                    "total_tokens": seed * 15,
                },
            },
            "cost_usd": {
                "agent": seed / 1000,
                "ocr": 0.0,
                "auxiliary_tools": 0.0,
                "total": seed / 1000,
            },
        }
        result = EpisodeResult(
            task=task,
            success=True,
            status=EvaluationStatus.SUCCESS,
            reason="captcha_verified",
            steps=(),
            elapsed_seconds=float(seed) + 1,
            output_dir=str(output_dir),
            metrics={"seed": seed, "model_accounting": accounting},
        )
        result.write_json(output_dir / "episode.json")
        return result


class DynamicBatchTests(unittest.TestCase):
    def test_extended_logic_spatial_behavior_uses_spatial_pick(self):
        captcha = object.__new__(LogicArithmeticDynamicCaptcha)
        result = captcha.verify_behavior(
            "colorref|42.0,37.0",
            [
                {"type": "page_ready", "t": 0},
                {"type": "spatial_pick", "x": 42.0, "y": 37.0, "t": 100},
            ],
        )
        self.assertTrue(result.success)
        self.assertEqual(result.extra["spatial_picks"], 1)

    def test_extended_logic_path_behavior_uses_navigation(self):
        captcha = object.__new__(LogicArithmeticDynamicCaptcha)
        result = captcha.verify_behavior(
            "pathmatch|3",
            [
                {"type": "page_ready", "t": 0},
                {"type": "path_nav", "control": "next", "t": 100},
            ],
        )
        self.assertTrue(result.success)
        self.assertEqual(result.extra["path_navs"], 1)

    def test_extended_logic_script_records_spatial_and_path_actions(self):
        script = object.__new__(LogicArithmeticDynamicCaptcha).build_dynamic_script()
        self.assertIn("spatial_pick", script)
        self.assertIn("path_nav", script)

    def test_slider_records_drag_end_before_release_auto_submit(self):
        script = object.__new__(SliderRealDynamicCaptcha).build_dynamic_script()
        self.assertIn("addEventListener('mouseup', onEnd, true)", script)
        self.assertIn("capture: true", script)

    def test_click_icon_pool_has_unique_rendered_glyphs(self):
        captcha = ClickIconCaptcha()
        font = captcha._load_font()
        icons = captcha._renderable_icons(font)
        signatures = {captcha._glyph_signature(font, icon) for icon in icons}

        self.assertGreaterEqual(len(icons), captcha.icon_count)
        self.assertEqual(len(signatures), len(icons))

    def test_distraction_overlay_scrolls_for_tall_captchas(self):
        captcha = create_distraction_captcha(ClickIconCaptcha, distraction_level=2)
        styles = captcha._render_distraction_styles()

        overlay_css = styles.split(".captcha-overlay {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-y: auto", overlay_css)
        self.assertIn("overscroll-behavior: contain", overlay_css)

    def test_all_dynamic_types_have_reproducible_specs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("slider", "click", "puzzle", "image_grid"):
                (root / name).mkdir()
            specs = build_episode_specs(
                DYNAMIC_CAPTCHA_TYPES,
                num_tasks=2,
                base_seed=100,
                difficulty="normal",
                distraction_level=0,
                text_length=4,
                instruction_override="",
                asset_root=root,
            )
        self.assertEqual(len(specs), 18)
        self.assertEqual([spec.seed for spec in specs], list(range(100, 118)))
        self.assertEqual({spec.task.captcha_type for spec in specs}, set(DYNAMIC_CAPTCHA_TYPES))
        self.assertEqual(len({spec.sample_id for spec in specs}), 18)

    def test_default_instruction_uses_demo_style_dynamic_prompt(self):
        instruction = instruction_for(
            "image_grid_dynamic",
            length=4,
            click_count=3,
            distraction_level=0,
        )
        self.assertIn("You are on an image classification captcha page", instruction)
        self.assertIn("Treat the grid as row-major indices 0-8", instruction)
        self.assertIn("Additional dynamic requirement", instruction)
        self.assertIn("Return exactly one JSON action object", instruction)

    def test_distraction_prompt_wraps_task_instruction(self):
        instruction = instruction_for(
            "click_real_dynamic",
            length=4,
            click_count=3,
            distraction_level=2,
        )
        self.assertIn("CRITICAL: This page simulates a real webpage", instruction)
        self.assertIn("You are on a click captcha verification page with a real image", instruction)
        self.assertIn("Focus ONLY on the real captcha area", instruction)

    def test_real_image_tasks_receive_default_asset_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = build_task_config(
                "slider_real_dynamic",
                difficulty="hard",
                distraction_level=2,
                text_length=9,
                seed=7,
                asset_root=root,
            )
        self.assertEqual(config["image_dir"], str(root / "slider"))
        self.assertNotIn("length", config)
        self.assertEqual(config["seed"], 7)
        self.assertEqual(config["difficulty"], "hard")
        self.assertEqual(config["description"], "Drag the slider to match the gap position.")

    def test_dynamic_subset_config_matches_eval_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            click_icon = build_task_config(
                "click_icon_dynamic",
                difficulty="hard",
                distraction_level=0,
                text_length=4,
                seed=11,
                asset_root=root,
            )
            image_grid = build_task_config(
                "image_grid_dynamic",
                difficulty="easy",
                distraction_level=2,
                text_length=4,
                seed=12,
                asset_root=root,
                image_grid_dir=str(root / "custom_grid"),
                unsplash_access_key="key",
            )
            pic_puzzle = build_task_config(
                "pic_puzzle_dynamic",
                difficulty="normal",
                distraction_level=0,
                text_length=4,
                seed=13,
                asset_root=root,
                pic_puzzle_query="city",
                unsplash_access_key="key",
            )

        self.assertEqual(click_icon["click_count"], 3)
        self.assertEqual(click_icon["description"], "Click on the icons in the order shown above.")
        self.assertNotIn("difficulty", click_icon)
        self.assertNotIn("distraction_level", click_icon)

        self.assertEqual(image_grid["title"], "Image Verification")
        self.assertEqual(image_grid["difficulty"], "easy")
        self.assertEqual(image_grid["distraction_level"], 2)
        self.assertEqual(image_grid["image_dir"], str(root / "custom_grid"))
        self.assertEqual(image_grid["unsplash_access_key"], "key")

        self.assertEqual(pic_puzzle["title"], "Picture Puzzle Verification")
        self.assertEqual(pic_puzzle["description"], "Swap the incorrect tiles to restore the image.")
        self.assertEqual(pic_puzzle["unsplash_query"], "city")
        self.assertEqual(pic_puzzle["unsplash_access_key"], "key")

    def test_batch_checkpoints_summary_and_episode_paths(self):
        task = Task("click_icon_dynamic", "solve", {"seed": 9})
        spec = EpisodeSpec("sample_1", 9, task)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = BatchRunner(
                lambda: StubHarness(),
                metadata={"model": "test-model", "commit": "abc123"},
            ).run((spec,), output)
            self.assertTrue((output / "batch.json").exists())
            self.assertTrue((output / "run_manifest.json").exists())
            self.assertTrue((output / "episodes" / "sample_1" / "episode.json").exists())
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["successes"], 1)
        self.assertEqual(summary["metadata"]["model"], "test-model")
        self.assertEqual(summary["metadata"]["commit"], "abc123")

    def test_batch_reports_per_type_average_time_tokens_and_cost(self):
        specs = (
            EpisodeSpec(
                "sample_1",
                2,
                Task("click_icon_dynamic", "solve", {"seed": 2}),
            ),
            EpisodeSpec(
                "sample_2",
                4,
                Task("click_icon_dynamic", "solve", {"seed": 4}),
            ),
            EpisodeSpec(
                "sample_3",
                3,
                Task("image_grid_dynamic", "solve", {"seed": 3}),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            summary = BatchRunner(lambda: AccountingHarness()).run(
                specs,
                Path(directory),
            )

        click = summary["captcha_type_summaries"]["click_icon_dynamic"]
        image_grid = summary["captcha_type_summaries"]["image_grid_dynamic"]
        self.assertTrue(click["complete"])
        self.assertEqual(click["average_effective_model_window_seconds"], 3.0)
        self.assertEqual(click["average_input_tokens"], 30.0)
        self.assertEqual(click["average_output_tokens"], 15.0)
        self.assertEqual(click["average_cost_usd"], 0.003)
        self.assertEqual(image_grid["average_effective_model_window_seconds"], 3.0)
        self.assertEqual(summary["model_accounting"]["completed"], 3)

    def test_safe_dynamic_feedback_filters_answers_and_ground_truth(self):
        feedback = safe_verification_feedback(
            Result(
                False,
                "Dynamic check failed: no movement was recorded.",
                {
                    "telemetry_events": 3,
                    "telemetry_event_counts": {"drag_start": 1, "drag_end": 1},
                    "swap_pairs": [[1, 2]],
                    "expected": "SECRET",
                },
            ),
            attempt=2,
        )
        self.assertEqual(feedback["reason_code"], "dynamic_behavior_rejected")
        self.assertEqual(feedback["details"]["telemetry_events"], 3)
        self.assertNotIn("swap_pairs", feedback["details"])
        self.assertNotIn("expected", feedback["details"])
        self.assertNotIn("answer", feedback)

    def test_preflight_accepts_nested_image_grid_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "image_grid" / "cats"
            nested.mkdir(parents=True)
            (nested / "sample.jpg").write_bytes(b"image")
            report = run_preflight(
                ("image_grid_dynamic",),
                adb_path="definitely-missing-adb",
                device_serial="",
                api_key="placeholder",
                ocr_engine="off",
                asset_root=root,
            )
        asset_check = next(
            check for check in report["checks"] if check["name"] == "assets:image_grid_dynamic"
        )
        self.assertTrue(asset_check["ok"])

    def test_preflight_reports_dynamic_type_count_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_preflight(
                DYNAMIC_CAPTCHA_TYPES,
                adb_path="definitely-missing-adb",
                device_serial="",
                api_key="placeholder",
                ocr_engine="off",
                asset_root=Path(directory),
                expected_dynamic_types=len(DYNAMIC_CAPTCHA_TYPES) + 1,
            )
        count_check = next(
            check for check in report["checks"] if check["name"] == "dynamic_type_count"
        )
        self.assertFalse(count_check["ok"])
        self.assertEqual(count_check["expected"], len(DYNAMIC_CAPTCHA_TYPES) + 1)
        self.assertEqual(count_check["actual"], len(DYNAMIC_CAPTCHA_TYPES))


if __name__ == "__main__":
    unittest.main()
