from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lingua_relay.audio import AudioProcessManager, WasapiDeviceManager
from lingua_relay.config import OverlaySettings, Settings
from lingua_relay.languages import SUPPORTED_LANGUAGES


class ColorButton(QPushButton):
    """Compact color picker that keeps a validated #RRGGBB value."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.clicked.connect(self._choose)
        self._refresh()

    def color(self) -> str:
        return self._color.name(QColor.NameFormat.HexRgb).upper()

    def set_color(self, color: str) -> None:
        resolved = QColor(color)
        if not resolved.isValid():
            raise ValueError(f"invalid color: {color}")
        self._color = resolved
        self._refresh()

    def _choose(self) -> None:
        selected = QColorDialog.getColor(self._color, self, "选择颜色")
        if selected.isValid():
            self._color = selected
            self._refresh()

    def _refresh(self) -> None:
        value = self.color()
        foreground = "#101218" if self._color.lightnessF() > 0.58 else "#FFFFFF"
        self.setText(value)
        self.setStyleSheet(
            f"QPushButton {{ background: {value}; color: {foreground}; "
            "border: 1px solid #667085; border-radius: 5px; padding: 5px 12px; }}"
        )


class SettingsDialog(QDialog):
    """User-facing settings editor for captions, appearance, and live cadence."""

    remove_models_requested = Signal()
    uninstall_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._initial = settings
        self._result = settings
        self.setWindowTitle("LinguaRelay · 用户设置")
        self.resize(700, 650)
        self.setMinimumSize(600, 560)

        root = QVBoxLayout(self)
        intro = QLabel("字幕外观会立即应用；标注为“下次启动”的实时参数需重启软件。")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #667085;")
        root.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "常规")
        tabs.addTab(self._build_audio_tab(), "音频源")
        tabs.addTab(self._build_appearance_tab(), "字幕外观")
        tabs.addTab(self._build_realtime_tab(), "识别与翻译")
        tabs.addTab(self._build_llm_tab(), "大模型")
        tabs.addTab(self._build_storage_tab(), "存储与卸载")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def result_settings(self) -> Settings:
        return self._result

    def realtime_changed(self) -> bool:
        return self._result.asr != self._initial.asr

    def correction_changed(self) -> bool:
        return self._result.correction != self._initial.correction

    def model_changed(self) -> bool:
        return (
            self._result.asr.model != self._initial.asr.model
            or self._result.translation.model != self._initial.translation.model
            or self._result.translation.model_path != self._initial.translation.model_path
        )

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.source_language = self._language_combo(self._initial.app.source_language)
        self.target_language = self._language_combo(self._initial.app.target_language)
        self.source_language.currentIndexChanged.connect(lambda: self._avoid_same_route(True))
        self.target_language.currentIndexChanged.connect(lambda: self._avoid_same_route(False))
        form.addRow("源语言", self.source_language)
        form.addRow("目标语言", self.target_language)

        self.display_mode = QComboBox()
        self.display_mode.addItem("双语同时显示", "bilingual")
        self.display_mode.addItem("仅显示译文", "translated")
        self._select_data(self.display_mode, self._initial.overlay.display_mode)
        form.addRow("字幕显示", self.display_mode)

        self.retention_seconds = QDoubleSpinBox()
        self.retention_seconds.setRange(0, 120)
        self.retention_seconds.setDecimals(1)
        self.retention_seconds.setSingleStep(0.5)
        self.retention_seconds.setSuffix(" 秒")
        self.retention_seconds.setSpecialValueText("一直保留")
        self.retention_seconds.setValue(self._initial.overlay.retention_seconds)
        form.addRow("字幕保留时间", self.retention_seconds)

        self.history_enabled = QCheckBox("保存字幕历史记录")
        self.history_enabled.setChecked(self._initial.app.history_enabled)
        form.addRow("历史记录", self.history_enabled)

        self.status_visible = QCheckBox("显示语言方向和处理状态")
        self.status_visible.setChecked(self._initial.overlay.status_visible)
        form.addRow("状态栏", self.status_visible)

        self.click_through = QCheckBox("让鼠标点击穿过悬浮窗")
        self.click_through.setChecked(self._initial.overlay.click_through)
        form.addRow("交互", self.click_through)
        return page

    def _build_audio_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        note = QLabel(
            "系统输出适合整台电脑；指定进程只捕获该进程及其子进程；麦克风适合会议发言。"
            "进程音频需要 Windows 10 2004 或更高版本，受 DRM 保护的音频可能无法捕获。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #175CD3; background: #EFF8FF; padding: 9px;")
        root.addWidget(note)
        form = QFormLayout()

        self.audio_source = QComboBox()
        self.audio_source.addItem("系统输出（所有应用）", "system")
        self.audio_source.addItem("指定进程及其子进程", "process")
        self.audio_source.addItem("麦克风", "microphone")
        self._select_data(self.audio_source, self._initial.audio.source)
        self.audio_source.currentIndexChanged.connect(self._update_audio_controls)
        form.addRow("捕获来源", self.audio_source)

        self.output_device = QComboBox()
        self.output_device.addItem("跟随系统默认输出设备", "default")
        self.microphone_device = QComboBox()
        self.microphone_device.addItem("跟随系统默认麦克风", "default")
        try:
            manager = WasapiDeviceManager()
            for device in manager.list_devices():
                self.output_device.addItem(device.name, device.device_id)
            for device in manager.list_microphones():
                self.microphone_device.addItem(device.name, device.device_id)
        except Exception as error:
            self.output_device.setToolTip(f"设备枚举失败：{error}")
            self.microphone_device.setToolTip(f"设备枚举失败：{error}")
        if self.output_device.findData(self._initial.audio.device) < 0:
            self.output_device.addItem(self._initial.audio.device, self._initial.audio.device)
        if self.microphone_device.findData(self._initial.audio.microphone_device) < 0:
            self.microphone_device.addItem(
                self._initial.audio.microphone_device,
                self._initial.audio.microphone_device,
            )
        self._select_data(self.output_device, self._initial.audio.device)
        self._select_data(self.microphone_device, self._initial.audio.microphone_device)
        form.addRow("系统输出设备", self.output_device)
        form.addRow("麦克风设备", self.microphone_device)

        process_row = QWidget()
        process_layout = QHBoxLayout(process_row)
        process_layout.setContentsMargins(0, 0, 0, 0)
        self.audio_process = QComboBox()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh_processes)
        process_layout.addWidget(self.audio_process, 1)
        process_layout.addWidget(refresh)
        form.addRow("目标进程", process_row)
        root.addLayout(form)
        self.audio_help = QLabel()
        self.audio_help.setWordWrap(True)
        self.audio_help.setStyleSheet("color: #667085;")
        root.addWidget(self.audio_help)
        root.addStretch(1)
        self._refresh_processes()
        self._update_audio_controls()
        return page

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.source_font = QFontComboBox()
        self.source_font.setCurrentFont(QFont(self._initial.overlay.source_font_family))
        self.source_size = self._font_size(self._initial.overlay.source_font_size)
        form.addRow("原文字体", self._font_row(self.source_font, self.source_size))
        self.source_color = ColorButton(self._initial.overlay.source_color)
        form.addRow("原文颜色", self.source_color)

        self.translation_font = QFontComboBox()
        self.translation_font.setCurrentFont(QFont(self._initial.overlay.translation_font_family))
        self.translation_size = self._font_size(self._initial.overlay.translation_font_size)
        form.addRow("译文字体", self._font_row(self.translation_font, self.translation_size))
        self.translation_color = ColorButton(self._initial.overlay.translation_color)
        form.addRow("译文颜色", self.translation_color)

        self.background_color = ColorButton(self._initial.overlay.background_color)
        form.addRow("背景颜色", self.background_color)
        self.background_opacity = self._percentage(
            self._initial.overlay.background_opacity, minimum=10
        )
        form.addRow("背景不透明度", self.background_opacity)
        self.window_opacity = self._percentage(self._initial.overlay.opacity)
        form.addRow("窗口整体不透明度", self.window_opacity)

        reset = QPushButton("恢复外观默认值")
        reset.clicked.connect(self._reset_appearance)
        form.addRow("", reset)
        return page

    def _build_realtime_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        note = QLabel(
            "以下参数影响识别切片和模型任务队列，保存后将在下次启动时生效。"
            "更短的间隔更及时，但会增加 CPU/GPU 占用。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9A6700; background: #FFF8C5; padding: 8px;")
        root.addWidget(note)
        form = QFormLayout()

        self.asr_model = QComboBox()
        self.asr_model.addItem("Base · 最低占用（约 140 MiB）", "base")
        self.asr_model.addItem("Small · 均衡推荐（约 460 MiB）", "small")
        self.asr_model.addItem("Medium · 更高准确率（约 1.5 GiB）", "medium")
        self.asr_model.addItem("Large-v3 Turbo · 高质量低延迟（约 1.6 GiB）", "large-v3-turbo")
        if self.asr_model.findData(self._initial.asr.model) < 0:
            self.asr_model.addItem(f"自定义：{self._initial.asr.model}", self._initial.asr.model)
        self._select_data(self.asr_model, self._initial.asr.model)
        self.asr_model.currentIndexChanged.connect(self._update_model_guidance)
        form.addRow("识别模型", self.asr_model)

        self.asr_quality = QComboBox()
        self.asr_quality.addItem("极速 · 贪心解码", "fast")
        self.asr_quality.addItem("均衡 · 抑制重复（推荐）", "balanced")
        self.asr_quality.addItem("精确 · Beam 5", "accurate")
        self._select_data(
            self.asr_quality,
            "accurate"
            if self._initial.asr.beam_size >= 5
            else "balanced"
            if self._initial.asr.repetition_penalty > 1
            else "fast",
        )
        form.addRow("识别解码", self.asr_quality)

        runtime = QWidget()
        runtime_layout = QHBoxLayout(runtime)
        runtime_layout.setContentsMargins(0, 0, 0, 0)
        self.asr_device = QComboBox()
        for label, value in (("自动", "auto"), ("CPU", "cpu"), ("NVIDIA GPU", "cuda")):
            self.asr_device.addItem(label, value)
        self._select_data(self.asr_device, self._initial.asr.device)
        self.asr_compute = QComboBox()
        for label, value in (
            ("自动精度", "auto"),
            ("INT8", "int8"),
            ("FP16", "float16"),
            ("INT8 + FP16", "int8_float16"),
            ("FP32", "float32"),
        ):
            self.asr_compute.addItem(label, value)
        self._select_data(self.asr_compute, self._initial.asr.compute_type)
        runtime_layout.addWidget(self.asr_device)
        runtime_layout.addWidget(self.asr_compute)
        form.addRow("识别硬件", runtime)

        self.translation_model = QComboBox()
        self.translation_model.addItem(
            "M2M100 418M · 快速本地翻译（约 910 MiB）", "facebook/m2m100_418M"
        )
        self.translation_model.addItem(
            "M2M100 1.2B · 高质量本地翻译（约 2.5 GiB）", "facebook/m2m100_1.2B"
        )
        if self.translation_model.findData(self._initial.translation.model) < 0:
            self.translation_model.addItem(
                f"自定义：{self._initial.translation.model}", self._initial.translation.model
            )
        self._select_data(self.translation_model, self._initial.translation.model)
        self.translation_model.currentIndexChanged.connect(self._update_model_guidance)
        form.addRow("翻译模型", self.translation_model)

        self.translation_quality = QComboBox()
        self.translation_quality.addItem("极速 · Beam 1", "fast")
        self.translation_quality.addItem("均衡 · Beam 2（推荐）", "balanced")
        self.translation_quality.addItem("精确 · Beam 4", "accurate")
        self._select_data(
            self.translation_quality,
            "accurate"
            if self._initial.translation.beam_size >= 4
            else "balanced"
            if self._initial.translation.beam_size >= 2
            else "fast",
        )
        form.addRow("翻译解码", self.translation_quality)

        self.model_guidance = QLabel()
        self.model_guidance.setWordWrap(True)
        self.model_guidance.setStyleSheet("color: #667085;")
        form.addRow("选择建议", self.model_guidance)

        self.latency_profile = QComboBox()
        self.latency_profile.addItem("平衡（推荐）", "balanced")
        self.latency_profile.addItem("极速字幕", "realtime")
        self.latency_profile.addItem("省资源", "efficient")
        self.latency_profile.addItem("自定义", "custom")
        self.latency_profile.currentIndexChanged.connect(self._apply_latency_profile)
        form.addRow("使用方案", self.latency_profile)

        self.partial_interval = QComboBox()
        for value in (320, 640, 960, 1280):
            self.partial_interval.addItem(f"{value} 毫秒", value)
        if self.partial_interval.findData(self._initial.asr.partial_interval_ms) < 0:
            self.partial_interval.addItem(
                f"{self._initial.asr.partial_interval_ms} 毫秒",
                self._initial.asr.partial_interval_ms,
            )
        self._select_data(self.partial_interval, self._initial.asr.partial_interval_ms)
        form.addRow("增量识别间隔", self.partial_interval)

        self.adaptive_partial = QCheckBox("长语音自动降低重复识别频率，避免队列积压")
        self.adaptive_partial.setChecked(self._initial.asr.adaptive_partial_enabled)
        form.addRow("自适应刷新", self.adaptive_partial)

        self.punctuation_enabled = QCheckBox("稳定结果出现句末标点时立即断句")
        self.punctuation_enabled.setChecked(self._initial.asr.punctuation_boundary_enabled)
        form.addRow("标点断句", self.punctuation_enabled)

        self.punctuation_min = QDoubleSpinBox()
        self.punctuation_min.setRange(0.32, 5.0)
        self.punctuation_min.setDecimals(2)
        self.punctuation_min.setSingleStep(0.1)
        self.punctuation_min.setSuffix(" 秒")
        self.punctuation_min.setValue(self._initial.asr.punctuation_boundary_min_seconds)
        form.addRow("标点断句最短语音", self.punctuation_min)

        self.preferred_segment = QDoubleSpinBox()
        self.preferred_segment.setRange(1.0, 10.0)
        self.preferred_segment.setDecimals(1)
        self.preferred_segment.setSingleStep(0.5)
        self.preferred_segment.setSuffix(" 秒")
        self.preferred_segment.setValue(self._initial.asr.preferred_segment_seconds)
        form.addRow("优先切段时长", self.preferred_segment)

        self.max_caption = QDoubleSpinBox()
        self.max_caption.setRange(2.0, 10.0)
        self.max_caption.setDecimals(1)
        self.max_caption.setSingleStep(0.5)
        self.max_caption.setSuffix(" 秒")
        self.max_caption.setValue(self._initial.asr.max_caption_seconds)
        form.addRow("单条字幕最长时长", self.max_caption)

        self.suppress_credits = QCheckBox("过滤“字幕制作人 / Subtitles by”等模板化误识别")
        self.suppress_credits.setChecked(self._initial.asr.suppress_credit_hallucinations)
        form.addRow("幻觉抑制", self.suppress_credits)

        self.context_hint = QPlainTextEdit()
        self.context_hint.setPlainText(self._initial.asr.context_hint)
        self.context_hint.setPlaceholderText(
            "可选：会议主题、参会者姓名、产品名和专业术语。不要填写密码或敏感信息。"
        )
        self.context_hint.setMaximumHeight(88)
        form.addRow("识别上下文", self.context_hint)
        root.addLayout(form)
        root.addStretch(1)
        self._select_latency_profile()
        self._update_model_guidance()
        return page

    def _build_llm_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        note = QLabel(
            "大模型只负责异步修正，不会阻塞本地识别与快速翻译。推荐先使用“完整句异步修正”；"
            "云端模式会把字幕和少量上下文发送到所填 API。API 密钥只从环境变量读取，不写入配置文件。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #175CD3; background: #EFF8FF; padding: 9px;")
        root.addWidget(note)
        form = QFormLayout()

        self.llm_mode = QComboBox()
        self.llm_mode.addItem("关闭", "off")
        self.llm_mode.addItem("完整句异步修正（推荐）", "asynchronous")
        self.llm_mode.addItem("临时字幕也异步修正（更耗资源）", "live")
        self._select_data(self.llm_mode, self._initial.correction.mode)
        form.addRow("修正方式", self.llm_mode)

        self.llm_provider = QComboBox()
        self.llm_provider.addItem("不接入大模型", "none")
        self.llm_provider.addItem("本地 OpenAI 兼容服务", "local")
        self.llm_provider.addItem("云端 OpenAI 兼容 API", "openai_compatible")
        self._select_data(self.llm_provider, self._initial.correction.provider)
        self.llm_provider.currentIndexChanged.connect(self._update_llm_controls)
        form.addRow("服务类型", self.llm_provider)

        presets = QWidget()
        preset_layout = QHBoxLayout(presets)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        ollama = QPushButton("Ollama 本地")
        ollama.clicked.connect(lambda: self._apply_llm_preset("local", "http://127.0.0.1:11434/v1"))
        lm_studio = QPushButton("LM Studio 本地")
        lm_studio.clicked.connect(
            lambda: self._apply_llm_preset("local", "http://127.0.0.1:1234/v1")
        )
        presets.layout().addWidget(ollama)
        presets.layout().addWidget(lm_studio)
        presets.layout().addStretch(1)
        form.addRow("快速预设", presets)

        self.llm_endpoint = QLineEdit(self._initial.correction.endpoint)
        self.llm_endpoint.setPlaceholderText("例如 http://127.0.0.1:11434/v1 或 https://…/v1")
        form.addRow("API 地址", self.llm_endpoint)
        self.llm_model = QLineEdit(self._initial.correction.model)
        self.llm_model.setPlaceholderText("填写服务端显示的模型 ID")
        form.addRow("模型 ID", self.llm_model)
        self.llm_api_key_env = QLineEdit(self._initial.correction.api_key_env)
        self.llm_api_key_env.setPlaceholderText("LINGUA_RELAY_API_KEY")
        form.addRow("密钥环境变量", self.llm_api_key_env)

        self.llm_context = QSpinBox()
        self.llm_context.setRange(0, 20)
        self.llm_context.setValue(self._initial.correction.context_segments)
        self.llm_context.setSuffix(" 条")
        form.addRow("参考前文", self.llm_context)
        self.llm_timeout = QDoubleSpinBox()
        self.llm_timeout.setRange(1, 60)
        self.llm_timeout.setValue(self._initial.correction.timeout_seconds)
        self.llm_timeout.setSuffix(" 秒")
        form.addRow("请求超时", self.llm_timeout)
        self.llm_rpm = QSpinBox()
        self.llm_rpm.setRange(1, 600)
        self.llm_rpm.setValue(self._initial.correction.requests_per_minute)
        self.llm_rpm.setSuffix(" 次/分")
        form.addRow("速率上限", self.llm_rpm)
        self.llm_max_tokens = QSpinBox()
        self.llm_max_tokens.setRange(64, 4096)
        self.llm_max_tokens.setValue(self._initial.correction.max_tokens)
        form.addRow("最大输出 Token", self.llm_max_tokens)
        self.llm_temperature = QDoubleSpinBox()
        self.llm_temperature.setRange(0, 2)
        self.llm_temperature.setDecimals(2)
        self.llm_temperature.setSingleStep(0.05)
        self.llm_temperature.setValue(self._initial.correction.temperature)
        form.addRow("温度", self.llm_temperature)
        root.addLayout(form)
        key_help = QLabel(
            "云端密钥示例：先在 PowerShell 设置 $env:LINGUA_RELAY_API_KEY='…'，再从同一终端启动；"
            "如需长期使用，请设置 Windows 用户环境变量并重新启动 LinguaRelay。"
        )
        key_help.setWordWrap(True)
        key_help.setStyleSheet("color: #667085;")
        root.addWidget(key_help)
        root.addStretch(1)
        self._update_llm_controls()
        return page

    def _build_storage_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        model_title = QLabel("本地模型")
        model_title.setStyleSheet("font-weight: 600; font-size: 15px;")
        root.addWidget(model_title)
        model_note = QLabel(
            "删除当前语音识别与翻译模型可释放约 1.05–1.36 GiB 空间。配置和字幕历史不会被删除；"
            "下次启动时可以重新选择现有模型或下载模型包。"
        )
        model_note.setWordWrap(True)
        root.addWidget(model_note)
        self.remove_models_button = QPushButton("删除本地模型并退出…")
        self.remove_models_button.clicked.connect(self._request_model_removal)
        root.addWidget(self.remove_models_button)

        uninstall_title = QLabel("卸载应用")
        uninstall_title.setStyleSheet("font-weight: 600; font-size: 15px; margin-top: 18px;")
        root.addWidget(uninstall_title)
        uninstall_note = QLabel(
            "启动 Windows 卸载程序。卸载时可以选择是否同时删除本地模型；配置和字幕历史默认保留。"
        )
        uninstall_note.setWordWrap(True)
        root.addWidget(uninstall_note)
        self.uninstall_button = QPushButton("卸载 LinguaRelay…")
        self.uninstall_button.clicked.connect(self._request_uninstall)
        root.addWidget(self.uninstall_button)
        root.addStretch(1)
        return page

    def _request_model_removal(self) -> None:
        self.reject()
        self.remove_models_requested.emit()

    def _request_uninstall(self) -> None:
        self.reject()
        self.uninstall_requested.emit()

    def accept(self) -> None:
        try:
            candidate = self._collect()
            candidate.validate()
        except ValueError as error:
            QMessageBox.warning(self, "设置无效", str(error))
            return
        self._result = candidate
        super().accept()

    def _collect(self) -> Settings:
        overlay = replace(
            self._initial.overlay,
            display_mode=str(self.display_mode.currentData()),
            retention_seconds=self.retention_seconds.value(),
            status_visible=self.status_visible.isChecked(),
            click_through=self.click_through.isChecked(),
            source_font_family=self.source_font.currentFont().family(),
            source_font_size=self.source_size.value(),
            source_color=self.source_color.color(),
            translation_font_family=self.translation_font.currentFont().family(),
            translation_font_size=self.translation_size.value(),
            translation_color=self.translation_color.color(),
            background_color=self.background_color.color(),
            background_opacity=self.background_opacity.value() / 100,
            opacity=self.window_opacity.value() / 100,
        )
        asr_quality = {
            "fast": (1, 1.0, 0),
            "balanced": (1, 1.05, 3),
            "accurate": (5, 1.08, 3),
        }[str(self.asr_quality.currentData())]
        asr = replace(
            self._initial.asr,
            model=str(self.asr_model.currentData()),
            revision="",
            device=str(self.asr_device.currentData()),
            compute_type=str(self.asr_compute.currentData()),
            beam_size=asr_quality[0],
            repetition_penalty=asr_quality[1],
            no_repeat_ngram_size=asr_quality[2],
            partial_interval_ms=int(self.partial_interval.currentData()),
            adaptive_partial_enabled=self.adaptive_partial.isChecked(),
            punctuation_boundary_enabled=self.punctuation_enabled.isChecked(),
            punctuation_boundary_min_seconds=self.punctuation_min.value(),
            preferred_segment_seconds=self.preferred_segment.value(),
            max_caption_seconds=self.max_caption.value(),
            max_window_seconds=self.max_caption.value(),
            max_segment_seconds=self.max_caption.value(),
            suppress_credit_hallucinations=self.suppress_credits.isChecked(),
            context_hint=self.context_hint.toPlainText().strip(),
        )
        process_data = self.audio_process.currentData()
        process_id, process_name = (
            (int(process_data[0]), str(process_data[1]))
            if isinstance(process_data, tuple) and len(process_data) == 2
            else (self._initial.audio.process_id, self._initial.audio.process_name)
        )
        audio = replace(
            self._initial.audio,
            source=str(self.audio_source.currentData()),
            device=str(self.output_device.currentData()),
            microphone_device=str(self.microphone_device.currentData()),
            process_id=process_id,
            process_name=process_name,
        )
        translation_model = str(self.translation_model.currentData())
        translation_quality = {"fast": 1, "balanced": 2, "accurate": 4}[
            str(self.translation_quality.currentData())
        ]
        if translation_model == "facebook/m2m100_1.2B":
            translation_path = self._initial.translation.model_path.parent / "m2m100_1.2b_ct2"
            translation_revision = "59ab27e0af8c91c3e31de75be965167ce09e0038"
        elif translation_model == "facebook/m2m100_418M":
            translation_path = self._initial.translation.model_path.parent / "m2m100_418m_ct2"
            translation_revision = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
        else:
            translation_path = self._initial.translation.model_path
            translation_revision = self._initial.translation.revision
        translation = replace(
            self._initial.translation,
            model=translation_model,
            revision=translation_revision,
            model_path=translation_path,
            beam_size=translation_quality,
            repetition_penalty=1.05 if translation_quality > 1 else 1.0,
            no_repeat_ngram_size=3 if translation_quality > 1 else 0,
        )
        app = replace(
            self._initial.app,
            source_language=str(self.source_language.currentData()),
            target_language=str(self.target_language.currentData()),
            history_enabled=self.history_enabled.isChecked(),
        )
        provider = str(self.llm_provider.currentData())
        correction = replace(
            self._initial.correction,
            mode="off" if provider == "none" else str(self.llm_mode.currentData()),
            provider=provider,
            endpoint=self.llm_endpoint.text().strip(),
            model=self.llm_model.text().strip(),
            api_key_env=self.llm_api_key_env.text().strip(),
            context_segments=self.llm_context.value(),
            timeout_seconds=self.llm_timeout.value(),
            requests_per_minute=self.llm_rpm.value(),
            max_tokens=self.llm_max_tokens.value(),
            temperature=self.llm_temperature.value(),
        )
        return replace(
            self._initial,
            app=app,
            overlay=overlay,
            audio=audio,
            asr=asr,
            translation=translation,
            correction=correction,
        )

    def _refresh_processes(self) -> None:
        if not hasattr(self, "audio_process"):
            return
        current = self.audio_process.currentData()
        wanted_id = self._initial.audio.process_id
        self.audio_process.clear()
        try:
            processes = AudioProcessManager().list_processes()
        except Exception as error:
            self.audio_process.addItem(f"无法读取进程：{error}", None)
            return
        for process in processes:
            self.audio_process.addItem(
                f"{process.name}  ·  PID {process.process_id}",
                (process.process_id, process.name),
            )
        selected = current if current is not None else (wanted_id, self._initial.audio.process_name)
        index = self.audio_process.findData(selected)
        if index < 0 and wanted_id:
            self.audio_process.addItem(
                f"{self._initial.audio.process_name or '未运行'}  ·  PID {wanted_id}",
                (wanted_id, self._initial.audio.process_name),
            )
            index = self.audio_process.count() - 1
        if index >= 0:
            self.audio_process.setCurrentIndex(index)

    def _update_audio_controls(self) -> None:
        source = str(self.audio_source.currentData())
        self.output_device.setEnabled(source == "system")
        self.microphone_device.setEnabled(source == "microphone")
        self.audio_process.setEnabled(source == "process")
        help_text = {
            "system": "捕获电脑当前播放的所有声音；切换默认输出设备后会自动重连。",
            "microphone": (
                "使用独立 WASAPI 输入，适合现场发言；建议在 Windows 声音设置中启用降噪与回声消除。"
            ),
            "process": "只捕获所选进程及其子进程。应用重启后会按进程名自动寻找新 PID。",
        }[source]
        self.audio_help.setText(help_text)

    def _update_model_guidance(self) -> None:
        if not hasattr(self, "model_guidance"):
            return
        asr_model = str(self.asr_model.currentData())
        translation_model = str(self.translation_model.currentData())
        if asr_model in {"medium", "large-v3-turbo"}:
            asr_text = "高级识别模型建议使用 NVIDIA GPU；纯 CPU 也能运行，但延迟和占用会明显提高。"
        else:
            asr_text = "Base 速度优先，Small 在中/日/英/韩四语上通常更稳。"
        if translation_model.endswith("1.2B"):
            mt_text = "1.2B 翻译模型需额外下载约 2.5 GiB，并建议至少 16 GB 内存。"
        else:
            mt_text = "418M 翻译模型延迟最低，适合实时字幕。"
        self.model_guidance.setText(asr_text + " " + mt_text)

    def _select_latency_profile(self) -> None:
        current = (
            self._initial.asr.partial_interval_ms,
            self._initial.asr.adaptive_partial_enabled,
            round(self._initial.asr.preferred_segment_seconds, 1),
            round(self._initial.asr.max_caption_seconds, 1),
        )
        profiles = {
            (320, True, 3.2, 6.0): "balanced",
            (320, False, 2.4, 4.0): "realtime",
            (640, True, 4.8, 8.0): "efficient",
        }
        self._select_data(self.latency_profile, profiles.get(current, "custom"))

    def _apply_latency_profile(self) -> None:
        profile = self.latency_profile.currentData()
        values = {
            "balanced": (320, True, 3.2, 6.0),
            "realtime": (320, False, 2.4, 4.0),
            "efficient": (640, True, 4.8, 8.0),
        }.get(profile)
        if values is None or not hasattr(self, "partial_interval"):
            return
        interval, adaptive, preferred, maximum = values
        self._select_data(self.partial_interval, interval)
        self.adaptive_partial.setChecked(adaptive)
        self.preferred_segment.setValue(preferred)
        self.max_caption.setValue(maximum)

    def _apply_llm_preset(self, provider: str, endpoint: str) -> None:
        self._select_data(self.llm_provider, provider)
        self.llm_endpoint.setText(endpoint)
        if self.llm_mode.currentData() == "off":
            self._select_data(self.llm_mode, "asynchronous")
        self.llm_model.setFocus()

    def _update_llm_controls(self) -> None:
        enabled = self.llm_provider.currentData() != "none"
        for control in (
            self.llm_mode,
            self.llm_endpoint,
            self.llm_model,
            self.llm_api_key_env,
            self.llm_context,
            self.llm_timeout,
            self.llm_rpm,
            self.llm_max_tokens,
            self.llm_temperature,
        ):
            control.setEnabled(enabled)

    def _avoid_same_route(self, source_changed: bool) -> None:
        if self.source_language.currentData() != self.target_language.currentData():
            return
        combo = self.target_language if source_changed else self.source_language
        combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())

    def _reset_appearance(self) -> None:
        defaults = OverlaySettings()
        self.source_font.setCurrentFont(QFont(defaults.source_font_family))
        self.source_size.setValue(defaults.source_font_size)
        self.source_color.set_color(defaults.source_color)
        self.translation_font.setCurrentFont(QFont(defaults.translation_font_family))
        self.translation_size.setValue(defaults.translation_font_size)
        self.translation_color.set_color(defaults.translation_color)
        self.background_color.set_color(defaults.background_color)
        self.background_opacity.setValue(round(defaults.background_opacity * 100))
        self.window_opacity.setValue(round(defaults.opacity * 100))

    @staticmethod
    def _language_combo(current: str) -> QComboBox:
        combo = QComboBox()
        for code, language in SUPPORTED_LANGUAGES.items():
            combo.addItem(f"{language.native_name} ({code})", code)
        SettingsDialog._select_data(combo, current)
        return combo

    @staticmethod
    def _select_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _font_size(value: int) -> QSpinBox:
        control = QSpinBox()
        control.setRange(8, 72)
        control.setSuffix(" pt")
        control.setValue(value)
        return control

    @staticmethod
    def _font_row(font: QFontComboBox, size: QSpinBox) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(font, 1)
        layout.addWidget(size)
        return container

    @staticmethod
    def _percentage(value: float, *, minimum: int = 20) -> QSpinBox:
        control = QSpinBox()
        control.setRange(minimum, 100)
        control.setSuffix(" %")
        control.setValue(round(value * 100))
        return control
