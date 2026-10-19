import unittest
from unittest.mock import patch

from hll.cli import build_parser, build_run_metadata, resolve_ocr_engine


class CliOcrSelectionTests(unittest.TestCase):
    def test_auto_ocr_prefers_local_modelscope_for_text(self):
        with patch("hll.cli.local_modelscope_ocr_available", return_value=True):
            self.assertEqual(resolve_ocr_engine("auto", ("text",)), "modelscope")

    def test_auto_ocr_falls_back_to_vlm_for_text(self):
        with patch("hll.cli.local_modelscope_ocr_available", return_value=False):
            self.assertEqual(resolve_ocr_engine("auto", ("text",)), "vlm")

    def test_auto_ocr_is_off_for_non_text_batches(self):
        with patch("hll.cli.local_modelscope_ocr_available", return_value=True):
            self.assertEqual(resolve_ocr_engine("auto", ("text", "slider_real")), "off")
            self.assertEqual(resolve_ocr_engine("auto", ("slider_real_dynamic",)), "off")

    def test_explicit_ocr_engine_is_honored(self):
        self.assertEqual(resolve_ocr_engine("vlm", ("slider_real_dynamic",)), "vlm")
        self.assertEqual(resolve_ocr_engine("modelscope", ("slider_real_dynamic",)), "modelscope")
        self.assertEqual(resolve_ocr_engine("off", ("text",)), "off")

    def test_default_grounding_budget_allows_one_recovery_crop(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.max_ground_steps, 3)

    def test_run_metadata_records_reproducibility_and_redacts_keys(self):
        args = build_parser().parse_args(
            ["--model", "test-model", "--api-key", "secret", "--unsplash-access-key", "photo-key"]
        )
        git_values = {
            ("rev-parse", "--abbrev-ref", "HEAD"): "mcp-tool",
            ("rev-parse", "HEAD"): "abc123",
            ("status", "--porcelain"): " M hll/agent.py",
        }
        with patch("hll.cli._git_value", side_effect=lambda *value: git_values.get(value, "")):
            metadata = build_run_metadata(
                args=args,
                captcha_types=("text",),
                base_seed=7,
                base_url="http://example.test/v1",
                ocr_engine_name="vlm",
            )

        self.assertEqual(metadata["schema_version"], "1.2")
        self.assertEqual(metadata["commit"], "abc123")
        self.assertTrue(metadata["git_dirty"])
        self.assertEqual(metadata["cli_args"]["api_key"], "<redacted>")
        self.assertEqual(metadata["cli_args"]["unsplash_access_key"], "<redacted>")
        self.assertEqual(metadata["model_config"]["max_output_tokens"], 4096)
        self.assertEqual(len(metadata["workflow"]["prompt_sha256"]), 64)
        self.assertEqual(len(metadata["tool_schema"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
