"""設定の破損・不正値に対する堅牢性のテスト。

settings.json は手動編集や書き込み中断で壊れうる（例: id / port が非数値）。
壊れた値が1件混ざっただけで起動全体がクラッシュしたり、レジストリが空のまま
復旧できなくなったりしないことを確認する。
"""

from __future__ import annotations

import json

from modbus_sim.datastore import SlaveRegistry
from modbus_sim.models import CommSettings
from modbus_sim.settings_model import apply_dict_to_comm
from modbus_sim.settings_store import SettingsStore


class TestSlaveRegistryLoadFromDictRobustness:
    def test_non_numeric_slave_id_is_skipped_not_fatal(self) -> None:
        reg = SlaveRegistry()
        reg.load_from_dict({"slaves": [{"id": "not-a-number", "tag": "x", "points": []}]})
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


class TestApplyDictToComm:
    def test_bad_numeric_fields_do_not_raise(self) -> None:
        comm = CommSettings()
        apply_dict_to_comm(
            comm, {"tcp": {"host": "127.0.0.1", "port": "abc"}, "rtu": {"baudrate": "oops"}}
        )
        # host は妥当なので反映され、port は不正なので未設定のまま
        assert comm.tcp_host == "127.0.0.1"
        assert comm.tcp_port is None
        assert "tcp_port" not in comm.configured

    def test_valid_fields_still_apply_when_other_field_is_bad(self) -> None:
        comm = CommSettings()
        apply_dict_to_comm(
            comm, {"rtu": {"port": "COM3", "baudrate": "garbage", "parity": "Even"}}
        )
        assert comm.rtu_port == "COM3"
        assert comm.rtu_parity == "Even"
        # baudrate は不正なのでスキップされ、未設定のまま
        assert comm.rtu_baudrate is None
        assert "rtu_baudrate" not in comm.configured

    def test_invalid_host_is_skipped(self) -> None:
        comm = CommSettings()
        apply_dict_to_comm(comm, {"tcp": {"host": "not-an-ip", "port": 5020}})
        assert "tcp_host" not in comm.configured
        assert comm.tcp_port == 5020


class TestLoadPipelineRobustness:
    def test_corrupted_slaves_and_rtu_fields_do_not_crash_startup(self, tmp_path) -> None:
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
        data = SettingsStore(path).load()
        comm = CommSettings()
        apply_dict_to_comm(comm, data)  # 例外を送出しないこと
        tcp_reg = SlaveRegistry()
        tcp_reg.load_from_dict({"slaves": data.get("tcp_slaves", [])})

        assert tcp_reg.list_slave_ids() == [1]
        assert comm.tcp_port == 5020

    def test_corrupt_json_returns_empty_dict(self, tmp_path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{ not valid json", encoding="utf-8")
        assert SettingsStore(path).load() == {}
