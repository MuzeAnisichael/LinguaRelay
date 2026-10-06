# 验证证据与需求追踪

本页回答三个问题：每项需求由哪些现有测试支持、历史结果实际证明了什么、仍需怎样验收。功能状态以[统一需求](REQUIREMENTS.zh-CN.md)为准，执行入口见[开发指引](DEVELOPMENT.zh-CN.md)，发行物验证见[发布流程](RELEASE.md)。

本页于 **2026-10-06** 回填并随 0.3.3 实施更新，源码基线 [`af920a5`](https://github.com/MuzeAnisichael/LinguaRelay/commit/af920a5d100247f8913f46f5e6bed5034ec316d5)。早前文档回填轮没有重跑功能；本轮新回归/回放另记，不借用旧成绩。当前任务以[交接](HANDOFF.zh-CN.md)为准，范围见[0.3.3 计划](PLAN-v0.3.3.zh-CN.md)。历史结果不自动适用之后工作树，也不证明 0.3.3 公开发布。

这是**人工维护的需求追踪表**。现有 CI 会执行测试，但尚未自动核验需求 ID 与测试的对应关系、链接完整性或每项验收覆盖；不能据此宣称防止需求漂移或保证零遗漏。表中的“现有测试”表示已核对测试文件及关键断言，不表示本次运行通过。

## 验证层次不能相互替代

| 层次 | 能支持的结论 | 不能替代的验证 |
|---|---|---|
| 文档与源码核对 | 需求、实现入口、测试和报告可追溯；描述与当前代码一致 | 实际执行成功、性能或质量 |
| 单元与故障注入 | 配置、队列、状态机、回滚、超时、模拟服务故障的指定行为 | 真实设备、真实模型、网络尾延迟和长时资源占用 |
| Qt 与合成媒体集成 | 窗口状态、编辑流程、SQLite、指定媒体解码/编码路径可运行 | 真实上屏延迟、多显示器易读性、所有视频容器/播放器兼容性 |
| 源码 CI | 指定提交在 Windows runner 和所列 Python 版本上的检查结果 | 用户安装环境、冻结 EXE、CUDA 或真实音频质量 |
| 最终 EXE 自测 | 被打包的运行库、Qt、SQLite、合成媒体路径在该环境中可加载/执行 | 真实录音、用户模型推理、听感、干净机器矩阵 |
| 隔离安装回归 | 测试标识下安装、重复安装/升级清理、卸载及合成用户文件保留 | 对用户现有注册安装的实际升级、所有 Windows 版本、签名信任 |
| 真实设备与模型基准 | 指定硬件、模型、参数和语料下的延迟、质量、资源数据 | 不同配置、语言、音频场景或机器上的普遍保证 |
| 人类质量评审 | 所列评审者、准则和样本下的语义判断 | 所有内容都准确；模型辅助盲评也不能冒充人类评审 |

## 需求与现有测试映射

每行列出关键证据，不是所有测试函数的穷举。未来新增或改变行为时，应补充相应断言，并将提交、实际执行结果和仍未验证的范围一并记录。

### 实时字幕与配置

| 需求 ID | 已有测试与关键验收行为 | 历史证据 | 已知覆盖缺口 |
|---|---|---|---|
| R-LANG-01 | [语言](../tests/test_languages.py)、[路由](../tests/test_translation_routes.py)、[ASR 模型](../tests/test_asr_model.py)、[流式 ASR](../tests/test_asr_streaming.py)：中/日/英/韩的 12 个有向组合、显式语言、拒绝同语种和英语专用模型、不自动检测语言 | [M2](benchmarks/m2-small-cuda-final.json)、[M3](benchmarks/m3-m2m100-cuda-final.json) | 路由可用不等于 12 个方向质量合格；每种语言的口音、噪声与真实长语音尚无充分新证据 |
| R-AUDIO-01 | [设备](../tests/test_audio_devices.py)、[捕获](../tests/test_audio_capture.py)、[进程](../tests/test_audio_processes.py)、[音频处理](../tests/test_audio_processing.py)：系统/麦克风分开枚举，按来源选择捕获器，设备变化/故障重试，PID 按名称恢复，混声道/重采样/定长块 | [M1 长测](benchmarks/m1-30min-windows.json)、[M2 WASAPI 烟雾](benchmarks/m2-wasapi-stream-smoke.json) | 模拟捕获不证明所有物理设备可用；进程树、保护音频、蓝牙切换、睡眠恢复和持续非静音负载需设备矩阵 |
| R-LIVE-01 | [ASR 分段](../tests/test_asr_streaming.py)、[队列](../tests/test_asr_buffer.py)、[稳定前缀](../tests/test_stabilizer.py)、[MT](../tests/test_mt_streaming.py)、[服务](../tests/test_service_correction.py)、[背压](../tests/test_service_backpressure.py)、[停止](../tests/test_service_shutdown.py)、[生命周期](../tests/test_streaming_lifecycle.py)、[悬浮窗](../tests/test_overlay.py)、[迟到投递](../tests/test_desktop_delivery.py)：partial/final、断句、先显原文、旧版本隔离；满 final/有限重试/共同停止期限/恢复/历史失败不中断 | [M2](benchmarks/m2-small-cuda-final.json)、[M5](benchmarks/m5-release-gate.json) | 受控队列与录制隔离已有新回归，不能替代真实设备长测。硬切跨段上下文、重复推理、错误稳定前缀和实际绘制延迟未充分评估 |
| R-UI-01 | [悬浮窗](../tests/test_overlay.py)、[设置界面](../tests/test_settings_view.py)、[设置持久化](../tests/test_settings_io.py)、[历史界面](../tests/test_history_view.py)、[历史记录](../tests/test_history.py)：双语/仅译文、几何保留与最小缩放、保留时长、字体颜色/透明度、紧凑按钮、搜索和修订去重 | [2026-09-07 EXE 自测](benchmarks/v0.3.3-local-validation.json)加载设置及窗口组件但不显示窗口 | 真实拖动操作、高 DPI/多屏/不同字体、穿透与快捷键交互、读速和长会话可读性未由这些断言证明 |
| R-LLM-01 | [provider](../tests/test_correction_provider.py)、[引擎](../tests/test_correction_engine.py)、[限流/熔断](../tests/test_correction_controls.py)、[提示词](../tests/test_correction_prompt.py)、[批量修正](../tests/test_correction_batch.py)、[服务](../tests/test_service_correction.py)：连接复用、响应校验、禁用/停止丢弃晚结果、上下文边界、过期版本防回退、失败保留快译及修订来源 | [M4 模拟故障](benchmarks/m4-correction-fault-gates.json)、[OpenRouter 实测](benchmarks/OPENROUTER-v0.3.3.zh-CN.md) | 小样本调用非音频端到端；模型辅助评估非人工认证；误改、排队后上屏率、长会话/本地 LLM 硬件仍需验证。版本链仅覆盖启用历史的实时 final 及历史批量修订，离线仍缺同等追溯 |
| R-MODEL-01 | [模型包](../tests/test_model_pack.py)、[高级模型](../tests/test_advanced_models.py)、[安装脚本](../tests/test_release_scripts.py)：SHA-256 校验、篡改/越界拒绝、复用已有完整模型、推荐/轻量档、仅删除清单所属文件、检测目录文案不冒充完整性校验 | [模型说明](MODELS.md)、[2026-09-07 本地验证](benchmarks/v0.3.3-local-validation.json) | 安装脚本文案测试不等于真实模型下载与卸载全流程；不覆盖所有高级权重的损坏、断网恢复、磁盘不足和性能 |

### 录制与后期工作台

| 需求 ID | 已有测试与关键验收行为 | 历史证据 | 已知覆盖缺口 |
|---|---|---|---|
| R-REC-01 | [音频运行时](../tests/test_audio_runtime.py)、[录制](../tests/test_offline_recording.py)、[离线任务](../tests/test_offline_tasks.py)：未加载/加载失败仍录制、暂停字幕不暂停录制、录制暂停时锁源、去除暂停空档、旧块边界、写入失败清理、落盘片段恢复和分块合并 | `af920a5` 前轮回归；早期 [M1](benchmarks/m1-30min-windows.json)仅作捕获基线，不证明新录制链路 | 后期任务期间禁止开始录制，尚非任意场景并行；假捕获/合成片段不证明长会议无损；合成慢提交/满 handoff 样本守恒已回归，仍缺实际模型/设备持续过载、磁盘满/拔设备实测 |
| R-IMPORT-01 | [媒体](../tests/test_offline_media.py)：合成 WAV 探测、归一化为 16 kHz 单声道、MP3 导出后可探测；[处理器](../tests/test_offline_processor.py)覆盖解码阶段取消与可重用工作音频 | [2026-09-07 媒体往返自测](benchmarks/v0.3.3-local-validation.json) | 当前直接媒体单测不是视频容器测试；多容器、第一音轨选择、起始时间偏移、损坏媒体和长文件仍缺覆盖；没有多音轨选择功能 |
| R-OFFLINE-01 | [处理器](../tests/test_offline_processor.py)、[任务控制](../tests/test_offline_tasks.py)、[工作台](../tests/test_offline_workbench.py)：统一处理选项、时间轴字幕、LLM 失败保留快译、有界上下文、可取消限流、熔断恢复、各阶段取消、线程实际结束后解锁、恢复原暂停状态、退出不重启、晚回调隔离 | `af920a5` 前轮回归；无当前版本真实长文件性能报告 | 原生加载/解码/推理不能强杀；尚无取消耗时分布、最终质量或长文件内存上限证明；离线仅保存最终 cue，未保存同等快译/修订版本链 |
| R-EDIT-01 | [项目存储](../tests/test_offline_project.py)、[工作台](../tests/test_offline_workbench.py)：字幕时间/文本持久化，项目 ID 路径保护，字幕替换与完成状态原子提交，取消保留旧字幕，活动任务防误编辑/串项目 | `af920a5` 前轮回归；[EXE SQLite/窗口自测](benchmarks/v0.3.3-local-validation.json) | 播放/波形精确定位和不同媒体时间轴需听看核验；项目重命名、删除、批量管理、字幕合并拆分仍非现有能力 |
| R-EXPORT-01 | [导出](../tests/test_offline_export.py)：WebVTT 毫秒时间戳与 JSONL 字段；[媒体](../tests/test_offline_media.py)：MP3 可生成/探测；[历史](../tests/test_history.py)：CSV 修订来源、SRT 最新版本与播放顺序 | [EXE 媒体自测](benchmarks/v0.3.3-local-validation.json) | 产品列出的 WAV/FLAC/MP3/VTT/SRT/ASS/TXT/CSV/JSONL 不等于逐格式全面测试；离线 SRT/ASS/TXT/CSV/FLAC 及目标播放器兼容性仍缺专项覆盖。MP3 与 VTT 分别输出，无双语布局选项 |

### 分发与项目约束

| 需求 ID | 已有测试与关键验收行为 | 历史证据 | 已知覆盖缺口 |
|---|---|---|---|
| R-PACK-01 | [构建脚本](../tests/test_release_scripts.py)、[自测门禁](../tests/test_self_test.py)、[隔离安装脚本](../tests/test_installer_smoke_script.py)、[更新](../tests/test_updates.py)：环境/外来 DLL 拒绝、实际包元数据 SBOM、Qt 裁剪依赖、自测退出码/报告/超时、卸载保留用户文件和测试目录边界 | [2026-09-07 最终 EXE 与隔离安装结果](benchmarks/v0.3.3-local-validation.json) | 源码脚本测试不等于重新构建了 EXE；旧发行物自测不覆盖 `af920a5`。未签名，干净机器、生产安装升级和 CUDA 矩阵未完成 |
| R-QUALITY-01 | [ASR 指标](../tests/test_asr_metrics.py)、[模拟修正基准](../tests/test_correction_benchmark.py)、[API 基准保护](../tests/test_openrouter_benchmark.py)、[运行状态](../tests/test_runtime_state.py)、[追踪](../tests/test_telemetry.py)、[回放](../tests/test_reliability_replay.py)：WER/CER、三类门禁、费用与输入保护、不覆盖报告、缺失/失败/取消/时钟关联、公开语料与本地模型预检查 | [基准索引](benchmarks/README.md)、[M5](benchmarks/m5-release-gate.json)、[OpenRouter](benchmarks/OPENROUTER-v0.3.3.zh-CN.md) | 指标计算正确不等于质量达标；旧 M5 保留，新门禁无已确认的性能/质量阈值时为未评估。真实上屏、12 方向质量、音频损失、長时资源和人类评审仍缺 |
| R-MAINT-01 | [需求基线](REQUIREMENTS.zh-CN.md)、[开发指引](DEVELOPMENT.zh-CN.md)、[架构](ARCHITECTURE.md)、本表和 [CI 定义](../.github/workflows/ci.yml)；现有模块测试为结构整理提供回归入口 | `af920a5` 前轮本地检查与对应 CI | 暂无需求 ID 关联、需求遗漏或文档漂移的自动门禁；人工追踪表不是自动覆盖率报告 |
| R-FUTURE-01 | [语言](../tests/test_languages.py)、[配置](../tests/test_config.py)测试拒绝当前不支持的语言/配置边界；[扩语种方案](LANGUAGE-EXPANSION.zh-CN.md)与[路线图](ROADMAP.zh-CN.md)记录计划 | 无未来功能完成证据 | 更多语言、自动检测、混音、说话人分离、跨平台和云同步不能因底层模型具备能力而标为已实现；确认范围后另建验收 |
| R-IDENTITY-01 | [SBOM 测试](../tests/test_release_scripts.py)明确断言 `Copyright (c) 2026 Leeleelee`；[版本资源](../packaging/version_info.txt)、[安装器](../packaging/installer.iss)、[图标资源](../assets/linguarelay.ico)与 [spec](../packaging/LinguaRelay.spec)可人工核对；[ASR 测试](../tests/test_asr_streaming.py)覆盖字幕制作人模板幻觉过滤 | [变更记录](../CHANGELOG.md)记录署名与图标修改 | 没有作者/版权/安装器/所有图标显示的一致性专项测试；字幕中的“制作人”幻觉不是软件作者信息，过滤用例不能证明所有误识别消失 |
| R-PRIVACY-01 | [默认配置](../tests/test_config.py)：LLM 关闭、不保存实时原始音频；[设置](../tests/test_settings_view.py)、[端点配置](../tests/test_correction_config.py)、[provider](../tests/test_correction_provider.py)：仅保存密钥变量名、云端缺密钥先失败、禁止带凭据端点、不跟随重定向/不回显服务内容；[模型](../tests/test_model_pack.py)、[批处理](../tests/test_correction_batch.py)、[自测](../tests/test_self_test.py)、[安装](../tests/test_installer_smoke_script.py)覆盖指定文件保留/隔离 | [隐私说明](PRIVACY.zh-CN.md)、[2026-09-07 文件保留及合成字幕范围](benchmarks/v0.3.3-local-validation.json) | 默认本地处理不等于永不联网：检查更新/下载模型会联网；显式录制/导入会落盘，字幕历史默认保存。现有测试不是全路径网络审计或所有日志零泄漏证明，卸载保留只覆盖明确样本 |

### 已知问题与补测关联

问题的状态、影响和处理优先级以[已知问题台账](KNOWN-ISSUES.zh-CN.md)为准；本页只追踪证据与验收，不将静态风险写成已发生的真实设备事故。

| 台账 | 对应需求与本页补测方向 |
|---|---|
| [K-001](KNOWN-ISSUES.zh-CN.md#k-001) | R-LIVE-01、R-REC-01：满 final 背压、录制连续性和停止可达性 |
| [K-002](KNOWN-ISSUES.zh-CN.md#k-002) | R-QUALITY-01：实际音频到绘制的统一时钟基准 |
| [K-003](KNOWN-ISSUES.zh-CN.md#k-003) | R-LANG-01、R-QUALITY-01：四语分项、12 方向质量、人类评审与有效门槛 |
| [K-004](KNOWN-ISSUES.zh-CN.md#k-004) | R-LIVE-01、R-QUALITY-01：重复窗口推理、过期工作和负载曲线 |
| [K-005](KNOWN-ISSUES.zh-CN.md#k-005) | R-LIVE-01：音频断句边界、跨段上下文和起音完整性 |
| [K-006](KNOWN-ISSUES.zh-CN.md#k-006) | R-LIVE-01：稳定前缀错误驻留、翻译上下文与改写 |
| [K-007](KNOWN-ISSUES.zh-CN.md#k-007) | R-UI-01、R-QUALITY-01：占位显示、真实修订上屏率和可读性 |
| [K-008](KNOWN-ISSUES.zh-CN.md#k-008) | R-LLM-01：网络/排队/限流延迟、收益与误改、实际采用率 |
| [K-009](KNOWN-ISSUES.zh-CN.md#k-009) | R-AUDIO-01、R-REC-01：真实设备、持续语音、重连与长期运行 |
| [K-010](KNOWN-ISSUES.zh-CN.md#k-010) | R-IMPORT-01、R-OFFLINE-01、R-EDIT-01、R-EXPORT-01：长文件资源、取消耗时、UI 响应和导出 |
| [K-011](KNOWN-ISSUES.zh-CN.md#k-011) | R-MODEL-01、R-PACK-01：Windows/硬件/模型矩阵与最终发行物 |
| [K-012](KNOWN-ISSUES.zh-CN.md#k-012) | R-FUTURE-01：新增语言、项目管理等先确认范围再验收 |

## 2026-10-06 当前源码验收

已完成 0.3.3 可靠性实现的本地验收：**343 项测试通过，30.85 秒**；完整 Ruff/格式检查通过，`.release-venv` 的 `pip check` 无冲突。完整 pytest 在开发 `.venv` 中运行，既有其它工具依赖冲突未改动；不能把隔离环境依赖检查写成其中重跑了全测。沙箱原子保存/路径读取拒绝后，在正常权限下重跑，不弱化保护。

新增证据见[当日范围与结果](benchmarks/LOCAL-PIPELINE-2026-10-06.zh-CN.md)、[合成回放](benchmarks/reliability-2026-10-06.json)、[已有本地模型回放](benchmarks/local-pipeline-2026-10-06.json)。报告含 base HEAD、dirty 状态及实现文件 SHA-256，关联真实 ASR/MT/service/widget 阶段；不是不同阶段分位数相加。两种回放功能门禁通过，性能/质量均未评估；假模型八条 final，真实 Small/M2M100 CUDA 四个方向各一个 FLEURS 样本，无物理采集、LLM 或像素绘制。

录制隔离新回归见[音频背压](../tests/test_audio_backpressure.py)：慢实时提交时 9 个确定性 PCM 块全部写入 WAV，四块取消/一块拒绝只归属于字幕 handoff；写盘/合并阻塞的共同停止期限、所有权保留和重试也已覆盖。停止期限不等于硬中断原生/磁盘调用；不由合成录音证明真实设备长测无损。

四语 ASR 错误和 12 个缺 widget 确认的 revision 仍诚实保留；不包装成完美识别或所有 final/音频丢失。后续主要验证缺口与候选阈值见下文。源码提交/推送/对应 CI 的最新完成状态以[交接](HANDOFF.zh-CN.md)为准，未构建或发布安装包。

## 历史执行记录及适用边界

### 2026 年 10 月 5 日源码整理

- 提交：[`af920a5`](https://github.com/MuzeAnisichael/LinguaRelay/commit/af920a5d100247f8913f46f5e6bed5034ec316d5)，主要涉及独立音频/录制生命周期、离线控制、取消和分块合并。
- 前轮本地执行记录为 **256 项测试通过**，并完成静态检查。此数字来自该轮交付记录，不是本次重新执行所得；仓库没有与 9 月 JSON 同格式的新增本地结果文件。
- [对应 GitHub CI](https://github.com/MuzeAnisichael/LinguaRelay/actions/runs/37288396489) 的 Windows Python **3.11、3.12** 两个任务均为 `success`。本轮只读核对任务及步骤状态；日志下载权限受限，未据此声称独立核对了 CI 内测试数量。
- 这轮没有生成新 EXE/安装包、进行真实设备长测或重新调用付费 API。不能把 9 月的发行物结果转记为此提交已通过打包验证。

### 2026 年 9 月 7 日开发快照

[本地验证 JSON](benchmarks/v0.3.3-local-validation.json)记载 Windows x64 build 26200、Python 3.11.7、隔离锁版本环境、**206 项测试通过**，以及当时冻结 EXE 和安装器的结果。

- 最终 EXE 自测涵盖运行库导入、SQLite 项目、合成媒体往返、Qt 窗口/媒体组件及设置窗口加载。报告明确没有显示窗口、播放音频、采集真实设备或载入用户配置/模型。
- 安装回归使用与正式包同源逻辑、独立 `SmokeTest` 标识的变体，检查重复安装、旧 DLL 清理、已安装 EXE 自测、静默卸载和合成配置/导出/模型文件保留；不修改用户现有注册项/快捷方式。它不是生产注册安装的实际升级。
- 当时包体积、SHA-256、SBOM 与未签名状态仅归属于该批产物。报告明确未验证干净 Windows/CUDA/真实采集长测；杀毒扫描条件不足，不能称为“安全扫描通过”。

### M1 到 M5 的测量边界

| 报告 | 原始事实 | 不能据此推导 |
|---|---|---|
| [M1 30 分钟采集](benchmarks/m1-30min-windows.json) | 约 1,800 秒、5,623 块，其中 5,595 块被判为静音；记录零丢块，RSS 增长约 7.97 MiB | 约 99.5% 块静音的采集运行不是持续会议语音识别/翻译/录制共同负载验证 |
| [M2 Small CUDA](benchmarks/m2-small-cuda-final.json) | 四语各 5 条 FLEURS，共 20 条；首个非空 partial 聚合 p50 0.792 秒、p95 2.019 秒；每语种重复固定语料至约 30 分钟音频量，整段重复推理墙钟约 214.4 秒 | 音频累计时长不等于连续运行两小时会议；首个非空结果不一定正确/稳定，更不是首次译文上屏 |
| M2 配置与当前默认值 | 报告使用 24 秒窗口/段长；[当前默认配置](../src/lingua_relay/config.py)为 6 秒上限并包含后来的自适应节奏/标点策略 | 旧窗口数据不能直接证明当前配置的延迟、断句或质量；15 秒 WASAPI 烟雾也不能替代长测 |
| [M3 翻译](benchmarks/m3-m2m100-cuda-final.json) | 8 条自编 CC0 平行句、12 条路线，主要验证路由与热态推理延迟 | 12 条路线被执行不等于每条路线经过充分质量认证 |
| [M4 修正故障](benchmarks/m4-correction-fault-gates.json) | 进程内假 provider 和模拟故障，验证快译不阻塞、修订来源与熔断 | 不包含网络、真实 LLM 语义质量或实际会议 |
| [M5 门禁](benchmarks/m5-release-gate.json) | 将 ASR 测量与 MT 推理时间相加，得到组合首字幕 p50 **2.98 秒**、p95 **11.77 秒**；ASR 容许错误率不超过 100%，MT chrF/BLEU 有报告但无质量分数通过下限 | 组合计算不是采集到绘制的实测；`all_passed` 不能解释为高准确率、低尾延迟或严格质量认证 |

[M5 脚本](../scripts/run_m5_quality_gate.py)的上述宽松门槛保留为历史入口，本轮未改写旧脚本或报告。0.3.3 新增独立三类门禁，未确认的性能/质量阈值保持未评估；这不是修订 M5 后得出的准确性证明。旧 M5 混合统计不同语言的 WER/CER；新回放分别报告，不能把混合数字包装成一个通用“识别准确率”。

### OpenRouter 小样本修正

[2026-09-07 报告](benchmarks/OPENROUTER-v0.3.3.zh-CN.md)记录 **204 次成功调用、0 次失败**，服务返回费用合计 **$0.00635959**；预算预留上界为 $0.552624，低于当时用户授权 $1。输入是项目自编字幕样本，未使用用户录音/私人字幕。历史授权与余额不自动授权未来付费运行。

这些调用包括同组 36 条混合字幕的两种传输比较，以及 30 条英语→中文真实 M2M100 快译的修正；“真实快译”仍不表示输入经过真实语音识别。统计的是从 `revise()` 到完整响应校验的耗时，不是首 token、音频端到端或实际修订上屏耗时。路由/网络波动也限制了连接复用效果的因果归因。

质量审查为隐藏模型名后的**模型辅助盲评**，不是母语者或人类专家评审。30 条组可接受译文从 16/30 到 28/30 不代表软件整体 93.3% 准确率；0/16 误改不证明总体误改概率为零。API 两秒内返回率不等于上屏覆盖率，运行时排队、限流、过期丢弃与字幕保留时间仍会减少用户实际看到的修订。

## 后续真实场景拟验收方案

本节是**后续真实设备/质量验收草案**，不是已达标结果；本轮基础工具不表示此表全部完成，也没有新增真实设备/质量 CI 门禁。数值需结合硬件档位、用户场景和新基线确认，不拿更强机器的结果宣传所有机器。

### 统一记录与指标定义

每次运行至少记录提交 SHA、UTC/本地日期、Windows/CPU/GPU/RAM/驱动、Python/推理库、模型 ID 与 revision/文件哈希、精度/beam/VAD/窗口/队列/语言/LLM 参数、语料来源与许可、样本量、冷启动/热态、失败/取消样本和报告路径。固定随机种子及输入顺序，并保留可追溯的失败例子；含隐私的音频不得为了复现自动提交。

| 指标 | 拟定定义与防误读要求 |
|---|---|
| 首个非空原文、首个正确原文、稳定原文延迟 | 分开统计；用带时间轴的参考语音标定起点，记下对应事件实际进入界面的时间。不能仅用推理耗时或段落开始时间充当所有延迟 |
| 快译上屏、最终字幕、LLM 修订延迟 | 分别测音频锚点→快译绘制、句末→final 绘制、请求提交/网络开始→完整响应/修订绘制；用相同单调时钟串联音频、队列、推理、事件与 Qt 绘制 |
| 尾延迟与失效 | 报 p50/p95，样本足够时再报 p99，并公开分位数算法、样本数、超时/取消/缺字幕数量；不能仅在成功样本中隐藏失效 |
| ASR 质量 | 中文/日语 CER、英语/韩语 WER 分开；公开正规化/分词规则。另列人名、术语、数字、单位、否定和重复/漏句，不能只靠平均编辑距离 |
| 翻译与修正质量 | 12 个方向分别统计语义保留、遗漏、无依据补充、角色/数字/否定错误。固定基线快译，报告实质改善率、残留错误率及“原本可接受译文被改坏”的误改率和分母 |
| 修订实际覆盖与闪烁 | 分开记录符合修正条件、排队、发起请求、按时完成、被采用、确实上屏的数量；记录字幕改写次数/字符比例、错误驻留时间和读速，不能用 API 成功率替代 |
| 音频完整性 | 分开统计设备原始包、归一化块、ASR 输入与录音写入的序号/样本数/时间缺口；fresh-first 丢旧块必须显式计数，不能把录音缺失当作正常降级 |
| 资源与取消 | CPU/GPU 使用率、RSS/VRAM 峰值和稳定期增长、临时磁盘峰值、每阶段耗时；记录取消请求→任务真正结束→界面解锁，而不只测按钮立即变色 |

### 语料与人工质量

英语→中文为第一优先方向，但四种源语言和全部 12 个翻译方向不能被一个聚合成绩掩盖。建议首轮每方向至少 100 条独立短句/上下文片段，并为每种源语言准备有参考文本的连续语音；数量是拟定，不是现有覆盖。

覆盖安静语音、口音、音乐/环境噪声、低音量、长句不断句、短促句、同音专名、数字/单位/否定、未完成句、空白/静音和明确指定语言下的夹杂词。分别测固定正确原文的 MT、ASR 输出的 MT、最终 LLM 修正，避免将上游识别错误隐藏在整体评分里。

关键语言方向由胜任该语言的人类评审隐藏模型名并交叉复核；模型辅助评审可帮助筛选样本，但必须独立标记。译法有歧义时允许多个合理答案，不以流畅或参考字面相同判准确。

### 拟定场景与通过条件

| 场景 | 拟定验证与条件，不代表当前通过 |
|---|---|
| 1 倍速实时回放 | 同一公开/获授权音频通过实际采集→ASR→MT→可选 LLM→窗口，冷启动与热态分开。可讨论热态首个可用译文 p50 ≤ 1.5 秒、p95 ≤ 3 秒的档位目标；测量锚点和硬件先固定，不承诺全设备达到 |
| 密集断句与慢消费者 | 人工放慢 ASR/MT/LLM、压满 final 队列，同时录制并停止/恢复；验证各阶段不会无限等待、不会错误宣告成功，final 要么完成要么明确进入有界待处理/失败状态，而非静默丢弃以换取低延迟 |
| 音频长期运行 | 先 30 分钟持续有效语音，再考虑 2 小时真实墙钟运行；包括三类音源、切换/重连、实时暂停及录制暂停。正常目标工况要求录音无缺样本；故障下所有损失必须可见。不能用加速重复语料代替 |
| 长文件与取消 | 使用例如 60/180 分钟音频/视频，记录分阶段资源曲线；检查模型加载、解码、ASR、MT、LLM、合并和提交边界取消，旧字幕不丢、原媒体不覆盖、没有取消后晚成功。分块合并测试不能代替整条后期管线内存验证 |
| 展示与时间轴 | 双语/仅译文、字幕保留、短句/长句/无空格语言、100%/150%/200% 缩放与多显示器；实际观察闪烁/读速，并听看核验字幕轴、播放定位及各导出格式 |
| 模型与硬件矩阵 | 至少区分 Windows CPU-only/低资源、NVIDIA CUDA 的不同显存档；ASR Base/Small 与高级模型、MT 418M/1.2B、本地/云 LLM 分别记录。超出显存/内存的组合应给明确提示或标不支持，不能只统计成功设备 |
| 质量门槛 | 先保存四语/12 方向基线，再确认按场景的 CER/WER、语义错误与误改上限及容许退化；关键数字/否定/角色回归样本不得新增错误。具体统计阈值须有足够样本支撑，不能沿用 ASR ≤ 100% 作为质量合格标准 |
| 发行物 | 仅在明确准备发布时，对该提交重新生成最终 EXE/安装器，执行自测、隔离安装和干净机器矩阵，并记录产物哈希；不得从源码 CI 或旧包结果推导新包可用 |

## 后续维护要求

需求或实现变更时，同时核对本表的测试入口、边界与历史证据。新增测试应描述它实际保护的行为；没有真实设备/人工评审证据时，明确写“未验证”，不以“测试全部通过”省略范围。

历史 JSON 和原始测量保留原日期/配置，新的运行新增报告，不覆盖旧结论。文档轮只记录文档检查；功能轮记录实际命令、提交、结果与失败；发行轮另记录最终产物和安装范围。若只提出验收目标，不应改写为已实现或已通过的门禁。
