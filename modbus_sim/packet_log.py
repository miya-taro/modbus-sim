"""Modbus ADU のログ用サマリ生成。"""

from __future__ import annotations

from modbus_sim.config import CommMode

_FC_NAMES = {
    0x01: "ReadCoils",
    0x02: "ReadDiscreteInputs",
    0x03: "ReadHoldingRegisters",
    0x04: "ReadInputRegisters",
    0x05: "WriteSingleCoil",
    0x06: "WriteSingleRegister",
    0x0F: "WriteMultipleCoils",
    0x10: "WriteMultipleRegisters",
}


def _u16(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def _extract_pdu(mode: CommMode, packet: bytes) -> tuple[int, bytes] | None:
    """Return (device_id, pdu_bytes) without CRC/MBAP."""
    if mode == CommMode.TCP:
        if len(packet) < 8:
            return None
        return packet[6], packet[7:]
    if len(packet) < 2:
        return None
    device = packet[0]
    # RTU: slave + PDU + CRC(2)。短すぎる場合は CRC なしとして扱う
    if len(packet) >= 4:
        return device, packet[1:-2]
    return device, packet[1:]


def _format_registers(data: bytes) -> str:
    values = [_u16(data, i) for i in range(0, len(data) - 1, 2)]
    return "[" + ",".join(str(v) for v in values) + "]"


def summarize_modbus_packet(mode: CommMode, packet: bytes) -> str | None:
    """
    パケットから device / FC / アドレス / 値 などの短い要約を返す。
    解釈できない場合は None。
    """
    extracted = _extract_pdu(mode, packet)
    if extracted is None:
        return None
    device, pdu = extracted
    if not pdu:
        return None
    fc = pdu[0]
    # 例外応答 (FC | 0x80)
    if fc & 0x80:
        code = pdu[1] if len(pdu) > 1 else -1
        base = fc & 0x7F
        name = _FC_NAMES.get(base, f"FC{base:02X}")
        return f"device={device} FC={fc:02X} Exception {name} code={code}"

    name = _FC_NAMES.get(fc, f"FC{fc:02X}")

    # 読み取り要求: FC, addr(2), count(2)
    if fc in (0x01, 0x02, 0x03, 0x04) and len(pdu) == 5:
        return (
            f"device={device} FC={fc:02X} {name} "
            f"addr={_u16(pdu, 1)} count={_u16(pdu, 3)}"
        )

    # 読み取り応答: FC, byte_count, data...
    if fc in (0x01, 0x02, 0x03, 0x04) and len(pdu) >= 2:
        byte_count = pdu[1]
        data = pdu[2 : 2 + byte_count]
        if fc in (0x03, 0x04) and len(data) == byte_count:
            return (
                f"device={device} FC={fc:02X} {name} "
                f"values={_format_registers(data)}"
            )
        if fc in (0x01, 0x02) and len(data) == byte_count:
            bits = ",".join(f"{b:02X}" for b in data)
            return f"device={device} FC={fc:02X} {name} bits=[{bits}]"

    # Write single register: FC, addr(2), value(2)
    if fc == 0x06 and len(pdu) >= 5:
        return (
            f"device={device} FC={fc:02X} {name} "
            f"addr={_u16(pdu, 1)} value={_u16(pdu, 3)}"
        )

    # Write single coil: FC, addr(2), value(2)  (0xFF00 / 0x0000)
    if fc == 0x05 and len(pdu) >= 5:
        raw = _u16(pdu, 3)
        return (
            f"device={device} FC={fc:02X} {name} "
            f"addr={_u16(pdu, 1)} value={'ON' if raw == 0xFF00 else 'OFF'}"
        )

    # Write multiple registers request: FC, addr, count, byte_count, data
    if fc == 0x10 and len(pdu) >= 6:
        addr = _u16(pdu, 1)
        count = _u16(pdu, 3)
        byte_count = pdu[5]
        # 要求 (データあり) vs 応答 (6バイト固定)
        if len(pdu) == 6:
            return f"device={device} FC={fc:02X} {name} addr={addr} count={count}"
        data = pdu[6 : 6 + byte_count]
        return (
            f"device={device} FC={fc:02X} {name} "
            f"addr={addr} count={count} values={_format_registers(data)}"
        )

    # Write multiple coils request/response
    if fc == 0x0F and len(pdu) >= 5:
        addr = _u16(pdu, 1)
        count = _u16(pdu, 3)
        if len(pdu) == 5:
            return f"device={device} FC={fc:02X} {name} addr={addr} count={count}"
        if len(pdu) >= 6:
            byte_count = pdu[5]
            data = pdu[6 : 6 + byte_count]
            bits = ",".join(f"{b:02X}" for b in data)
            return (
                f"device={device} FC={fc:02X} {name} "
                f"addr={addr} count={count} bits=[{bits}]"
            )

    return f"device={device} FC={fc:02X} {name}"


def detect_invalid_tcp_frame(packet: bytes) -> str | None:
    """明らかに不正な Modbus TCP フレームなら理由文字列を返す。

    バイト不足（ストリーム途中）は None（まだ待たせる）。
    """
    if len(packet) < 6:
        return None
    protocol_id = _u16(packet, 2)
    if protocol_id != 0:
        return f"Invalid Modbus protocol id: {protocol_id}"
    length = _u16(packet, 4)
    if length < 1:
        return f"Invalid MBAP length: {length}"
    return None


def format_trace_log_line(mode: CommMode, sending: bool, packet: bytes, *, timestamp: str) -> str:
    direction = "TX" if sending else "RX"
    hex_bytes = packet.hex(" ").upper()
    summary = summarize_modbus_packet(mode, packet)
    label = mode.value.upper()
    if summary:
        return f"[{timestamp}] {label} {direction} {summary} | {hex_bytes}"
    return f"[{timestamp}] {label} {direction} {hex_bytes}"
