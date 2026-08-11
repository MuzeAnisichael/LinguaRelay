# 隐私说明（v0.1.0）

LinguaRelay 默认在本机处理电脑输出音频。本项目没有遥测、广告、账号或云同步服务。

## 数据如何处理

- 系统输出音频通过 Windows WASAPI loopback 捕获，仅在内存中交给本地 ASR；应用不提供录音保存功能。
- faster-whisper 与 M2M100 模型在本机执行。首次启动会从固定的 GitHub Release 地址下载模型包，并逐文件校验 SHA-256。
- 完整字幕默认以 JSON Lines 写入 `%LOCALAPPDATA%\LinguaRelay\history.jsonl`，以支持查看、导出和后期修正。可在配置中关闭 `history_enabled`，也可手动删除该文件。
- 配置、模型、下载缓存和最多 5 份崩溃报告位于 `%LOCALAPPDATA%\LinguaRelay`。崩溃报告包含版本、异常消息和调用栈，不主动包含音频；异常消息可能包含本地路径。
- 应用会向 GitHub Releases API 检查新版本，并在首次安装模型时访问 GitHub。GitHub 会按其政策看到常规网络元数据（例如 IP 地址）。更新只提醒，不会静默安装。

## 可选大模型修正

修正功能默认关闭。选择本地 provider 时只允许 loopback 地址。选择 OpenAI-compatible 云端 provider 时，应用会向你配置的 HTTPS 端点发送：源字幕、快速译文、最近文本上下文及匹配的术语表条目。API 密钥只从指定环境变量读取，不写入配置或字幕历史。

在启用云端修正前，请确认端点提供方的隐私、保留和跨境传输政策适合你的用途。不要把 v0.1.0 用于未经授权的监听、敏感或受监管音频。

## 删除数据

退出 LinguaRelay 后，删除 `%LOCALAPPDATA%\LinguaRelay` 即可移除模型、缓存、配置、字幕历史和崩溃报告。卸载程序只移除应用文件，不自动删除这份用户数据，以免意外丢失历史记录。
