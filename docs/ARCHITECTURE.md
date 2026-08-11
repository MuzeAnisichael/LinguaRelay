# LinguaRelay 架构设计

## 1. 设计原则

1. **首屏字幕优先。** 大模型不得阻塞第一版译文。
2. **显式语言优先。** 用户从 `zh / ja / en / ko` 中选择源语言和目标语言，不运行自动检测。
3. **有界队列。** 音频、识别和修正队列都必须设置上限；系统过载时丢弃过期的中间结果，不累积无限延迟。
4. **结果可替换。** 音频、ASR、机器翻译和大模型修正均通过端口接口隔离。
5. **默认本地和最少留存。** 默认不保存音频，API 修正默认关闭。
6. **先测量再优化。** 每个片段记录捕获、端点检测、ASR、翻译、修正和绘制耗时。

## 2. 组件与数据流

```text
WASAPI loopback
      |
      v
AudioCapture --PCM--> Resampler/RingBuffer --> VAD/Segmenter
                                              |
                                              v
                                      Streaming ASR worker
                                              |
                                     partial/final transcript
                                              |
                                              v
                                      Fast MT worker ------> Overlay
                                              |                 |
                                              +--> History <----+
                                                     |
                                                     v
                                          Optional LLM reviser
                                                     |
                                             revision event
                                                     |
                                             Overlay + History
```

所有跨线程通信使用带容量限制的队列。UI 线程只消费不可变事件，不执行模型推理。

## 3. 初版技术选择

| 层 | 首选 | 理由 | 替换条件 |
|---|---|---|---|
| 桌面框架 | Python 3.11 + PySide6 | AI 生态完整，能快速验证透明置顶窗 | 启动体积、内存或分发成为主要问题时评估 .NET/Rust |
| 系统音频 | PyAudioWPatch / WASAPI loopback | 已实现默认/指定设备、切换检测和自动重连 | 需要按进程捕获或更低抖动时使用原生 WASAPI/NAudio sidecar |
| 重采样 | 流式 SoXR | 已实现双声道 PCM 到 16 kHz 单声道 float32，保留跨块滤波状态 | 原生音频进程落地时重新评估 |
| 音频缓冲 | 固定 320 ms 块 + 有界新鲜优先队列 | 已实现背压、静音连续性、时间戳和丢弃计数 | ASR 基准后调整块大小 |
| 语音识别 | 多语言 faster-whisper small | `zh/ja/en/ko` 显式语言；本机 CUDA float16 达到 M2 延迟门槛 | 无 CUDA 时回退 CPU INT8；后续按更多硬件档位重新基准 |
| 端点检测 | 在线能量门控 + final Silero VAD | partial 避免重复 VAD 开销，final 用 Silero 清理静音 | 字幕断句体验不足时加入标点/语义端点器 |
| 即时翻译 | 按 `(source, target)` 路由的 provider registry | 覆盖四语全部 12 个方向，不锁定单一模型 | 某方向本地模型不达标时提供显式 API 选项 |
| 大模型修正 | Provider 接口，默认关闭 | 不绑定厂商；可接本地或兼容 API | 在延迟、费用、隐私基准完成后选择默认实现 |
| 历史 | JSONL + 原子追加 | 简单、可检查、便于离线重译 | 需要全文检索和会话管理时迁移 SQLite |

Windows 官方文档说明 WASAPI 回环可从渲染端点捕获正在播放的音频，即使硬件没有专用 loopback 设备；不过受保护内容可能不可捕获：
https://learn.microsoft.com/windows/win32/coreaudio/loopback-recording

M1 捕获线程只把回调 PCM 放入有界原始包队列；工作线程负责流式降混、SoXR 重采样、固定块切分和音量计算。默认设备每隔固定时间重新解析，身份或格式变化时重建流；异常采用有上限的指数退避。消费者落后时淘汰最旧输出块，以保证延迟有界。

## 4. 语言与翻译路由

内部规范代码为简体中文 `zh`、日语 `ja`、英语 `en`、韩语 `ko`，配置入口会把 `zh-CN / zh-Hans / jp / kr` 等别名归一化。源语言代码直接传给 ASR，禁止以自动检测作为隐式回退。

翻译层不保存全局模型名，而按 `(source_language, target_language)` 选择 provider，共有 12 个有向方向。每条路线必须标记为直接模型、经枢轴语言或远端 API，并分别记录许可、质量和延迟。枢轴翻译不能静默启用。

