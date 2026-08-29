"""CommSettings と永続化 dict の相互変換（UI 非依存）。

`ui/settings_panel.py` の `to_dict()` / `apply_settings()` が担っていた
「画面値 ⇔ 設定 dict」の変換ロジックを、Qt に依存しない純粋関数として持つ。
壊れた値が混ざっても例外を出さず、妥当な項目だけ反映する（堅牢性）。
"""

from __future__ import annotations

from typing import Any

from modbus_sim.config import Parity, RtuConfig, TcpConfig
from modbus_sim.models import CommSettings
from modbus_sim.network import normalize_host

_RTU_INT_FIELDS = (
    ("baudrate", "rtu_baudrate"),
    ("bytesize", "rtu_bytesize"),
    ("stopbits", "rtu_stopbits"),
)


def comm_to_dict(comm: CommSettings) -> dict[str, Any]:
    """設定済み項目のみを含む dict を返す（settings.json の tcp / rtu ブロック）。"""
    data: dict[str, Any] = {}
    if "tcp_host" in comm.configured or "tcp_port" in comm.configured:
        data["tcp"] = {"host": comm.tcp_host, "port": comm.tcp_port}
    rtu: dict[str, Any] = {}
    if "rtu_port" in comm.configured:
        rtu["port"] = comm.rtu_port
    if "rtu_baudrate" in comm.configured:
        rtu["baudrate"] = comm.rtu_baudrate
    if "rtu_parity" in comm.configured:
        rtu["parity"] = comm.rtu_parity
    if "rtu_bytesize" in comm.configured:
        rtu["bytesize"] = comm.rtu_bytesize
    if "rtu_stopbits" in comm.configured:
        rtu["stopbits"] = comm.rtu_stopbits
    if rtu:
        data["rtu"] = rtu
    return data


def apply_dict_to_comm(comm: CommSettings, data: dict[str, Any]) -> None:
    """設定 dict を CommSettings へ反映する。不正値はスキップし例外を出さない。"""
    tcp = data.get("tcp", {})
    if isinstance(tcp, dict):
        host = tcp.get("host")
        if host:
            try:
                comm.tcp_host = normalize_host(str(host))
                comm.mark("tcp_host")
            except ValueError:
                pass
        port = tcp.get("port")
        if port is not None:
            try:
                comm.tcp_port = int(port)
                comm.mark("tcp_port")
            except (TypeError, ValueError):
                pass

    rtu = data.get("rtu", {})
    if isinstance(rtu, dict):
        port_name = rtu.get("port")
        if port_name:
            comm.rtu_port = str(port_name)
            comm.mark("rtu_port")
        for key, attr in _RTU_INT_FIELDS:
            raw_value = rtu.get(key)
            if raw_value is None:
                continue
            try:
                setattr(comm, attr, int(raw_value))
                comm.mark(attr)
            except (TypeError, ValueError):
                continue
        parity = rtu.get("parity")
        if parity:
            comm.rtu_parity = str(parity)
            comm.mark("rtu_parity")


def comm_to_tcp_config(comm: CommSettings) -> TcpConfig:
    """稼働開始用に検証済みの TcpConfig を返す。不足・不正なら ValueError。"""
    host = (comm.tcp_host or "").strip()
    if not host:
        raise ValueError("IP アドレスを設定してください")
    if comm.tcp_port is None:
        raise ValueError("ポート番号を設定してください")
    try:
        port = int(comm.tcp_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("ポート番号は整数で入力してください") from exc
    if not 1 <= port <= 65535:
        raise ValueError("ポート番号は 1〜65535 です")
    from modbus_sim.platform_util import privileged_tcp_ports_restricted

    if privileged_tcp_ports_restricted() and port < 1024:
        raise ValueError(
            f"ポート {port} は特権ポートです。Linux/WSL では root 以外バインドできません。"
            "5020 など 1024 以上を指定してください"
            "（ネイティブ Windows では 502 も利用可能です）"
        )
    return TcpConfig(host=host, port=port)


def comm_to_rtu_config(comm: CommSettings) -> RtuConfig:
    """稼働開始用に検証済みの RtuConfig を返す。不足・不正なら ValueError。"""
    port = (comm.rtu_port or "").strip()
    if not port:
        raise ValueError("シリアルポートを設定してください")
    if comm.rtu_baudrate is None:
        raise ValueError("ボーレートを設定してください")
    if not comm.rtu_parity:
        raise ValueError("パリティを設定してください")
    if comm.rtu_bytesize is None:
        raise ValueError("データビットを設定してください")
    if comm.rtu_stopbits is None:
        raise ValueError("ストップビットを設定してください")
    try:
        parity = Parity(comm.rtu_parity)
    except ValueError as exc:
        raise ValueError("パリティは None / Even / Odd です") from exc
    try:
        return RtuConfig(
            port=port,
            baudrate=int(comm.rtu_baudrate),
            parity=parity,
            bytesize=int(comm.rtu_bytesize),
            stopbits=int(comm.rtu_stopbits),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("RTU の数値項目が不正です") from exc
