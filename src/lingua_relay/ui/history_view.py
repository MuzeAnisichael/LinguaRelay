from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from lingua_relay.history import JsonlHistory, latest_history_rows


class HistoryWindow(QMainWindow):
    """Searchable, latest-revision-first caption history browser."""

    export_requested = Signal()

    def __init__(self, history_path: Path, icon: QIcon | None = None) -> None:
        super().__init__()
        self.history_path = history_path
        self._rows: tuple[dict[str, object], ...] = ()
        self._visible_rows: tuple[dict[str, object], ...] = ()
        self.setWindowTitle("LinguaRelay · 历史记录")
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(1040, 700)
        self.setMinimumSize(760, 500)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索原文、译文或模型…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filters)
        controls.addWidget(self.search, 1)
        self.route_filter = QComboBox()
        self.route_filter.addItem("全部语言方向", "")
        self.route_filter.currentIndexChanged.connect(self._apply_filters)
        controls.addWidget(self.route_filter)
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("全部结果", "")
        self.kind_filter.addItem("本地快译", "final")
        self.kind_filter.addItem("LLM 修正", "revised")
        self.kind_filter.currentIndexChanged.connect(self._apply_filters)
        controls.addWidget(self.kind_filter)
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        controls.addWidget(refresh_button)
        export_button = QPushButton("导出…")
        export_button.clicked.connect(self.export_requested.emit)
        controls.addWidget(export_button)
        root.addLayout(controls)

        self.summary = QLabel()
        self.summary.setStyleSheet("color: #667085;")
        root.addWidget(self.summary)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("时间", "方向", "原文", "译文", "结果"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_selection)
        splitter.addWidget(self.table)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 8, 0, 0)
        detail_header = QHBoxLayout()
        detail_header.addWidget(QLabel("记录详情"))
        detail_header.addStretch(1)
        copy_button = QPushButton("复制译文")
        copy_button.clicked.connect(self._copy_translation)
        detail_header.addWidget(copy_button)
        detail_layout.addLayout(detail_header)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        detail_layout.addWidget(self.details)
        splitter.addWidget(detail_panel)
        splitter.setSizes((430, 210))
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)

    def refresh(self) -> None:
        try:
            rows = tuple(JsonlHistory(self.history_path).read_all())
        except (OSError, ValueError):
            rows = ()
        self._rows = latest_history_rows(rows)
        selected_route = self.route_filter.currentData()
        routes = sorted(
            {f"{row.get('source_language')}→{row.get('target_language')}" for row in self._rows}
        )
        self.route_filter.blockSignals(True)
        self.route_filter.clear()
        self.route_filter.addItem("全部语言方向", "")
        for route in routes:
            self.route_filter.addItem(route.upper(), route)
        index = self.route_filter.findData(selected_route)
        self.route_filter.setCurrentIndex(max(0, index))
        self.route_filter.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self.search.text().strip().casefold()
        route = str(self.route_filter.currentData() or "")
        kind = str(self.kind_filter.currentData() or "")
        visible: list[dict[str, object]] = []
        for row in self._rows:
            row_route = f"{row.get('source_language')}→{row.get('target_language')}"
            if route and row_route != route:
                continue
            if kind and str(row.get("state") or "final") != kind:
                continue
            searchable = " ".join(
                str(row.get(key) or "")
                for key in (
                    "source_text",
                    "translated_text",
                    "source_language",
                    "target_language",
                    "correction_provider",
                    "correction_model",
                )
            ).casefold()
            if query and query not in searchable:
                continue
            visible.append(row)
        self._visible_rows = tuple(visible)
        self._populate_table()

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self._visible_rows))
        for index, row in enumerate(self._visible_rows):
            revision = int(row.get("revision") or 0)
            kind = "LLM 修正" if row.get("state") == "revised" else "本地快译"
            if revision:
                kind += f" · v{revision}"
            values = (
                _display_time(row.get("created_at")),
                f"{str(row.get('source_language') or '').upper()} → "
                f"{str(row.get('target_language') or '').upper()}",
                str(row.get("source_text") or ""),
                str(row.get("translated_text") or row.get("source_text") or ""),
                kind,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
        self.summary.setText(f"显示 {len(self._visible_rows)} 条 · 共 {len(self._rows)} 个语音片段")
        if self._visible_rows:
            self.table.selectRow(0)
        else:
            self.details.setHtml("<p style='color:#667085'>没有符合条件的记录。</p>")

    def _selected_row(self) -> dict[str, object] | None:
        index = self.table.currentRow()
        if 0 <= index < len(self._visible_rows):
            return self._visible_rows[index]
        return None

    def _show_selection(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        source = escape(str(row.get("source_text") or ""))
        translation = escape(str(row.get("translated_text") or row.get("source_text") or ""))
        route = (
            f"{str(row.get('source_language') or '').upper()} → "
            f"{str(row.get('target_language') or '').upper()}"
        )
        provider = escape(str(row.get("correction_provider") or "本地快译"))
        model = escape(str(row.get("correction_model") or "—"))
        created = escape(_display_time(row.get("created_at")))
        self.details.setHtml(
            f"<p style='color:#667085'>{created} · {route} · {provider} · {model}</p>"
            f"<h3>原文</h3><p>{source}</p><h3>译文</h3><p>{translation}</p>"
        )

    def _copy_translation(self) -> None:
        row = self._selected_row()
        if row is not None:
            QApplication.clipboard().setText(
                str(row.get("translated_text") or row.get("source_text") or "")
            )


def _display_time(value: Any) -> str:
    text = str(value or "")
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return text
    return parsed.strftime("%Y-%m-%d %H:%M:%S")
