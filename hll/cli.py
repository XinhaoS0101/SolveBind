from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from hll.agent import CaptchaAgent
from hll.batch import BatchRunner, EpisodeSpec
from hll.captcha import AdbCaptchaEnvironment, CaptchaEvaluator
from hll.captcha.task_config import (
    DYNAMIC_CAPTCHA_TYPES,
    build_task_config,
    default_asset_root,
)
from hll.domain import Task
from hll.executor import ToolExecutor
from hll.experiment import build_reproducibility_manifest
from hll.harness import Harness, HarnessConfig
from hll.instructions import instruction_for
from hll.model import OpenAICompatibleVisionModel
from hll.metrics import PricingConfig
from hll.tools.ocr import (
    DEFAULT_DETECTION_MODEL,
    DEFAULT_RECOGNITION_MODEL,
    ModelScopeOcrEngine,
    OcrTool,
    VlmOcrEngine,
)
from hll.preflight import run_preflight
from hll.runtime_env import load_dotenv_for_cli
from hll.workflow import WorkflowConfig, WorkflowPolicy


CAPTCHA_TYPES = (
    "text",
    "slider_real",
    "slider_real_dynamic",
    "click_icon",
    "click_icon_dynamic",
    "click_real",
    "click_real_dynamic",
    "puzzle_real",
    "puzzle_real_dynamic",
    "pic_puzzle",
    "pic_puzzle_dynamic",
    "image_grid",
    "image_grid_dynamic",
    "missing_piece",
    "missing_piece_dynamic",
    "logic_arithmetic",
    "logic_arithmetic_dynamic",
    "five_line",
    "five_line_dynamic",
)


