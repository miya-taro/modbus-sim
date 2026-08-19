"""設定の破損・不正値に対する堅牢性のテスト。

settings.json は手動編集や書き込み中断で壊れうる（例: id / port が非数値）。
壊れた値が1件混ざっただけでアプリ起動全体がクラッシュしたり、
レジストリが空のまま復旧できなくなったりしないことを確認する。
"""

from __future__ import annotations

import json
import sys

import pytest
from PySide6.QtWidgets import QApplication

from modbus_sim.datastore import SlaveRegistry
from modbus_sim.settings_store import SettingsStore
from modbus_sim.ui.settings_panel import SettingsPanel


@pytest.fixture
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


class TestSlaveRegistryLoadFromDictRobustness:
    def test_non_numeric_slave_id_is_skipped_not_fatal(self) -> None:
        reg = SlaveRegistry()
        reg.load_from_dict({"slaves": [{"id": "not-a-number", "tag": "x", "points": []}]})
        # 不正な id のエントリはスキップされ、既定 Slave 1 にフォールバックする
        assert reg.list_slave_ids() == [1]

    def test_valid_entries_survive_alongside_invalid_one(self) -> None:
        reg = SlaveRegistry()
        reg.load_from_dict(
            {
                "slaves": [
                    {"id": "oops", "tag": "bad", "points": []},
                    {"id": 5, "tag": "good", "points": []},
                ]
            }
        )
        assert reg.list_slave_ids() == [5]
        assert reg.get_tag(5) == "good"

    def test_unhashable_selected_slave_id_does_not_raise(self) -> None:
        reg = SlaveRegistry()
        reg.load_from_dict(
            {"slaves": [{"id": 1, "tag": "", "points": []}], "selected_slave_id": ["not", "hashable"]}
        )
        assert reg.selected_slave_id == 1


class TestSettingsPanelApplySettings:
    def test_bad_numeric_fields_do_not_raise_and_reset_initializing(self, qapp: QApplication) -> None:
        panel = SettingsPanel()
        panel.apply_settings({"tcp": {"host": "127.0.0.1", "port": "abc"}, "rtu": {"baudrate": "oops"}})
        assert panel._initializing is False
        # host は妥当なので反映され、port は不正なので未設定のまま
        assert panel.comm.tcp_host == "127.0.0.1"
        assert panel.comm.tcp_port is None

    def test_valid_fields_still_apply_when_other_field_is_bad(self, qapp: QApplication) -> None:
        panel = SettingsPanel()
        # baudrate はコンボの初期選択により構築時点で既定値 9600 が configured 済み。
        # "garbage" を渡しても例外を出さず、既定値のまま変わらないことを確認する。
        panel.apply_settings(
            {"rtu": {"port": "COM3", "baudrate": "garbage", "parity": "Even"}}
        )
        assert panel.comm.rtu_port == "COM3"
        assert panel.comm.rtu_parity == "Even"
        assert panel.comm.rtu_baudrate == 9600


class TestSettingsStoreApplyRobustness:
    def test_corrupted_slaves_and_rtu_fields_do_not_crash_startup(self, qapp: QApplication, tmp_path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "tcp": {"host": "127.0.0.1", "port": 5020},
                    "tcp_slaves": [{"id": "oops", "tag": "", "points": []}],
                    "rtu": {"baudrate": "garbage"},
                }
            ),
            encoding="utf-8",
        )
        store = SettingsStore(path)
        panel = SettingsPanel()
        tcp_reg = SlaveRegistry()
        rtu_reg = SlaveRegistry()

        store.apply(panel, tcp_reg, rtu_reg)  # 例外を送出しないこと

        assert tcp_reg.list_slave_ids() == [1]
        assert panel.comm.tcp_port == 5020
