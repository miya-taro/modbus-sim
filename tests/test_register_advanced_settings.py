"""異常応答強制 / 応答遅延 / 値の自動変化 のテスト。"""

from __future__ import annotations

import asyncio
import sys
import time

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from modbus_sim.config import AutoMode, FaultException, FaultMode, RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveDatastore, SlaveRegistry
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.ui.slave_panel import TAG_COL, RegisterAdvancedDialog, SlavePanel


@pytest.fixture
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def _hr(address: int, raw: int = 0, **kwargs) -> RegisterPoint:
    return RegisterPoint(address=address, kind=RegisterKind.HOLDING_REGISTER, raw=raw, **kwargs)


class TestForcedExceptionOverTcp:
    @pytest.mark.asyncio
    async def test_exception_mode_returns_configured_exception_code(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            _hr(10, raw=1, fault_mode=FaultMode.EXCEPTION, fault_exception=FaultException.DEVICE_BUSY)
        )
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19301))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19301)
            assert await client.connect()
            result = await client.read_holding_registers(10, count=1, device_id=1)
            assert result.isError()
            assert result.exception_code == 6  # DEVICE_BUSY
            client.close()
        finally:
            await mgr.stop_tcp()

    @pytest.mark.asyncio
    async def test_registers_without_fault_are_unaffected(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        slave = reg.get_slave(1)
        slave.upsert_point(
            _hr(10, raw=1, fault_mode=FaultMode.EXCEPTION, fault_exception=FaultException.DEVICE_BUSY)
        )
        slave.upsert_point(_hr(20, raw=42))
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19302))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19302)
            assert await client.connect()
            result = await client.read_holding_registers(20, count=1, device_id=1)
            assert not result.isError()
            assert result.registers == [42]
            client.close()
        finally:
            await mgr.stop_tcp()


class TestResponseDelayOverTcp:
    @pytest.mark.asyncio
    async def test_fixed_delay_is_applied(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(30, raw=7, delay_min_ms=250, delay_max_ms=250))
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19303))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19303)
            assert await client.connect()
            start = time.monotonic()
            result = await client.read_holding_registers(30, count=1, device_id=1)
            elapsed = time.monotonic() - start
            assert not result.isError()
            assert result.registers == [7]
            assert elapsed >= 0.2
            client.close()
        finally:
            await mgr.stop_tcp()


class TestNoResponseOverTcp:
    @pytest.mark.asyncio
    async def test_no_response_mode_never_answers_within_timeout(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(40, raw=1, fault_mode=FaultMode.NO_RESPONSE))
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19304))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19304)
            assert await client.connect()
            with pytest.raises(Exception):  # noqa: B017 - pymodbus wraps cancellation in its own exception
                await asyncio.wait_for(
                    client.read_holding_registers(40, count=1, device_id=1), timeout=0.5
                )
            client.close()
        finally:
            await mgr.stop_tcp()


