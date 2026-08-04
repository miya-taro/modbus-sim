"""レジスタ表の一括操作（複製・範囲追加・コピー/貼り付け）のテスト。"""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from modbus_sim.config import RegisterKind, ValueKind
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.models import RegisterPoint
from modbus_sim.ui.slave_panel import ADDR_COL, RangeAddDialog, SlavePanel


@pytest.fixture
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def _row_for_address(panel: SlavePanel, address: int) -> int:
    for row in range(panel.table.rowCount()):
        item = panel.table.item(row, ADDR_COL)
        if item is not None and item.text() == str(address):
            return row
    raise AssertionError(f"address {address} not found in grid")


class TestDuplicateRows:
    def test_duplicate_picks_next_free_address(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            RegisterPoint(
                address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16,
                raw=99, tag="flow",
            )
        )
        panel = SlavePanel(slave_registry=reg)
        row = _row_for_address(panel, 10)

        panel._duplicate_rows([row])

        addresses = sorted(p.address for p in reg.get_slave(1).list_points())
        assert addresses == [10, 11]
        dup = reg.get_slave(1).get_point(11, RegisterKind.HOLDING_REGISTER)
        assert dup is not None
        assert dup.raw == 99
        assert dup.tag == "flow"

    def test_duplicate_skips_occupied_addresses(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        slave = reg.get_slave(1)
        slave.upsert_point(
            RegisterPoint(address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=1)
        )
        slave.upsert_point(
            RegisterPoint(address=11, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=2)
        )
        panel = SlavePanel(slave_registry=reg)
        row = _row_for_address(panel, 10)

        panel._duplicate_rows([row])

        addresses = sorted(p.address for p in slave.list_points())
        assert addresses == [10, 11, 12]

    def test_duplicate_int32_steps_by_two(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            RegisterPoint(address=100, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.INT32, raw=42)
        )
        panel = SlavePanel(slave_registry=reg)
        row = _row_for_address(panel, 100)

        panel._duplicate_rows([row])

        addresses = sorted(p.address for p in reg.get_slave(1).list_points())
        assert addresses == [100, 102]


class TestCopyPaste:
    def test_copy_then_paste_into_other_slave(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        reg.add_slave(2)
        reg.get_slave(1).upsert_point(
            RegisterPoint(
                address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16,
                raw=99, tag="flow",
            )
        )
        panel = SlavePanel(slave_registry=reg)
        row = _row_for_address(panel, 10)
        panel._copy_rows([row])

        panel._registry.selected_slave_id = 2
        panel._rebuild()
        panel._paste_rows()

        point = reg.get_slave(2).get_point(10, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.raw == 99
        assert point.tag == "flow"

    def test_paste_from_external_tsv_without_header(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        QApplication.clipboard().setText("50\thr\tuint16\t123\tmytag\n51\tcoil\tbool\t1\t")

        panel._paste_rows()

        p50 = reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER)
        p51 = reg.get_slave(1).get_point(51, RegisterKind.COIL)
        assert p50 is not None and p50.raw == 123 and p50.tag == "mytag"
        assert p51 is not None and bool(p51.raw) is True

    def test_paste_invalid_line_reports_error_but_keeps_valid_ones(
        self, qapp: QApplication, monkeypatch
    ) -> None:
        from PySide6.QtWidgets import QMessageBox

        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: warnings.append(a) or QMessageBox.StandardButton.Ok
        )
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        QApplication.clipboard().setText("50\thr\tuint16\t1\t\nnot-a-number\thr\tuint16\t1\t")

        panel._paste_rows()

        assert reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER) is not None
        assert len(warnings) == 1


class TestRangeAddDialog:
    def test_range_add_creates_sequential_points(self, qapp: QApplication, monkeypatch) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.set_active_kind(RegisterKind.INPUT_REGISTER)

        orig_init = RangeAddDialog.__init__

        def fake_init(self, parent=None, *, default_kind=RegisterKind.HOLDING_REGISTER) -> None:
            orig_init(self, parent, default_kind=default_kind)
            self.start_address.setValue(100)
            self.count_field.setValue(3)
            self.raw_field.setText("7")
            self.tag_prefix_field.setText("S")

        monkeypatch.setattr(RangeAddDialog, "__init__", fake_init)
        monkeypatch.setattr(RangeAddDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

        panel._open_range_add_dialog()

        points = sorted(
            (p.address, p.kind, p.raw, p.tag) for p in reg.get_slave(1).list_points()
        )
        assert points == [
            (100, RegisterKind.INPUT_REGISTER, 7, "S0"),
            (101, RegisterKind.INPUT_REGISTER, 7, "S1"),
            (102, RegisterKind.INPUT_REGISTER, 7, "S2"),
        ]

    def test_range_add_cancelled_adds_nothing(self, qapp: QApplication, monkeypatch) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        monkeypatch.setattr(RangeAddDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

        panel._open_range_add_dialog()

        assert reg.get_slave(1).list_points() == []

    def test_import_simple_addr_raw_uses_active_kind(self, qapp: QApplication, tmp_path) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.set_active_kind(RegisterKind.COIL)
        path = tmp_path / "map.csv"
        path.write_text("Addr,Raw,Tag\n7,1,flag\n", encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        panel._import_register_map_text(text, action_label="取込")
        point = reg.get_slave(1).get_point(7, RegisterKind.COIL)
        assert point is not None
        assert point.raw == 1
        assert point.tag == "flag"
