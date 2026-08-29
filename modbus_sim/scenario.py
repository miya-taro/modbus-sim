"""シナリオ実行エンジン。

タイムライン上のステップ列を順に実行する。スレーブ値の変更・サーバ起動停止・
マスターリクエスト＋期待値アサートを組み合わせる。「シナリオ」タブおよび
`POST /api/scenario/run` から呼ばれる。

JSON 形式:
{
  "name": "...",
  "reset": true,               # 実行前に両レジストリを初期化（既定 true）
  "stop_on_failure": false,
  "tcp_slaves": [...], "rtu_slaves": [...],   # 任意: 初期レジスタ構成
  "steps": [
    {"type": "start_server", "mode": "tcp", "host": "127.0.0.1", "port": 5020},
    {"type": "set_point", "mode": "tcp", "slave_id": 1, "kind": "hr",
     "address": 0, "datatype": "float32", "raw": 3.14},
    {"type": "set_word_order", "mode": "tcp", "slave_id": 1, "order": "CDAB"},
    {"type": "set_frame_fault", "mode": "tcp", "slave_id": 1, "fault": "drop", "rate": 1.0},
    {"type": "master_connect", "mode": "tcp", "host": "127.0.0.1", "port": 5020},
    {"type": "master_request", "function": "read_holding_registers",
     "address": 0, "count": 1, "datatype": "float32", "word_order": "CDAB",
     "expect": {"ok": true, "values": [3.14]}},
    {"type": "wait", "ms": 200},
    {"type": "log", "message": "..."},
    {"type": "master_disconnect"},
    {"type": "stop_server", "mode": "tcp"}
  ]
}
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from modbus_sim.config import FrameFault, Parity, RegisterKind, RtuConfig, TcpConfig, ValueKind
from modbus_sim.models import RegisterPoint
from modbus_sim.wordorder import WordOrder

_KIND_BY_SLUG = {
    "hr": RegisterKind.HOLDING_REGISTER,
    "ir": RegisterKind.INPUT_REGISTER,
    "coil": RegisterKind.COIL,
    "di": RegisterKind.DISCRETE_INPUT,
}
_DEFAULT_SLAVES = {"slaves": [{"id": 1, "tag": "", "points": []}]}


def _approx_equal(a: Any, b: Any, tol: float = 1e-4) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= tol
    return a == b


def _check_expect(expect: dict, result: dict) -> str | None:
    """期待条件を満たさなければ不一致理由を返す。満たせば None。"""
    if "ok" in expect and bool(result.get("ok")) != bool(expect["ok"]):
        return f"ok: expected {expect['ok']} got {result.get('ok')}"
    if "exception_code" in expect and result.get("exception_code") != expect["exception_code"]:
        return f"exception_code: expected {expect['exception_code']} got {result.get('exception_code')}"
    if "error_contains" in expect and expect["error_contains"] not in str(result.get("error", "")):
        return f"error_contains: {expect['error_contains']!r} not in {result.get('error')!r}"
    if "values" in expect:
        got = result.get("values", [])
        want = expect["values"]
        if len(got) != len(want) or any(not _approx_equal(g, w) for g, w in zip(got, want)):
            return f"values: expected {want} got {got}"
    return None


async def run_scenario(state, scenario: dict) -> dict:
    """scenario を state（AppState）上で実行し、結果を返す。"""
    steps = scenario.get("steps", [])
    stop_on_failure = bool(scenario.get("stop_on_failure", False))

    if scenario.get("reset", True):
        tcp_init = {"slaves": scenario["tcp_slaves"]} if scenario.get("tcp_slaves") else _DEFAULT_SLAVES
        rtu_init = {"slaves": scenario["rtu_slaves"]} if scenario.get("rtu_slaves") else _DEFAULT_SLAVES
        state.tcp_registry.load_from_dict(tcp_init)
        state.rtu_registry.load_from_dict(rtu_init)

    results: list[dict] = []
    overall_ok = True

    for index, step in enumerate(steps):
        stype = step.get("type", "")
        t0 = time.perf_counter()
        ok = True
        detail = ""
        try:
            detail = await _run_step(state, stype, step) or ""
            if detail.startswith("MISMATCH "):
                ok = False
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "index": index,
                "type": stype,
                "ok": ok,
                "detail": detail,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
            }
        )
        if not ok:
            overall_ok = False
            if stop_on_failure:
                break

    passed = sum(1 for r in results if r["ok"])
    return {
        "name": scenario.get("name", ""),
        "ok": overall_ok,
        "steps": results,
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
    }


async def _run_step(state, stype: str, step: dict) -> str | None:
    if stype == "wait":
        await asyncio.sleep(max(0, step.get("ms", 0)) / 1000)
        return None

    if stype == "log":
        return str(step.get("message", ""))

    if stype == "set_point":
        reg = state.registry(step.get("mode", "tcp"))
        slave = reg.get_slave(int(step.get("slave_id", 1)))
        kind = _KIND_BY_SLUG[step["kind"]]
        if kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
            datatype = ValueKind.BOOL
        else:
            datatype = ValueKind(step.get("datatype", "uint16"))
        raw = step.get("raw", step.get("value", 0))
        raw = float(raw) if datatype.is_float else int(raw)
        slave.upsert_point(RegisterPoint(address=int(step["address"]), kind=kind, datatype=datatype, raw=raw, tag=step.get("tag", "")))
        return f"set {step.get('mode','tcp')}/{step.get('slave_id',1)} {step['kind']}[{step['address']}]={raw}"

    if stype == "set_word_order":
        state.registry(step.get("mode", "tcp")).set_word_order(int(step.get("slave_id", 1)), WordOrder(step["order"]))
        return f"word_order={step['order']}"

    if stype == "set_frame_fault":
        state.registry(step.get("mode", "tcp")).set_frame_fault(
            int(step.get("slave_id", 1)), FrameFault(step.get("fault", "none")), step.get("rate")
        )
        return f"frame_fault={step.get('fault')}"

    if stype == "start_server":
        mode = step.get("mode", "tcp")
        if mode == "tcp":
            host = step.get("host", state.comm.tcp_host or "127.0.0.1")
            port = int(step.get("port", state.comm.tcp_port or 5020))
            await state.manager.start_tcp(TcpConfig(host=host, port=port), state.identity.to_pymodbus())
            return f"tcp server {host}:{port}"
        cfg = RtuConfig(
            port=step.get("port", state.comm.rtu_port or "COM1"),
            baudrate=int(step.get("baudrate", state.comm.rtu_baudrate or 9600)),
            parity=Parity(step.get("parity", state.comm.rtu_parity or "Even")),
            bytesize=int(step.get("bytesize", state.comm.rtu_bytesize or 8)),
            stopbits=int(step.get("stopbits", state.comm.rtu_stopbits or 1)),
        )
        await state.manager.start_rtu(cfg, state.identity.to_pymodbus())
        return f"rtu server {cfg.port}"

    if stype == "stop_server":
        mode = step.get("mode", "tcp")
        await (state.manager.stop_tcp() if mode == "tcp" else state.manager.stop_rtu())
        return f"{mode} server stopped"

    if stype == "master_connect":
        mode = step.get("mode", "tcp")
        if mode == "tcp":
            await state.master.connect_tcp(TcpConfig(host=step.get("host", "127.0.0.1"), port=int(step.get("port", 5020))))
        else:
            await state.master.connect_rtu(
                RtuConfig(
                    port=step["port"],
                    baudrate=int(step.get("baudrate", 9600)),
                    parity=Parity(step.get("parity", "Even")),
                    bytesize=int(step.get("bytesize", 8)),
                    stopbits=int(step.get("stopbits", 1)),
                )
            )
        return f"master connected {state.master.describe()['target']}"

    if stype == "master_disconnect":
        await state.master.disconnect()
        return "master disconnected"

    if stype == "master_request":
        result = await state.master.request(
            function=step["function"],
            device_id=int(step.get("device_id", 1)),
            address=int(step.get("address", 0)),
            count=int(step.get("count", 1)),
            datatype=ValueKind(step.get("datatype", "uint16")),
            word_order=WordOrder(step.get("word_order", "ABCD")),
            values=step.get("values"),
        )
        expect = step.get("expect")
        if expect:
            reason = _check_expect(expect, result)
            if reason:
                return f"MISMATCH {reason} | result={result}"
        return f"ok={result.get('ok')} values={result.get('values')}"

    raise ValueError(f"未知のステップ type: {stype}")
