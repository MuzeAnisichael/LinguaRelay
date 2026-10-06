# 统一需求与实现状态

本页是需求与现状的索引，不代替架构说明或测试报告。需求编号用于讨论、Issue、提交说明和回归测试关联；后续更新状态时应同时更新证据和边界。历史用户意图见[项目上下文](PROJECT-CONTEXT.zh-CN.md)，开放问题见[台账](KNOWN-ISSUES.zh-CN.md)，测试/报告覆盖见[验证索引](VERIFICATION.zh-CN.md)，本轮范围见[交接](HANDOFF.zh-CN.md)。

截至 2026-10-06，经 GitHub 公共 API 核实公开版为 **v0.3.2**，`main` 源码为 **0.3.3，尚未公开发布**。用户已确认[版本规划](PLAN-v0.3.3.zh-CN.md)，收口可靠性与测量工具；本地验收后推送源码并核验 CI，不构建/发布安装包。[CHANGELOG](../CHANGELOG.md) 区分未发布修改与历史开发快照；`docs/releases/v0.3.3.md` 是历史发布草稿，不作为已公开发行的证明。实际结果见[交接](HANDOFF.zh-CN.md)。

## 如何理解状态与证据

- **已实现**：当前代码具有该能力；不等于所有机器、音频或语言方向都已达到性能/质量目标。
- **main 未发布改进**：当前源码包含改进，公开 v0.3.2 不一定包含。
- **部分完成**：主路径存在，但表中明确列出的产品能力或验证仍缺失。
- **计划 / 不在当前范围**：尚未实现，不能作为现有功能宣传。
- 测试文件证明可复现的逻辑或回归覆盖；测试是否通过以对应提交的实际运行结果为准。历史基准只覆盖报告中指定的日期、数据、硬件和配置。
- **K-xxx** 是当前开放问题，**H-xxx** 是保留的历史问题/修复记录；它们不是自动创建的 GitHub Issue。“本轮登记”不等于“本轮修复”。原有 15 个需求 ID 保留，补充署名和隐私两个 ID，不重编号。

## 实时字幕与配置

