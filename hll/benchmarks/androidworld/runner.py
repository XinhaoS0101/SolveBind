from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from android_world import checkpointer as checkpointer_lib
from android_world import constants, registry, suite_utils
from android_world.env import env_launcher

from hll.benchmarks.androidworld.agent import HllAndroidWorldAgent
from hll.benchmarks.androidworld.harness_adapter import run_harness_suite
from hll.model import OpenAICompatibleVisionModel
from hll.runtime_env import load_dotenv_for_cli


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv_for_cli()
    args = build_parser().parse_args(argv)
    task_registry = registry.TaskRegistry()
    family_registry = task_registry.get_registry(family=args.suite_family)
    if args.list_tasks:
        print("\n".join(sorted(family_registry)))
        return 0

    api_key = args.api_key or os.getenv("OPENAI_API_KEY", "")
    base_url = (
        args.base_url
        or os.getenv("OPENAI_BASE_URL", "")
        or os.getenv("OPENAI_API_URL", "")
        or "https://api.openai.com/v1"
    )
    if not api_key:
        raise SystemExit(
            "missing API key: pass --api-key, export OPENAI_API_KEY, or configure .env"
        )

    checkpoint_dir = (
        Path(args.checkpoint_dir).expanduser().resolve()
        if args.checkpoint_dir
        else Path(
            checkpointer_lib.create_run_directory(
                str(Path(args.output_dir).expanduser().resolve())
            )
        )
    )
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpointer_lib.IncrementalCheckpointer(str(checkpoint_dir))
    model = OpenAICompatibleVisionModel(
        base_url=base_url,
        api_key=api_key,
        model=args.model,
        timeout_seconds=args.model_timeout,
        max_tokens=args.max_output_tokens,
        billing_category=(
            "agent" if args.runner == "captcha-harness" else "androidworld_agent"
        ),
    )
    ocr_model = (
        OpenAICompatibleVisionModel(
            base_url=base_url,
            api_key=api_key,
            model=args.model,
            timeout_seconds=args.model_timeout,
            max_tokens=args.max_output_tokens,
            billing_category="ocr",
        )
        if args.runner == "captcha-harness" and args.enable_ocr
        else None
    )

    env = env_launcher.load_and_setup_env(
        console_port=args.console_port,
        emulator_setup=args.perform_emulator_setup,
        freeze_datetime=args.freeze_datetime,
        adb_path=args.adb_path,
        grpc_port=args.grpc_port,
    )
    fatal_error = ""
    try:
        suite = suite_utils.create_suite(
            family_registry,
            n_task_combinations=args.num_tasks,
            seed=args.task_seed,
            tasks=_parse_tasks(args.tasks),
            use_identical_params=args.fixed_task_seed,
        )
        suite.suite_family = args.suite_family
        if args.runner == "prompt-only":
            agent = HllAndroidWorldAgent(
                env,
                model,
                artifact_dir=checkpoint_dir / "artifacts",
                transition_pause=(
                    None if args.transition_pause < 0 else args.transition_pause
                ),
                history_limit=args.history_limit,
                max_ui_elements=args.max_ui_elements,
            )
            try:
                suite_utils.run(
                    suite,
                    agent,
                    checkpointer=checkpoint,
                    demo_mode=False,
                    process_episodes_fn=_process_episodes_with_model_fail_fast,
                )
            except _FatalModelBackendError:
                fatal_error = (
                    "model backend request failed; stopped the batch after the "
                    "first infrastructure error"
                )
        else:
            _, model_failed = run_harness_suite(
                suite,
                env=env,
                model=model,
                ocr_model=ocr_model,
                checkpointer=checkpoint,
                checkpoint_dir=checkpoint_dir,
                adb_path=args.adb_path,
                device_serial=(
                    args.device_serial or f"emulator-{args.console_port}"
                ),
                history_limit=args.history_limit,
                max_ui_elements=args.max_ui_elements,
                transition_pause=(
                    None if args.transition_pause < 0 else args.transition_pause
                ),
                max_read_only_steps=args.max_read_only_steps,
                episode_timeout=args.episode_timeout,
                model_base_url=base_url,
                model_api_key=api_key,
                model_name=args.model,
                enable_ocr=args.enable_ocr,
            )
            if model_failed:
                fatal_error = (
                    "model backend request failed; stopped the batch after the "
                    "first infrastructure error"
                )
    finally:
        env.close()

    summary = _build_summary(checkpoint.load())
    if fatal_error:
        summary["fatal_error"] = fatal_error
    summary.update(
        {
            "agent": (
                "hll_captcha_harness"
                if args.runner == "captcha-harness"
                else "hll_androidworld_prompt_only"
            ),
            "runner": args.runner,
            "model": args.model,
            "suite_family": args.suite_family,
            "task_seed": args.task_seed,
            "num_tasks_per_template": args.num_tasks,
            "ocr_enabled": bool(
                args.runner == "captcha-harness" and args.enable_ocr
            ),
            "checkpoint_dir": str(checkpoint_dir),
        }
    )
    summary_path = checkpoint_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["infrastructure_errors"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hll.benchmarks.androidworld",
        description="Evaluate the HLL structured vision agent with AndroidWorld.",
    )
    parser.add_argument("--list-tasks", action="store_true")
    parser.add_argument(
        "--runner",
        choices=("captcha-harness", "prompt-only"),
        default="captcha-harness",
        help="use the full HLL Harness or the lightweight prompt-only baseline",
    )
    parser.add_argument(
        "--suite-family",
        default=registry.TaskRegistry.ANDROID_WORLD_FAMILY,
        choices=(
            registry.TaskRegistry.ANDROID_WORLD_FAMILY,
            registry.TaskRegistry.ANDROID_FAMILY,
            registry.TaskRegistry.INFORMATION_RETRIEVAL_FAMILY,
            registry.TaskRegistry.MINIWOB_FAMILY_SUBSET,
        ),
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=None,
        help="task names separated by spaces or commas; omit to run the family",
    )
    parser.add_argument("--num-tasks", type=_positive_int, default=1)
    parser.add_argument("--task-seed", type=int, default=30)
    parser.add_argument("--fixed-task-seed", action="store_true")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5.5"))
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model-timeout", type=float, default=600.0)
    parser.add_argument("--max-output-tokens", type=_positive_int, default=4096)
    parser.add_argument("--history-limit", type=int, default=8)
    parser.add_argument("--max-ui-elements", type=_positive_int, default=120)
    parser.add_argument("--max-read-only-steps", type=int, default=8)
    parser.add_argument("--episode-timeout", type=float, default=3600.0)
    ocr_group = parser.add_mutually_exclusive_group()
    ocr_group.add_argument(
        "--enable-ocr",
        dest="enable_ocr",
        action="store_true",
        help="enable general screen-text OCR for the HLL Harness (default)",
    )
    ocr_group.add_argument(
        "--disable-ocr",
        dest="enable_ocr",
        action="store_false",
        help="disable the AndroidWorld screen-text OCR action",
    )
    parser.set_defaults(enable_ocr=True)
    parser.add_argument(
        "--transition-pause",
        type=float,
        default=-1.0,
        help="negative uses AndroidWorld auto stabilization",
    )
    parser.add_argument(
        "--adb-path",
        default=os.getenv(
            "ADB_PATH",
            str(Path.home() / "Library/Android/sdk/platform-tools/adb"),
        ),
    )
    parser.add_argument("--console-port", type=int, default=5554)
    parser.add_argument("--device-serial", default="")
    parser.add_argument("--grpc-port", type=int, default=8554)
    parser.add_argument("--perform-emulator-setup", action="store_true")
    parser.add_argument(
        "--no-freeze-datetime",
        action="store_false",
        dest="freeze_datetime",
        default=True,
    )
    parser.add_argument("--checkpoint-dir", default="")
    parser.add_argument("--output-dir", default="outputs/androidworld")
    return parser