def main(argv: list[str] | None = None) -> int:
    load_dotenv_for_cli()
    args = build_parser().parse_args(argv)
    if args.list_types:
        print("\n".join(CAPTCHA_TYPES))
        return 0

    captcha_types = DYNAMIC_CAPTCHA_TYPES if args.all_dynamic else (args.captcha_type,)
    api_key = args.api_key or os.getenv("OPENAI_API_KEY", "")
    base_url = (
        args.base_url
        or os.getenv("OPENAI_BASE_URL", "")
        or os.getenv("OPENAI_API_URL", "")
        or "https://api.openai.com/v1"
    )
    asset_root = Path(args.asset_root).expanduser().resolve()
    ocr_engine_name = resolve_ocr_engine(args.ocr_engine, captcha_types)

    preflight = (
        {"ok": True, "checks": [], "errors": []}
        if args.no_preflight and not args.preflight_only
        else run_preflight(
            captcha_types,
            adb_path=args.adb_path,
            device_serial=args.device_serial,
            api_key=api_key,
            ocr_engine=ocr_engine_name,
            asset_root=asset_root,
            expected_dynamic_types=(
                args.expected_dynamic_types
                if args.all_dynamic and args.expected_dynamic_types > 0
                else None
            ),
        )
    )
    if args.preflight_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0 if preflight["ok"] else 2
    if not args.no_preflight and not preflight["ok"]:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 2
    if not api_key:
        raise SystemExit(
            "missing API key: pass --api-key, export OPENAI_API_KEY, or put OPENAI_API_KEY=... in .env"
        )

    base_seed = args.seed if args.seed is not None else secrets.randbits(31)
    pricing = PricingConfig.from_environment()
    run_label = "all_dynamic" if args.all_dynamic else args.captcha_type
    run_name = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{_slug(run_label)}"
    output_dir = Path(args.output_dir) / run_name
    specs = build_episode_specs(
        captcha_types,
        num_tasks=args.num_tasks,
        base_seed=base_seed,
        difficulty=args.difficulty,
        distraction_level=args.distraction_level,
        text_length=args.text_length,
        instruction_override=args.instruction,
        asset_root=asset_root,
        slider_image_dir=args.slider_image_dir,
        click_image_dir=args.click_image_dir,
        puzzle_image_dir=args.puzzle_image_dir,
        image_grid_dir=args.image_grid_dir,
        pic_puzzle_query=args.pic_puzzle_query,
        unsplash_access_key=args.unsplash_access_key,
    )
    run_metadata = build_run_metadata(
        args=args,
        captcha_types=captcha_types,
        base_seed=base_seed,
        base_url=base_url,
        ocr_engine_name=ocr_engine_name,
        pricing=pricing,
    )

    model = OpenAICompatibleVisionModel(
        base_url=base_url,
        api_key=api_key,
        model=args.model,
        timeout_seconds=args.model_timeout,
        max_tokens=args.max_output_tokens,
        billing_category="agent",
    )
    if ocr_engine_name == "vlm":
        ocr_model = OpenAICompatibleVisionModel(
            base_url=base_url,
            api_key=api_key,
            model=args.model,
            timeout_seconds=args.model_timeout,
            max_tokens=args.max_output_tokens,
            billing_category="ocr",
        )
        ocr_tool = OcrTool(VlmOcrEngine(ocr_model))
    elif ocr_engine_name == "modelscope":
        ocr_tool = OcrTool(ModelScopeOcrEngine())
    else:
        ocr_tool = None

    def harness_factory() -> Harness:
        environment = AdbCaptchaEnvironment(
            adb_path=args.adb_path,
            device_serial=args.device_serial,
            host=args.host,
            port=args.port,
            page_ready_timeout=args.page_ready_timeout,
            page_load_retries=args.page_load_retries,
            page_retry_interval=args.page_retry_interval,
            force_stop_browser_on_open=args.force_stop_browser_on_open,
            foreground_url_check=args.foreground_url_check,
            settle_seconds=args.settle_seconds,
        )
        return Harness(
            agent=CaptchaAgent(model, ocr_enabled=ocr_tool is not None),
            environment=environment,
            evaluator=CaptchaEvaluator(
                environment,
                poll_seconds=args.evaluator_poll_seconds,
            ),
            executor=ToolExecutor(
                environment,
                ocr_tool=ocr_tool,
                model_base_url=base_url,
                model_api_key=api_key,
                model_name=args.model,
            ),
            workflow=WorkflowPolicy(
                WorkflowConfig(
                    max_ground_steps=args.max_ground_steps,
                    max_execute_steps=args.max_execute_phase_steps,
                    max_corrections=args.max_corrections,
                    max_refreshes=args.max_refreshes,
                )
            ),
            config=HarnessConfig(
                max_steps=args.max_steps,
                max_read_only_steps=args.max_read_only_steps,
                max_invalid_actions=args.max_invalid_actions,
                timeout_seconds=args.timeout,
            ),
            metadata=run_metadata,
            pricing=pricing,
        )

    summary = BatchRunner(harness_factory, metadata=run_metadata).run(specs, output_dir)
    print(
        json.dumps(
            {
                "planned": summary["planned"],
                "completed": summary["completed"],
                "successes": summary["successes"],
                "failures": summary["failures"],
                "errors": summary["errors"],
                "base_seed": base_seed,
                "output_dir": summary["output_dir"],
                "batch_path": str((output_dir / "batch.json").resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if summary["errors"]:
        return 1
    if args.fail_on_unsolved and summary["failures"]:
        return 1
    return 0


def build_episode_specs(
    captcha_types: tuple[str, ...],
    *,
    num_tasks: int,
    base_seed: int,
    difficulty: str,
    distraction_level: int,
    text_length: int,
    instruction_override: str,
    asset_root: Path,
    slider_image_dir: str = "",
    click_image_dir: str = "",
    puzzle_image_dir: str = "",
    image_grid_dir: str = "",
    pic_puzzle_query: str = "",
    unsplash_access_key: str = "",
) -> tuple[EpisodeSpec, ...]:
    specs: list[EpisodeSpec] = []
    index = 0
    for captcha_type in captcha_types:
        for ordinal in range(1, num_tasks + 1):
            seed = base_seed + index
            sample_id = f"{index + 1:04d}_{_slug(captcha_type)}_{ordinal:04d}_seed_{seed}"
            config = build_task_config(
                captcha_type,
                difficulty=difficulty,
                distraction_level=distraction_level,
                text_length=text_length,
                seed=seed,
                asset_root=asset_root,
                slider_image_dir=slider_image_dir or None,
                click_image_dir=click_image_dir or None,
                puzzle_image_dir=puzzle_image_dir or None,
                image_grid_dir=image_grid_dir or None,
                pic_puzzle_query=pic_puzzle_query or None,
                unsplash_access_key=unsplash_access_key or None,
            )
            config["sample_id"] = sample_id
            click_count = int(config.get("click_count", 3) or 3)
            specs.append(
                EpisodeSpec(
                    sample_id=sample_id,
                    seed=seed,
                    task=Task(
                        captcha_type=captcha_type,
                        instruction=instruction_override
                        or instruction_for(
                            captcha_type,
                            length=text_length,
                            click_count=click_count,
                            distraction_level=distraction_level,
                        ),
                        config=config,
                    ),
                )
            )
            index += 1
    return tuple(specs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hll",
        description="Run one or more CAPTCHAs and collect isolated trajectories.",
    )
    parser.add_argument("--list-types", action="store_true")
    parser.add_argument("--captcha-type", choices=CAPTCHA_TYPES, default="text")
    parser.add_argument(
        "--all-dynamic",
        action="store_true",
        help="run every dynamic CAPTCHA type; --num-tasks applies per type",
    )
    parser.add_argument(
        "--num-tasks",
        type=_positive_int,
        default=1,
        help="number of episodes per selected CAPTCHA type",
    )
    parser.add_argument("--seed", type=int, default=None, help="base seed; each episode adds one")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--difficulty", choices=("easy", "normal", "hard"), default="normal")
    parser.add_argument("--distraction-level", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--text-length", type=_positive_int, default=4)
    parser.add_argument("--asset-root", default=str(default_asset_root()))
    parser.add_argument("--slider-image-dir", default="", help="override image dir for slider_real_dynamic")
    parser.add_argument("--click-image-dir", default="", help="override image dir for click_real_dynamic")
    parser.add_argument("--puzzle-image-dir", default="", help="override image dir for puzzle_real_dynamic")
    parser.add_argument("--image-grid-dir", default="", help="override image dir for image_grid_dynamic")
    parser.add_argument("--pic-puzzle-query", default="", help="Unsplash query for pic_puzzle_dynamic")
    parser.add_argument("--unsplash-access-key", default="", help="Unsplash access key for pic_puzzle_dynamic and image_grid_dynamic")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o"))
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model-timeout", type=float, default=120.0)
    parser.add_argument(
        "--max-output-tokens",
        type=_positive_int,
        default=int(os.getenv("HLL_MODEL_MAX_TOKENS", "4096") or 4096),
        help="maximum visible+reasoning completion tokens for each model request",
    )
    parser.add_argument(
        "--ocr-engine",
        choices=("auto", "vlm", "modelscope", "off"),
        default=os.getenv("HLL_OCR_ENGINE", "auto"),
        help="auto enables OCR only for text-only runs, preferring cached local ModelScope OCR",
    )
    parser.add_argument("--adb-path", default=os.getenv("ADB_PATH", "adb"))
    parser.add_argument("--device-serial", default=os.getenv("ANDROID_SERIAL", ""))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--page-ready-timeout", type=float, default=20.0)
    parser.add_argument("--page-load-retries", type=int, default=2)
    parser.add_argument("--page-retry-interval", type=float, default=1.0)
    parser.add_argument(
        "--no-force-stop-browser",
        action="store_false",
        dest="force_stop_browser_on_open",
        default=True,
        help="do not force-stop common Android browsers before opening the CAPTCHA URL",
    )
    parser.add_argument(
        "--no-foreground-url-check",
        action="store_false",
        dest="foreground_url_check",
        default=True,
        help="skip accessibility-text confirmation that the browser is on the expected URL",
    )
    parser.add_argument("--settle-seconds", type=float, default=0.8)
    parser.add_argument("--evaluator-poll-seconds", type=float, default=0.5)
    parser.add_argument("--max-steps", type=_positive_int, default=32)
    parser.add_argument("--max-read-only-steps", type=int, default=4)
    parser.add_argument("--max-invalid-actions", type=int, default=2)
    parser.add_argument("--max-ground-steps", type=_positive_int, default=3)
    parser.add_argument("--max-execute-phase-steps", type=_positive_int, default=24)
    parser.add_argument("--max-corrections", type=_positive_int, default=1)
    parser.add_argument("--max-refreshes", type=_positive_int, default=1)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument(
        "--expected-dynamic-types",
        type=int,
        default=int(os.getenv("HLL_EXPECTED_DYNAMIC_TYPES", "0") or 0),
        help="when --all-dynamic is used, fail preflight if the registered dynamic task count differs",
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--no-preflight", action="store_true")
    parser.add_argument("--fail-on-unsolved", action="store_true")
    return parser


def resolve_ocr_engine(requested: str, captcha_types: tuple[str, ...]) -> str:
    if requested != "auto":
        return requested
    if captcha_types != ("text",):
        return "off"
    return "modelscope" if local_modelscope_ocr_available() else "vlm"


def local_modelscope_ocr_available() -> bool:
    if importlib.util.find_spec("modelscope") is None:
        return False
    hub = Path.home() / ".cache" / "modelscope" / "hub"
    return all(
        (hub / Path(*model_id.split("/"))).is_dir()
        for model_id in (DEFAULT_DETECTION_MODEL, DEFAULT_RECOGNITION_MODEL)
    )


def build_run_metadata(
    *,
    args: argparse.Namespace,
    captcha_types: tuple[str, ...],
    base_seed: int,
    base_url: str,
    ocr_engine_name: str,
    pricing: PricingConfig | None = None,
) -> dict[str, object]:
    redacted_args = {
        key: (
            "<redacted>"
            if key in {"api_key", "unsplash_access_key"} and value
            else value
        )
        for key, value in vars(args).items()
    }
    metadata: dict[str, object] = {
        "schema_version": "1.2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": _git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git_value("rev-parse", "HEAD"),
        "git_dirty": bool(_git_value("status", "--porcelain")),
        "model": args.model,
        "base_url": base_url,
        "captcha_types": list(captcha_types),
        "dynamic_type_count": len(captcha_types) if args.all_dynamic else 0,
        "base_seed": base_seed,
        "difficulty": args.difficulty,
        "distraction_level": args.distraction_level,
        "ocr_engine": ocr_engine_name,
        "model_config": {
            "model": args.model,
            "base_url": base_url,
            "timeout_seconds": args.model_timeout,
            "max_output_tokens": args.max_output_tokens,
            "ocr_engine": ocr_engine_name,
        },
        "pricing": (pricing or PricingConfig()).to_dict(),
        "workflow_config": {
            "max_ground_steps": args.max_ground_steps,
            "max_execute_steps": args.max_execute_phase_steps,
            "max_corrections": args.max_corrections,
            "max_refreshes": args.max_refreshes,
        },
        "cli_args": redacted_args,
    }
    metadata.update(build_reproducibility_manifest())
    return metadata


def _git_value(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "run"
