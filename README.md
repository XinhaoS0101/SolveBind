# SolveBind

English | [简体中文](README_CN.md)

Code for **Correct Answers, Closed Gates: SolveBind for GUI Agents at the Verification Barrier**.

SolveBind combines hierarchical tool-based solving with evidence-grounded runtime supervision. A vision model proposes operations; the runtime binds tool evidence to pending actions, checks execution progress, and limits correction and refresh attempts. Adapters support nine dynamic verification families and AndroidWorld application tasks.

The Python package retains the internal name `hll` for compatibility with the original implementation. The installed command is `solvebind` (also available as `hll`).

## Installation

Use Python 3.10 or newer. Core installation needs only Pillow and requests:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Set `OPENAI_API_KEY`, `OPENAI_MODEL`, and, if needed, `OPENAI_BASE_URL` in your local `.env`. The selected model and endpoint must support image inputs and the Chat Completions request format. Both the agent and model-backed tools use these settings. API calls require your own account and credentials.

CAPTCHA execution also requires Android SDK platform tools (`adb`), one authorized Android device or emulator, and Chrome (`com.android.chrome`). Set `ADB_PATH` and `ANDROID_SERIAL` if needed. With multiple devices, select one using `--device-serial`. For the paper verification setup, the emulator used Android API 36, portrait 1080 × 2400, and 420 dpi.

## Android SDK and CAPTCHA emulator setup

These steps carry over the HLL emulator setup used for the verification experiments. If you already have an Android SDK and a working `agent-debug` AVD, reuse them.

1. Install Android Studio and open **SDK Manager**. Under **SDK Tools**, install Android SDK Platform-Tools, Android Emulator, and Android SDK Command-line Tools. Under **SDK Platforms**, install the Android API 36 system image used below.
2. Open **Device Manager** and create a phone AVD named `agent-debug`. Select the **Medium Phone** hardware profile, an API 36 **Google Play** system image and portrait orientation. The verification setup uses a 1080 × 2400 display, 420 dpi, 4 CPU cores, 2048 MB RAM and 16 GB internal storage. Choose a matching hardware profile or configure a custom profile. On Apple Silicon, use `arm64-v8a`; on Intel/AMD hosts, choose a compatible image architecture and record it for comparisons.
3. Boot the AVD and finish Chrome's first-run screens. Verify that the browser package `com.android.chrome` is installed.

