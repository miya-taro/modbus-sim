"""レジスタ一括操作（範囲追加 / CSV・TSV 取込 / 複製）の UI 非依存ロジック。

`ui/slave_panel.py` にあった実装を Qt から切り離したもの。API 層と（当面は）
UI 層の両方から呼べる純粋関数群。
"""

from __future__ import annotations

from modbus_sim.config import REGISTER_COUNT, RegisterKind, ValueKind
from modbus_sim.datastore import SlaveDatastore, parse_raw_input, validate_address
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


def next_free_address(
    slave: SlaveDatastore, kind: RegisterKind, datatype: ValueKind, start: int
) -> int | None:
    step = datatype.register_span
    address = start
    while address + step - 1 < REGISTER_COUNT:
        if all(slave.get_point(address + i, kind) is None for i in range(step)):
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
        except ValueError as exc:
            errors.append(f"Addr {address}: {exc}")
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
        except ValueError as exc:
            errors.append(f"{line_no}行目: {exc}")
            continue
        slave.upsert_point(
            RegisterPoint(address=address, kind=kind, datatype=datatype, tag=tag, raw=raw)
        )
        if first_kind is None:
            first_kind = kind
        added += 1
    return added, errors, first_kind
