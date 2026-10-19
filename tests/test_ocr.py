import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from hll.domain import Action, ActionKind, Observation
from hll.model import ModelReply
from hll.tools.ocr import (
    OcrReading,
    OcrTool,
    VlmOcrEngine,
    clamp_region,
    extract_boxed_captcha_text,
    normalize_captcha_text,
    parse_vlm_ocr_text,
)


class FakeModel:
    def complete(self, messages):
        self.messages = messages
        return ModelReply(" M9-YA. ", {"total_tokens": 12})


class BoxedModel:
    def complete(self, messages):
        self.messages = messages
        return ModelReply(r"\box{M9-YA}", {"total_tokens": 12})


class RefusalModel:
    def complete(self, messages):
        self.messages = messages
        return ModelReply("I can't help bypass a verification challenge.", {"total_tokens": 7})


class FakeOcrEngine:
    name = "fake"

    def __init__(self, text):
        self.text = text

    def recognize(self, image_path):
        return OcrReading(text=self.text, raw_text=self.text, engine=self.name)


class ParseErrorEngine:
    name = "vlm"

    def recognize(self, image_path):
        return OcrReading(
            text="",
            raw_text="I can't help bypass a verification challenge.",
            engine=self.name,
            metadata={"ocr_parse_error": "model_refusal"},
        )


class OcrTests(unittest.TestCase):
    def test_vlm_engine_preserves_raw_and_normalized_text(self):
        model = FakeModel()
        reading = VlmOcrEngine(model).recognize(Path("crop.png"))
        self.assertEqual(reading.text, "M9YA")
        self.assertEqual(reading.raw_text, " M9-YA. ")
        self.assertEqual(reading.usage["total_tokens"], 12)
        self.assertEqual(model.messages[0].image_path, "crop.png")
        self.assertIn("cropped captcha image", model.messages[0].text)
        self.assertIn("distorted characters", model.messages[0].text)
        self.assertIn("Respond with ONLY the characters", model.messages[0].text)
        self.assertNotIn(r"\box", model.messages[0].text)

    def test_vlm_engine_accepts_boxed_reply_without_prompting_for_it(self):
        model = BoxedModel()
        reading = VlmOcrEngine(model).recognize(Path("crop.png"))
        self.assertEqual(reading.text, "M9YA")
        self.assertEqual(reading.raw_text, r"\box{M9-YA}")
        self.assertNotIn(r"\box{TEXT}", model.messages[0].text)

    def test_normalize_keeps_only_alphanumeric_text(self):
        self.assertEqual(normalize_captcha_text("`A 7-B!`"), "A7B")

    def test_extract_boxed_text_from_vlm_reply(self):
        self.assertEqual(extract_boxed_captcha_text(r"The answer is \box{M9YA}."), "M9YA")
        self.assertEqual(extract_boxed_captcha_text(r"\boxed{A 7-B}"), "A7B")

    def test_extract_boxed_text_requires_box(self):
        self.assertEqual(extract_boxed_captcha_text("The CAPTCHA reads M9YA."), "")

    def test_parse_vlm_ocr_text_accepts_plain_and_boxed_replies(self):
        self.assertEqual(parse_vlm_ocr_text("GxGG"), ("GxGG", ""))
        self.assertEqual(parse_vlm_ocr_text(r"\box{A 7-B}"), ("A7B", ""))

    def test_parse_vlm_ocr_text_reports_diagnostic_failures(self):
        self.assertEqual(parse_vlm_ocr_text("EMPTY"), ("", "empty"))
        self.assertEqual(
            parse_vlm_ocr_text("Captcha Verification"),
            ("", "wrong_region_likely"),
        )
        self.assertEqual(
            parse_vlm_ocr_text("I can't help bypass a verification challenge."),
            ("", "model_refusal"),
        )
        self.assertEqual(
            parse_vlm_ocr_text("THISISFARLONGERTHANACAPTCHA", max_text_length=8),
            ("", "implausible_length"),
        )

    def test_vlm_engine_marks_refusal(self):
        reading = VlmOcrEngine(RefusalModel()).recognize(Path("crop.png"))
        self.assertEqual(reading.text, "")
        self.assertEqual(reading.metadata["ocr_parse_error"], "model_refusal")

    def test_region_is_sorted_and_clamped(self):
        region = clamp_region({"x1": 90, "y1": -2, "x2": 10, "y2": 80}, 100, 60)
        self.assertEqual(region, (10, 0, 90, 60))

    def test_ocr_tool_suppresses_overlong_canonical_action(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "screen.png"
            _write_image(image_path)
            observation = Observation(
                step=0,
                screenshot_path=str(image_path),
                width=20,
                height=20,
                instruction="solve",
                safe_state={},
            )
            action = Action(ActionKind.OCR, {"x1": 0, "y1": 0, "x2": 20, "y2": 20})

            short = OcrTool(FakeOcrEngine("A7B9"), max_suggested_text_length=8).execute(
                action,
                observation,
            )
            long = OcrTool(
                FakeOcrEngine("THISISFARLONGERTHANACAPTCHA"),
                max_suggested_text_length=8,
            ).execute(action, observation)

        self.assertIn("suggested_action", short.details)
        self.assertNotIn("suggested_action", long.details)
        self.assertEqual(long.details["ocr_text"], "")
        self.assertEqual(long.details["ocr_parse_error"], "implausible_length")
        self.assertEqual(long.details["suggested_action_suppressed"], "ocr_text_too_long")

    def test_ocr_tool_promotes_parse_error(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "screen.png"
            _write_image(image_path)
            result = OcrTool(ParseErrorEngine()).execute(
                Action(ActionKind.OCR, {"x1": 0, "y1": 0, "x2": 20, "y2": 20}),
                Observation(
                    step=1,
                    screenshot_path=str(image_path),
                    width=20,
                    height=20,
                    instruction="read captcha",
                    safe_state={},
                ),
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.details["ocr_text"], "")
        self.assertEqual(result.details["ocr_parse_error"], "model_refusal")
        self.assertEqual(result.details["engine_metadata"]["ocr_parse_error"], "model_refusal")
        self.assertIn("prompt_feedback", result.details)
        self.assertNotIn("suggested_action", result.details)


def _write_image(path):
    from PIL import Image

    Image.new("RGB", (20, 20), "white").save(path)


if __name__ == "__main__":
    unittest.main()