| ID | 目标 | 实现状态 | 实现与验收证据 | 边界 | 下一步 |
|---|---|---|---|---|---|
| R-LANG-01 | 中文、日语、英语、韩语手动互译 | 已实现：12 个有向语言组合 | [语言定义](../src/lingua_relay/languages.py)、[路由测试](../tests/test_translation_routes.py)、[M3 报告](benchmarks/m3-m2m100-cuda-final.json) | 不自动识别语言；模型支持更多语言不等于产品已支持 | 按方向评估质量后再扩语种 |
| R-AUDIO-01 | 系统输出、指定进程树、指定麦克风捕获 | 已实现 | [音频模块](../src/lingua_relay/audio/)、[捕获测试](../tests/test_audio_capture.py)、[进程测试](../tests/test_audio_processes.py) | 同时选择一种来源；不混音；进程捕获受 Windows 版本与受保护音频限制 | 扩充真实设备、重连和长时运行矩阵 |
| R-LIVE-01 | 尽早显示识别与快译，避免长段文字堆积 | 已实现：partial 快译、稳定前缀、端点/长度上限；main 增加有界 final 提交、输出/重试期限、过载暂停与诚实收尾 | [流式 ASR](../src/lingua_relay/asr/streaming.py)、[生命周期故障](../tests/test_streaming_lifecycle.py)、[服务背压](../tests/test_service_backpressure.py)、[架构策略](ARCHITECTURE.md#5-流式策略) | 原生调用不可硬杀；Whisper 仍重算窗口，无跨段音频重叠；K-001 设备残余、K-004–K-007 仍开放 | 用同配置音频回放及设备长测建立体验/质量基线；逻辑回归不等于实时性达标 |
| R-UI-01 | 简洁可拖动/缩放悬浮窗，双语或仅译文，历史和用户设置 | 已实现 | [UI 模块](../src/lingua_relay/ui/)、[悬浮窗测试](../tests/test_overlay.py)、[设置测试](../tests/test_settings_view.py)、[历史测试](../tests/test_history_view.py) | 屏幕缩放、多显示器、真实音频交互仍需环境验证 | 收集易读性与多显示器案例 |
| R-LLM-01 | 可选本地/API 修正，不阻塞快译，保留原文与修订 | 已实现实时 final 历史修订与批量历史修订；离线修订追溯部分完成；main 改进预设、连接复用、过期保护与取消 | [修正模块](../src/lingua_relay/correction/)、[引擎测试](../tests/test_correction_engine.py)、[provider 测试](../tests/test_correction_provider.py)、[2026-09-07 实测](benchmarks/OPENROUTER-v0.3.3.zh-CN.md) | 默认关闭；密钥来自环境变量；HTTP 非流式，live 是提交策略；实时 final 仅开启历史时持久化，离线只保存最终 cue，无同等版本链；晚到修订未必上屏。K-007/K-008 | 分别测 API 延迟、显示覆盖与人工净收益；确认离线原译文/修订链需求 |
| R-MODEL-01 | 复用已有模型、明确下载/硬件指引、独立模型卸载 | 已实现；main 改进安装检测文案 | [模型说明](MODELS.md)、[模型包测试](../tests/test_model_pack.py)、[高级模型测试](../tests/test_advanced_models.py) | 安装器发现目录不代表模型完整；应用校验后采用；大模型受磁盘、内存和显存限制 | 增加硬件分档实测，不自动下载或静默改变配置 |

## 录制与后期工作台

| ID | 目标 | 实现状态 | 实现与验收证据 | 边界 | 下一步 |
|---|---|---|---|---|---|
| R-REC-01 | 任意时间开始/暂停/继续/结束录制，异常可恢复 | 主流程已实现；main 独立于模型加载/实时暂停，新增有界异步实时 handoff，字幕过载不暂停录制 | [音频运行时](../src/lingua_relay/audio/runtime.py)、[运行时测试](../tests/test_audio_runtime.py)、[录制测试](../tests/test_offline_recording.py) | 后期与录制互斥；暂停空档从媒体轴删除，暂停期间锁源；片段恢复非推理断点；磁盘/设备故障仍可能缺样本。K-001 设备残余/K-009/K-010 | 合成慢提交样本守恒已有回归；继续实际设备长测，任务并行须单独设计 |
| R-IMPORT-01 | 导入音频、分离视频音轨并复用后期管线 | 已实现 | [媒体处理](../src/lingua_relay/offline/media.py)、[媒体测试](../tests/test_offline_media.py) | 只选第一个音轨，工作音频为 16 kHz 单声道；不覆盖源文件；无多音轨选择和原始高保真保存选项 | 覆盖更多实际容器、时间戳偏移与长文件 |
| R-OFFLINE-01 | 更准确的后期识别/翻译，可选 LLM，有任务进度和取消 | 已实现；main 未发布改进：统一选项与协作取消 | [处理器](../src/lingua_relay/offline/processor.py)、[处理器测试](../tests/test_offline_processor.py)、[任务控制测试](../tests/test_offline_tasks.py)、[工作台测试](../tests/test_offline_workbench.py) | 单任务串行；后期释放实时模型；MT 沿用全局配置；原生调用延后取消；无推理断点续跑；合并按块不等于整段 ASR 低内存，高质量档不保证每条更优。K-010 | 测长文件内存、取消耗时、窗口响应及失败恢复 |
| R-EDIT-01 | 音频时间轴、播放定位、波形、字幕编辑 | 已实现；项目管理部分完成 | [项目存储](../src/lingua_relay/offline/project.py)、[项目测试](../tests/test_offline_project.py)、[工作台测试](../tests/test_offline_workbench.py) | 可编辑时间、原文、译文；尚无项目重命名/删除/批量管理和字幕合并拆分工具 | 按使用场景规划项目管理与批量工作流 |
| R-EXPORT-01 | 音频和字幕多格式导出 | 已实现：WAV/FLAC/MP3/VTT/SRT/ASS/TXT/CSV/JSONL | [导出实现](../src/lingua_relay/offline/export.py)、[导出测试](../tests/test_offline_export.py) | MP3 与 VTT 分别导出；不是单个“mp3.vtt”音频字幕复合格式；没有双语字幕布局选项 | 验证目标播放器兼容性，再设计批量/双语导出 |

## 分发、验证与后续范围

| ID | 目标 | 实现状态 | 实现与验收证据 | 边界 | 下一步 |
|---|---|---|---|---|---|
| R-PACK-01 | Windows EXE、安装/升级/卸载，模型独立分发与数据保留 | 已实现；0.3.1/0.3.2 已公开修复 Qt 启动；main 有隔离环境、锁版本、实际组件 SBOM 与卸载保护改进 | [发布流程](RELEASE.md)、[打包测试](../tests/test_release_scripts.py)、[隔离安装测试](../tests/test_installer_smoke_script.py)、[历史本地验证](benchmarks/v0.3.3-local-validation.json) | 未签名；本轮不构建/发布；隔离安装测试不等于用户现有安装实际升级或干净机器测试 | 只有明确发布时才重建最终 EXE、隔离安装器与校验产物 |
| R-QUALITY-01 | 准确性、实时性、稳定性与资源占用有可追溯依据 | 部分完成：故障回归、历史基准；main 新增有界追踪与回放、三类门禁独立状态和无效/混配置拒绝 | [验证索引](VERIFICATION.zh-CN.md)、[基准索引](benchmarks/README.md)、[追踪/门禁](../src/lingua_relay/telemetry.py)、[追踪测试](../tests/test_telemetry.py) | widget 更新不等于物理绘制；旧 M5 宽门槛不证明质量；缺正式方向阈值、设备长测与人工评审。K-002/K-003/K-009/K-011 | 固定公开语料/硬件建立新基线，再确认性能/质量门槛，不因工具存在宣布达标 |
| R-MAINT-01 | 可维护目录、统一追踪、跨会话不丢需求与问题 | main 未发布改进：职责拆分；本轮补入口、交接、沿革、台账和验证索引 | [入口规则](../AGENTS.md)、[工作协议](DEVELOPMENT.zh-CN.md#防上下文偏移的工作协议)、[交接](HANDOFF.zh-CN.md)、[验证映射](VERIFICATION.zh-CN.md)、[变更记录](../CHANGELOG.md) | 人工维护/评审，不是永久记忆或自动覆盖门禁；父目录会话须显式读项目规则；保留历史和用户文件 | 每轮更新交接和相关条目，检查证据/映射；自动校验需另行确认 |
| R-FUTURE-01 | 更多语言、更完整后期项目管理 | 计划 | [路线图](ROADMAP.zh-CN.md)、[扩语种方案](LANGUAGE-EXPANSION.zh-CN.md) | 自动检测、混音、说话人分离、跨平台、账号/云同步均不在当前实现范围 | 先确认使用场景和验收标准，再分里程碑实施 |
| R-IDENTITY-01 | 项目作者、发布者与版权为 Leeleelee，简洁图标 | 已实现署名与图标资源；完整发行/渲染验证仍有边界 | [许可证](../LICENSE)、[安装器](../packaging/installer.iss)、[资源目录](../assets/)、[发布脚本测试](../tests/test_release_scripts.py)、[界面测试](../tests/test_overlay.py) | 署名模板过滤不等于可以改写正常媒体制作人；图标加载/渲染需实包人工检查 | 每次发行核对 EXE/安装器/SBOM/界面署名和图标 |
| R-PRIVACY-01 | 默认本地、显式录制/云端、凭据与用户数据保护 | 已实现主要边界；按改动持续回归 | [隐私说明](PRIVACY.zh-CN.md)、[provider 测试](../tests/test_correction_provider.py)、[设置读写测试](../tests/test_settings_io.py)、[打包测试](../tests/test_release_scripts.py) | 云端启用后传输字幕文本/指定上下文；用户主动录制/导入会本地落盘；默认卸载保留数据不等于所有手工路径已实测 | 网络/落盘/卸载变更需显式影响说明、脱敏证据及保护回归 |

## 验证记录的使用方式

2026-09-07 的 [0.3.3 本地验证记录](benchmarks/v0.3.3-local-validation.json) 保存了当时的 206 项回归、冻结 EXE 自测、隔离安装/升级/卸载与包体积结果；它不是 2026-10-05 工作树的回归结果，也不证明 v0.3.3 已公开发布。该次测试没有播放音频、采集真实设备或载入用户模型，并明确保留了干净机器、CUDA、长期运行等未验证项。

后续修改应运行[开发指引中的相应测试层级](DEVELOPMENT.zh-CN.md#按改动规模选择验证)，在提交/CI 中记录新结果，不覆盖旧报告或将历史结果移花接木到新代码。
