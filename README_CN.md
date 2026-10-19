# SolveBind

[English](README.md) | 简体中文

论文 **Correct Answers, Closed Gates: SolveBind for GUI Agents at the Verification Barrier** 的代码实现。

SolveBind 将分层工具求解与基于证据的运行时监督结合起来：视觉模型提出操作，运行时将工具证据绑定到待执行动作、检查执行进度，并限制纠正和刷新次数。项目支持九类动态验证码任务以及 AndroidWorld 应用任务。

为兼容原有实现，Python 包保留内部名称 `hll`。安装后的命令为 `solvebind`，也可使用 `hll`。

## 安装

使用 Python 3.10 或更新版本。核心实现仅依赖 Pillow 和 requests：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

在本地 `.env` 中设置 `OPENAI_API_KEY`、`OPENAI_MODEL`，必要时设置 `OPENAI_BASE_URL`。模型及其接口需要支持图片输入和 Chat Completions 请求格式。Agent 与调用模型的工具共用这些配置。调用 API 需要使用你自己的账号和凭据。

验证码执行还需要 Android SDK Platform-Tools（`adb`）、一台已授权的 Android 设备或模拟器，以及 Chrome（`com.android.chrome`）。根据实际情况设置 `ADB_PATH` 和 `ANDROID_SERIAL`；连接多台设备时，通过 `--device-serial` 选择目标设备。论文中的验证码模拟器使用 Android API 36、竖屏 1080 × 2400 和 420 dpi。

## Android SDK 与验证码模拟器配置

以下步骤复用 HLL 验证码实验的模拟器配置。如果已有 Android SDK 和可用的 `agent-debug` AVD，可以直接复用。

1. 安装 Android Studio，打开 **SDK Manager**。在 **SDK Tools** 中安装 Android SDK Platform-Tools、Android Emulator 和 Android SDK Command-line Tools；在 **SDK Platforms** 中安装下方使用的 Android API 36 系统镜像。
2. 打开 **Device Manager**，创建名为 `agent-debug` 的手机 AVD。选择 **Medium Phone** 硬件配置、API 36 **Google Play** 系统镜像和竖屏方向。验证码实验配置为 1080 × 2400、420 dpi、4 核 CPU、2048 MB 内存和 16 GB 内部存储。选择匹配的硬件配置，或创建自定义配置。Apple Silicon 使用 `arm64-v8a`；Intel/AMD 主机选择兼容的镜像架构，并在对比实验中记录实际架构。
3. 启动 AVD，完成 Chrome 首次启动时的引导，确认已安装浏览器包 `com.android.chrome`。

