# 开发路线图

## M0：项目基础（已完成）

- [x] 明确 Windows 首发；
- [x] 将手动语言范围确定为简体中文、日语、英语、韩语，共 12 个互译方向；
- [x] 建立公开 GitHub 仓库、MIT 许可、CI 和贡献指南；
- [x] 建立配置、领域事件、历史记录和悬浮窗演示；
- [x] 记录架构、模型许可和延迟预算。

验收：`lingua-relay doctor`、`lingua-relay demo`、`pytest` 和 `ruff check .` 可运行。

## M1：音频捕获（已完成）

- [x] 枚举 WASAPI 输出设备，以稳定名称标识设备；
- [x] 使用 `audio-select` 将用户选择保存到 `config.toml`；
- [x] 捕获默认或指定输出设备的 loopback 音频；
- [x] 将交错 PCM 流式转换为单声道 16 kHz `float32`；
- [x] 输出固定 320 ms 音频块和单调时间戳；
- [x] 使用有界新鲜数据优先缓冲，记录原始包与输出块丢弃数；
- [x] 支持静音连续性、默认设备变化检测、指定设备恢复和指数退避重连；
- [x] 实现 RMS/峰值音量计与低音量回环自检；
- [x] 实现 30 分钟持续运行、格式连续性和内存增长验收。

验收命令：

```powershell
lingua-relay audio-devices
lingua-relay audio-self-test
lingua-relay audio-stress --minutes 30 --report data/m1-stress.json
```

本机验收记录见 `docs/benchmarks/`。任何音频都只在内存中处理，报告只保存设备和性能指标。

## M2：四语实时识别（已完成）

- [x] 集成 faster-whisper `base/small` 并完成 CPU INT8 / NVIDIA float16 基准；
- [x] 将 `zh / ja / en / ko` 作为显式 `language` 参数传入，禁止自动检测；
- [x] 针对中文、日语、英语、韩语实现在线端点检测、Silero VAD、重叠窗口和稳定前缀；
- [x] 建立 partial/final 状态和丢弃过期 partial 的有界背压策略；
- [x] 使用固定修订的 CC-BY-4.0 FLEURS 四语测试集；
- [x] 记录 WER/CER、首条非空 partial P50/P95、内存和持续运行表现。

本机最终验收采用 `small/CUDA float16`。四语首条非空 partial P50 分别为约 0.71 / 0.72 / 0.91 / 1.03 秒；每种语言处理超过 30 分钟音频，674 次持续推理错误数为 0，持续阶段 RSS 增长 5.84 MiB。推理队列容量为 4，事件队列容量为 16，旧 partial 可替换而 final 不丢弃。详细报告见 `docs/benchmarks/m2-small-cuda-final.json`。

## M3：12 方向即时翻译与完整悬浮窗（已完成）

- [x] 建立 `(source_language, target_language) -> translator provider` 路由表；
- [x] 通过固定版本 M2M100/CTranslate2 支持 `zh / ja / en / ko` 全部 12 个直接互译方向；
- [x] 使用单实例预热、LRU 缓存和有界队列，过载时替换旧 partial 并保留 final；
- [x] 本地模型覆盖全部方向，因此 M3 不启用远程 API 回退；provider 路由保留后续扩展点；
- [x] 支持“仅显示译文”和“双语同时显示”，partial 淡化、final 固定，翻译失败回退原文；
- [x] 支持字号、位置、透明度、点击穿透和全局显示/隐藏快捷键；
- [x] 托盘菜单支持开始/暂停、手动源/目标语言、设备、显示模式、历史和退出；
- [x] 支持 JSONL 历史及 JSONL/CSV/SRT 导出；
- [x] 准备 PyInstaller、独立模型包、Inno Setup 安装器和 GitHub 打包工作流。

验收：12 个方向都能运行并有独立基准；快速译文 P50 不高于 1.8 秒；翻译失败时仍显示原文。

## M4：异步大模型修正（已完成）

- [x] 定义仅允许回环地址的本地 provider 与强制 HTTPS 的 OpenAI-compatible 云端 provider；
- [x] 实现最近上下文、按语言方向过滤的术语表、超时、熔断和速率限制；
- [x] 支持完整句异步修正、实验性的 partial/final 实时修正和会话历史批量修正；
- [x] 用追加式 revision 事件保留快速译文、父版本、修正译文和 provider/model 信息；
- [x] UI 明确显示本地快译、本地处理或云端传输状态；
- [x] 修正提示词携带显式源/目标语言，并将字幕内容作为不可信数据，不重新检测语言。

验收：`m4-correction-fault-gates.json` 的非阻塞、断线、熔断和追溯门禁全部通过；
关闭或断开修正 provider 不影响快速链路，任何修正都能追溯原译文。

## M5：质量与发布

- 构建包含会议、视频、口音和背景音乐的合法四语测试集；
- 记录 WER/CER、术语命中率、翻译质量和端到端延迟；
- 打包为 Windows 安装程序，首次启动按需下载模型并展示许可证；
- 崩溃恢复、自动更新策略、隐私说明和威胁建模；
- 发布 `v0.1.0`。

## 暂不进入初版

- 自动检测语言；
- 简体中文、日语、英语、韩语之外的语言；
- 麦克风与系统音频混音；
- 按单个进程捕获音频；
- macOS/Linux；
- 多人说话人分离；
- OCR/屏幕文字翻译；
- 账号、云同步和团队协作。
