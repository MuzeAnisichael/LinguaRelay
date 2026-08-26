from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from lingua_relay.asr.faster_whisper import PINNED_MODEL_REVISIONS
from lingua_relay.config import Settings


@dataclass(frozen=True, slots=True)
class ModelDownload:
    kind: str
    label: str
    size: str


class _DownloadWorker(QObject):
    progress = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        settings: Settings,
        model_root: Path,
        downloads: tuple[ModelDownload, ...],
    ) -> None:
        super().__init__()
        self.settings = settings
        self.model_root = model_root
        self.downloads = downloads

    def run(self) -> None:
        try:
            self.model_root.mkdir(parents=True, exist_ok=True)
            for item in self.downloads:
                self.progress.emit(f"正在下载并校验 {item.label}（{item.size}）…")
                if item.kind == "asr":
                    self._download_asr()
                else:
                    self._download_translation()
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
        else:
            self.finished.emit()

    def _download_asr(self) -> None:
        from faster_whisper.utils import download_model

        model = self.settings.asr.model
        download_model(
            model,
            cache_dir=str(self.model_root),
            revision=self.settings.asr.revision or PINNED_MODEL_REVISIONS.get(model),
            local_files_only=False,
        )

    def _download_translation(self) -> None:
        from huggingface_hub import snapshot_download

        destination = self.settings.translation.model_path
        destination.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id="michaelfeil/ct2fast-m2m100_1.2B",
            revision="081c9b82953d4eeb2309daabf2951e395c5dc979",
            local_dir=str(destination),
            allow_patterns=(
                "config.json",
                "model.bin",
                "sentencepiece.bpe.model",
                "shared_vocabulary.txt",
                "special_tokens_map.json",
                "tokenizer_config.json",
                "vocab.json",
            ),
        )


class _DownloadDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        model_root: Path,
        downloads: tuple[ModelDownload, ...],
        parent: QWidget | None,
    ) -> None:
        super().__init__(parent)
        self.succeeded = False
        self.setWindowTitle("安装高级模型")
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        self.status = QLabel("正在准备下载…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(progress)
        note = QLabel("下载可断点续传。完成前请保持网络连接，不要退出 LinguaRelay。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #667085;")
        layout.addWidget(note)

        self.thread = QThread(self)
        self.worker = _DownloadWorker(settings, model_root, downloads)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self._complete)
        self.worker.failed.connect(self._fail)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)

    def start(self) -> int:
        self.thread.start()
        result = self.exec()
        self.thread.quit()
        self.thread.wait()
        return result

    def _complete(self) -> None:
        self.succeeded = True
        self.accept()

    def _fail(self, detail: str) -> None:
        QMessageBox.critical(
            self,
            "模型安装失败",
            "模型未安装完成，原设置不会被更改。\n\n" + detail,
        )
        self.reject()


def ensure_advanced_models(
    settings: Settings,
    model_root: Path,
    parent: QWidget | None = None,
) -> bool:
    downloads = missing_model_downloads(settings, model_root)
    if not downloads:
        return True
    detail = "\n".join(f"• {item.label}：{item.size}" for item in downloads)
    answer = QMessageBox.question(
        parent,
        "需要安装模型",
        "所选高级模型尚未安装：\n\n"
        + detail
        + "\n\n文件来自 Hugging Face，下载后在本地运行。是否现在安装？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False
    dialog = _DownloadDialog(settings, model_root, downloads, parent)
    return dialog.start() == QDialog.DialogCode.Accepted and dialog.succeeded


def missing_model_downloads(settings: Settings, model_root: Path) -> tuple[ModelDownload, ...]:
    missing: list[ModelDownload] = []
    asr_sizes = {
        "base": "约 140 MiB",
        "small": "约 460 MiB",
        "medium": "约 1.5 GiB",
        "large-v3-turbo": "约 1.6 GiB",
        "large-v3": "约 3.0 GiB",
    }
    if settings.asr.model in asr_sizes and not _asr_installed(
        settings.asr.model,
        settings.asr.revision,
        model_root,
    ):
        missing.append(
            ModelDownload(
                "asr",
                f"Whisper {settings.asr.model}",
                asr_sizes[settings.asr.model],
            )
        )
    if (
        settings.translation.model == "facebook/m2m100_1.2B"
        and not (settings.translation.model_path / "model.bin").is_file()
    ):
        missing.append(ModelDownload("translation", "M2M100 1.2B", "约 2.5 GiB"))
    return tuple(missing)


def advanced_model_directories(model_root: Path) -> tuple[Path, ...]:
    return (
        model_root / "models--Systran--faster-whisper-medium",
        model_root / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
        model_root / "models--Systran--faster-whisper-large-v3",
        model_root / "m2m100_1.2b_ct2",
    )


def _asr_installed(model: str, revision: str, model_root: Path) -> bool:
    try:
        from faster_whisper.utils import download_model

        download_model(
            model,
            cache_dir=str(model_root),
            revision=revision or PINNED_MODEL_REVISIONS.get(model),
            local_files_only=True,
        )
    except Exception:
        return False
    return True