Android Studio 的创建界面和启动参数可参考官方 [AVD 创建指南](https://developer.android.com/studio/run/managing-avds)与[模拟器命令行指南](https://developer.android.com/studio/run/emulator-commandline)。

在终端配置 SDK 工具路径。macOS 示例：

```bash
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export ADB_PATH="$ANDROID_SDK_ROOT/platform-tools/adb"
export EMULATOR_PATH="$ANDROID_SDK_ROOT/emulator/emulator"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"
```

Linux 常见 SDK 路径为 `$HOME/Android/Sdk`；请以 Android Studio SDK Manager 显示的实际位置为准。

在一个终端列出 AVD，并启动验证码设备：

```bash
adb version
"$EMULATOR_PATH" -list-avds
"$EMULATOR_PATH" -avd agent-debug -port 5554 -no-snapshot -no-boot-anim
```

在另一个终端等待设备连接，并检查配置：

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

`sys.boot_completed` 应返回 `1`。验证码实验预期 API 为 `36`，分辨率为 `1080x2400`，密度为 `420`，并能查到 `package:com.android.chrome`。如果设备仍在启动，等待后再次检查启动状态，再运行 preflight。验证码适配器会打开本地托管的页面，并为选定的服务器端口建立 ADB reverse 转发。

两种评测使用不同的设备配置：

| 评测 | AVD | 系统镜像 | 设备接口 |
| --- | --- | --- | --- |
| HLL 动态验证码 | `agent-debug` | API 36，Google Play | ADB 与 Chrome，无需 root |
| AndroidWorld 应用任务 | `AndroidWorldAvd` | Android 13 / API 33，Google APIs | 支持 root 的 ADB，以及端口 8554 上的模拟器 gRPC |

两个启动示例都使用控制台端口 5554，因此同一时间启动其中一个。如果需要同时运行，为第二个 AVD 指定不同的偶数控制台端口，例如 5556，并选择对应的序列号 `emulator-5556`。运行 AndroidWorld 时，同时更新 `--console-port` 和 `--device-serial`，并确保 gRPC 端口与启动命令一致。

## 本地演示

仓库不附带评测图片。可以生成合成图片用于本地冒烟测试：

```bash
python -m scripts.generate_demo_assets
python -m hll --list-types
python -m hll --all-dynamic --preflight-only
python -m hll --captcha-type click_icon_dynamic --num-tasks 1 --seed 0
```

如果只需要在浏览器预览页面，无需配置模型或 Android 设备：

```bash
python -m web.captcha_page --type click_icon_dynamic --seed 0 --port 8000
```

在本机打开 `http://127.0.0.1:8000`。独立服务器默认禁用答案调试接口。

合成素材与自动生成的备用图片用于环境配置和冒烟测试，**不能复现论文的图片分布或报告分数**。正式评测时，通过 `--asset-root /path/to/images` 指定自己的素材：

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

本地图片支持 PNG、JPEG 和 WebP。可选的 Unsplash/Pexels 接入从本地环境读取凭据，演示不依赖这些服务。远程图片可能随运行时间变化。

## 验证码评测

以下命令为每类生成 10 个 episode，共 90 个；对支持难度设置的类型使用 hard 难度，干扰等级为 2，并显式设置论文中描述的执行预算。通过 `OPENAI_MODEL` 或 `--model` 指定骨干模型：

```bash
python -m hll --all-dynamic --num-tasks 10 --seed 30 \
  --difficulty hard --distraction-level 2 \
  --model-timeout 180 --max-output-tokens 4096 --timeout 1200 \
  --max-steps 32 --max-read-only-steps 4 --max-invalid-actions 2 \
  --max-ground-steps 3 --max-execute-phase-steps 24 \
  --max-corrections 1 --max-refreshes 1 \
  --asset-root /path/to/images --output-dir outputs/verification
```

其中 `30` 只是基础随机种子的示例值，不代表论文原始计分样本的种子。每个 episode 将自身索引加到基础种子上。对比实验应固定素材集合，并记录实际使用的模型、接口、随机种子和配置。

九类动态验证码为：`slider_real_dynamic`、`click_icon_dynamic`、`click_real_dynamic`、`puzzle_real_dynamic`、`pic_puzzle_dynamic`、`image_grid_dynamic`、`missing_piece_dynamic`、`logic_arithmetic_dynamic` 和 `five_line_dynamic`。

运行会在选定输出目录中保存批次汇总、运行清单、增量 episode 轨迹和截图。成功与否由环境验证决定，模型发出 `finish` 动作本身不代表任务成功。轨迹记录模型与工具用量、耗时和工作流决策。添加 `--fail-on-unsolved`，可让未完成任务的运行返回失败退出码。

在本地分析运行结果：

```bash
python -m hll.analysis outputs/verification --output-dir outputs/analysis
```

使用 `python -m hll --help` 查看全部参数。CLI 默认难度和超时面向本地使用；运行接近论文设置的实验时，应采用上方显式参数。

## AndroidWorld 安装与模拟器配置

适配器使用 AndroidWorld 官方的任务初始化、评测和清理流程。以下步骤复用 HLL 现有的 AndroidWorld 安装及本地配置指南。AndroidWorld 作为外部依赖，其源码、APK 和模拟器镜像在本地下载，不包含在本仓库中。

### 复用已有环境

如果已有 HLL 的 `androidworld` Conda 环境，可以继续使用。在 SolveBind 仓库根目录执行：

```bash
conda activate androidworld
python -m pip install -e .
python -c "import sys, android_world; print(sys.executable); print(android_world.__file__)"
python -m hll.benchmarks.androidworld --list-tasks
```

已有的 AndroidWorld 可编辑安装可能指向原 HLL 项目的 `local_deps/android_world`，这种情况可以正常使用。无需把第三方源码复制到 SolveBind，也无需重建已经初始化的 AVD。

### 创建新的 Python 环境

首次配置时使用 Conda 和 Python 3.11.8。在 SolveBind 仓库根目录执行：

```bash
conda create -n androidworld python=3.11.8 -y
conda activate androidworld
git clone https://github.com/google-research/android_world.git local_deps/android_world
git -C local_deps/android_world checkout 3e50888527ef9f29b9157ecd537e408008bb1c85
python -m pip install -r local_deps/android_world/requirements.txt
python -m pip install -e local_deps/android_world
python -m pip install -e .
```

固定提交与现有 HLL 安装使用的 AndroidWorld 版本一致。先安装其 `requirements.txt`，再安装可编辑包；该依赖文件包含非 Docker 运行所需的依赖。本地第三方源码目录已加入 Git 忽略规则。

如果尚未安装 `ffmpeg`，macOS 可执行 `brew install ffmpeg`，Ubuntu/Debian 可执行 `sudo apt install ffmpeg`。

### 创建 AndroidWorld AVD

在 Android Studio **Device Manager** 中单独创建一个 AVD：

- 硬件配置：**Pixel 6**，竖屏 1080 × 2400。
- 系统镜像：**Android 13 / Tiramisu / API 33 / Google APIs**。
- 名称：`AndroidWorldAvd`。
- 镜像架构：Apple Silicon 使用 `arm64-v8a`；其他主机选择兼容的架构。

这里应选择 Google APIs 镜像。Google Play Store 镜像无法提供 AndroidWorld 应用快照所需的 root ADB 权限。如果已有初始化完成的 `AndroidWorldAvd`，可直接进入启动步骤。

### 启动并检查模拟器

使用前文 Android SDK 部分配置的环境变量。从命令行启动，以启用模拟器 gRPC：

```bash
"$EMULATOR_PATH" \
  -avd AndroidWorldAvd \
  -port 5554 \
  -no-snapshot \
  -grpc 8554 \
  -no-boot-anim
```

每次冷启动后，在另一个终端执行：

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

等待启动完成状态返回 `1`。root 检查应显示 `uid=0`，API 等级应为 `33`，分辨率应为 `1080x2400`。如果 `adb root` 提示 production builds 不支持 root，说明镜像不符合此配置要求。gRPC 端口应与 SolveBind 运行器的 `--grpc-port` 一致。

### 新 AVD 的一次性初始化

对于新建或已清空数据的 AndroidWorld AVD，先通过上游随机代理安装应用并完成评测环境初始化。此步骤不需要模型 API：

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

后续运行复用已安装的应用和快照。仅在新建、清空或重建 AVD 后再次使用 `--perform_emulator_setup`。随机代理最终任务失败，与环境初始化错误是两种不同情况。

如果 AndroidWorld 已安装在其他目录，使用对应源码目录中的 `run.py` 执行一次性初始化。

### 本地 API 33 兼容处理

已验证的 HLL 环境针对 API 33 ARM64 镜像，对 AndroidWorld 的两个源码文件做了本地修改。已有用户可以直接复用该安装；新克隆的上游源码不包含这些修改：

- `android_world/env/device_constants.py` 中的应用快照目录改为 `/data/local/tmp/android_world/snapshots`。原路径 `/data/data/android_world/snapshots` 在本地配置的冷启动过程中会被清理。
- `android_world/env/setup_device/apps.py` 中，AudioRecorder 和 Joplin 使用 `adb_utils.launch_app(cls.app_name, env.controller)` 启动；VLC 通过 launcher 组件 `org.videolan.vlc/.StartActivity` 启动，命令为 `shell am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n org.videolan.vlc/.StartActivity`。这些操作替换了该镜像上返回状态码 251 的 `monkey` 启动调用。

如果首次配置时遇到上述冷启动或应用启动问题，在外部源码中做对应调整，再执行首次初始化。这些兼容处理属于外部环境，不改变 SolveBind Agent 或官方成功评测器。

### 运行 SolveBind

激活 `androidworld`，按前文配置本地 `.env`，并启动已经初始化的 AVD。先列出任务，再运行一个任务：

```bash
python -m hll.benchmarks.androidworld --list-tasks
GRPC_ENABLE_FORK_SUPPORT=0 \
python -m hll.benchmarks.androidworld \
  --runner captcha-harness --tasks OpenAppTaskEval --num-tasks 1 \
  --task-seed 30 --console-port 5554 --device-serial emulator-5554 --grpc-port 8554 \
  --model-timeout 600 --max-output-tokens 4096 \
  --adb-path "$ADB_PATH" --output-dir outputs/androidworld
```

默认的 `captcha-harness` 运行器使用共享监督器和官方完成评测器。AndroidWorld 专用工具保留普通应用的文本及 UI 语义。使用 `--disable-ocr` 禁用屏幕文本 OCR；使用 `--runner prompt-only` 选择可选的诊断对照入口。在 `--tasks` 后添加任务名称运行子集，省略 `--tasks` 则运行所选任务族。

在该环境中运行完整回归测试：

```bash
conda run -n androidworld python -m unittest discover -s tests -v
```

在现有本地 AndroidWorld 安装中，**185 项测试全部通过，无跳过**，任务列表命令正常加载 **116 个任务**。这些检查验证了适配器导入及模拟任务接口；端到端任务还需要正在运行的模拟器和已配置的模型。

## 代码结构

| 路径 | 用途 |
| --- | --- |
| `hll/agent.py` | 模型提示与结构化动作提议 |
| `hll/tools/` | 感知、定位、求解和交互能力 |
| `hll/state.py`、`hll/workflow.py` | 共享协议状态、待执行动作绑定、进度与恢复 |
| `hll/harness.py`、`hll/executor.py` | 受监督的调度、episode 生命周期与预算 |
| `hll/captcha/`、`web/captcha/` | Android/浏览器适配器与带交互记录的本地验证码环境 |
| `hll/benchmarks/androidworld/` | AndroidWorld 任务适配器与官方评测接入 |
| `hll/batch.py`、`hll/metrics.py`、`hll/analysis.py` | 批次采集、模型用量统计与离线诊断 |
| `tests/` | 核心回归测试与可选 AndroidWorld 测试 |
| `scripts/` | 合成演示素材生成工具 |

论文中的 Perceive / Ground / Solve / Act / Verify 表示能力职责，并不与独立模块或调用一一对应。运行时阶段为 observe、ground、execute、submit_check、recover 和 done。

## 测试

```bash
python -m unittest discover -s tests -v
```

核心测试使用模拟的模型和设备接口，以及临时生成的图片。未安装 AndroidWorld 时，会跳过依赖该包的测试。GitHub 工作流在 Python 3.10 和 3.12 上运行核心测试。

本地 ModelScope OCR 为可选功能：

```bash
python -m pip install -e '.[modelscope-ocr]'
python -m hll --captcha-type text --ocr-engine modelscope
```

安装此旧版 OCR 扩展请使用 Python 3.10 环境。它依赖受平台限制的 Torch/TensorFlow 版本，不属于核心冒烟测试流程。`--ocr-engine vlm` 使用已配置的视觉模型；自动 OCR 默认只对纯文本验证码运行启用，在动态验证码批次中默认关闭。

## 开源范围

本项目整理自现有实现，包含 SolveBind 核心运行时与任务适配器。基线仓库、内部笔记、论文稿件、图表、实验输出、凭据和已采集的图片数据集均不随项目发布。

原实验启动脚本引用了 `--workflow-ablation`，但当前 CLI 没有对应参数。因此，此版本不宣称能够完整复现论文中的六种运行时消融配置或对比表格。精确复现这些结果还需要原始评测实例、最终评测清单和对应消融实现。

真实模型与设备评测，以及可选 ModelScope 功能，需要在目标环境中另行验证。AndroidWorld 适配器回归测试已在现有本地 Conda 环境中通过，具体结果见前文。单元测试不代表论文评测分数。

## 许可证

以下保留原 MIT 版权及许可声明。完整声明直接收录于中英文 README，仓库不额外添加许可证说明文档。

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
