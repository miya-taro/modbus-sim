"""レジスタ行 / Slave の削除操作に関するテスト。"""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from modbus_sim.config import RegisterKind, ValueKind
from modbus_sim.datastore import SlaveDatastore, SlaveRegistry
from modbus_sim.models import RegisterPoint
from modbus_sim.ui.slave_panel import ADDR_COL, SlavePanel


@pytest.fixture
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def _row_for_address(panel: SlavePanel, address: int) -> int:
    for row in range(panel.table.rowCount()):
        item = panel.table.item(row, ADDR_COL)
        if item is not None and item.text() == str(address):
            return row
    raise AssertionError(f"address {address} not found in grid")


class TestSlaveDatastoreRemovePoint:
    def test_remove_point_deletes_and_resets_memory(self) -> None:
        slave = SlaveDatastore(1)
        point = RegisterPoint(
            address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=42
        )
        slave.upsert_point(point)
        assert slave.get_point(10, RegisterKind.HOLDING_REGISTER) is not None

        removed = slave.remove_point(10, RegisterKind.HOLDING_REGISTER)
        assert removed is True
        assert slave.get_point(10, RegisterKind.HOLDING_REGISTER) is None
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 10) == 0

    def test_remove_point_missing_returns_false(self) -> None:
        slave = SlaveDatastore(1)
        assert slave.remove_point(10, RegisterKind.HOLDING_REGISTER) is False

    def test_remove_point_invalidates_sim_devices(self) -> None:
        reg = SlaveRegistry()
        slave = reg.get_slave(1)
        slave.upsert_point(
            RegisterPoint(address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16)
        )
        reg.build_sim_devices()
        reg._sim_devices = "sentinel"  # type: ignore[assignment]
        slave.remove_point(10, RegisterKind.HOLDING_REGISTER)
        assert reg._sim_devices is None


class TestSlaveRegistryRemoveSlave:
    def test_remove_slave(self) -> None:
        reg = SlaveRegistry()
        reg.add_slave(2)
        reg.remove_slave(2)
        assert reg.list_slave_ids() == [1]

    def test_remove_last_slave_raises(self) -> None:
        reg = SlaveRegistry()
        with pytest.raises(ValueError):
            reg.remove_slave(1)

    def test_remove_unknown_slave_raises(self) -> None:
        reg = SlaveRegistry()
        with pytest.raises(KeyError):
            reg.remove_slave(99)

    def test_remove_selected_slave_falls_back_to_remaining(self) -> None:
        reg = SlaveRegistry()
        reg.add_slave(2)
        reg.selected_slave_id = 2
        reg.remove_slave(2)
        assert reg.selected_slave_id == 1


class TestSlavePanelDeleteUI:
    def test_delete_row_via_menu_removes_point(self, qapp: QApplication, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("50")
        row = _row_for_address(panel, 50)
        assert reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER) is not None

        panel._delete_rows([row])

        assert reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER) is None

    def test_delete_row_cancelled_keeps_point(self, qapp: QApplication, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("50")
        row = _row_for_address(panel, 50)

        panel._delete_rows([row])

        assert reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER) is not None

    def test_draft_row_is_not_deletable(self, qapp: QApplication, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        draft_row = panel.table.rowCount() - 1
        assert panel._selected_data_rows() == [] or draft_row not in panel._selected_data_rows()

    def test_remove_slave_button_disabled_with_single_slave(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        assert panel.remove_slave_button.isEnabled() is False

    def test_remove_slave_button_enabled_with_multiple_slaves(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        reg.add_slave(2)
        panel = SlavePanel(slave_registry=reg)
        assert panel.remove_slave_button.isEnabled() is True

    def test_remove_slave_removes_selected(self, qapp: QApplication, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        reg = SlaveRegistry()
        reg.add_slave(2)
        panel = SlavePanel(slave_registry=reg)
        reg.selected_slave_id = 2
        panel._registry.selected_slave_id = 2

        panel._remove_slave()

        assert reg.list_slave_ids() == [1]

    def test_remove_slave_cancelled_keeps_slave(self, qapp: QApplication, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
        reg = SlaveRegistry()
        reg.add_slave(2)
        panel = SlavePanel(slave_registry=reg)
        panel._registry.selected_slave_id = 2

        panel._remove_slave()

        assert reg.list_slave_ids() == [1, 2]


class TestErrorCellFeedback:
    def test_invalid_address_marks_cell_with_tooltip(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        row = panel.table.rowCount() - 1
        panel.table.item(row, ADDR_COL).setText("999999")

        item = panel.table.item(row, ADDR_COL)
        assert item.toolTip() != ""

    def test_valid_address_clears_previous_error_mark(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        row = panel.table.rowCount() - 1
        panel.table.item(row, ADDR_COL).setText("999999")
        assert panel.table.item(row, ADDR_COL).toolTip() != ""

        panel.table.item(row, ADDR_COL).setText("50")
        row = _row_for_address(panel, 50)
        assert panel.table.item(row, ADDR_COL).toolTip() == ""


class TestKeyboardShortcuts:
    def test_panel_has_no_event_filter_override(self, qapp: QApplication) -> None:
        """eventFilter 再帰クラッシュ回避のため、ショートカット方式であること。"""
        panel = SlavePanel(slave_registry=SlaveRegistry())
        assert "eventFilter" not in type(panel).__dict__
        assert hasattr(panel, "_shortcut_copy")
        assert hasattr(panel, "_shortcut_delete_rows")

    def test_shortcut_delete_removes_selected_row(
        self, qapp: QApplication, monkeypatch
    ) -> None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("50")
        row = _row_for_address(panel, 50)
        panel.table.selectRow(row)

        panel._shortcut_delete_rows()
        assert reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER) is None
