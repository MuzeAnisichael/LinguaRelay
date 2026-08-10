# LinguaRelay

面向 Windows 的低延迟桌面实时翻译字幕工具，并预留本地大模型或 API 修正层。

> 当前状态：已完成架构规划和可运行的悬浮窗脚手架；音频到翻译的完整链路是下一里程碑，暂不适合生产使用。

[English](README.md) · [架构](docs/ARCHITECTURE.md) · [路线图](docs/ROADMAP.zh-CN.md)

## 初版目标

LinguaRelay 在后台运行，通过 WASAPI 回环捕获默认扬声器输出，在屏幕下方显示一个轻量、置顶、尽量不影响操作的字幕窗。

首版主动收窄范围：

- Windows 10/11；
- 手动指定源语言和目标语言，不做自动语言检测；
- 第一条语言路线为英语到简体中文；
- `faster-whisper small/int8` 负责低延迟语音识别；
- OPUS-MT 英中模型负责第一时间翻译；
- 大模型修正默认关闭，以异步方式修正已经显示的字幕或历史记录；
- 默认不保存原始音频，翻译历史仅保存在本地且可关闭。

## 为什么拆成快、慢两条链路

```text
系统音频 -> 语音识别 -> 快速机器翻译 -> 悬浮窗
                            |
                            +-> 可选大模型修正 -> 更新悬浮窗/历史
```

实时翻译不应等待大模型。即使本地模型速度不足、API 超时或网络中断，第一版字幕仍然继续工作。大模型只负责利用上下文修正专有名词、标点、歧义和历史译文。

## 快速运行悬浮窗演示

建议使用 Python 3.11：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
lingua-relay doctor
lingua-relay demo
```

演示模式不会捕获音频，也不会下载模型。开始接入真实链路前，请复制 `config.example.toml` 为 `config.toml`。

## 隐私提示

系统回环音频可能包含会议、消息通知或其他敏感内容。项目默认不保存音频；若启用云端大模型修正，字幕文本会发送给所选服务商，届时界面必须给出清晰提示。API 密钥不得写入配置文件或提交到 Git。

## 开源许可

项目代码使用 [MIT License](LICENSE)。用户自行下载的模型权重继续受各自许可证约束，详见[模型选择](docs/MODELS.md)。

