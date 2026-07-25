"""Communication log panel (PySide6)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

LOG_EXAMPLES = """# ログ出力例
[2026-07-07 22:00:01] TCP RX device=1 FC=03 ReadHoldingRegisters addr=0 count=10 | 00 01 00 00 00 06 01 03 00 00 00 0A
[2026-07-07 22:00:01] TCP TX device=1 FC=03 ReadHoldingRegisters values=[0,0,...] | 00 01 00 00 00 17 01 03 14 ...
[2026-07-07 22:00:02] RTU RX device=1 FC=03 ReadHoldingRegisters addr=0 count=10 | 01 03 00 00 00 0A C5 CD
[2026-07-07 22:00:03] TCP INVALID Unable to decode request: FF FF 00 01 00 00"""


class LogPanel(QWidget):
    def __init__(self, on_clear: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_clear = on_clear
        self._lines: list[str] = []

        header = QHBoxLayout()
        header.addWidget(QLabel("通信ログ", styleSheet="font-weight: bold; font-size: 13px;"))
        header.addWidget(QLabel("RX/TX の要約（FC/アドレス/値）と生パケット（16進）を表示します"))
        header.addStretch()
        self.clear_button = QPushButton("クリア")
        self.clear_button.clicked.connect(self._on_clear_click)
        header.addWidget(self.clear_button)

        self.log_field = QTextEdit()
        self.log_field.setReadOnly(True)
        self.log_field.setPlainText(LOG_EXAMPLES)
        self.log_field.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.log_field)

    def set_lines(self, lines: list[str]) -> bool:
        display = lines if lines else [LOG_EXAMPLES]
        if display == self._lines:
            return False
        self._lines = list(display)
        self.log_field.setPlainText("\n".join(self._lines))
        return True

    def _on_clear_click(self) -> None:
        self._lines = []
        self.log_field.setPlainText(LOG_EXAMPLES)
        if self._on_clear:
            self._on_clear()
