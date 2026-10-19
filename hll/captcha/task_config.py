from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


DYNAMIC_CAPTCHA_TYPES = (
    "slider_real_dynamic",
    "click_icon_dynamic",
    "click_real_dynamic",
    "puzzle_real_dynamic",
    "pic_puzzle_dynamic",
    "image_grid_dynamic",
    "missing_piece_dynamic",
    "logic_arithmetic_dynamic",
    "five_line_dynamic",
)

ASSET_SUBDIRECTORIES = {
    "slider_real": "slider",
    "slider_real_dynamic": "slider",
    "click_real": "click",
    "click_real_dynamic": "click",
    "puzzle_real": "puzzle",
    "puzzle_real_dynamic": "puzzle",
    "image_grid": "image_grid",
    "image_grid_dynamic": "image_grid",
}

DYNAMIC_CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "slider_real_dynamic": {
        "description": "Drag the slider to match the gap position.",
        "difficulty": True,
    },
    "click_icon_dynamic": {
        "click_count": 3,
        "description": "Click on the icons in the order shown above.",
    },
    "click_real_dynamic": {
        "click_count": 3,
        "description": "Click on the characters in the order shown above.",
    },
    "puzzle_real_dynamic": {
        "description": "Drag the puzzle piece to complete the image.",
        "difficulty": True,
    },
    "pic_puzzle_dynamic": {
        "title": "Picture Puzzle Verification",
        "description": "Swap the incorrect tiles to restore the image.",
        "difficulty": True,
    },
    "image_grid_dynamic": {
        "title": "Image Verification",
        "description": "Select all images matching the given category.",
        "difficulty": True,
    },
    "missing_piece_dynamic": {
        "title": "Missing Piece Verification",
        "description": "Select the correct piece to complete the image.",
        "difficulty": True,
    },
    "logic_arithmetic_dynamic": {
        "title": "Logic and Arithmetic Verification",
        "description": "Solve the current logic or arithmetic challenge, then click Verify.",
    },
    "five_line_dynamic": {
        "title": "Five-in-a-row puzzle",
        "description": "Move one piece to form five in a row, then click Verify.",
    },
}


def default_asset_root() -> Path:
    return Path(__file__).resolve().parents[2] / "web" / "captcha" / "images"


def build_task_config(
    captcha_type: str,
    *,
    difficulty: str,
    distraction_level: int,
    text_length: int,
    seed: int,
    asset_root: Path | None = None,
    slider_image_dir: str | None = None,
    click_image_dir: str | None = None,
    puzzle_image_dir: str | None = None,
    image_grid_dir: str | None = None,
    pic_puzzle_query: str | None = None,
    unsplash_access_key: str | None = None,
) -> dict[str, Any]:


    config: dict[str, Any] = {
        "seed": int(seed),
    }
    if distraction_level > 0:
        config["distraction_level"] = int(distraction_level)
    if captcha_type == "text":
        config["length"] = int(text_length)

    dynamic_defaults = DYNAMIC_CONFIG_DEFAULTS.get(captcha_type)
    if dynamic_defaults:
        for key, value in dynamic_defaults.items():
            if key == "difficulty":
                if value:
                    config["difficulty"] = difficulty
                continue
            config[key] = value

    if captcha_type == "pic_puzzle_dynamic" and pic_puzzle_query:
        config["unsplash_query"] = pic_puzzle_query

    if captcha_type in {"pic_puzzle_dynamic", "image_grid_dynamic"} and unsplash_access_key:
        config["unsplash_access_key"] = unsplash_access_key

    subdirectory = ASSET_SUBDIRECTORIES.get(captcha_type)
    if subdirectory:
        override = {
            "slider_real": slider_image_dir,
            "slider_real_dynamic": slider_image_dir,
            "click_real": click_image_dir,
            "click_real_dynamic": click_image_dir,
            "puzzle_real": puzzle_image_dir,
            "puzzle_real_dynamic": puzzle_image_dir,
            "image_grid": image_grid_dir,
            "image_grid_dynamic": image_grid_dir,
        }.get(captcha_type)
        config["image_dir"] = override or str((asset_root or default_asset_root()) / subdirectory)
    return config


def required_asset_directories(
    captcha_types: Iterable[str],
    *,
    asset_root: Path | None = None,
) -> dict[str, Path]:
    root = asset_root or default_asset_root()
    return {
        captcha_type: root / ASSET_SUBDIRECTORIES[captcha_type]
        for captcha_type in captcha_types
        if captcha_type in ASSET_SUBDIRECTORIES
    }