## 5. 流式策略

Whisper 不是严格的逐 token 流式模型。MVP 使用滑动窗口：

- 320 ms 音频块进入环形缓冲区；
- 能量门控判定出现语音后，每 320 ms 尝试生成一次重叠窗口；
- partial 跳过重复 Silero 计算，final 启用 faster-whisper 集成的 Silero VAD；
- 对连续两次假设求稳定前缀，稳定部分立即提交；
- 普通片段在静音达到 640 ms 时结束；连续语音超过 6 秒后，检测到 320 ms 短停顿即可优先切段；
- 即使没有停顿，单条字幕也在 10 秒时强制提交，避免长音频结束后集中显示和翻译大量文字；
- 最终文本进入快速翻译，未稳定文本仅作为浅色预览；
- 队列过载时淘汰旧的 partial，不丢 final。

默认优先切段点为 6 秒、字幕硬上限和模型窗口上限为 10 秒。新增的 `max_caption_seconds` 独立于旧版 `max_segment_seconds`，因此升级后即使用户配置仍保留 24 秒窗口，也会应用新的 10 秒字幕上限。推理队列容量 4，但只保留一个最新 partial 槽；final 会先淘汰同片段 partial，队列满且只有 final 时施加有界阻塞。模型完成较旧 revision 后还会再次检查并丢弃过期结果。CUDA 模型在开始捕获前执行一次显式固定语言预热，避免首条音频承担运行库初始化开销。

这样会用少量重复计算换取更自然的增量字幕，并避免把每次抖动都写入历史。

## 6. 大模型修正模式

### `off`

完全不调用大模型，是默认值，也是低配设备的稳定基线。

### `asynchronous`

字幕先显示快速翻译。句子结束后，将最近若干条上下文、原文和快速译文送入本地模型或 API。修正结果用相同 `segment_id` 替换当前字幕并追加 revision 记录。

### `live`（实验性）

partial 和 final 都可提交给独立修正线程；快译仍先显示。该模式必须有超时、熔断、速率限制和回退，且不得改变已经确认的专有名词表。

### 建议的修正输入

- 固定源/目标语言；
- 最近 4–8 个已完成片段；
- 当前原文和快速译文；
- 用户词汇表；
- 约束：仅输出修正译文，不解释，不添加原文不存在的信息。

### Provider 与修订记录

- `local` 复用 OpenAI-compatible chat-completions 格式，只接受 `localhost` 或回环 IP；连接前再次验证解析结果，且不跟随重定向；
- `openai_compatible` 只接受 HTTPS，Bearer 密钥只读取 `api_key_env` 指定的环境变量；
- provider 超时、断线、限流或熔断只改变修正状态，不得把主字幕服务置为错误；
- 每条 `revised` 事件复用 `segment_id`，并保存 `parent_revision`、`original_translation`、`revision_source`、`processing_scope`、provider 和 model；
- `history-revise` 只写入新的 JSONL 文件，先复制所有原事件，再追加批量修订。

## 7. 延迟与质量预算

首个可用版本的目标（以实际硬件基准为准）：

| 指标 | 目标 |
|---|---:|
| 首条 partial 出现 P50 | <= 1.2 s |
| final 快速译文 P50 | <= 1.8 s |
| final 快速译文 P95 | <= 3.0 s |
| UI 绘制 | <= 50 ms |
| 连续运行内存 | <= 1.5 GB（CPU 模型） |
| 过载后的队列恢复 | <= 5 s |

质量评估不能只看 BLEU。测试集应包含视频、会议、游戏、口音、背景音乐、专有名词和静音切换，并分别记录 WER/CER、COMET（适用时）、术语命中率和主观断句评分。

## 8. 线程和故障边界

- 捕获线程只做设备读取和轻量格式转换；
- ASR、MT、LLM 各自拥有工作线程和超时；
- 切换音频设备时重建捕获流，不重启 UI；
- API 连续失败触发短期熔断，状态显示为“快速翻译运行中，修正暂停”；
- 模型加载失败不得导致空白窗口，应给出可操作的诊断信息；
- 每次会话生成随机 ID，日志不记录音频内容和密钥。

## 9. 后续平台演进

MVP 验证需求后再决定是否拆成“原生音频守护进程 + Python 模型服务”。在没有测量证据前，保持单进程和清晰端口，以降低部署复杂度。