def _parse_tasks(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    tasks = []
    for value in values:
        tasks.extend(item.strip() for item in value.split(",") if item.strip())
    return tasks or None


def _build_summary(episodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    success_key = constants.EpisodeConstants.IS_SUCCESSFUL
    exception_key = constants.EpisodeConstants.EXCEPTION_INFO
    valid = [item for item in episodes if item.get(exception_key) is None]
    successes = sum(float(item.get(success_key, 0.0) or 0.0) for item in valid)
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    model_seconds = 0.0
    tool_usage: dict[str, Any] = {
        "total_calls": 0,
        "successful_calls": 0,
        "read_only_calls": 0,
        "action_calls": 0,
        "direct_dispatches": 0,
        "results_delivered": 0,
        "read_only_followed_by_action": 0,
        "by_name": {},
    }
    for episode in episodes:
        step_data = episode.get(constants.EpisodeConstants.EPISODE_DATA, {})
        if not isinstance(step_data, Mapping):
            continue
        for item in step_data.get("model_usage", []) or []:
            if not isinstance(item, Mapping):
                continue
            for key in usage:
                usage[key] += int(item.get(key, 0) or 0)
        model_seconds += sum(
            float(value or 0.0)
            for value in (step_data.get("model_seconds", []) or [])
        )
        aux_data = episode.get(constants.EpisodeConstants.AUX_DATA, {})
        if not isinstance(aux_data, Mapping):
            continue
        episode_tools = aux_data.get("hll_tool_usage", {})
        if not isinstance(episode_tools, Mapping):
            continue
        for key in tool_usage:
            if key != "by_name":
                tool_usage[key] += int(episode_tools.get(key, 0) or 0)
        by_name = episode_tools.get("by_name", {})
        if isinstance(by_name, Mapping):
            for name, count in by_name.items():
                tool_usage["by_name"][str(name)] = (
                    int(tool_usage["by_name"].get(str(name), 0))
                    + int(count or 0)
                )
    total = len(valid)
    return {
        "planned_or_loaded": len(episodes),
        "valid_episodes": total,
        "success_sum": successes,
        "accuracy": round(successes / total, 4) if total else 0.0,
        "infrastructure_errors": len(episodes) - total,
        "model_usage": usage,
        "model_seconds": round(model_seconds, 4),
        "hll_tool_usage": tool_usage,
    }


def _process_episodes_with_model_fail_fast(
    episodes: list[dict[str, Any]],
    print_summary: bool = False,
) -> Any:
    result = suite_utils.process_episodes(episodes, print_summary=print_summary)
    _raise_on_model_backend_error(episodes)
    return result


def _raise_on_model_backend_error(episodes: Sequence[Mapping[str, Any]]) -> None:
    if not episodes:
        return
    error = episodes[-1].get(constants.EpisodeConstants.EXCEPTION_INFO)
    if error and "ModelRequestError" in str(error):
        raise _FatalModelBackendError


class _FatalModelBackendError(RuntimeError):
    pass


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed
