"""Desktop recording and offline-task orchestration, separate from the tray UI."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QSystemTrayIcon

from lingua_relay.offline import (
    OfflineProcessor,
    ProcessingOptions,
    RecordingSession,
    export_project,
    probe_media,
)
from lingua_relay.service import RealtimeCaptionService
from lingua_relay.ui.advanced_models import ensure_advanced_models
from lingua_relay.ui.offline_workbench import OfflineWorkbench


@dataclass(frozen=True, slots=True)
class OfflineTaskResult:
    project_id: str
    status: str
    detail: str = ""


class OfflineWorker(QObject):
    """Stop realtime, process cooperatively, restore its state, then settle once."""

    progress = Signal(str, float, str)
    done = Signal()

    def __init__(
        self,
        processor: OfflineProcessor,
        service: RealtimeCaptionService,
        project_id: str,
        options: ProcessingOptions,
    ) -> None:
        super().__init__()
        self.processor = processor
        self.service = service
        self.project_id = project_id
        self.options = options
        self.cancelled = threading.Event()
        self.result: OfflineTaskResult | None = None
        self._lifecycle_lock = threading.Lock()
        self._restart_service = True
        self._accepting_cancel = True

    def _check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise InterruptedError("处理已取消")

    @Slot()
    def run(self) -> None:
        service_stopped = False
        restore_realtime = False
        was_paused = False
        result = OfflineTaskResult(self.project_id, "failed", "后期任务未完成")
        try:
            self._check_cancelled()
            original_state = self.service.snapshot().state
            was_paused = bool(getattr(self.service, "paused", original_state == "paused"))
            restore_realtime = original_state not in {"stopped", "error"}
            self.service.stop()
            service_stopped = True
            self._check_cancelled()
            self.service.release_resources()
            self._check_cancelled()
            self.processor.process(
                self.project_id,
                self.options,
                on_progress=lambda value, message: self.progress.emit(
                    self.project_id, value, message
                ),
                cancel=self.cancelled,
            )
        except InterruptedError:
            result = OfflineTaskResult(self.project_id, "cancelled")
        except Exception as error:
            result = OfflineTaskResult(
                self.project_id, "failed", f"{type(error).__name__}: {error}"
            )
        else:
            # A normal return means the backend committed the completed project.
            # A cancellation arriving after that boundary cannot undo success.
            result = OfflineTaskResult(self.project_id, "completed")
        finally:
            with self._lifecycle_lock:
                self._accepting_cancel = False
                if service_stopped and restore_realtime and self._restart_service:
                    try:
                        self.service.start(paused=was_paused)
                    except Exception as error:
                        detail = f"恢复实时字幕失败：{type(error).__name__}: {error}"
                        if result.detail:
                            detail = f"{result.detail}\n{detail}"
                        result = OfflineTaskResult(self.project_id, "failed", detail)
                self.result = result
            self.done.emit()

    def cancel(self, *, restart_service: bool = True) -> bool:
        with self._lifecycle_lock:
            # Once shutdown forbids restart, a later ordinary cancel cannot
            # re-enable it. Never close the model/client while it is in flight.
            self._restart_service = self._restart_service and restart_service
            if not self._accepting_cancel:
                return False
            self.cancelled.set()
            return True


class _TaskRelay(QObject):
    """Qt-affine receiver: widget updates must never run in the model thread."""

    def __init__(self, owner, worker: OfflineWorker, thread: QThread) -> None:
        super().__init__(owner.app)
        self.owner = owner
        self.worker = worker
        self.worker_thread = thread

    @Slot(str, float, str)
    def progress(self, project_id: str, value: float, message: str) -> None:
        self.owner._offline_progress(self.worker, project_id, value, message)

    @Slot()
    def finished(self) -> None:
        try:
            self.owner._offline_thread_finished(self.worker, self.worker_thread)
        finally:
            self.deleteLater()


class OfflineTasksMixin:
    """Controller-side UI coordination; all methods run on the main Qt thread."""

    def _init_offline_tasks(self) -> None:
        self._offline_thread: QThread | None = None
        self._offline_worker: OfflineWorker | None = None
        self._offline_relay: _TaskRelay | None = None
        self._offline_preparing = False
        self._shutting_down = False

    def _offline_is_busy(self) -> bool:
        return self._offline_preparing or self._offline_worker is not None

    def _warn_offline_busy(self) -> None:
        QMessageBox.information(
            None, "后期处理进行中", "请等待当前任务完成，或先在工作台取消任务。"
        )

    def toggle_recording(self) -> None:
        if self._shutting_down:
            return
        snapshot = self.service.snapshot()
        if snapshot.recording_state in {"recording", "paused"}:
            try:
                self.service.stop_recording()
            except Exception as error:
                QMessageBox.critical(None, "无法结束录制", str(error))
                return
            if snapshot.recording_project_id:
                self.show_workbench(select_id=snapshot.recording_project_id)
                self._start_offline_processing(
                    snapshot.recording_project_id, self._offline_workbench.processing_options()
                )
            return
        if self._offline_is_busy():
            self._warn_offline_busy()
            return
        # Audio capture is independent of realtime model loading/readiness.
        source_label = {
            "system": "系统音频",
            "microphone": "麦克风",
            "process": self.settings.audio.process_name.strip() or "进程音频",
        }.get(self.settings.audio.source, "音频")
        project = self.project_store.create_project(
            title=f"{datetime.now():%Y-%m-%d %H-%M-%S} · {source_label}",
            kind="recording",
            source_language=self.settings.app.source_language,
            target_language=self.settings.app.target_language,
        )
        try:
            self.service.start_recording(RecordingSession(self.project_store, project.id))
        except Exception as error:
            self.project_store.update_project(project.id, status="failed", error=str(error))
            QMessageBox.critical(None, "无法开始录制", str(error))

    def toggle_recording_pause(self) -> None:
        state = self.service.snapshot().recording_state
        try:
            if state == "recording":
                self.service.pause_recording()
            elif state == "paused":
                self.service.resume_recording()
        except Exception as error:
            QMessageBox.warning(None, "录制状态切换失败", str(error))

    def show_workbench(self, *, select_id: str | None = None) -> None:
        viewer = getattr(self, "_offline_workbench", None)
        if viewer is None:
            viewer = OfflineWorkbench(self.project_store, self.icon)
            viewer.import_audio_requested.connect(lambda: self._import_media("audio"))
            viewer.import_video_requested.connect(lambda: self._import_media("video"))
            viewer.process_requested.connect(self._start_offline_processing)
            viewer.cancel_requested.connect(self._cancel_offline_processing)
            viewer.export_requested.connect(self._export_offline_project)
            self._offline_workbench = viewer
        viewer.refresh(select_id=select_id)
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

    def _import_media(self, kind: str) -> None:
        if self._shutting_down:
            return
        if self._offline_is_busy():
            self._warn_offline_busy()
            return
        if self.service.snapshot().recording_state in {"recording", "paused"}:
            QMessageBox.warning(None, "正在录制", "请先结束录制，再导入媒体运行后期处理。")
            return
        if kind == "video":
            title = "导入视频"
            file_filter = "视频文件 (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;所有文件 (*)"
        else:
            title = "导入音频"
            file_filter = "音频文件 (*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(None, title, str(Path.home()), file_filter)
        if not path:
            return
        try:
            info = probe_media(path)
            if kind == "video" and not info.has_video:
                raise ValueError("所选文件不包含视频轨，请使用“导入音频”")
            project = self.project_store.create_project(
                title=Path(path).stem,
                kind=kind,
                source_path=path,
                source_language=self.settings.app.source_language,
                target_language=self.settings.app.target_language,
            )
            self.project_store.update_project(project.id, duration_ms=info.duration_ms)
        except Exception as error:
            QMessageBox.critical(None, "无法导入媒体", str(error))
            return
        self.show_workbench(select_id=project.id)
        self._start_offline_processing(project.id, self._offline_workbench.processing_options())

    def _start_offline_processing(self, project_id: str, options: ProcessingOptions) -> None:
        if self._shutting_down:
            return
        if self._offline_is_busy():
            self._warn_offline_busy()
            return
        if self.service.snapshot().recording_state in {"recording", "paused"}:
            QMessageBox.warning(None, "正在录制", "请先结束录制，再运行后期处理。")
            return
        candidate = replace(
            self.settings, asr=replace(self.settings.asr, model=options.asr_model, revision="")
        )
        viewer = getattr(self, "_offline_workbench", None)
        self._offline_preparing = True
        try:
            if not ensure_advanced_models(candidate, self.model_root, viewer):
                return
        finally:
            self._offline_preparing = False
        if self._shutting_down:
            return
        processor = OfflineProcessor(self.project_store, self.settings, self.model_root)
        thread = QThread(self.app)
        worker = OfflineWorker(processor, self.service, project_id, options)
        relay = _TaskRelay(self, worker, thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(relay.progress)
        # quit() is thread-safe. A direct connection also works while shutdown
        # waits for this worker and the GUI event loop is no longer dispatching.
        worker.done.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.finished)
        thread.finished.connect(thread.deleteLater)
        self._offline_thread = thread
        self._offline_worker = worker
        self._offline_relay = relay
        if viewer is not None:
            viewer.processing_started(project_id)
        thread.start()

    def _cancel_offline_processing(self, project_id: str) -> None:
        worker = self._offline_worker
        if worker is None or worker.project_id != project_id:
            return
        if worker.cancel():
            viewer = getattr(self, "_offline_workbench", None)
            if viewer is not None:
                viewer.processing_cancelling(project_id)

    def _offline_progress(
        self, worker: OfflineWorker, project_id: str, value: float, message: str
    ) -> None:
        if self._shutting_down or worker is not self._offline_worker:
            return
        viewer = getattr(self, "_offline_workbench", None)
        if viewer is not None:
            viewer.update_progress(project_id, value, message)

    def _offline_thread_finished(self, worker: OfflineWorker, thread: QThread) -> None:
        if worker is not self._offline_worker or thread is not self._offline_thread:
            return
        self._offline_worker = None
        self._offline_thread = None
        self._offline_relay = None
        if self._shutting_down:
            return
        result = worker.result or OfflineTaskResult(worker.project_id, "failed", "任务意外结束")
        viewer = getattr(self, "_offline_workbench", None)
        if viewer is not None:
            viewer.processing_finished(
                result.project_id, result.detail, cancelled=result.status == "cancelled"
            )
        if result.status == "completed":
            self.tray.showMessage(
                "LinguaRelay",
                "后期识别与翻译已完成，可以查看、编辑或导出字幕。",
                QSystemTrayIcon.MessageIcon.Information,
            )

    def _export_offline_project(self, project_id: str, path: str) -> None:
        try:
            export_project(self.project_store, project_id, path)
        except Exception as error:
            QMessageBox.critical(None, "导出失败", str(error))
        else:
            self.tray.showMessage(
                "LinguaRelay", f"已导出：{Path(path).name}", QSystemTrayIcon.MessageIcon.Information
            )

    def _shutdown_offline_tasks(self) -> None:
        self._shutting_down = True
        if self._offline_worker is not None:
            self._offline_worker.cancel(restart_service=False)
        if self._offline_thread is not None and self._offline_thread.isRunning():
            # Model calls cancel cooperatively. Do not destroy a live QThread
            # or restart realtime while the application is shutting down.
            self._offline_thread.wait()