class TestTickAutoValues:
    def test_increment_wraps_within_range(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(1, raw=8, auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=10, auto_step=1, auto_period_sec=1.0)
        )
        seen = []
        for _ in range(4):
            slave.tick_auto_values(1.0)
            seen.append(slave.get_point(1, RegisterKind.HOLDING_REGISTER).raw)
        assert seen == [9, 10, 0, 1]

    def test_increment_does_not_step_before_period_elapses(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(1, raw=0, auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=10, auto_step=1, auto_period_sec=2.0)
        )
        changed = slave.tick_auto_values(0.5)
        assert changed is False
        assert slave.get_point(1, RegisterKind.HOLDING_REGISTER).raw == 0

    def test_random_walk_stays_within_bounds(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(
                2,
                raw=50,
                auto_mode=AutoMode.RANDOM_WALK,
                auto_min=0,
                auto_max=100,
                auto_step=5,
                auto_period_sec=0.1,
            )
        )
        for _ in range(50):
            slave.tick_auto_values(0.1)
            value = slave.get_point(2, RegisterKind.HOLDING_REGISTER).raw
            assert 0 <= value <= 100

    def test_sine_oscillates_between_min_and_max(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(3, raw=0, auto_mode=AutoMode.SINE, auto_min=0, auto_max=100, auto_period_sec=4.0)
        )
        values = []
        for _ in range(9):
            slave.tick_auto_values(0.5)
            values.append(slave.get_point(3, RegisterKind.HOLDING_REGISTER).raw)
        assert max(values) == 100
        assert min(values) == 0

    def test_disabled_range_is_a_no_op(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(_hr(4, raw=5, auto_mode=AutoMode.INCREMENT))  # auto_min == auto_max == 0
        changed = slave.tick_auto_values(10.0)
        assert changed is False
        assert slave.get_point(4, RegisterKind.HOLDING_REGISTER).raw == 5

    def test_coil_is_not_affected_by_auto_mode(self) -> None:
        # RegisterPoint.auto_mode は Coil にも設定できるが、tick では無視される
        # （Coil/Discrete Input は自動変化に非対応のため）。
        slave = SlaveDatastore(1)
        point = RegisterPoint(
            address=5,
            kind=RegisterKind.COIL,
            datatype=ValueKind.BOOL,
            raw=0,
            auto_mode=AutoMode.INCREMENT,
            auto_min=0,
            auto_max=1,
            auto_period_sec=0.1,
        )
        slave.upsert_point(point)
        changed = slave.tick_auto_values(1.0)
        assert changed is False

    def test_registry_ticks_every_slave_not_just_the_first(self) -> None:
        # any([...]) ではなく全 slave を評価すること（短絡評価による後続 slave の
        # tick スキップの回帰防止）。
        reg = SlaveRegistry()
        reg.add_slave(2)
        reg.get_slave(1).upsert_point(
            _hr(1, raw=0, auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=10, auto_step=1, auto_period_sec=1.0)
        )
        reg.get_slave(2).upsert_point(
            _hr(1, raw=0, auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=10, auto_step=1, auto_period_sec=1.0)
        )
        reg.tick_auto_values(1.0)
        assert reg.get_slave(1).get_point(1, RegisterKind.HOLDING_REGISTER).raw == 1
        assert reg.get_slave(2).get_point(1, RegisterKind.HOLDING_REGISTER).raw == 1


class TestPersistenceRoundTrip:
    def test_advanced_settings_survive_to_dict_load_from_dict(self) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            _hr(
                6,
                raw=3,
                fault_mode=FaultMode.EXCEPTION,
                fault_exception=FaultException.GATEWAY_NO_RESPONSE,
                delay_min_ms=10,
                delay_max_ms=50,
                auto_mode=AutoMode.SINE,
                auto_min=1,
                auto_max=99,
                auto_step=2.5,
                auto_period_sec=3.0,
            )
        )
        data = reg.to_dict()

        restored = SlaveRegistry()
        restored.load_from_dict(data)
        point = restored.get_slave(1).get_point(6, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.fault_mode == FaultMode.EXCEPTION
        assert point.fault_exception == FaultException.GATEWAY_NO_RESPONSE
        assert point.delay_min_ms == 10
        assert point.delay_max_ms == 50
        assert point.auto_mode == AutoMode.SINE
        assert point.auto_min == 1
        assert point.auto_max == 99
        assert point.auto_step == 2.5
        assert point.auto_period_sec == 3.0

    def test_plain_points_do_not_gain_advanced_keys(self) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(7, raw=1))
        data = reg.to_dict()
        point_data = data["slaves"][0]["points"][0]
        assert "fault_mode" not in point_data
        assert "auto_mode" not in point_data


class TestRegisterAdvancedDialog:
    def test_apply_to_updates_all_fields(self, qapp: QApplication) -> None:
        point = _hr(8, raw=1)
        dialog = RegisterAdvancedDialog(None, point)
        dialog.fault_mode_combo.setCurrentIndex(list(FaultMode).index(FaultMode.EXCEPTION))
        dialog.fault_exception_combo.setCurrentIndex(
            list(FaultException).index(FaultException.ILLEGAL_DATA_ADDRESS)
        )
        dialog.delay_min_spin.setValue(5)
        dialog.delay_max_spin.setValue(15)
        dialog.auto_mode_combo.setCurrentIndex(list(AutoMode).index(AutoMode.INCREMENT))
        dialog.auto_min_spin.setValue(0)
        dialog.auto_max_spin.setValue(20)
        dialog.auto_step_spin.setValue(2)
        dialog.auto_period_spin.setValue(1.5)

        dialog.apply_to(point)

        assert point.fault_mode == FaultMode.EXCEPTION
        assert point.fault_exception == FaultException.ILLEGAL_DATA_ADDRESS
        assert point.delay_min_ms == 5
        assert point.delay_max_ms == 15
        assert point.auto_mode == AutoMode.INCREMENT
        assert point.auto_min == 0
        assert point.auto_max == 20
        assert point.auto_step == 2
        assert point.auto_period_sec == 1.5

    def test_auto_group_disabled_for_coil(self, qapp: QApplication) -> None:
        point = RegisterPoint(address=9, kind=RegisterKind.COIL, datatype=ValueKind.BOOL, raw=0)
        dialog = RegisterAdvancedDialog(None, point)
        assert dialog.auto_mode_combo.parentWidget().isEnabled() is False

    def test_delay_max_less_than_min_is_rejected(self, qapp: QApplication, monkeypatch) -> None:
        warnings = []
        monkeypatch.setattr(
            "modbus_sim.ui.slave_panel.QMessageBox.warning",
            lambda *a, **k: warnings.append(a) or None,
        )
        point = _hr(11, raw=1)
        dialog = RegisterAdvancedDialog(None, point)
        dialog.delay_min_spin.setValue(100)
        dialog.delay_max_spin.setValue(10)
        dialog._on_accept()
        assert len(warnings) == 1

    def test_auto_max_not_greater_than_min_is_rejected(self, qapp: QApplication, monkeypatch) -> None:
        warnings = []
        monkeypatch.setattr(
            "modbus_sim.ui.slave_panel.QMessageBox.warning",
            lambda *a, **k: warnings.append(a) or None,
        )
        point = _hr(12, raw=1)
        dialog = RegisterAdvancedDialog(None, point)
        dialog.auto_mode_combo.setCurrentIndex(list(AutoMode).index(AutoMode.INCREMENT))
        dialog.auto_min_spin.setValue(10)
        dialog.auto_max_spin.setValue(10)
        dialog._on_accept()
        assert len(warnings) == 1


