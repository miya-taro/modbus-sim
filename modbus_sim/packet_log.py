"""Modbus ADU のログ用サマリ生成とパケットレベル異常注入。"""

from __future__ import annotations

import random

from modbus_sim.config import CommMode, FrameFault

_FC_NAMES = {
    0x01: "ReadCoils",
    0x02: "ReadDiscreteInputs",
    0x03: "ReadHoldingRegisters",
    0x04: "ReadInputRegisters",
    0x05: "WriteSingleCoil",
    0x06: "WriteSingleRegister",
    0x07: "ReadExceptionStatus",
    0x08: "Diagnostics",
    0x0B: "GetCommEventCounter",
    0x0C: "GetCommEventLog",
    0x0F: "WriteMultipleCoils",
    0x10: "WriteMultipleRegisters",
    0x11: "ReportServerId",
    0x16: "MaskWriteRegister",
    0x17: "ReadWriteMultipleRegisters",
    0x2B: "ReadDeviceIdentification",
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


def corrupt_frame(mode: CommMode, packet: bytes, fault: FrameFault) -> bytes:
    """応答フレームにパケットレベル異常を加えて返す。

    - DROP:     空バイト列（マスタはタイムアウト）
    - TRUNCATE: 末尾 1〜3 バイトを欠落
    - BAD_CRC:  RTU は末尾 CRC バイトを反転、TCP は MBAP length を実長と食い違わせる
    """
    if fault == FrameFault.DROP:
        return b""
    if not packet:
        return packet
    if fault == FrameFault.TRUNCATE:
        n = random.randint(1, 3)
        if len(packet) - n < 1:
            n = len(packet) - 1
        return packet[: len(packet) - n] if n > 0 else packet
    if fault == FrameFault.BAD_CRC:
        if mode == CommMode.RTU:
            return packet[:-1] + bytes([packet[-1] ^ 0xFF])
        if len(packet) >= 6:
            # 実長と異なる MBAP length を書き込む
            bad = (len(packet) + 7) & 0xFFFF
            return packet[:4] + bytes([bad >> 8, bad & 0xFF]) + packet[6:]
        return packet[:-1] + bytes([packet[-1] ^ 0xFF])
    return packet


def format_trace_log_line(mode: CommMode, sending: bool, packet: bytes, *, timestamp: str) -> str:
    direction = "TX" if sending else "RX"
    hex_bytes = packet.hex(" ").upper()
    summary = summarize_modbus_packet(mode, packet)
    label = mode.value.upper()
    if summary:
        return f"[{timestamp}] {label} {direction} {summary} | {hex_bytes}"
    return f"[{timestamp}] {label} {direction} {hex_bytes}"
