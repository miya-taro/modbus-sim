"""レジスタ一括操作（範囲追加 / CSV・TSV 取込 / 複製）の UI 非依存ロジック。

`ui/slave_panel.py` にあった実装を Qt から切り離したもの。API 層と（当面は）
UI 層の両方から呼べる純粋関数群。
"""

from __future__ import annotations

from modbus_sim.config import REGISTER_COUNT, RegisterKind, ValueKind
from modbus_sim.datastore import (
    SlaveDatastore,
    parse_raw_input,
    validate_address,
    validate_datatype_value,
)
from modbus_sim.models import RegisterPoint

_KIND_LABELS = {
    RegisterKind.HOLDING_REGISTER: "Holding Register",
    RegisterKind.INPUT_REGISTER: "Input Register",
    RegisterKind.COIL: "Coil",
    RegisterKind.DISCRETE_INPUT: "Discrete Input",
}
_KIND_BY_LABEL = {label.lower(): kind for kind, label in _KIND_LABELS.items()}

_BIT_DATATYPES = (ValueKind.BOOL,)
_REGISTER_DATATYPES = (
    ValueKind.UINT16,
    ValueKind.INT16,
    ValueKind.INT32,
    ValueKind.FLOAT32,
    ValueKind.FLOAT64,
)


def datatype_choices_for(kind: RegisterKind) -> tuple[ValueKind, ...]:
    if kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
        return _BIT_DATATYPES
    return _REGISTER_DATATYPES


def default_datatype_for(kind: RegisterKind) -> ValueKind:
    return datatype_choices_for(kind)[0]


def parse_kind(text: str) -> RegisterKind:
    text = text.strip()
    try:
        return RegisterKind(text.lower())
    except ValueError:
        pass
    kind = _KIND_BY_LABEL.get(text.lower())
    if kind is None:
        raise ValueError(f"Kind '{text}' を解釈できません")
    return kind


def parse_datatype(text: str, kind: RegisterKind) -> ValueKind:
    text = text.strip()
    try:
        datatype = ValueKind(text.lower())
    except ValueError as exc:
        raise ValueError(f"Datatype '{text}' を解釈できません") from exc
    allowed = datatype_choices_for(kind)
    if datatype not in allowed:
        raise ValueError(
            f"この Kind では Datatype は {', '.join(k.value for k in allowed)} のみ有効です"
        )
    return datatype


def occupied_addresses(slave: SlaveDatastore, kind: RegisterKind) -> set[int]:
    """指定 kind で既存点が占有している全アドレス（多レジスタ型の継続分を含む）。"""
    occ: set[int] = set()
    for point in slave.points.values():
        if point.kind == kind:
            occ.update(range(point.address, point.address + point.datatype.register_span))
    return occ


def find_overlap(
    slave: SlaveDatastore,
    address: int,
    kind: RegisterKind,
    datatype: ValueKind,
    *,
    ignore_key: tuple[int, RegisterKind] | None = None,
) -> RegisterPoint | None:
    """address..address+span-1 が同一 kind の既存点と重なる場合その点を返す。

    int32 / float32（2 レジスタ）や float64（4 レジスタ）の継続アドレスに別の点を
    置いてしまう不整合を防ぐ。ignore_key は編集対象の点自身を除外するために使う。
    """
    span = datatype.register_span
    for point in slave.points.values():
        if point.kind != kind or point.key == ignore_key:
            continue
        other_span = point.datatype.register_span
        if address < point.address + other_span and point.address < address + span:
            return point
    return None


def next_free_address(
    slave: SlaveDatastore, kind: RegisterKind, datatype: ValueKind, start: int
) -> int | None:
    step = datatype.register_span
    occ = occupied_addresses(slave, kind)
    address = start
    while address + step - 1 < REGISTER_COUNT:
        if all((address + i) not in occ for i in range(step)):
            return address
        address += 1
    return None


def add_register_range(
    slave: SlaveDatastore,
    *,
    start: int,
    count: int,
    kind: RegisterKind,
    datatype: ValueKind,
    raw: int | float,
    tag_prefix: str = "",
) -> tuple[int, list[str]]:
    step = datatype.register_span
    added = 0
    errors: list[str] = []
    for i in range(count):
        address = start + i * step
        try:
            validate_address(address, datatype)
            validate_datatype_value(datatype, raw)
        except ValueError as exc:
            errors.append(f"Addr {address}: {exc}")
            continue
        clash = find_overlap(slave, address, kind, datatype)
        if clash is not None:
            errors.append(
                f"Addr {address}: Addr {clash.address}"
                f"（{clash.datatype.value}）と重複します"
            )
            continue
        tag = f"{tag_prefix}{i}" if tag_prefix else ""
        slave.upsert_point(
            RegisterPoint(address=address, kind=kind, datatype=datatype, tag=tag, raw=raw)
        )
        added += 1
    return added, errors


def duplicate_points(
    slave: SlaveDatastore, points: list[RegisterPoint]
) -> tuple[int, list[str]]:
    added = 0
    skipped: list[str] = []
    for point in points:
        step = point.datatype.register_span
        new_address = next_free_address(
            slave, point.kind, point.datatype, point.address + step
        )
        if new_address is None:
            skipped.append(f"Addr {point.address}（空きアドレスが見つかりません）")
            continue
        slave.upsert_point(
            RegisterPoint(
                address=new_address,
                kind=point.kind,
                datatype=point.datatype,
                tag=point.tag,
                raw=point.raw,
            )
        )
        added += 1
    return added, skipped


def import_register_map_text(
    slave: SlaveDatastore, text: str, *, active_kind: RegisterKind
) -> tuple[int, list[str], RegisterKind | None]:
    """CSV/TSV/貼り付けテキストを取り込む。

    1 行が `Addr, Kind, Datatype, Raw[, Tag]` または `Addr, Raw[, Tag]`（現在の Kind へ）。
    戻り値: (取り込み件数, エラー行メッセージ, 最初に取り込んだ Kind)
    """
    added = 0
    errors: list[str] = []
    first_kind: RegisterKind | None = None
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(","))]
        if parts[0].lower() == "addr":
            continue
        try:
            address = int(parts[0])
            if len(parts) >= 4:
                kind = parse_kind(parts[1])
                datatype = parse_datatype(parts[2], kind)
                raw = parse_raw_input(parts[3], datatype)
                tag = parts[4] if len(parts) > 4 else ""
            elif len(parts) >= 2:
                kind = active_kind
                datatype = default_datatype_for(kind)
                raw = parse_raw_input(parts[1], datatype)
                tag = parts[2] if len(parts) > 2 else ""
            else:
                raise ValueError(
                    "列数が不足しています（Addr/Kind/Datatype/Raw または Addr/Raw）"
                )
            validate_address(address, datatype)
            validate_datatype_value(datatype, raw)
        except ValueError as exc:
            errors.append(f"{line_no}行目: {exc}")
            continue
        clash = find_overlap(slave, address, kind, datatype, ignore_key=(address, kind))
        if clash is not None:
            errors.append(
                f"{line_no}行目: Addr {address} は Addr {clash.address}"
                f"（{clash.datatype.value}）と重複します"
            )
            continue
        slave.upsert_point(
            RegisterPoint(address=address, kind=kind, datatype=datatype, tag=tag, raw=raw)
        )
        if first_kind is None:
            first_kind = kind
        added += 1
    return added, errors, first_kind