class TestSlavePanelAdvancedDialogIntegration:
    def test_open_advanced_dialog_applies_settings_to_registry_point(
        self, qapp: QApplication, monkeypatch
    ) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(13, raw=1))
        panel = SlavePanel(slave_registry=reg)

        def fake_init(self, parent, point) -> None:
            RegisterAdvancedDialog.__wrapped_init__(self, parent, point)
            self.fault_mode_combo.setCurrentIndex(list(FaultMode).index(FaultMode.NO_RESPONSE))

        RegisterAdvancedDialog.__wrapped_init__ = RegisterAdvancedDialog.__init__
        monkeypatch.setattr(RegisterAdvancedDialog, "__init__", fake_init)
        monkeypatch.setattr(RegisterAdvancedDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

        row = next(
            i for i, p in enumerate(panel._row_meta) if p is not None and p.address == 13
        )
        panel._open_advanced_dialog(row)

        point = reg.get_slave(1).get_point(13, RegisterKind.HOLDING_REGISTER)
        assert point.fault_mode == FaultMode.NO_RESPONSE
        assert point.has_advanced_settings() is True

    def test_open_advanced_dialog_cancelled_leaves_point_unchanged(
        self, qapp: QApplication, monkeypatch
    ) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(14, raw=1))
        panel = SlavePanel(slave_registry=reg)
        monkeypatch.setattr(RegisterAdvancedDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

        row = next(
            i for i, p in enumerate(panel._row_meta) if p is not None and p.address == 14
        )
        panel._open_advanced_dialog(row)

        point = reg.get_slave(1).get_point(14, RegisterKind.HOLDING_REGISTER)
        assert point.has_advanced_settings() is False


class TestGridEditPreservesAdvancedSettings:
    """通常のグリッド編集（Tag/Raw等）で詳細設定が消えないことの回帰テスト。"""

    def test_editing_tag_keeps_fault_mode(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            _hr(15, raw=1, fault_mode=FaultMode.EXCEPTION, fault_exception=FaultException.DEVICE_BUSY)
        )
        panel = SlavePanel(slave_registry=reg)
        row = next(i for i, p in enumerate(panel._row_meta) if p is not None and p.address == 15)

        panel.table.item(row, TAG_COL).setText("hello")

        point = reg.get_slave(1).get_point(15, RegisterKind.HOLDING_REGISTER)
        assert point.tag == "hello"
        assert point.fault_mode == FaultMode.EXCEPTION
        assert point.fault_exception == FaultException.DEVICE_BUSY

    def test_editing_raw_keeps_auto_mode_settings(self, qapp: QApplication) -> None:
        from modbus_sim.ui.slave_panel import RAW_COL

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            _hr(
                16,
                raw=1,
                auto_mode=AutoMode.SINE,
                auto_min=0,
                auto_max=100,
                auto_period_sec=3.0,
            )
        )
        panel = SlavePanel(slave_registry=reg)
        row = next(i for i, p in enumerate(panel._row_meta) if p is not None and p.address == 16)

        panel.table.item(row, RAW_COL).setText("42")

        point = reg.get_slave(1).get_point(16, RegisterKind.HOLDING_REGISTER)
        assert point.raw == 42
        assert point.auto_mode == AutoMode.SINE
        assert point.auto_min == 0
        assert point.auto_max == 100
        assert point.auto_period_sec == 3.0
