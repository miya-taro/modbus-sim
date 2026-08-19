"""サーバ起動失敗時の内部状態の整合性テスト。

start_tcp / start_rtu が失敗した場合（ポート使用中など）に tcp_running /
rtu_running が True のまま固まらないこと、続けて別ポートで再起動できることを確認する。
固まると UI 上は「停止」表示のままアプリを再起動するまで一切開始できなくなる。
"""

from __future__ import annotations

import pytest
from pymodbus.transport import NULLMODEM_HOST

from modbus_sim.config import Parity, RtuConfig, TcpConfig
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.server_manager import ModbusServerManager


@pytest.mark.asyncio
async def test_tcp_running_state_recovers_after_bind_failure() -> None:
    blocker = ModbusServerManager(slave_registry=SlaveRegistry())
    await blocker.start_tcp(TcpConfig(host="127.0.0.1", port=17999))
    mgr = ModbusServerManager(slave_registry=SlaveRegistry())
    try:
        assert mgr.tcp_running is False
        with pytest.raises(Exception):
            await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=17999))
        # 失敗直後も running のまま固まらないこと
        assert mgr.tcp_running is False

        # 別ポートで正常に再起動できること
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=18001))
        assert mgr.tcp_running is True
    finally:
        if mgr.tcp_running:
            await mgr.stop_tcp()
        await blocker.stop_tcp()


@pytest.mark.asyncio
async def test_rtu_running_state_recovers_after_bind_failure() -> None:
    port = f"{NULLMODEM_HOST}:98"
    config = RtuConfig(port=port, baudrate=9600, parity=Parity.EVEN, bytesize=8, stopbits=1)
    blocker = ModbusServerManager(slave_registry=SlaveRegistry())
    await blocker.start_rtu(config)
    mgr = ModbusServerManager(slave_registry=SlaveRegistry())
    try:
        assert mgr.rtu_running is False
        with pytest.raises(Exception):
            await mgr.start_rtu(config)
        assert mgr.rtu_running is False

        other_config = RtuConfig(
            port=f"{NULLMODEM_HOST}:97", baudrate=9600, parity=Parity.EVEN, bytesize=8, stopbits=1
        )
        await mgr.start_rtu(other_config)
        assert mgr.rtu_running is True
    finally:
        if mgr.rtu_running:
            await mgr.stop_rtu()
        await blocker.stop_rtu()
