"""Main PySide6 application window."""

from __future__ import annotations

import asyncio
import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase
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
from modbus_sim.datastore import rtu_registry, tcp_registry
from modbus_sim.fonts_util import ensure_cjk_fonts
from modbus_sim.platform_util import is_wsl
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.settings_store import SettingsStore
from modbus_sim.ui.async_runner import AsyncRunner
from modbus_sim.ui.log_panel import LogPanel
from modbus_sim.ui.settings_panel import SettingsPanel
from modbus_sim.ui.slave_panel import SlavePanel

TAB_SETTINGS = 0
TAB_TCP_SLAVE = 1
TAB_RTU_SLAVE = 2
TAB_LOG = 3


async def _prebuild_sim_devices() -> None:
    await asyncio.to_thread(tcp_registry.build_sim_devices)
    await asyncio.to_thread(rtu_registry.build_sim_devices)


async def _start_tcp_server(manager: ModbusServerManager, config: TcpConfig) -> None:
    await asyncio.to_thread(tcp_registry.build_sim_devices)
    await manager.start_tcp(config)


class ServerBridge(QObject):
    tcp_state_changed = Signal(bool)
    rtu_state_changed = Signal(bool)
    log_dirty = Signal()
    error = Signal(str)


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

        self._async = AsyncRunner()
        self._settings_store = SettingsStore()
        self._log_dirty = False
        self._last_log_count = 0
        self._tcp_busy = False
        self._rtu_busy = False

        self.settings_panel = SettingsPanel(on_change=self._schedule_save)
        self.tcp_slave_panel = SlavePanel(
            slave_registry=tcp_registry,
            on_change=self._schedule_save,
            title="TCP スレーブ設定値",
        )
        self.rtu_slave_panel = SlavePanel(
            slave_registry=rtu_registry,
            on_change=self._schedule_save,
            title="RTU スレーブ設定値",
        )
        self.log_panel = LogPanel()

        self.server_manager = ModbusServerManager(
            tcp_registry=tcp_registry,
            rtu_registry=rtu_registry,
            on_log=lambda _msg: self._bridge.log_dirty.emit(),
            on_tcp_state_change=lambda running: self._bridge.tcp_state_changed.emit(running),
            on_rtu_state_change=lambda running: self._bridge.rtu_state_changed.emit(running),
        )
        self.log_panel._on_clear = lambda: self.server_manager.log_buffer.clear()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_settings)

        self._settings_store.apply(self.settings_panel, tcp_registry, rtu_registry)
        self.tcp_slave_panel._rebuild()
        self.rtu_slave_panel._rebuild()

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
        self.tabs.addTab(self.tcp_slave_panel, "TCP スレーブ")
        self.tabs.addTab(self.rtu_slave_panel, "RTU スレーブ")
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
        self.tcp_slave_panel.set_grid_enabled(True)
        self.rtu_slave_panel.set_grid_enabled(True)
        self.tcp_slave_panel.set_server_running(self.server_manager.tcp_running)
        self.rtu_slave_panel.set_server_running(self.server_manager.rtu_running)

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
        tcp_registry.selected_slave_id = self.tcp_slave_panel._registry.selected_slave_id
        rtu_registry.selected_slave_id = self.rtu_slave_panel._registry.selected_slave_id
        self._settings_store.save(self.settings_panel, tcp_registry, rtu_registry)

    def _on_tab_changed(self, index: int) -> None:
        if index in (TAB_TCP_SLAVE, TAB_RTU_SLAVE):
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
            self._tcp_busy = False
            self.tcp_button.setEnabled(True)
            self._bridge.log_dirty.emit()

        if self.server_manager.tcp_running:
            self._async.submit(self.server_manager.stop_tcp()).add_done_callback(_done)
        else:
            try:
                config = self.settings_panel.get_tcp_config()
            except Exception as exc:  # noqa: BLE001
                self.slave_error.setText(str(exc))
                self._tcp_busy = False
                self.tcp_button.setEnabled(True)
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
            self._rtu_busy = False
            self.rtu_button.setEnabled(True)
            self._bridge.log_dirty.emit()

        if self.server_manager.rtu_running:
            self._async.submit(self.server_manager.stop_rtu()).add_done_callback(_done)
        else:
            try:
                config = self.settings_panel.get_rtu_config()
            except Exception as exc:  # noqa: BLE001
                self.slave_error.setText(str(exc))
                self._rtu_busy = False
                self.rtu_button.setEnabled(True)
                return
            self._async.submit(self.server_manager.start_rtu(config)).add_done_callback(_done)

    def _poll_ui(self) -> None:
        index = self.tabs.currentIndex()
        if index == TAB_TCP_SLAVE:
            self.tcp_slave_panel.refresh_from_server()
        elif index == TAB_RTU_SLAVE:
            self.rtu_slave_panel.refresh_from_server()
        self.tcp_slave_panel.refresh_activity(self.server_manager.tcp_running)
        self.rtu_slave_panel.refresh_activity(self.server_manager.rtu_running)

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


