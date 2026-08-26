from __future__ import annotations

import wave
from contextlib import suppress
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPolygonF
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lingua_relay.languages import SUPPORTED_LANGUAGES
from lingua_relay.offline.processor import ProcessingOptions
from lingua_relay.offline.project import Cue, OfflineProjectStore


class WaveformWidget(QWidget):
    seek_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(74)
        self._peaks = np.zeros(0, dtype=np.float32)
        self._duration_ms = 0
        self._position_ms = 0

    def load(self, path: Path | None) -> None:
        self._peaks = np.zeros(0, dtype=np.float32)
        self._duration_ms = 0
        if path and path.suffix.lower() == ".wav" and path.is_file():
            try:
                with wave.open(str(path), "rb") as stream:
                    count = stream.getnframes()
                    rate = stream.getframerate()
                    channels = stream.getnchannels()
                    width = stream.getsampwidth()
                    if width == 2:
                        bin_count = min(1200, max(1, count // 256))
                        frames_per_bin = max(1, count // bin_count)
                        peaks: list[float] = []
                        while len(peaks) < bin_count:
                            raw = stream.readframes(frames_per_bin)
                            if not raw:
                                break
                            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
                            if channels > 1:
                                usable = len(samples) - len(samples) % channels
                                samples = samples[:usable].reshape(-1, channels).mean(axis=1)
                            if len(samples):
                                peaks.append(float(np.max(np.abs(samples))) / 32768.0)
                        self._peaks = np.asarray(peaks, dtype=np.float32)
                    self._duration_ms = round(count * 1000 / rate)
            except (OSError, wave.Error, ValueError):
                pass
        self.update()

    def set_position(self, milliseconds: int) -> None:
        self._position_ms = milliseconds
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111827"))
        if not len(self._peaks):
            painter.setPen(QColor("#667085"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "音频波形")
            return
        middle = self.height() / 2
        x_scale = self.width() / max(1, len(self._peaks) - 1)
        y_scale = self.height() * 0.42
        upper = [
            QPointF(index * x_scale, middle - peak * y_scale)
            for index, peak in enumerate(self._peaks)
        ]
        lower = [
            QPointF(index * x_scale, middle + peak * y_scale)
            for index, peak in reversed(tuple(enumerate(self._peaks)))
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#4f8cff"))
        painter.drawPolygon(QPolygonF(upper + lower))
        if self._duration_ms:
            x = self.width() * self._position_ms / self._duration_ms
            painter.setPen(QPen(QColor("#ffcb66"), 2))
            painter.drawLine(round(x), 0, round(x), self.height())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._duration_ms and event.button() == Qt.MouseButton.LeftButton:
            position = round(self._duration_ms * event.position().x() / max(1, self.width()))
            self.seek_requested.emit(max(0, min(self._duration_ms, position)))


class OfflineWorkbench(QMainWindow):
    import_audio_requested = Signal()
    import_video_requested = Signal()
    process_requested = Signal(str, object)
    export_requested = Signal(str, str)

    def __init__(self, store: OfflineProjectStore, icon: QIcon | None = None) -> None:
        super().__init__()
        self.store = store
        self._project_id: str | None = None
        self._loading_cues = False
        self._loading_project = False
        self.setWindowTitle("LinguaRelay · 录制与离线工作台")
        self.resize(1180, 720)
        if icon:
            self.setWindowIcon(icon)
        self.audio_output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self._build_ui()
        self._connect_player()
        self.refresh()

    @property
    def current_project_id(self) -> str | None:
        return self._project_id

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        toolbar = QHBoxLayout()
        audio_button = QPushButton("导入音频")
        video_button = QPushButton("导入视频")
        audio_button.clicked.connect(self.import_audio_requested.emit)
        video_button.clicked.connect(self.import_video_requested.emit)
        toolbar.addWidget(audio_button)
        toolbar.addWidget(video_button)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("识别模型"))
        self.model_combo = QComboBox()
        self.model_combo.addItem("Base · 最快 / 入门电脑", "base")
        self.model_combo.addItem("Small · 日常均衡", "small")
        self.model_combo.addItem("Medium · 更准确", "medium")
        self.model_combo.addItem("Large-v3 Turbo · 推荐", "large-v3-turbo")
        self.model_combo.addItem("Large-v3 · 最高准确度", "large-v3")
        self.model_combo.setCurrentIndex(3)
        self.model_combo.setToolTip(
            "Turbo 适合大多数电脑；Large-v3 更慢且占用更高，适合有独显或短音频精修。"
        )
        toolbar.addWidget(self.model_combo, 1)
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("快速", "fast")
        self.quality_combo.addItem("均衡", "balanced")
        self.quality_combo.addItem("精确", "accurate")
        self.quality_combo.setCurrentIndex(1)
        toolbar.addWidget(self.quality_combo)
        self.llm_checkbox = QCheckBox("大模型精修")
        self.llm_checkbox.setToolTip("使用“用户设置 → 大模型”中配置的本地或 API 服务逐句精修")
        toolbar.addWidget(self.llm_checkbox)
        self.process_button = QPushButton("开始后期处理")
        self.process_button.clicked.connect(self._request_process)
        toolbar.addWidget(self.process_button)
        self.export_button = QPushButton("导出…")
        self.export_button.clicked.connect(self._request_export)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)
        route_row = QHBoxLayout()
        route_row.addWidget(QLabel("项目语言"))
        self.source_language = QComboBox()
        self.target_language = QComboBox()
        for code, language in SUPPORTED_LANGUAGES.items():
            label = f"{language.native_name} ({code})"
            self.source_language.addItem(label, code)
            self.target_language.addItem(label, code)
        self.source_language.currentIndexChanged.connect(self._route_changed)
        self.target_language.currentIndexChanged.connect(self._route_changed)
        route_row.addWidget(self.source_language)
        route_row.addWidget(QLabel("→"))
        route_row.addWidget(self.target_language)
        route_note = QLabel("处理前可单独设置；源语言仍不自动检测")
        route_note.setStyleSheet("color: #667085;")
        route_row.addWidget(route_note)
        route_row.addStretch(1)
        layout.addLayout(route_row)

        splitter = QSplitter()
        self.projects = QListWidget()
        self.projects.setMinimumWidth(265)
        self.projects.currentItemChanged.connect(self._select_project)
        splitter.addWidget(self.projects)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.title = QLabel("请选择项目")
        self.title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.meta = QLabel("")
        self.meta.setStyleSheet("color: #667085;")
        detail_layout.addWidget(self.title)
        detail_layout.addWidget(self.meta)
        self.waveform = WaveformWidget()
        self.waveform.seek_requested.connect(self.player.setPosition)
        detail_layout.addWidget(self.waveform)
        transport = QHBoxLayout()
        self.play_button = QPushButton("▶ 播放")
        self.play_button.clicked.connect(self._toggle_playback)
        self.position = QLabel("00:00.000 / 00:00.000")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.sliderMoved.connect(self.player.setPosition)
        transport.addWidget(self.play_button)
        transport.addWidget(self.position)
        transport.addWidget(self.seek, 1)
        detail_layout.addLayout(transport)

        self.cues = QTableWidget(0, 4)
        self.cues.setHorizontalHeaderLabels(("开始", "结束", "原文", "译文"))
        header = self.cues.horizontalHeader()
        header.resizeSection(0, 105)
        header.resizeSection(1, 105)
        header.setStretchLastSection(True)
        self.cues.setColumnWidth(2, 330)
        self.cues.itemChanged.connect(self._cue_changed)
        self.cues.cellClicked.connect(self._cue_clicked)
        detail_layout.addWidget(self.cues, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress_label = QLabel("就绪")
        status_row = QHBoxLayout()
        status_row.addWidget(self.progress, 1)
        status_row.addWidget(self.progress_label)
        detail_layout.addLayout(status_row)
        splitter.addWidget(detail)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def _connect_player(self) -> None:
        self.player.positionChanged.connect(self._player_position)
        self.player.durationChanged.connect(lambda value: self.seek.setRange(0, value))
        self.player.playbackStateChanged.connect(
            lambda state: self.play_button.setText(
                "Ⅱ 暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "▶ 播放"
            )
        )

    def refresh(self, *, select_id: str | None = None) -> None:
        desired = select_id or self._project_id
        self.projects.clear()
        selected: QListWidgetItem | None = None
        for project in self.store.list_projects():
            label = (
                f"{_status_icon(project.status)}  {project.title}\n"
                f"{_kind_label(project.kind)} · {_duration(project.duration_ms)}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            item.setToolTip(project.error or project.status)
            self.projects.addItem(item)
            if project.id == desired:
                selected = item
        if selected is not None:
            self.projects.setCurrentItem(selected)
        elif self.projects.count():
            self.projects.setCurrentRow(0)
        else:
            self._project_id = None
            self._show_empty()

    def update_progress(self, project_id: str, value: float, message: str) -> None:
        if project_id == self._project_id:
            self.progress.setValue(round(max(0.0, min(1.0, value)) * 1000))
            self.progress_label.setText(message)

    def processing_options(self) -> ProcessingOptions:
        return ProcessingOptions(
            asr_model=str(self.model_combo.currentData()),
            quality=str(self.quality_combo.currentData()),
            use_llm=self.llm_checkbox.isChecked(),
        )

    def processing_finished(self, project_id: str, error: str = "") -> None:
        self.process_button.setEnabled(True)
        if error:
            QMessageBox.critical(self, "后期处理失败", error)
        self.refresh(select_id=project_id)

    def _select_project(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        project_id = str(current.data(Qt.ItemDataRole.UserRole))
        self._project_id = project_id
        project = self.store.get_project(project_id)
        self._loading_project = True
        self.source_language.setCurrentIndex(
            max(0, self.source_language.findData(project.source_language))
        )
        self.target_language.setCurrentIndex(
            max(0, self.target_language.findData(project.target_language))
        )
        self._loading_project = False
        self.title.setText(project.title)
        self.meta.setText(
            f"{_kind_label(project.kind)} · {project.source_language.upper()} → "
            f"{project.target_language.upper()} · {_status_label(project.status)} · "
            f"{_duration(project.duration_ms)}" + (f" · {project.error}" if project.error else "")
        )
        if project.audio_path and project.audio_path.is_file():
            self.player.setSource(QUrl.fromLocalFile(str(project.audio_path)))
            self.waveform.load(project.audio_path)
        else:
            self.player.setSource(QUrl())
            self.waveform.load(None)
        self.progress.setValue(round(project.progress * 1000))
        self.progress_label.setText(_status_label(project.status))
        self._load_cues(self.store.list_cues(project_id))

    def _route_changed(self) -> None:
        if self._loading_project or not self._project_id:
            return
        source = str(self.source_language.currentData())
        target = str(self.target_language.currentData())
        if source == target:
            self._loading_project = True
            target = next(code for code in SUPPORTED_LANGUAGES if code != source)
            self.target_language.setCurrentIndex(self.target_language.findData(target))
            self._loading_project = False
        project = self.store.update_project(
            self._project_id,
            source_language=source,
            target_language=target,
            status="ready",
            progress=0,
            error="",
        )
        self.meta.setText(
            f"{_kind_label(project.kind)} · {source.upper()} → {target.upper()} · "
            f"{_status_label(project.status)} · {_duration(project.duration_ms)}"
        )

    def _load_cues(self, cues: tuple[Cue, ...]) -> None:
        self._loading_cues = True
        self.cues.setRowCount(len(cues))
        for row, cue in enumerate(cues):
            values = (
                _clock(cue.start_ms),
                _clock(cue.end_ms),
                cue.source_text,
                cue.translated_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, cue.id)
                self.cues.setItem(row, column, item)
        self._loading_cues = False

    def _cue_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_cues:
            return
        row = item.row()
        try:
            cue_id = int(self.cues.item(row, 0).data(Qt.ItemDataRole.UserRole))
            self.store.update_cue(
                cue_id,
                start_ms=_parse_clock(self.cues.item(row, 0).text()),
                end_ms=_parse_clock(self.cues.item(row, 1).text()),
                source_text=self.cues.item(row, 2).text(),
                translated_text=self.cues.item(row, 3).text(),
            )
        except Exception as error:
            self.progress_label.setText(f"编辑未保存：{error}")

    def _cue_clicked(self, row: int, _column: int) -> None:
        with suppress(ValueError):
            self.player.setPosition(_parse_clock(self.cues.item(row, 0).text()))

    def _request_process(self) -> None:
        if not self._project_id:
            return
        self.process_button.setEnabled(False)
        self.process_requested.emit(self._project_id, self.processing_options())

    def _request_export(self) -> None:
        if not self._project_id:
            return
        project = self.store.get_project(self._project_id)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出离线项目",
            str(Path.home() / f"{project.title}.vtt"),
            "WebVTT (*.vtt);;SubRip (*.srt);;ASS 字幕 (*.ass);;纯文本 (*.txt);;"
            "CSV (*.csv);;JSON Lines (*.jsonl);;MP3 音频 (*.mp3);;"
            "WAV 音频 (*.wav);;FLAC 音频 (*.flac)",
        )
        if path:
            self.export_requested.emit(self._project_id, path)

    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _player_position(self, value: int) -> None:
        self.seek.setValue(value)
        self.waveform.set_position(value)
        self.position.setText(f"{_clock(value)} / {_clock(self.player.duration())}")

    def _show_empty(self) -> None:
        self.title.setText("还没有离线项目")
        self.meta.setText("可从悬浮窗开始录制，或在此导入音频/视频。")
        self.cues.setRowCount(0)
        self.waveform.load(None)


def _clock(milliseconds: int) -> str:
    minutes, remainder = divmod(max(0, milliseconds), 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _parse_clock(value: str) -> int:
    try:
        minutes_text, rest = value.strip().split(":", 1)
        seconds_text, millis_text = rest.split(".", 1)
        return int(minutes_text) * 60_000 + int(seconds_text) * 1000 + int(millis_text[:3])
    except (ValueError, IndexError) as error:
        raise ValueError("时间应为 MM:SS.mmm") from error


def _duration(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def _kind_label(kind: str) -> str:
    return {"recording": "录制", "audio": "音频", "video": "视频"}.get(kind, kind)


def _status_icon(status: str) -> str:
    return {
        "recording": "●",
        "recording_paused": "Ⅱ",
        "processing": "◌",
        "completed": "✓",
        "failed": "!",
    }.get(status, "○")


def _status_label(status: str) -> str:
    return {
        "ready": "等待处理",
        "recording": "正在录制",
        "recording_paused": "录制已暂停",
        "processing": "正在后期处理",
        "completed": "已完成",
        "failed": "处理失败",
        "cancelled": "已取消",
    }.get(status, status)
