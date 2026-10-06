# 开发指引与目录导航

先读[项目入口规则](../AGENTS.md)、[当前交接](HANDOFF.zh-CN.md)和[统一需求与状态](REQUIREMENTS.zh-CN.md)，再按[架构](ARCHITECTURE.md)定位模块。最新公开版按仓库记录为 v0.3.2，源码版本 0.3.3 尚未发布；日常提交、测试、CI 产物与正式发版是不同操作。当次范围与验证记录以交接页为检查点，不从旧任务文字推导授权。

## 防上下文偏移的工作协议

### 从正确入口恢复

从 `LinguaRelay` 仓库根目录启动会话。若会话工作目录为父目录 `D:\SOME PROJECT`，必须显式读子目录的 `AGENTS.md`；Codex 沿仓库根到当前目录读取规则，不自动读取未进入的子目录规则。文件不是永久记忆或强制执行器，新会话/上下文压缩后仍需按入口重新核实。

大型或模糊任务先讨论，每次聚焦一个关键问题；总结已确认需求、设计、范围与假设后再实现。简单明确的小任务无需形式化长讨论。当次用户指示优先；历史用户需求保留但有冲突时先解释并确认，不让候选方案自动升级为承诺。

### 一类事实一个主要落点

| 文件 | 主要责任 | 不应该代替 |
|---|---|---|
| [AGENTS.md](../AGENTS.md) | 简短工作规则、恢复入口和产品不变量 | 完整需求历史、测试日志 |
| [PROJECT-CONTEXT](PROJECT-CONTEXT.zh-CN.md) | 对话需求/决策沿革与历史授权边界 | 当前实现状态和永久授权 |
| [REQUIREMENTS](REQUIREMENTS.zh-CN.md) | 稳定需求 ID、当前能力与范围 | 问题细节、性能认证 |
| [KNOWN-ISSUES](KNOWN-ISSUES.zh-CN.md) | K-/H- 问题、证据级别、关闭条件 | GitHub Issue 自动创建或本轮修复 |
| [VERIFICATION](VERIFICATION.zh-CN.md) | 需求→测试→报告→缺口及验收口径 | 声称所有列出的测试刚刚运行 |
| [ADR](decisions/) / [ARCHITECTURE](ARCHITECTURE.md) | 为什么这样设计、当前数据流/边界 | 下一步授权 |
| [ROADMAP](ROADMAP.zh-CN.md) | 已落地阶段与候选顺序 | 固定发版日期或自动实施许可 |
| [HANDOFF](HANDOFF.zh-CN.md) | 最新检查点、未完成项、下一步与当次授权 | 长期全量历史 |
| [CHANGELOG](../CHANGELOG.md) / [基准报告](benchmarks/README.md) | 版本历史与原配置的日期化证据 | 当前工作树新结果 |

只读取本次相关的详细条目，不把所有报告和聊天全文塞进入口规则。摘要帮助恢复，但重要结论应可由需求、代码和报告重新验证。

### 变更检查点

1. **开始**：检查分支/提交/工作树，读入口与交接；关联已有 R-/K-/H- ID。新需求或新问题先登记，并注明用户确认、建议、静态风险或复现证据。
2. **确认**：复杂变更说明影响范围、设计与验收，等待必要的用户选择；已确认范围内继续执行，不重复打断。扩大数据采集、收费或分发范围需新的明确授权。
3. **实施**：按模块拆小步；子任务约定文件所有权，回传 ID、结果和未验证项。代码整理不能删除历史要求或用户产物。
4. **验证**：按下表选层级；记录日期、代码/工作树、实际命令、模型/硬件/语料、结果及未运行项。只修复代码但没有复现/回归证据的条目仍保持开放。
5. **收尾/中断**：同步需求状态、台账、验证索引；关键取舍写 ADR，发布变化写 CHANGELOG；更新交接页。复查差异与相对链接，明确本地修改、推送和发布的区别。

当前由文档和 PR 评审人工执行，现有 CI 并不自动检查需求 ID 与测试覆盖，也不能保证绝对无 Context Drift。后续可另行确认自动校验方案；本轮不新增自动化脚本/工作流。

入口简短、历史和状态外置的做法参考 [Codex 项目规则加载说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)及[长期任务的持久化上下文建议](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)。只采用其工作方式，不修改用户全局配置。

## 目录索引

