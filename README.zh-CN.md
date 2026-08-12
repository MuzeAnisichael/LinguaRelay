# LinguaRelay

面向 Windows 的低延迟桌面实时翻译字幕工具，并预留本地大模型或 API 修正层。

> 当前状态：v0.1.1 是 Windows x64 Alpha 维护版，改进了模型就绪反馈、增量字幕、标点断句、可拖放缩放悬浮窗、模型复用、历史浏览和应用图标。

[English](README.md) · [架构](docs/ARCHITECTURE.md) · [路线图](docs/ROADMAP.zh-CN.md) · [v0.1.1 发布说明](docs/releases/v0.1.1.md) · [隐私说明](docs/PRIVACY.zh-CN.md)

## 安装 v0.1.1

从 [GitHub Releases](https://github.com/MuzeAnisichael/LinguaRelay/releases/tag/v0.1.1) 下载 Windows x64 安装包，使用 `SHA256SUMS.txt` 校验后运行。安装器会预检 LocalAppData；首次启动还会扫描程序旁、当前目录、`LINGUA_RELAY_MODEL_DIR` 指定目录和上次选择的目录，也可手动选择模型目录。任何现有模型在使用前都会按固定清单校验 SHA-256。模型文件与 v0.1.0 相同，升级用户不需要重复下载。

首版尚未进行 Authenticode 代码签名，Windows 可能显示“未知发布者”或 SmartScreen 提示。继续前请阅读发布说明、隐私说明和威胁模型。

## 产品目标

LinguaRelay 在后台运行，通过 WASAPI 回环捕获指定扬声器输出，在屏幕上显示一个轻量置顶字幕窗。首条字幕使用低延迟链路；可选的大模型在不阻塞实时字幕的前提下修正已完成字幕或历史记录。

初版范围调整为：

- Windows 10/11；
- 支持简体中文 `zh`、日语 `ja`、英语 `en`、韩语 `ko`；
- 源语言和目标语言均由用户手动选择，支持四种语言之间全部 12 个互译方向；
- 暂不启用自动语言检测；
- M2 使用多语言 `faster-whisper` 实现实时识别；
- M3 使用按语言方向选择模型的翻译路由，不再固定英中模型；
- 大模型修正默认关闭，支持本地和 HTTPS OpenAI-compatible 异步 provider；
- 默认不保存原始音频，字幕历史仅保存在本地且可关闭。

## 已完成的 M1 音频能力

- 枚举 WASAPI 回环设备，使用稳定的设备名称选择器，并可将选择保存到 `config.toml`；
- 可跟随系统默认输出设备切换，也可在指定设备中断后自动重连；
- 回调式捕获 16-bit PCM，流式降为单声道，并通过 SoXR 重采样到 16 kHz `float32`；
- 输出固定 320 ms 音频块和单调时间戳；
- 使用有界“新数据优先”队列，过载时不会无限积累延迟；
- 没有系统声音时连续生成静音块；
- 提供 RMS/峰值音量计、丢包计数、重连计数、回环测试音和持续运行压力测试。

## 已完成的 M2 四语识别能力

- 复用并预热一个多语言 `faster-whisper-small` 模型；
- 每次识别显式传入 `zh / ja / en / ko`，不允许自动语言检测回退；
- 每 320 ms 生成重叠窗口，在线能量端点检测，final 使用 Silero VAD；连续语音优先在 6 秒后的短停顿切段，并以 10 秒为单条字幕硬上限；
- 稳定识别结果出现明确的句号、问号或感叹号后立即结束当前段；识别文本会先显示，译文完成后原位替换；
- partial 区分稳定与未稳定文本，连续假设提交稳定前缀；
- 推理和事件队列均有固定上限，过载时替换旧 partial，保留 final；
- 提供 CPU/CUDA 诊断、音频文件识别、WASAPI 实时识别和可复现的 FLEURS 四语基准。

## 已完成的 M3 即时翻译与桌面能力

- 固定版本的 M2M100 418M/CTranslate2 通过一个预热实例直接覆盖四语全部 12 个方向；
- 翻译队列有界，旧 partial 可替换而 final 不丢失，翻译失败时继续显示原文；
- 悬浮窗支持整面拖动、四边/四角缩放并持久化布局，也支持“仅显示译文”和“双语同时显示”、partial 淡化、透明度、字号与点击穿透；
- 托盘支持暂停/继续、手动源/目标语言、音频设备、显示模式、历史、导出和退出；
- JSONL 历史可导出为 JSONL、CSV 或 SRT；
- 历史窗口支持搜索、语言方向与快译/LLM 修正筛选、详情查看和复制译文；
- 已准备 PyInstaller 应用目录、独立模型包、Inno Setup 安装器定义和 GitHub 打包工作流。

## 已完成的 M4 异步大模型修正

- 托盘可选择关闭、完整句异步修正或实验性的 partial/final 实时异步修正；
- 本地 provider 只能连接回环地址，云端 OpenAI-compatible provider 必须使用 HTTPS；
- API 密钥只从环境变量读取，不写入配置、日志或字幕历史；
- 修正请求固定携带手动选择的源/目标语言、最近上下文和按方向过滤的 JSON 术语表；
- 修正队列有界，并具备超时、速率限制和熔断；断线或超时不会阻塞本地快译；
- 每条修正以追加式 `revised` 事件保存父版本、原快译、provider/model 和本地/云端范围；
- `history-revise` 可把历史修正写入一个新 JSONL 文件，原记录完整保留。

本地 OpenAI-compatible 服务的最小配置示例：

```toml
[correction]
mode = "asynchronous"
provider = "local"
endpoint = "http://127.0.0.1:8080/v1"
model = "your-local-model"
```

云端 provider 使用 `provider = "openai_compatible"` 和 HTTPS 地址，并在启动前设置
`LINGUA_RELAY_API_KEY`（或 `api_key_env` 指定的其他环境变量）。可用
`lingua-relay correction-doctor --probe` 检查配置，但不要把密钥写入 TOML。

## 快速开始

建议使用 Python 3.11：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,audio,asr,translation]"
# NVIDIA Windows 机器还需要 CUDA 12 用户态运行库：
python -m pip install -e ".[gpu]"
lingua-relay doctor
lingua-relay asr-doctor --load
lingua-relay languages
lingua-relay audio-devices
lingua-relay audio-monitor --seconds 10
lingua-relay mt-prepare
lingua-relay mt-doctor --load
lingua-relay app
```

保存一个非默认音频端点：

```powershell
lingua-relay audio-select "wasapi:设备名称"
```

低音量回环自检会通过默认输出播放约一秒测试音：

```powershell
lingua-relay audio-self-test
```

执行完整 M1 稳定性测试：

```powershell
lingua-relay audio-stress --minutes 30 --report data/m1-stress.json
```

`lingua-relay demo` 仍可运行悬浮窗演示。修改语言和音频参数前，可以把 `config.example.toml` 复制为 `config.toml`。`asr-doctor --load` 会下载并预热配置的语音模型。

实时识别必须手动指定源语言：

```powershell
lingua-relay asr-stream --language ja
lingua-relay asr-transcribe sample.wav --language ko
```

复现 M2 本机基准：

```powershell
python -m pip install -e ".[benchmark]"
python scripts/fetch_fleurs_samples.py --samples-per-language 5
lingua-relay asr-benchmark data/fleurs-m2/manifest.json `
  --device cuda --compute-type float16 `
  --sustain-audio-minutes 30 --report data/m2.json
```

## 实时链路与修正链路

```text
系统音频 -> 语音识别 -> 快速机器翻译 -> 悬浮窗
                            |
                            +-> 可选大模型修正 -> 更新悬浮窗/历史
```

实时翻译不等待大模型。即使本地模型速度不足、API 超时或网络中断，第一版字幕仍然继续工作；大模型主要处理上下文、专有名词、标点和歧义。

## 隐私提示

系统回环音频可能包含会议、消息通知或其他敏感内容。项目默认只在内存中处理音频，不落盘；若启用云端修正，字幕文本会发送给所选服务商，界面必须明确显示这一状态。API 密钥不得写入仓库。

## 开源许可

项目代码使用 [MIT License](LICENSE)。用户自行下载的模型权重继续受各自许可证约束，详见[模型选择](docs/MODELS.md)和[第三方组件](THIRD_PARTY.md)。
