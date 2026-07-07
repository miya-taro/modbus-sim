"""Smoke tests for UI component construction."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def test_ui_components_construct() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    from modbus_sim.ui.log_panel import LogPanel
    from modbus_sim.ui.settings_panel import SettingsPanel
    from modbus_sim.ui.slave_panel import SlavePanel

    assert isinstance(SettingsPanel(), SettingsPanel)
    assert isinstance(SlavePanel(), SlavePanel)
    assert isinstance(LogPanel(), LogPanel)
    assert app is not None


if __name__ == "__main__":
    test_ui_components_construct()
    print("ui smoke test passed")