| 路径 | 职责 | 修改时注意 |
|---|---|---|
| [`src/lingua_relay/service.py`](../src/lingua_relay/service.py) | 实时字幕服务公共 API、ASR/MT/LLM 编排与事件投递 | 保持 UI 调用兼容；不要让模型或网络调用阻塞 UI |
| [`src/lingua_relay/audio/`](../src/lingua_relay/audio/) | 设备、系统/进程/麦克风捕获、归一化、有界音频队列；`runtime.py` 管理捕获与录制生命周期 | 音频捕获与模型加载就绪状态分离；录制时禁止换源 |
| [`src/lingua_relay/asr/`](../src/lingua_relay/asr/) | 模型封装、实时窗口/端点、识别队列与基准 | 始终传显式语言；保留 partial/final 与 revision 语义 |
| [`src/lingua_relay/mt/`](../src/lingua_relay/mt/) 与 [`translation.py`](../src/lingua_relay/translation.py) | 本地翻译模型、路由、缓存、最新结果替换与基准 | 保持 12 条路线；旧译文不能覆盖新识别 |
| [`src/lingua_relay/correction/`](../src/lingua_relay/correction/) | 本地/HTTPS provider、上下文、术语、速率、熔断、实时/批量修正 | 默认关闭；文本不可信；密钥只用环境变量；失败保留快译 |
| [`src/lingua_relay/offline/`](../src/lingua_relay/offline/) | `recording.py` 片段与恢复，`media.py` 媒体处理，`processor.py` 后期识别/翻译，`project.py` SQLite，`export.py` 导出 | 处理器不依赖 Qt；保留原媒体和已保存字幕；不能将恢复录音描述为任务断点续跑 |
| [`src/lingua_relay/ui/`](../src/lingua_relay/ui/) | `app.py` 桌面装配，悬浮窗/设置/历史/工作台；`offline_tasks.py` 隔离离线任务控制 | Widget 负责呈现与交互，控制器协调任务；模型计算放工作线程 |
| [`config.py`](../src/lingua_relay/config.py)、[`settings_io.py`](../src/lingua_relay/settings_io.py)、[`paths.py`](../src/lingua_relay/paths.py) | 配置结构/校验、持久化、用户数据路径 | 不硬编码用户路径，不保存凭据，不悄悄开启云端 |
| [`events.py`](../src/lingua_relay/events.py)、[`ports.py`](../src/lingua_relay/ports.py)、[`runtime_state.py`](../src/lingua_relay/runtime_state.py) | 领域事件、适配器接口与状态 | 跨线程使用明确消息，新增状态同步 UI 与测试 |
| [`tests/`](../tests/) | 按模块命名的单元、故障和 UI/媒体回归 | 默认使用合成数据、假 provider 或临时目录，不依赖私人录音 |
| [`scripts/`](../scripts/) | 构建、打包校验、模型准备与可复现基准入口 | API/模型下载、长测、安装和发布均不是普通测试的隐式步骤 |
| [`native/`](../native/) | Windows 进程音频辅助程序 | 改动后需原生编译和最终 EXE 验证 |
| [`packaging/`](../packaging/) | PyInstaller、Inno Setup、依赖锁、模型清单与第三方组件 | 发行环境与开发环境隔离；不得随意删除不同 ABI 的媒体库 |
| [`docs/`](./) | 当前需求、开发/架构指引、历史设计、发布草稿、日期化基准 | 新状态写当前文档，历史报告不改成新测量 |
| [`.github/workflows/`](../.github/workflows/) | CI 与 Windows 构建工作流 | 构建成功不等于已发布 GitHub Release |

`.venv/` 是开发环境，`.release-venv/` 是锁版本的发行环境；`build/`、`dist/`、`release/`、本地模型/配置/数据是工作产物，不是待整理的源代码。不要为了清理目录删除用户文件、录音或旧验证证据。

## 运行边界

实时入口由 UI 调用 `RealtimeCaptionService`，服务协调音频运行时、ASR、快译、可选 LLM 与事件。音频运行时拥有捕获和录制生命周期；识别尚未就绪不应成为保存音频的前提。录制使用同一种已选择音频来源，不引入系统与麦克风混音。

离线控制器协调工作台的处理选项、单个任务与实时服务切换；`OfflineProcessor` 只负责媒体到字幕的处理。任务运行时释放实时模型以避免同时占用两套模型资源。取消采用 `threading.Event` 协作检查，不强杀正在执行的原生调用；线程结束并按先前暂停意图恢复实时服务后才解锁 UI。录音片段恢复、任务取消、推理断点续跑是三个不同概念；最后一项尚未实现。

Qt 负责界面状态与用户操作。main 将录制路由与实时提交分线程，final admission 默认非阻塞、输出和服务重试有限时；持续过载明确暂停字幕、记录未完成项。停止采用共同期限，原生调用超时保留所有权，见 **K-001** 和 [ADR 0003](decisions/0003-bounded-waits-and-recording-isolation.md)。磁盘/设备故障及真实长测仍开放。通知回调需轻量，不在共享状态锁内调用；导出和媒体转换仍须独立测试。

## 开发环境与入口

