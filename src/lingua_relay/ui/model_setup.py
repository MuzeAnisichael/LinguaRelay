from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from lingua_relay.model_pack import (
    ModelPackManifest,
    adopt_existing_models,
    cleanup_stale_model_installs,
    download_model_pack,
    install_model_pack,
    load_model_pack_manifest,
    model_pack_status,
)


class _InstallThread(QThread):
    progressed = Signal(int, int, str)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, operation: Callable[[Callable[[int, int, str], None]], None]) -> None:
        super().__init__()
        self.operation = operation

    def run(self) -> None:
        try:
            self.operation(self.progressed.emit)
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.succeeded.emit()


class ModelSetupDialog(QDialog):
    def __init__(
        self,
        manifest: ModelPackManifest,
        model_root: Path,
        download_dir: Path,
    ) -> None:
        super().__init__()
        self.manifest = manifest
        self.model_root = model_root
        self.download_dir = download_dir
        self._thread: _InstallThread | None = None
        self.setWindowTitle("LinguaRelay 首次启动")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "实时识别与翻译在本机运行，需要安装约 "
                f"{manifest.total_installed_bytes / 1024**3:.2f} GiB 的固定版本模型。"
            )
        )
        licenses = QTextBrowser()
        licenses.setOpenExternalLinks(True)
        licenses.setHtml(_license_html(manifest))
        licenses.setMaximumHeight(190)
        layout.addWidget(licenses)
        self.consent = QCheckBox("我已阅读并接受上述模型许可证；同意从 GitHub Release 下载")
        layout.addWidget(self.consent)
        self.status = QLabel("模型会安装到用户 LocalAppData，不会上传电脑音频。")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.download_button = QPushButton("下载并安装模型")
        self.download_button.clicked.connect(self._download)
        layout.addWidget(self.download_button)
        self.local_button = QPushButton("从已下载的模型 ZIP 安装…")
        self.local_button.clicked.connect(self._choose_local)
        layout.addWidget(self.local_button)
        self.cancel_button = QPushButton("退出")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

    def _download(self) -> None:
        if not self._check_consent():
            return
        archive = self.download_dir / self.manifest.archive_name

        def operation(progress: Callable[[int, int, str], None]) -> None:
            download_model_pack(self.manifest, archive, progress)
            install_model_pack(archive, self.model_root, self.manifest, progress)

        self._start(operation)

    def _choose_local(self) -> None:
        if not self._check_consent():
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择 LinguaRelay 模型包",
            str(self.download_dir),
            "ZIP archives (*.zip)",
        )
        if selected:
            self._start(
                lambda progress: install_model_pack(
                    Path(selected), self.model_root, self.manifest, progress
                )
            )

    def _check_consent(self) -> bool:
        if self.consent.isChecked():
            return True
        QMessageBox.information(self, "需要确认", "请先阅读模型许可证并勾选确认。")
        return False

    def _start(self, operation: Callable[[Callable[[int, int, str], None]], None]) -> None:
        self._set_busy(True)
        self._thread = _InstallThread(operation)
        self._thread.progressed.connect(self._on_progress)
        self._thread.succeeded.connect(self._on_success)
        self._thread.failed.connect(self._on_failure)
        self._thread.start()

    def _on_progress(self, completed: int, total: int, message: str) -> None:
        self.status.setText(message)
        self.progress.setValue(min(1000, round(completed / max(total, 1) * 1000)))

    def _on_success(self) -> None:
        if self._thread is not None:
            self._thread.wait()
        self.status.setText("模型安装与完整性校验已完成。")
        self.progress.setValue(1000)
        self.accept()

    def _on_failure(self, message: str) -> None:
        if self._thread is not None:
            self._thread.wait()
        self._set_busy(False)
        self.status.setText("安装失败，可重试或选择已下载的 ZIP。")
        QMessageBox.critical(self, "模型安装失败", message)

    def _set_busy(self, busy: bool) -> None:
        self.consent.setEnabled(not busy)
        self.download_button.setEnabled(not busy)
        self.local_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)

    def reject(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            super().reject()


def ensure_model_pack(
    model_root: Path,
    manifest_path: Path,
    download_dir: Path,
) -> bool:
    manifest = load_model_pack_manifest(manifest_path)
    cleanup_stale_model_installs(model_root)
    if model_pack_status(model_root, manifest).ready:
        return True
    if model_pack_status(model_root, manifest, full_hash=True).ready:
        return adopt_existing_models(model_root, manifest).ready
    return (
        ModelSetupDialog(manifest, model_root, download_dir).exec() == QDialog.DialogCode.Accepted
    )


def _license_html(manifest: ModelPackManifest) -> str:
    rows = "".join(
        f"<li><b>{item.get('name', 'Model')}</b>: {item.get('license', 'See upstream')} "
        f'(<a href="{item.get("url", "")}">upstream</a>)</li>'
        for item in manifest.licenses
    )
    return (
        "<p>模型权重由各上游项目授权，应用本身使用 MIT 许可证。"
        "安装即表示你按相应许可证使用模型：</p><ul>" + rows + "</ul>"
    )
