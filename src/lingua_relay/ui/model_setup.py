from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    ModelInstallation,
    ModelPackManifest,
    ModelProfile,
    adopt_existing_models,
    cleanup_stale_model_installs,
    download_model_pack,
    install_model_pack,
    load_model_catalog,
    load_model_pack_manifest,
    model_files_status,
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
        profiles: tuple[ModelProfile, ...],
        model_root: Path,
        download_dir: Path,
        candidate_roots: Iterable[Path] = (),
    ) -> None:
        super().__init__()
        if not profiles:
            raise ValueError("at least one model profile is required")
        self.profiles = profiles
        self.model_root = model_root
        self.download_dir = download_dir
        self.selected_model_root: Path | None = None
        self.selected_profile: ModelProfile | None = None
        self._pending_model_root = model_root
        self._pending_profile = next(profile for profile in profiles if profile.recommended)
        self._thread: _InstallThread | None = None
        self.candidate_roots = tuple(candidate_roots)
        self.detected_model_root: Path | None = None
        self.setWindowTitle("LinguaRelay 首次启动")
        self.setMinimumWidth(680)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "请选择适合电脑性能的本地模型。两种方案都支持中文、日语、英语、韩语互译；"
            "模型只需安装一次，LinguaRelay 会优先检测并复用已有文件。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.profile_combo = QComboBox()
        for profile in profiles:
            suffix = "（推荐）" if profile.recommended else ""
            self.profile_combo.addItem(f"{profile.label}{suffix}", profile.profile_id)
        recommended = next(profile for profile in profiles if profile.recommended)
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(recommended.profile_id))
        layout.addWidget(self.profile_combo)
        self.profile_detail = QLabel()
        self.profile_detail.setWordWrap(True)
        self.profile_detail.setStyleSheet("background: #EFF8FF; color: #175CD3; padding: 9px;")
        layout.addWidget(self.profile_detail)
        self.licenses = QTextBrowser()
        self.licenses.setOpenExternalLinks(True)
        self.licenses.setMaximumHeight(160)
        layout.addWidget(self.licenses)
        self.consent = QCheckBox("我已阅读并接受上述模型许可证")
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
        self.detected_button = QPushButton("验证并使用已检测到的本地模型")
        self.detected_button.clicked.connect(self._use_detected_directory)
        self.detected_button.setVisible(self.detected_model_root is not None)
        if self.detected_model_root is not None:
            self.detected_button.setToolTip(str(self.detected_model_root))
            self.status.setText(f"检测到本地模型：{self.detected_model_root}")
        layout.addWidget(self.detected_button)
        self.directory_button = QPushButton("选择已有模型目录…")
        self.directory_button.clicked.connect(self._choose_directory)
        layout.addWidget(self.directory_button)
        self.local_button = QPushButton("从已下载的模型 ZIP 安装…")
        self.local_button.clicked.connect(self._choose_local)
        layout.addWidget(self.local_button)
        self.cancel_button = QPushButton("退出")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        self.profile_combo.currentIndexChanged.connect(self._refresh_profile)
        self._refresh_profile()

    @property
    def profile(self) -> ModelProfile:
        profile_id = str(self.profile_combo.currentData())
        return next(profile for profile in self.profiles if profile.profile_id == profile_id)

    @property
    def manifest(self) -> ModelPackManifest:
        return self.profile.manifest

    def _refresh_profile(self) -> None:
        profile = self.profile
        manifest = profile.manifest
        size = manifest.total_installed_bytes / 1024**3
        self.profile_detail.setText(
            f"{profile.summary}\n{profile.guidance}\n预计占用 {size:.2f} GiB；可随时在设置中卸载。"
        )
        self.licenses.setHtml(_license_html(manifest))
        self.detected_model_root = next(
            (
                root
                for root in self.candidate_roots
                if root != self.model_root and model_files_status(root, manifest).ready
            ),
            None,
        )
        self.detected_button.setVisible(self.detected_model_root is not None)
        if self.detected_model_root is not None:
            self.detected_button.setToolTip(str(self.detected_model_root))
            self.status.setText(f"检测到可复用的完整模型：{self.detected_model_root}")
        else:
            self.detected_button.setToolTip("")
            self.status.setText("模型安装到 LocalAppData；电脑音频默认只在本机内存中处理。")
        self.download_button.setText(f"下载并安装 {profile.label}")

    def _download(self) -> None:
        if not self._check_consent():
            return
        profile = self.profile
        manifest = profile.manifest
        archive = self.download_dir / manifest.archive_name

        def operation(progress: Callable[[int, int, str], None]) -> None:
            download_model_pack(manifest, archive, progress)
            install_model_pack(archive, self.model_root, manifest, progress)

        self._start(operation, selected_model_root=self.model_root, profile=profile)

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
            profile = self.profile
            self._start(
                lambda progress: install_model_pack(
                    Path(selected), self.model_root, profile.manifest, progress
                ),
                selected_model_root=self.model_root,
                profile=profile,
            )

    def _use_detected_directory(self) -> None:
        if self.detected_model_root is not None:
            self._use_directory(self.detected_model_root)

    def _choose_directory(self) -> None:
        if not self._check_consent():
            return
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择包含完整 LinguaRelay 模型的目录",
            str(self.download_dir.parent),
        )
        if selected:
            self._use_directory(Path(selected))

    def _use_directory(self, root: Path) -> None:
        if not self._check_consent():
            return

        profile = self.profile

        def operation(progress: Callable[[int, int, str], None]) -> None:
            status = adopt_existing_models(root, profile.manifest, progress)
            if not status.ready:
                raise ValueError(status.error or "所选目录不是完整、匹配的模型包")

        self._start(operation, selected_model_root=root, profile=profile)

    def _check_consent(self) -> bool:
        if self.consent.isChecked():
            return True
        QMessageBox.information(self, "需要确认", "请先阅读模型许可证并勾选确认。")
        return False

    def _start(
        self,
        operation: Callable[[Callable[[int, int, str], None]], None],
        *,
        selected_model_root: Path,
        profile: ModelProfile,
    ) -> None:
        self._set_busy(True)
        self._pending_model_root = selected_model_root
        self._pending_profile = profile
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
        self.selected_model_root = self._pending_model_root
        self.selected_profile = self._pending_profile
        self.accept()

    def _on_failure(self, message: str) -> None:
        if self._thread is not None:
            self._thread.wait()
        self._set_busy(False)
        self.status.setText("安装失败，可重试或选择已下载的 ZIP。")
        QMessageBox.critical(self, "模型安装失败", message)

    def _set_busy(self, busy: bool) -> None:
        self.consent.setEnabled(not busy)
        self.profile_combo.setEnabled(not busy)
        self.download_button.setEnabled(not busy)
        self.detected_button.setEnabled(not busy)
        self.directory_button.setEnabled(not busy)
        self.local_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)

    def reject(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            super().reject()


def ensure_model_pack(
    model_root: Path,
    manifest_path: Path,
    download_dir: Path,
    candidate_roots: Iterable[Path] = (),
) -> Path | None:
    """Backward-compatible single-pack installer used by tests and older integrations."""
    manifest = load_model_pack_manifest(manifest_path)
    asr_license = next((item for item in manifest.licenses if item.get("component") == "asr"), {})
    model_name = str(asr_license.get("name", "small")).rsplit("-", 1)[-1]
    profile = ModelProfile(
        profile_id="standard",
        label="标准模型",
        summary="固定版本的语音识别与翻译模型。",
        guidance="适合大多数电脑。",
        asr_model=model_name,
        recommended=True,
        manifest_path=Path(manifest_path),
        manifest=manifest,
    )
    installation = _ensure_profiles(model_root, (profile,), download_dir, candidate_roots)
    return None if installation is None else installation.root


def ensure_model_installation(
    model_root: Path,
    catalog_path: Path,
    download_dir: Path,
    candidate_roots: Iterable[Path] = (),
) -> ModelInstallation | None:
    profiles = load_model_catalog(catalog_path)
    return _ensure_profiles(model_root, profiles, download_dir, candidate_roots)


def _ensure_profiles(
    model_root: Path,
    profiles: tuple[ModelProfile, ...],
    download_dir: Path,
    candidate_roots: Iterable[Path],
) -> ModelInstallation | None:
    cleanup_stale_model_installs(model_root)
    ordered = tuple(sorted(profiles, key=lambda profile: not profile.recommended))
    for profile in ordered:
        if model_pack_status(model_root, profile.manifest).ready:
            return ModelInstallation(model_root, profile)
    for profile in ordered:
        if (
            model_files_status(model_root, profile.manifest).ready
            and adopt_existing_models(model_root, profile.manifest).ready
        ):
            return ModelInstallation(model_root, profile)

    remembered_path = download_dir.parent / "model-location.json"
    remembered_root: Path | None = None
    remembered_profile = ""
    try:
        remembered = json.loads(remembered_path.read_text(encoding="utf-8"))
        remembered_root = Path(str(remembered["root"]))
        remembered_profile = str(remembered.get("profile", ""))
    except (OSError, ValueError, KeyError, TypeError):
        legacy_path = download_dir.parent / "model-location.txt"
        try:
            remembered_root = Path(legacy_path.read_text(encoding="utf-8").strip())
        except OSError:
            remembered_root = None

    candidates = _deduplicate_roots(
        ((remembered_root,) if remembered_root is not None else ()) + tuple(candidate_roots)
    )
    if remembered_profile:
        ordered = tuple(
            sorted(ordered, key=lambda profile: profile.profile_id != remembered_profile)
        )
    for profile in ordered:
        for candidate in candidates:
            if candidate != model_root and model_pack_status(candidate, profile.manifest).ready:
                return ModelInstallation(candidate, profile)

    dialog = ModelSetupDialog(profiles, model_root, download_dir, candidates)
    if (
        dialog.exec() != QDialog.DialogCode.Accepted
        or dialog.selected_model_root is None
        or dialog.selected_profile is None
    ):
        return None
    installation = ModelInstallation(dialog.selected_model_root, dialog.selected_profile)
    remembered_path.parent.mkdir(parents=True, exist_ok=True)
    remembered_path.write_text(
        json.dumps(
            {
                "root": str(installation.root.resolve()),
                "profile": installation.profile.profile_id,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return installation


def _deduplicate_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not str(root).strip():
            continue
        try:
            resolved = root.expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        normalized = str(resolved).casefold()
        if normalized not in seen:
            seen.add(normalized)
            result.append(resolved)
    return tuple(result)


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
