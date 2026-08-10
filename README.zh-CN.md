# LinguaRelay

面向 Windows 的低延迟桌面实时翻译字幕工具，并预留本地大模型或 API 修正层。

> 当前状态：M2 中、日、英、韩实时语音识别已经完成；即时翻译属于下一个里程碑，项目暂不适合生产使用。

[English](README.md) · [架构](docs/ARCHITECTURE.md) · [路线图](docs/ROADMAP.zh-CN.md)

## 产品目标

LinguaRelay 在后台运行，通过 WASAPI 回环捕获指定扬声器输出，在屏幕上显示一个轻量置顶字幕窗。首条字幕使用低延迟链路；可选的大模型在不阻塞实时字幕的前提下修正已完成字幕或历史记录。

初版范围调整为：

- Windows 10/11；
- 支持简体中文 `zh`、日语 `ja`、英语 `en`、韩语 `ko`；
- 源语言和目标语言均由用户手动选择，支持四种语言之间全部 12 个互译方向；
- 暂不启用自动语言检测；
- M2 使用多语言 `faster-whisper` 实现实时识别；
- M3 使用按语言方向选择模型的翻译路由，不再固定英中模型；
- 大模型修正默认关闭，在 M4 以异步方式接入；
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
- 每 320 ms 生成重叠窗口，在线能量端点检测，final 使用 Silero VAD；
- partial 区分稳定与未稳定文本，连续假设提交稳定前缀；
- 推理和事件队列均有固定上限，过载时替换旧 partial，保留 final；
- 提供 CPU/CUDA 诊断、音频文件识别、WASAPI 实时识别和可复现的 FLEURS 四语基准。

## 快速开始

建议使用 Python 3.11：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,audio,asr]"
# NVIDIA Windows 机器还需要 CUDA 12 用户态运行库：
python -m pip install -e ".[gpu]"
lingua-relay doctor
lingua-relay asr-doctor --load
lingua-relay languages
lingua-relay audio-devices
lingua-relay audio-monitor --seconds 10
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