def _is_wsl() -> bool:
    return is_wsl()


def _xcb_libs_available() -> bool:
    for name in (
        "libxcb-cursor.so.0",
        "libxcb-icccm.so.4",
        "libxcb-keysyms.so.1",
        "libxcb-shape.so.0",
        "libxkbcommon-x11.so.0",
    ):
        try:
            ctypes.CDLL(name)
        except OSError:
            return False
    return True


def _prepare_qt_platform() -> None:
    """WSLg では Wayland より X11(xcb) の方がウィンドウが出やすい。"""
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if not is_wsl():
        return
    if _xcb_libs_available():
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        os.environ.pop("WAYLAND_DISPLAY", None)
        return
    # xcb が使えなくても Wayland で起動を試みる（COPY MODE 警告が出ることがある）
    print(
        "注意: WSL でウィンドウが不安定な場合は次を実行してください:\n"
        "  sudo apt install -y libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 "
        "libxcb-shape0 libxkbcommon-x11-0\n"
        "  export QT_QPA_PLATFORM=xcb",
        flush=True,
    )


def _place_on_primary_screen(window: QMainWindow) -> None:
    primary = QApplication.primaryScreen()
    if primary is None:
        return
    handle = window.windowHandle()
    if handle is not None and window.screen() != primary:
        handle.setScreen(primary)
    geo = primary.availableGeometry()
    frame = window.frameGeometry()
    frame.moveCenter(geo.center())
    window.move(frame.topLeft())


def _apply_ui_font(app: QApplication) -> None:
    """日本語が □ になるのを避けるため、CJK 対応フォントを優先する。"""
    # ユーザー領域に入れた Noto CJK などを明示ロード
    font_dirs = [
        Path.home() / ".local/share/fonts",
        Path("/usr/share/fonts"),
    ]
    for font_dir in font_dirs:
        if not font_dir.is_dir():
            continue
        for path in font_dir.rglob("*"):
            if path.suffix.lower() not in {".ttc", ".ttf", ".otf"}:
                continue
            name = path.name.lower()
            if "noto" in name and "cjk" in name and "sans" in name:
                QFontDatabase.addApplicationFont(str(path))

    preferred = (
        "Noto Sans CJK JP",
        "Noto Sans CJK JP Regular",
        "Noto Sans JP",
        "IPAexGothic",
        "IPAGothic",
        "Yu Gothic",
        "Meiryo",
        "Hiragino Sans",
    )
    families = set(QFontDatabase.families())
    for name in preferred:
        if name in families:
            app.setFont(QFont(name, 10))
            return
    print(
        "注意: 日本語フォントが見つかりません。ラベルが □ になる場合は次を実行してください:\n"
        "  sudo apt install -y fonts-noto-cjk",
        flush=True,
    )


def create_app() -> int:
    _prepare_qt_platform()
    ensure_cjk_fonts()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    _apply_ui_font(app)
    window = MainWindow()
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
    window.show()
    _place_on_primary_screen(window)
    window.raise_()
    window.activateWindow()
    print(
        f"GUI を起動しました (platform={app.platformName()})。"
        " ウィンドウが出ない場合は Windows のタスクバーも確認してください。",
        flush=True,
    )
    return app.exec()
