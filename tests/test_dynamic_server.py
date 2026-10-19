import importlib.util
import random
import unittest
import tempfile
from pathlib import Path
from scripts.generate_demo_assets import generate_assets

from hll.captcha.task_config import DYNAMIC_CAPTCHA_TYPES, build_task_config


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
class DynamicServerTests(unittest.TestCase):
    def test_image_grid_generation_is_seed_deterministic(self):
        from web.captcha.image_grid_captcha import ImageGridCaptcha

        first = ImageGridCaptcha(_generation_seed=12345)
        second = ImageGridCaptcha(_generation_seed=12345)

        self.assertEqual(first.generate(), second.generate())
        self.assertEqual(first._tiles_b64, second._tiles_b64)

    def test_every_dynamic_type_generates_a_behavior_page(self):
        from web.captcha_page import _create_captcha_factory

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        asset_root = Path(directory.name)
        generate_assets(asset_root)
        for index, captcha_type in enumerate(DYNAMIC_CAPTCHA_TYPES):
            with self.subTest(captcha_type=captcha_type):
                random.seed(9000 + index)
                config = build_task_config(
                    captcha_type,
                    difficulty="normal",
                    distraction_level=0,
                    text_length=4,
                    seed=9000 + index,
                    asset_root=asset_root,
                )
                captcha = _create_captcha_factory(captcha_type, config)()
                page = captcha.render_full_page()
                self.assertIn('id="captcha-form"', page)
                self.assertIn("__captchaBuildDynamicPayload", page)


if __name__ == "__main__":
    unittest.main()