推荐 Windows x64、Python 3.11。源代码声明支持 Python 3.11–3.13，当前 CI 矩阵覆盖 3.11/3.12；不要把声明范围误写为全部平台验证通过。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,runtime]"
.\.venv\Scripts\lingua-relay doctor --config config.example.toml
.\.venv\Scripts\lingua-relay app
```

`doctor` 诊断环境，不等于下载模型或端到端质量验收。首次运行通过应用显式选择/复用模型。需要转换翻译模型时额外安装 `.[translation]`；语料/质量基准使用 `.[benchmark]`，GPU 使用匹配硬件的 `.[gpu]`。仅文档或 mock 测试不需要下载权重，也不需要 API 密钥。CI 当前使用 `.[dev,audio,asr,translation]`，依赖范围见 [`pyproject.toml`](../pyproject.toml)。

## 按改动规模选择验证

先运行最接近修改点的测试，跨模块修改再扩展；应用源码、配置结构或跨模块行为修改合并前运行完整静态检查和逻辑回归。纯文档按对应层级验证。不要为一次文档改动重建安装器，也不要用几个单测代替发行物验证。

| 改动范围 | 优先验证 | 何时扩大 |
|---|---|---|
| 文档、目录链接、状态说明 | 核对相对链接/标题锚点、ID 唯一性与映射、引用测试文件、模板结构、当前源码/报告证据，`git diff --check` | 修改命令或配置示例时验证解析/入口；不将文档校验写成源码全测 |
| 单个领域模块 | 对应 `tests/test_<module>.py`，受影响文件的 Ruff | 接口/事件/配置变化时运行调用方测试 |
| 捕获/录制生命周期 | 音频、录制、服务状态相关测试 | 并发/队列改动加停止、重连、模型失败场景；真实设备变化另做明确授权的设备测试 |
| 后期处理/工作台 | `test_offline_processor.py`、`test_offline_media.py`、`test_offline_recording.py`、`test_offline_project.py`、`test_offline_tasks.py`、`test_offline_workbench.py` | 时间轴/导出变化加 `test_offline_export.py`；UI 控制器变化加服务切换和关闭窗口回归 |
| ASR/MT/LLM | `test_asr_streaming.py`、`test_mt_streaming.py`、`test_correction_*.py`、`test_service_correction.py` 等受影响文件 | 测性能或质量时再跑固定语料基准，显式记录设备/模型/预算 |
| 跨模块整理、准备提交 | 完整 Ruff、pytest、`pip check` | 通过不代表真实音频长测或安装包已验证 |
| 依赖、Qt、原生助手、冻结打包、安装逻辑 | 源码测试 + 锁环境校验 + 最终 EXE 自测 + 隔离安装回归 | 明确准备发布时再做完整构建、完整性校验、机器矩阵与发布步骤 |

例如只调整离线字幕拆分时，先运行：

```powershell
.\.venv\Scripts\python -m pytest tests/test_offline_processor.py tests/test_offline_export.py
```

应用源码/配置结构修改提交前完整回归（纯文档改动不需要重复执行此组）：

```powershell
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m pip check
git diff --check
```

普通回归不要访问真实 LLM 服务。真实 API 基准必须先确认提供商、模型、脱敏样本和费用上限，密钥只从用户指定的环境变量读取，报告不能泄露密钥。性能数字只引用实际运行报告；旧报告应继续带原日期和配置，参见[基准索引](benchmarks/README.md)。

## 可靠性回放（0.3.3 源码）

合成音频和假模型用于验证队列/停止/报告功能，不提供真实速度或翻译质量结论；加 `--qt-ui` 才确认实际 widget 更新，仍不是像素绘制。输出文件必须是新路径，工具拒绝覆盖已有报告。

```powershell
.\.venv\Scripts\python scripts/run_reliability_replay.py --segments 8 --qt-ui --output data/reliability-new.json
```

真实模型回放只使用显式传入的已有本地目录，不自动下载权重。manifest 必须符合工具的公开 FLEURS 许可/来源与时长检查；使用授权的固定样本，不上传私人媒体。模型目录、精度、输入哈希与阶段统计进入报告，字幕正文不进入报告。

```powershell
.\.venv\Scripts\python scripts/run_local_pipeline_replay.py --manifest data/fleurs-m2/manifest.json --asr-directory models/local-whisper --mt-directory models/local-m2m100 --device cuda --compute-type float16 --output data/local-pipeline-new.json
```

上面的目录是占位示例，必须替换为本机已有模型；无模型时只跑合成工具。四语四方向小样本、1×注入、隐藏 Qt 窗口和单次模型加载不能冒充 12 方向质量、真实捕获到上屏或冷/热态对照。指标定义与验收边界见[验证索引](VERIFICATION.zh-CN.md)和[基准索引](benchmarks/README.md)。

## 构建与发布边界

源码整理默认只验证源码，不自动安装、不构建 EXE、不发版。如任务明确涉及发行构建，使用独立 `.release-venv` 与 [`packaging/requirements-release.lock`](../packaging/requirements-release.lock)，不能从开发环境混入系统包。

```powershell
# 明确需要验证冻结运行时才执行；此命令不发布 GitHub Release。
.\scripts\build_windows.ps1 -Version 0.3.3

# 明确需要安装器时才额外使用 -Installer。
```

不要把生产安装器换一个 `/DIR` 就当成隔离测试。安装回归必须采用独立 `SmokeTest` 标识与固定测试目录；不覆盖用户安装注册项/快捷方式，不递归删除用户目录。最终 EXE 自测验证打包后的运行库、SQLite 和媒体路径，并不采集真实音频或替代干净机器测试。

完整步骤、SBOM、安装回归与发布检查见 [RELEASE.md](RELEASE.md)。只有用户明确要求正式发版并完成相应验证时，才创建标签、上传发行物、核对下载与校验值；普通 GitHub 推送和 Windows CI 构建产物不是发行版。
