"""Communication log panel (PySide6)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

LOG_EXAMPLES = """# ログ出力例
[2026-07-07 22:00:01] TCP RX device=1 FC=03 ReadHoldingRegisters addr=0 count=10 | 00 01 00 00 00 06 01 03 00 00 00 0A
[2026-07-07 22:00:01] TCP TX device=1 FC=03 ReadHoldingRegisters values=[0,0,...] | 00 01 00 00 00 17 01 03 14 ...
[2026-07-07 22:00:02] RTU RX device=1 FC=03 ReadHoldingRegisters addr=0 count=10 | 01 03 00 00 00 0A C5 CD
[2026-07-07 22:00:03] TCP INVALID Unable to decode request: FF FF 00 01 00 00"""

_MODE_ALL = "すべて"
_MODE_TCP = "TCP"
_MODE_RTU = "RTU"


class LogPanel(QWidget):
    def __init__(self, on_clear: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_clear = on_clear
        self._lines: list[str] = []
        self._raw_lines: list[str] = []
        self._paused = False

        header = QHBoxLayout()
        header.addWidget(QLabel("通信ログ", styleSheet="font-weight: bold; font-size: 13px;"))
        header.addWidget(QLabel("RX/TX の要約（FC/アドレス/値）と生パケット（16進）を表示します"))
        header.addStretch()
        self.clear_button = QPushButton("クリア")
        self.clear_button.clicked.connect(self._on_clear_click)
        header.addWidget(self.clear_button)

        toolbar = QHBoxLayout()
        self.mode_filter = QComboBox()
        self.mode_filter.addItems([_MODE_ALL, _MODE_TCP, _MODE_RTU])
        self.mode_filter.currentTextChanged.connect(lambda _t: self._render())
        toolbar.addWidget(QLabel("表示:"))
        toolbar.addWidget(self.mode_filter)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("絞り込み（例: FC=03 / device=1 / addr=100）")
        self.search_field.textChanged.connect(lambda _t: self._render())
        toolbar.addWidget(self.search_field, stretch=1)

        self.autoscroll_checkbox = QCheckBox("自動スクロール")
        self.autoscroll_checkbox.setChecked(True)
        self.autoscroll_checkbox.toggled.connect(self._on_autoscroll_toggled)
        toolbar.addWidget(self.autoscroll_checkbox)

        self.pause_button = QPushButton("一時停止")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._on_pause_toggled)
        toolbar.addWidget(self.pause_button)

        self.save_button = QPushButton("保存...")
        self.save_button.setToolTip("表示中のログをファイルへ保存します")
        self.save_button.clicked.connect(self._on_save_click)
        toolbar.addWidget(self.save_button)

        self.log_field = QTextEdit()
        self.log_field.setReadOnly(True)
        self.log_field.setPlainText(LOG_EXAMPLES)
        self.log_field.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addLayout(toolbar)
        layout.addWidget(self.log_field)

    def set_lines(self, lines: list[str]) -> bool:
        display = lines if lines else [LOG_EXAMPLES]
        if display == self._raw_lines:
            return False
        self._raw_lines = list(display)
        if self._paused:
            return False
        self._render()
        return True

    def _matches_mode(self, line: str) -> bool:
        mode = self.mode_filter.currentText()
        if mode == _MODE_ALL:
            return True
        return f"] {mode} " in line

    def _matches_search(self, line: str) -> bool:
        query = self.search_field.text().strip().lower()
        return not query or query in line.lower()

    def _filtered_lines(self) -> list[str]:
        if not self._raw_lines or self._raw_lines == [LOG_EXAMPLES]:
            return list(self._raw_lines)
        return [
            line
            for line in self._raw_lines
            if self._matches_mode(line) and self._matches_search(line)
        ]

    def _render(self) -> None:
        filtered = self._filtered_lines()
        text = "\n".join(filtered)
        if text == self._lines_text():
            return
        scrollbar = self.log_field.verticalScrollBar()
        previous_value = scrollbar.value()
        self._lines = filtered
        self.log_field.setPlainText(text)
        if self.autoscroll_checkbox.isChecked():
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(min(previous_value, scrollbar.maximum()))

    def _lines_text(self) -> str:
        return self.log_field.toPlainText()

    def _on_autoscroll_toggled(self, checked: bool) -> None:
        if checked:
            scrollbar = self.log_field.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_pause_toggled(self, checked: bool) -> None:
        self._paused = checked
        self.pause_button.setText("再開" if checked else "一時停止")
        if not checked:
            self._render()

    def _on_save_click(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "ログを保存", "modbus_sim_log.txt", "Text Files (*.txt);;All Files (*)"
        )
        if not path_str:
            return
        try:
            with open(path_str, "w", encoding="utf-8") as handle:
                handle.write(self._lines_text())
        except OSError as exc:
            QMessageBox.warning(self, "エラー", f"ログの保存に失敗しました:\n{exc}")
            return
        QMessageBox.information(self, "完了", "ログを保存しました。")

    def _on_clear_click(self) -> None:
        self._lines = []
        self._raw_lines = []
        self.log_field.setPlainText(LOG_EXAMPLES)
        if self._on_clear:
            self._on_clear()
