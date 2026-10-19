"""Generate synthetic smoke-test images, not paper evaluation assets."""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw
from web.captcha.image_grid_captcha import CATEGORIES, DISTRACTOR_QUERIES, ImageGridCaptcha


def generate_assets(output_dir: Path, seed: int = 0) -> int:
    rng = random.Random(seed)
    count = 0
    for family in ("slider", "click", "puzzle"):
        directory = output_dir / family
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(4):
            image = Image.new("RGB", (480, 320), (215, 232, 244))
            draw = ImageDraw.Draw(image)
            for _ in range(36):
                x, y = rng.randrange(440), rng.randrange(280)
                color = tuple(rng.randrange(35, 220) for _ in range(3))
                draw.rectangle((x, y, x + 40, y + 40), fill=color)
            image.save(directory / f"demo_{index:02d}.png")
            count += 1
    grid = ImageGridCaptcha(unsplash_access_key="")
    labels = sorted({item["label"] for item in CATEGORIES} | set(DISTRACTOR_QUERIES))
    for label in labels:
        directory = output_dir / "image_grid" / grid._label_to_dir_name(label)
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(4):
            image = grid._make_fallback_tile(label, True, rng)
            image.save(directory / f"demo_{index:02d}.png")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("web/captcha/images"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    count = generate_assets(args.output_dir, args.seed)
    print(f"Generated {count} demo images in {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
