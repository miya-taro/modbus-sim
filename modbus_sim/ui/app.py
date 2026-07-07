"""Main PySide6 application window."""

from __future__ import annotations

import asyncio
import sys

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modbus_sim.config import TcpConfig
from modbus_sim.datastore import registry
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.settings_store import SettingsStore
from modbus_sim.ui.async_runner import AsyncRunner
from modbus_sim.ui.log_panel import LogPanel
from modbus_sim.ui.settings_panel import SettingsPanel
from modbus_sim.ui.slave_panel import SlavePanel

TAB_SETTINGS = 0
TAB_SLAVE = 1
TAB_LOG = 2


async def _prebuild_sim_devices() -> None:
    await asyncio.to_thread(registry.build_sim_devices)


async def _start_tcp_server(manager: ModbusServerManager, config: TcpConfig) -> None:
    await asyncio.to_thread(registry.build_sim_devices)
    await manager.start_tcp(config)


class ServerBridge(QObject):
    tcp_state_changed = Signal(bool)
    rtu_state_changed = Signal(bool)
    log_dirty = Signal()
    error = Signal(str)
    operation_finished = Signal()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Modbus Simulator")
        self.resize(900, 640)
        self.setMinimumSize(800, 560)

        self._bridge = ServerBridge()
        self._bridge.tcp_state_changed.connect(self._refresh_tcp_status)
        self._bridge.rtu_state_changed.connect(self._refresh_rtu_status)
        self._bridge.log_dirty.connect(self._mark_log_dirty)
        self._bridge.error.connect(self._show_error)
        self._bridge.operation_finished.connect(self._on_operation_finished)

        self._async = AsyncRunner()
        self._settings_store = SettingsStore()
        self._log_dirty = False
        self._last_log_count = 0
        self._tcp_busy = False
        self._rtu_busy = False

        self.settings_panel = SettingsPanel(on_change=self._schedule_save)
        self.slave_panel = SlavePanel(on_change=self._schedule_save)
        self.log_panel = LogPanel()

        self.server_manager = ModbusServerManager(
            on_log=lambda _msg: self._bridge.log_dirty.emit(),
            on_tcp_state_change=lambda running: self._bridge.tcp_state_changed.emit(running),
            on_rtu_state_change=lambda running: self._bridge.rtu_state_changed.emit(running),
        )
        self.log_panel._on_clear = lambda: self.server_manager.log_buffer.clear()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_settings)

        self._settings_store.apply(self.settings_panel, registry)
        self.slave_panel._rebuild()

        self.tcp_status = QLabel("●")
        self.tcp_status_text = QLabel("TCP 停止")
        self.tcp_button = QPushButton("TCP 開始")
        self.tcp_button.clicked.connect(self._toggle_tcp)

        self.rtu_status = QLabel("●")
        self.rtu_status_text = QLabel("RTU 停止")
        self.rtu_button = QPushButton("RTU 開始")
        self.rtu_button.clicked.connect(self._toggle_rtu)

        self.slave_error = QLabel("")
        self.slave_error.setStyleSheet("color: #b00020;")

        header = QHBoxLayout()
        title = QLabel("Modbus TCP/RTU シミュレータ")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.tcp_status)
        header.addWidget(self.tcp_status_text)
        header.addWidget(self.tcp_button)
        header.addSpacing(16)
        header.addWidget(self.rtu_status)
        header.addWidget(self.rtu_status_text)
        header.addWidget(self.rtu_button)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.settings_panel, "通信設定")
        self.tabs.addTab(self.slave_panel, "スレーブ")
        self.tabs.addTab(self.log_panel, "通信ログ")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(header)
        layout.addWidget(self.slave_error)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_ui)
        self._poll_timer.start(500)

        self._update_grid_enabled()
        self.settings_panel.update_summary()
        self._async.submit(_prebuild_sim_devices())

    def _update_grid_enabled(self) -> None:
        self.slave_panel.set_grid_enabled(True)
        self.slave_panel.set_server_running(self.server_manager.any_running)

    @Slot()
    def _on_operation_finished(self) -> None:
        self._tcp_busy = False
        self._rtu_busy = False
        self.tcp_button.setEnabled(True)
        self.rtu_button.setEnabled(True)

    @Slot(bool)
    def _refresh_tcp_status(self, running: bool) -> None:
        color = "green" if running else "red"
        status = "TCP 待受中" if running else "TCP 停止"
        self.tcp_status.setStyleSheet(f"color: {color}; font-size: 14px;")
        self.tcp_status_text.setText(status)
        self.tcp_status_text.setStyleSheet(f"color: {color};")
        self.tcp_button.setText("TCP 停止" if running else "TCP 開始")
        self.settings_panel.set_tcp_settings_enabled(not running)
        self._update_grid_enabled()

    @Slot(bool)
    def _refresh_rtu_status(self, running: bool) -> None:
        color = "green" if running else "red"
        status = "RTU 待受中" if running else "RTU 停止"
        self.rtu_status.setStyleSheet(f"color: {color}; font-size: 14px;")
        self.rtu_status_text.setText(status)
        self.rtu_status_text.setStyleSheet(f"color: {color};")
        self.rtu_button.setText("RTU 停止" if running else "RTU 開始")
        self.settings_panel.set_rtu_settings_enabled(not running)
        self._update_grid_enabled()

    @Slot()
    def _mark_log_dirty(self) -> None:
        self._log_dirty = True

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self.slave_error.setText(message)

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save_settings(self) -> None:
        registry.selected_slave_id = self.slave_panel._registry.selected_slave_id
        self._settings_store.save(self.settings_panel, registry)

    def _on_tab_changed(self, index: int) -> None:
        if index == TAB_SLAVE:
            self._save_settings()

    def _toggle_tcp(self) -> None:
        if self._tcp_busy:
            return
        self.slave_error.setText("")
        self._tcp_busy = True
        self.tcp_button.setEnabled(False)

        def _done(future) -> None:
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                self._bridge.error.emit(str(exc))
            self._bridge.log_dirty.emit()
            self._bridge.operation_finished.emit()

        if self.server_manager.tcp_running:
            self._async.submit(self.server_manager.stop_tcp()).add_done_callback(_done)
        else:
            try:
                config = self.settings_panel.get_tcp_config()
            except Exception as exc:  # noqa: BLE001
                self.slave_error.setText(str(exc))
                self._bridge.operation_finished.emit()
                return
            self.tcp_status_text.setText("TCP 起動中...")
            self._async.submit(_start_tcp_server(self.server_manager, config)).add_done_callback(_done)

    def _toggle_rtu(self) -> None:
        if self._rtu_busy:
            return
        self.slave_error.setText("")
        self._rtu_busy = True
        self.rtu_button.setEnabled(False)

        def _done(future) -> None:
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                self._bridge.error.emit(str(exc))
            self._bridge.log_dirty.emit()
            self._bridge.operation_finished.emit()

        if self.server_manager.rtu_running:
            self._async.submit(self.server_manager.stop_rtu()).add_done_callback(_done)
        else:
            try:
                config = self.settings_panel.get_rtu_config()
            except Exception as exc:  # noqa: BLE001
                self.slave_error.setText(str(exc))
                self._bridge.operation_finished.emit()
                return
            self._async.submit(self.server_manager.start_rtu(config)).add_done_callback(_done)

    def _poll_ui(self) -> None:
        if self.tabs.currentIndex() == TAB_SLAVE:
            self.slave_panel.refresh_from_server()
        self.slave_panel.refresh_activity(self.server_manager.any_running)

        logs = list(self.server_manager.log_buffer)
        if self._log_dirty or len(logs) != self._last_log_count:
            self._log_dirty = False
            self.log_panel.set_lines(logs[-200:])
            self._last_log_count = len(logs)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_settings()
        if self.server_manager.any_running:
            future = self._async.submit(self.server_manager.stop_all())
            try:
                future.result(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        self._async.stop()
        super().closeEvent(event)


def create_app() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
