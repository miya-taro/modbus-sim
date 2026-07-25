"""Communication settings panel (PySide6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from modbus_sim.config import (
    BAUD_RATES,
    DATA_BITS,
    STOP_BITS,
    Parity,
    RtuConfig,
    TcpConfig,
)
from modbus_sim.models import CommSettings
from modbus_sim.network import list_bind_addresses, normalize_host


class SettingsPanel(QWidget):
    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_change = on_change
        self._initializing = True
        self._tcp_settings_enabled = True
        self._rtu_settings_enabled = True
        self.comm = CommSettings()

        self.tcp_host = QComboBox()
        self.tcp_host.setEditable(True)
        self.refresh_ip_button = QPushButton("IP再検出")
        self.tcp_port = QLineEdit()
        self.tcp_port.setPlaceholderText("例: 5020")
        self.tcp_group = QGroupBox("TCP")
        tcp_form = QFormLayout(self.tcp_group)
        ip_row = QWidget()
        ip_layout = QHBoxLayout(ip_row)
        ip_layout.setContentsMargins(0, 0, 0, 0)
        ip_layout.addWidget(self.tcp_host, stretch=1)
        ip_layout.addWidget(self.refresh_ip_button)
        tcp_form.addRow("IP", ip_row)
        tcp_form.addRow("Port", self.tcp_port)

        self.rtu_port = QComboBox()
        self.rtu_port.setEditable(True)
        self.refresh_ports_button = QPushButton("ポート再検出")
        self.rtu_baudrate = QComboBox()
        self.rtu_parity = QComboBox()
        self.rtu_bytesize = QComboBox()
        self.rtu_stopbits = QComboBox()

        self.rtu_group = QGroupBox("RTU")
        rtu_form = QFormLayout(self.rtu_group)
        port_row = QWidget()
        port_layout = QHBoxLayout(port_row)
        port_layout.setContentsMargins(0, 0, 0, 0)
        port_layout.addWidget(self.rtu_port, stretch=1)
        port_layout.addWidget(self.refresh_ports_button)
        rtu_form.addRow("シリアルポート", port_row)
        rtu_form.addRow("ボーレート", self.rtu_baudrate)
        rtu_form.addRow("パリティ", self.rtu_parity)
        rtu_form.addRow("Data bits", self.rtu_bytesize)
        rtu_form.addRow("Stop bits", self.rtu_stopbits)

        self.config_summary = QLabel("(未設定)")
        self.config_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.config_summary.setWordWrap(True)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("通信設定", styleSheet="font-weight: bold; font-size: 13px;"))
        layout.addWidget(QLabel("入力した項目のみ下の「現在の設定」に表示されます。IPv4/IPv6 に対応しています。"))
        layout.addWidget(self.tcp_group)
        layout.addWidget(self.rtu_group)
        layout.addWidget(QLabel("現在の設定", styleSheet="font-weight: bold;"))
        layout.addWidget(self.config_summary)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

        self._fill_combos()
        self._wire_handlers()
        self.refresh_ip_addresses()
        self.refresh_serial_ports()
        self._apply_mode_state()
        self._initializing = False
        self.update_summary()

    def refresh_ip_addresses(self) -> None:
        addresses = list_bind_addresses()
        current = self.tcp_host.currentText().strip()
        self.tcp_host.blockSignals(True)
        self.tcp_host.clear()
        self.tcp_host.addItems(addresses)
        if current:
            if current not in addresses:
                self.tcp_host.addItem(current)
            self.tcp_host.setCurrentText(current)
        self.tcp_host.blockSignals(False)

    def refresh_serial_ports(self) -> None:
        ports = [port.device for port in list_ports.comports()]
        current = self.rtu_port.currentText().strip()
        self.rtu_port.blockSignals(True)
        self.rtu_port.clear()
        if ports:
            self.rtu_port.addItems(ports)
            if current and current not in ports:
                self.rtu_port.addItem(current)
                self.rtu_port.setCurrentText(current)
            elif current in ports:
                self.rtu_port.setCurrentText(current)
        else:
            # 実在しない COM1 / ttyS* を仮置きしない（起動できないため）
            self.rtu_port.setEditable(True)
            self.rtu_port.lineEdit().setPlaceholderText(
                "シリアルポート未検出（例: COM3 / /dev/ttyUSB0）"
            )
            if current:
                self.rtu_port.addItem(current)
                self.rtu_port.setCurrentText(current)
            else:
                self.rtu_port.setCurrentIndex(-1)
        self.rtu_port.blockSignals(False)

    def set_tcp_settings_enabled(self, enabled: bool) -> None:
        self._tcp_settings_enabled = enabled
        self._apply_mode_state()

    def set_rtu_settings_enabled(self, enabled: bool) -> None:
        self._rtu_settings_enabled = enabled
        self._apply_mode_state()

    def get_tcp_config(self) -> TcpConfig:
        # コンボ初期表示だけでは configured に入らないため、画面上の値を正とする
        host = self.tcp_host.currentText().strip()
        port_text = self.tcp_port.text().strip()
        if not host:
            raise ValueError("IP アドレスを設定してください")
        if not port_text:
            raise ValueError("ポート番号を設定してください")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError("ポート番号は整数で入力してください") from exc
        if not 1 <= port <= 65535:
            raise ValueError("ポート番号は 1〜65535 です")
        from modbus_sim.platform_util import privileged_tcp_ports_restricted

        if privileged_tcp_ports_restricted() and port < 1024:
            raise ValueError(
                f"ポート {port} は特権ポートです。"
                "Linux/WSL では root 以外バインドできません。"
                "5020 など 1024 以上を指定してください"
                "（ネイティブ Windows では 502 も利用可能です）"
            )
        config = TcpConfig(host=host, port=port)
        self.comm.tcp_host = config.host
        self.comm.tcp_port = config.port
        self.comm.mark("tcp_host")
        self.comm.mark("tcp_port")
        self.update_summary()
        return config

    def get_rtu_config(self) -> RtuConfig:
        # コンボ初期表示だけでは configured に入らないため、画面上の値を正とする
        port = self.rtu_port.currentText().strip()
        baud_text = self.rtu_baudrate.currentText().strip()
        parity = self.rtu_parity.currentText().strip()
        bytesize_text = self.rtu_bytesize.currentText().strip()
        stopbits_text = self.rtu_stopbits.currentText().strip()
        if not port:
            raise ValueError("シリアルポートを設定してください")
        if not baud_text:
            raise ValueError("ボーレートを設定してください")
        if not parity:
            raise ValueError("パリティを設定してください")
        if not bytesize_text:
            raise ValueError("データビットを設定してください")
        if not stopbits_text:
            raise ValueError("ストップビットを設定してください")
        try:
            baudrate = int(baud_text)
            bytesize = int(bytesize_text)
            stopbits = int(stopbits_text)
        except ValueError as exc:
            raise ValueError("RTU の数値項目が不正です") from exc
        config = RtuConfig(
            port=port,
            baudrate=baudrate,
            parity=Parity(parity),
            bytesize=bytesize,
            stopbits=stopbits,
        )
        self.comm.rtu_port = config.port
        self.comm.rtu_baudrate = config.baudrate
        self.comm.rtu_parity = config.parity.value
        self.comm.rtu_bytesize = config.bytesize
        self.comm.rtu_stopbits = config.stopbits
        self.comm.mark("rtu_port")
        self.comm.mark("rtu_baudrate")
        self.comm.mark("rtu_parity")
        self.comm.mark("rtu_bytesize")
        self.comm.mark("rtu_stopbits")
        self.update_summary()
        return config

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if "tcp_host" in self.comm.configured:
            data["tcp"] = {"host": self.comm.tcp_host, "port": self.comm.tcp_port}
        elif "tcp_port" in self.comm.configured:
            data["tcp"] = {"host": self.comm.tcp_host, "port": self.comm.tcp_port}
        rtu: dict[str, Any] = {}
        if "rtu_port" in self.comm.configured:
            rtu["port"] = self.comm.rtu_port
        if "rtu_baudrate" in self.comm.configured:
            rtu["baudrate"] = self.comm.rtu_baudrate
        if "rtu_parity" in self.comm.configured:
            rtu["parity"] = self.comm.rtu_parity
        if "rtu_bytesize" in self.comm.configured:
            rtu["bytesize"] = self.comm.rtu_bytesize
        if "rtu_stopbits" in self.comm.configured:
            rtu["stopbits"] = self.comm.rtu_stopbits
        if rtu:
            data["rtu"] = rtu
        return data

    def apply_settings(self, data: dict[str, Any]) -> None:
        self._initializing = True
        tcp = data.get("tcp", {})
        if isinstance(tcp, dict):
            host = tcp.get("host")
            port = tcp.get("port")
            if host:
                self.refresh_ip_addresses()
                self.tcp_host.setCurrentText(str(host))
                self.comm.tcp_host = normalize_host(str(host))
                self.comm.mark("tcp_host")
            if port is not None:
                self.tcp_port.setText(str(port))
                self.comm.tcp_port = int(port)
                self.comm.mark("tcp_port")

        rtu = data.get("rtu", {})
        if isinstance(rtu, dict):
            port_name = rtu.get("port")
            if port_name:
                self.refresh_serial_ports()
                self.rtu_port.setCurrentText(str(port_name))
                self.comm.rtu_port = str(port_name)
                self.comm.mark("rtu_port")
            baud = rtu.get("baudrate")
            if baud is not None:
                self.rtu_baudrate.setCurrentText(str(baud))
                self.comm.rtu_baudrate = int(baud)
                self.comm.mark("rtu_baudrate")
            parity = rtu.get("parity")
            if parity:
                self.rtu_parity.setCurrentText(str(parity))
                self.comm.rtu_parity = str(parity)
                self.comm.mark("rtu_parity")
            bytesize = rtu.get("bytesize")
            if bytesize is not None:
                self.rtu_bytesize.setCurrentText(str(bytesize))
                self.comm.rtu_bytesize = int(bytesize)
                self.comm.mark("rtu_bytesize")
            stopbits = rtu.get("stopbits")
            if stopbits is not None:
                self.rtu_stopbits.setCurrentText(str(stopbits))
                self.comm.rtu_stopbits = int(stopbits)
                self.comm.mark("rtu_stopbits")

        self._initializing = False
        self.update_summary()

    def update_summary(self) -> None:
        lines = self.comm.summary_lines()
        self.config_summary.setText("\n".join(lines) if lines else "(未設定)")

    def _fill_combos(self) -> None:
        self.rtu_baudrate.clear()
        for rate in BAUD_RATES:
            self.rtu_baudrate.addItem(str(rate))
        self.rtu_baudrate.setCurrentText("9600")

        self.rtu_parity.clear()
        for parity in Parity:
            self.rtu_parity.addItem(parity.value)
        # 仕様既定: Even
        self.rtu_parity.setCurrentText(Parity.EVEN.value)

        self.rtu_bytesize.clear()
        for bits in DATA_BITS:
            self.rtu_bytesize.addItem(str(bits))
        # 仕様既定: 8（DATA_BITS 先頭も 8）
        self.rtu_bytesize.setCurrentText("8")

        self.rtu_stopbits.clear()
        for bits in STOP_BITS:
            self.rtu_stopbits.addItem(str(bits))
        self.rtu_stopbits.setCurrentText("1")

    def _wire_handlers(self) -> None:
        self.tcp_host.currentTextChanged.connect(lambda t: self._set_tcp_host(t))
        self.tcp_port.textChanged.connect(lambda t: self._set_tcp_port(t))
        self.rtu_port.currentTextChanged.connect(lambda t: self._set_rtu_port(t))
        self.rtu_baudrate.currentTextChanged.connect(lambda t: self._set_rtu_baudrate(t))
        self.rtu_parity.currentTextChanged.connect(lambda t: self._set_rtu_parity(t))
        self.rtu_bytesize.currentTextChanged.connect(lambda t: self._set_rtu_bytesize(t))
        self.rtu_stopbits.currentTextChanged.connect(lambda t: self._set_rtu_stopbits(t))
        self.refresh_ip_button.clicked.connect(self.refresh_ip_addresses)
        self.refresh_ports_button.clicked.connect(self._refresh_ports_click)

    def _notify_change(self) -> None:
        self.update_summary()
        if not self._initializing and self._on_change:
            self._on_change()

    def _set_tcp_host(self, value: str) -> None:
        text = value.strip()
        if not text:
            return
        try:
            self.comm.tcp_host = normalize_host(text)
            self.comm.mark("tcp_host")
            self._notify_change()
        except ValueError:
            pass

    def _set_tcp_port(self, value: str) -> None:
        if not value:
            return
        try:
            self.comm.tcp_port = int(value)
            self.comm.mark("tcp_port")
            self._notify_change()
        except ValueError:
            pass

    def _set_rtu_port(self, value: str) -> None:
        if value:
            self.comm.rtu_port = value.strip()
            self.comm.mark("rtu_port")
        self._notify_change()

    def _set_rtu_baudrate(self, value: str) -> None:
        if value:
            self.comm.rtu_baudrate = int(value)
            self.comm.mark("rtu_baudrate")
        self._notify_change()

    def _set_rtu_parity(self, value: str) -> None:
        if value:
            self.comm.rtu_parity = value
            self.comm.mark("rtu_parity")
        self._notify_change()

    def _set_rtu_bytesize(self, value: str) -> None:
        if value:
            self.comm.rtu_bytesize = int(value)
            self.comm.mark("rtu_bytesize")
        self._notify_change()

    def _set_rtu_stopbits(self, value: str) -> None:
        if value:
            self.comm.rtu_stopbits = int(value)
            self.comm.mark("rtu_stopbits")
        self._notify_change()

    def _refresh_ports_click(self) -> None:
        self.refresh_serial_ports()

    def _apply_mode_state(self) -> None:
        self.tcp_host.setEnabled(self._tcp_settings_enabled)
        self.refresh_ip_button.setEnabled(self._tcp_settings_enabled)
        self.tcp_port.setEnabled(self._tcp_settings_enabled)
        self.rtu_port.setEnabled(self._rtu_settings_enabled)
        self.refresh_ports_button.setEnabled(self._rtu_settings_enabled)
        self.rtu_baudrate.setEnabled(self._rtu_settings_enabled)
        self.rtu_parity.setEnabled(self._rtu_settings_enabled)
        self.rtu_bytesize.setEnabled(self._rtu_settings_enabled)
        self.rtu_stopbits.setEnabled(self._rtu_settings_enabled)
