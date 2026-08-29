"""レジスタ一括操作（複製・範囲追加・CSV/TSV 取込）のテスト。

旧 SlavePanel 経由の UI テストを、UI 非依存の modbus_sim.registry_ops に対する
ユニットテストへ移植したもの。
"""

from __future__ import annotations

from modbus_sim.config import RegisterKind, ValueKind
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.models import RegisterPoint
from modbus_sim.registry_ops import (
    add_register_range,
    duplicate_points,
    import_register_map_text,
)


def _hr(address: int, raw: int = 0, tag: str = "", datatype=ValueKind.UINT16) -> RegisterPoint:
    return RegisterPoint(
        address=address, kind=RegisterKind.HOLDING_REGISTER, datatype=datatype, raw=raw, tag=tag
    )


class TestDuplicate:
    def test_duplicate_picks_next_free_address(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        slave.upsert_point(_hr(10, raw=99, tag="flow"))

        added, skipped = duplicate_points(slave, [slave.get_point(10, RegisterKind.HOLDING_REGISTER)])

        assert (added, skipped) == (1, [])
        dup = slave.get_point(11, RegisterKind.HOLDING_REGISTER)
        assert dup is not None and dup.raw == 99 and dup.tag == "flow"

    def test_duplicate_skips_occupied_addresses(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        slave.upsert_point(_hr(10, raw=1))
        slave.upsert_point(_hr(11, raw=2))

        duplicate_points(slave, [slave.get_point(10, RegisterKind.HOLDING_REGISTER)])

        assert sorted(p.address for p in slave.list_points()) == [10, 11, 12]

    def test_duplicate_int32_steps_by_two(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        slave.upsert_point(_hr(100, raw=42, datatype=ValueKind.INT32))

        duplicate_points(slave, [slave.get_point(100, RegisterKind.HOLDING_REGISTER)])

        assert sorted(p.address for p in slave.list_points()) == [100, 102]

    def test_duplicate_float64_steps_by_four(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        slave.upsert_point(_hr(100, raw=1.5, datatype=ValueKind.FLOAT64))

        duplicate_points(slave, [slave.get_point(100, RegisterKind.HOLDING_REGISTER)])

        assert sorted(p.address for p in slave.list_points()) == [100, 104]


class TestRangeAdd:
    def test_range_add_creates_sequential_points(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        added, errors = add_register_range(
            slave,
            start=100,
            count=3,
            kind=RegisterKind.INPUT_REGISTER,
            datatype=ValueKind.UINT16,
            raw=7,
            tag_prefix="S",
        )
        assert (added, errors) == (3, [])
        points = sorted((p.address, p.kind, p.raw, p.tag) for p in slave.list_points())
        assert points == [
            (100, RegisterKind.INPUT_REGISTER, 7, "S0"),
            (101, RegisterKind.INPUT_REGISTER, 7, "S1"),
            (102, RegisterKind.INPUT_REGISTER, 7, "S2"),
        ]

    def test_range_add_reports_out_of_range_tail(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        added, errors = add_register_range(
            slave,
            start=65534,
            count=3,
            kind=RegisterKind.HOLDING_REGISTER,
            datatype=ValueKind.INT32,
            raw=0,
        )
        assert added == 1
        assert len(errors) == 2


class TestImportText:
    def test_paste_tsv_without_header(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        added, errors, first_kind = import_register_map_text(
            slave,
            "50\thr\tuint16\t123\tmytag\n51\tcoil\tbool\t1\t",
            active_kind=RegisterKind.HOLDING_REGISTER,
        )
        assert added == 2 and errors == []
        p50 = slave.get_point(50, RegisterKind.HOLDING_REGISTER)
        p51 = slave.get_point(51, RegisterKind.COIL)
        assert p50 is not None and p50.raw == 123 and p50.tag == "mytag"
        assert p51 is not None and bool(p51.raw) is True

    def test_invalid_line_reported_but_valid_kept(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        added, errors, _ = import_register_map_text(
            slave,
            "50\thr\tuint16\t1\t\nnot-a-number\thr\tuint16\t1\t",
            active_kind=RegisterKind.HOLDING_REGISTER,
        )
        assert added == 1
        assert len(errors) == 1
        assert slave.get_point(50, RegisterKind.HOLDING_REGISTER) is not None

    def test_simple_addr_raw_uses_active_kind(self) -> None:
        slave = SlaveRegistry().get_slave(1)
        added, errors, first_kind = import_register_map_text(
            slave, "Addr,Raw,Tag\n7,1,flag\n", active_kind=RegisterKind.COIL
        )
        assert added == 1 and errors == []
        point = slave.get_point(7, RegisterKind.COIL)
        assert point is not None and point.raw == 1 and point.tag == "flag"
        assert first_kind == RegisterKind.COIL