See the official [AVD creation guide](https://developer.android.com/studio/run/managing-avds) and [emulator command-line guide](https://developer.android.com/studio/run/emulator-commandline) for the Android Studio dialogs and launch options.

Configure SDK tools in your shell. For macOS:

```bash
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export ADB_PATH="$ANDROID_SDK_ROOT/platform-tools/adb"
export EMULATOR_PATH="$ANDROID_SDK_ROOT/emulator/emulator"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"
```

On Linux, the usual SDK location is `$HOME/Android/Sdk`; use the actual location shown by Android Studio's SDK Manager.

List available AVDs and start the CAPTCHA device in one terminal:

```bash
adb version
"$EMULATOR_PATH" -list-avds
"$EMULATOR_PATH" -avd agent-debug -port 5554 -no-snapshot -no-boot-anim
```

In a second terminal, wait for the device and check its configuration:

```bash
adb devices -l
adb -s emulator-5554 wait-for-device
adb -s emulator-5554 shell getprop sys.boot_completed
adb -s emulator-5554 shell getprop ro.build.version.sdk
adb -s emulator-5554 shell wm size
adb -s emulator-5554 shell wm density
adb -s emulator-5554 shell pm list packages com.android.chrome
export ANDROID_SERIAL=emulator-5554
```

`sys.boot_completed` should return `1`. The verification setup expects API `36`, size `1080x2400`, density `420`, and `package:com.android.chrome`. If boot is still in progress, wait and repeat the boot-completion check before running preflight. The CAPTCHA adapter opens the locally hosted page and establishes ADB reverse forwarding for the selected server port.

There are two distinct device setups:

| Evaluation | AVD | System image | Device interface |
| --- | --- | --- | --- |
| HLL dynamic verification | `agent-debug` | API 36, Google Play | ADB and Chrome; no root requirement |
| AndroidWorld application tasks | `AndroidWorldAvd` | Android 13 / API 33, Google APIs | Root-capable ADB and emulator gRPC on port 8554 |

Both launch examples use console port 5554, so run one at a time. To keep both running, assign the second AVD a different even console port, such as 5556, and select its matching serial `emulator-5556`. For AndroidWorld, update both `--console-port` and `--device-serial`, and keep its gRPC port consistent with the launch command.

## Local demonstration

The repository does not bundle evaluation images. Generate synthetic image fixtures for a local smoke test:

```bash
python -m scripts.generate_demo_assets
python -m hll --list-types
python -m hll --all-dynamic --preflight-only
python -m hll --captcha-type click_icon_dynamic --num-tasks 1 --seed 0
```

For a browser-only preview without a model or Android device:

```bash
python -m web.captcha_page --type click_icon_dynamic --seed 0 --port 8000
```

Open `http://127.0.0.1:8000` locally. The standalone server disables the answer-debug endpoint.

Synthetic fixtures and generated fallback images are for setup and smoke tests. They do **not** reproduce the paper's image distribution or reported scores. Supply your own evaluation assets using `--asset-root /path/to/images`:

```text
images/
├── slider/                # background images
├── click/                 # background images
├── puzzle/                # background images
└── image_grid/
    ├── cats/              # semantically matching category images
    ├── dogs/
    ├── cars/
    └── ...                # labels defined in web/captcha/image_grid_captcha.py
```

Local images use PNG, JPEG or WebP. Optional Unsplash/Pexels integrations use credentials from your local environment and are not required for the demo. Remote images can change across runs.

## Verification evaluation

The following command requests 10 episodes per family (90 total), with hard difficulty where supported, distraction level 2, and the execution limits described in the paper. Choose your backbone through `OPENAI_MODEL` or `--model`:

```bash
python -m hll --all-dynamic --num-tasks 10 --seed 30 \
  --difficulty hard --distraction-level 2 \
  --model-timeout 180 --max-output-tokens 4096 --timeout 1200 \
  --max-steps 32 --max-read-only-steps 4 --max-invalid-actions 2 \
  --max-ground-steps 3 --max-execute-phase-steps 24 \
  --max-corrections 1 --max-refreshes 1 \
  --asset-root /path/to/images --output-dir outputs/verification
```

Here `30` is an example base seed, not a claim that these are the original scored instances. Each episode adds its index to the base seed. Use a fixed asset collection and record the actual model, endpoint, seeds and configuration when comparing runs.

The nine dynamic types are `slider_real_dynamic`, `click_icon_dynamic`, `click_real_dynamic`, `puzzle_real_dynamic`, `pic_puzzle_dynamic`, `image_grid_dynamic`, `missing_piece_dynamic`, `logic_arithmetic_dynamic`, and `five_line_dynamic`.

Runs write batch summaries, manifests, incremental episode traces and screenshots under the selected output directory. Success is determined by environment verification. A model's `finish` action alone does not establish success. Model/tool usage, latency and workflow decisions are recorded in the traces. To return a failing exit code for unsolved tasks, add `--fail-on-unsolved`.

Analyze a run locally:

```bash
python -m hll.analysis outputs/verification --output-dir outputs/analysis
```

Use `python -m hll --help` for all supported arguments. Default CLI difficulty and timeouts are intended for local use; the explicit settings above are needed for paper-style runs.

## AndroidWorld installation and emulator setup

The adapter uses AndroidWorld's official task initialization, evaluator and cleanup. The following setup is adapted from HLL's existing AndroidWorld installation and local-configuration guides. AndroidWorld remains an external dependency; its source, APKs and emulator images are downloaded locally rather than included in this repository.

### Reuse an existing environment

If you already have the HLL `androidworld` Conda environment, keep using it. From the SolveBind repository root:

```bash
conda activate androidworld
python -m pip install -e .
python -c "import sys, android_world; print(sys.executable); print(android_world.__file__)"
python -m hll.benchmarks.androidworld --list-tasks
```

An existing editable AndroidWorld installation may point to the original HLL `local_deps/android_world` checkout; this is valid. There is no need to copy that third-party checkout into SolveBind or rebuild an initialized AVD.

### Fresh Python environment

For a fresh setup, use Conda and Python 3.11.8. Run these commands from the SolveBind repository root:

```bash
conda create -n androidworld python=3.11.8 -y
conda activate androidworld
git clone https://github.com/google-research/android_world.git local_deps/android_world
git -C local_deps/android_world checkout 3e50888527ef9f29b9157ecd537e408008bb1c85
python -m pip install -r local_deps/android_world/requirements.txt
python -m pip install -e local_deps/android_world
python -m pip install -e .
```

This commit matches the AndroidWorld checkout used by the existing HLL installation. Install its `requirements.txt` before the editable package; the dependency file includes requirements for non-Docker execution. The local checkout is ignored by Git.

Install `ffmpeg` if it is absent: `brew install ffmpeg` on macOS, or `sudo apt install ffmpeg` on Ubuntu/Debian.

### Create the AndroidWorld AVD

In Android Studio **Device Manager**, create a separate AVD with:

- Hardware profile: **Pixel 6**, portrait 1080 × 2400.
- System image: **Android 13 / Tiramisu / API 33 / Google APIs**.
- Name: `AndroidWorldAvd`.
- Image architecture: `arm64-v8a` on Apple Silicon; use a compatible architecture on other hosts.

Choose the Google APIs image for this setup. A Google Play Store image cannot provide the root ADB access required by AndroidWorld's application snapshots. Existing initialized `AndroidWorldAvd` users can proceed directly to startup.

### Start and check the emulator

Use the SDK environment variables from the earlier Android SDK section. Start from the command line so the emulator exposes gRPC:

```bash
"$EMULATOR_PATH" \
  -avd AndroidWorldAvd \
  -port 5554 \
  -no-snapshot \
  -grpc 8554 \
  -no-boot-anim
```

After every cold boot, run in another terminal:

```bash
adb devices -l
adb -s emulator-5554 wait-for-device
adb -s emulator-5554 shell getprop sys.boot_completed
adb -s emulator-5554 root
adb -s emulator-5554 wait-for-device
adb -s emulator-5554 shell id
adb -s emulator-5554 shell getprop ro.build.version.sdk
adb -s emulator-5554 shell wm size
```

Wait until boot completion returns `1`. The root check should show `uid=0`, the API level should be `33`, and the display should be `1080x2400`. An `adb root` error about production builds indicates an unsuitable image. The gRPC port must match `--grpc-port` in the SolveBind runner.

### Initialize a new AVD once

For a new or wiped AndroidWorld AVD, install its applications and create the evaluation setup once using the upstream random agent. This setup does not require a model API:

```bash
GRPC_ENABLE_FORK_SUPPORT=0 \
python local_deps/android_world/run.py \
  --suite_family=android_world \
  --agent_name=random_agent \
  --perform_emulator_setup \
  --tasks=OpenAppTaskEval \
  --n_task_combinations=1 \
  --adb_path="$ADB_PATH" \
  --console_port=5554 \
  --output_path=outputs/androidworld_setup
```

Subsequent runs reuse the initialized applications and snapshots. Repeat `--perform_emulator_setup` only after creating, wiping or rebuilding the AVD. A random-agent task failure is distinct from an environment initialization error.

If AndroidWorld is already installed in another directory, use that checkout's `run.py` for the one-time initialization command.

### Local API 33 compatibility notes

The validated HLL installation includes two local AndroidWorld source-file changes for its API 33 ARM64 image. Existing users can reuse that installation. A fresh upstream checkout does not include these changes:

- In `android_world/env/device_constants.py`, the application snapshot directory is `/data/local/tmp/android_world/snapshots`; the original `/data/data/android_world/snapshots` was cleared on cold boot in the local setup.
- In `android_world/env/setup_device/apps.py`, AudioRecorder and Joplin are started with `adb_utils.launch_app(cls.app_name, env.controller)`. VLC is started through its launcher component `org.videolan.vlc/.StartActivity`, using `shell am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n org.videolan.vlc/.StartActivity`. These replace `monkey` launch calls that returned status 251 on that image.

If those cold-boot or application-launch failures occur in a fresh checkout, apply the corresponding adjustments before rerunning first-time initialization. The compatibility changes belong to the external environment and do not alter the SolveBind agent or official success evaluator.

### Run SolveBind

Activate `androidworld`, configure your local `.env` as described above, and start the initialized AVD. First list the tasks, then run one:

```bash
python -m hll.benchmarks.androidworld --list-tasks
GRPC_ENABLE_FORK_SUPPORT=0 \
python -m hll.benchmarks.androidworld \
  --runner captcha-harness --tasks OpenAppTaskEval --num-tasks 1 \
  --task-seed 30 --console-port 5554 --device-serial emulator-5554 --grpc-port 8554 \
  --model-timeout 600 --max-output-tokens 4096 \
  --adb-path "$ADB_PATH" --output-dir outputs/androidworld
```

The default `captcha-harness` runner uses the shared supervisor and official completion evaluator. AndroidWorld-specific tools preserve general application text and UI semantics. `--disable-ocr` disables its screen-text OCR; `--runner prompt-only` selects the optional diagnostic comparison. Add task names after `--tasks` to run a subset, or omit `--tasks` to run the selected family.

Run the full regression suite in this environment:

```bash
conda run -n androidworld python -m unittest discover -s tests -v
```

With the existing local AndroidWorld installation, all **185 tests passed with no skips**, and the task-list command loaded **116 tasks**. These checks validate adapter imports and mocked task interfaces; an end-to-end task additionally requires a running emulator and a configured model.

## Source layout

| Path | Purpose |
| --- | --- |
| `hll/agent.py` | Model prompting and structured action proposals |
| `hll/tools/` | Perception, grounding, solving and interaction capabilities |
| `hll/state.py`, `hll/workflow.py` | Shared protocol state, pending-action binding, progress and recovery |
| `hll/harness.py`, `hll/executor.py` | Mediated dispatch, episode lifecycle and budgets |
| `hll/captcha/`, `web/captcha/` | Android/browser adapter and instrumented local verification environment |
| `hll/benchmarks/androidworld/` | AndroidWorld task adapter and official evaluation integration |
| `hll/batch.py`, `hll/metrics.py`, `hll/analysis.py` | Batch collection, model accounting and offline diagnostics |
| `tests/` | Core regression tests and optional AndroidWorld tests |
| `scripts/` | Synthetic demo-asset setup |

The paper's Perceive / Ground / Solve / Act / Verify roles describe capability responsibilities. They do not map one-to-one to separate modules or calls; runtime stages are observe, ground, execute, submit_check, recover and done.

## Tests

```bash
python -m unittest discover -s tests -v
```

Core tests use mocked model/device interfaces and generated temporary images. AndroidWorld-dependent tests are skipped when that optional package is absent. The GitHub workflow runs the core suite on Python 3.10 and 3.12.

Local ModelScope OCR is optional:

```bash
python -m pip install -e '.[modelscope-ocr]'
python -m hll --captcha-type text --ocr-engine modelscope
```

Use a Python 3.10 environment for this legacy OCR extra. It has platform-specific Torch/TensorFlow requirements and is not part of the core smoke-test path. `--ocr-engine vlm` uses the configured vision model; automatic OCR is enabled for text-only runs and disabled for dynamic batches by default.

## Release scope

This is a cleaned release of the supplied implementation. It includes SolveBind's core runtime and task adapters. It excludes baseline repositories, internal notes, manuscripts, figures, recorded experiment outputs, credentials and collected image datasets.

The supplied experimental launcher references `--workflow-ablation`, but the supplied CLI has no such argument. Consequently, this release does not advertise a complete reproduction of the paper's six runtime-ablation configurations or comparative tables. The original benchmark instances, final evaluation manifests and corresponding ablation implementation are needed to reproduce those results exactly.

Real model/device evaluations and the optional ModelScope stack must be validated separately in the target environment. The AndroidWorld adapter regression suite has been verified in the existing local Conda environment as described above. No paper scores are claimed from the unit tests.

## License

The original MIT copyright and permission notice is retained below. It is included in both READMEs so this repository has no additional license documentation files.

```text
MIT License

Copyright (c) 2026 cyChen2003

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
