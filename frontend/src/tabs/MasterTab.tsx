import { useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { MASTER_FUNCTIONS, WORD_ORDERS } from "../types";
import type { Datatype, Mode } from "../types";

const BAUD = [9600, 19200, 38400, 115200];
const PARITY = ["None", "Even", "Odd"];
const REG_DATATYPES: Datatype[] = ["uint16", "int16", "int32", "float32", "float64"];

export function MasterTab() {
  const { master, masterLog, masterResult, setMaster, setMasterResult, setError } = useStore();

  const [mode, setMode] = useState<Mode>("tcp");
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState("5020");
  const [rtuPort, setRtuPort] = useState("");
  const [baud, setBaud] = useState("9600");
  const [parity, setParity] = useState("Even");

  const [fn, setFn] = useState("read_holding_registers");
  const [deviceId, setDeviceId] = useState("1");
  const [address, setAddress] = useState("0");
  const [count, setCount] = useState("1");
  const [datatype, setDatatype] = useState<Datatype>("uint16");
  const [wordOrder, setWordOrder] = useState("ABCD");
  const [writeValues, setWriteValues] = useState("");
  const [interval, setInterval] = useState("1000");

  const isWrite = useMemo(() => MASTER_FUNCTIONS.find((f) => f.value === fn)?.write ?? false, [fn]);
  const isBitFn = fn.includes("coil") || fn.includes("discrete");

  const connect = async () => {
    try {
      const body =
        mode === "tcp"
          ? { mode, host, port: Number(port) }
          : { mode, rtu_port: rtuPort, baudrate: Number(baud), parity };
      setMaster(await api.masterConnect(body));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const disconnect = async () => {
    try {
      setMaster(await api.masterDisconnect());
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const requestArgs = () => {
    const values = isWrite
      ? writeValues
          .split(/[,\s]+/)
          .filter(Boolean)
          .map(Number)
      : null;
    return {
      function: fn,
      device_id: Number(deviceId),
      address: Number(address),
      count: Number(count),
      datatype,
      word_order: wordOrder,
      values,
      interval_ms: Number(interval),
    };
  };

  const send = async () => {
    try {
      setMasterResult(await api.masterRequest(requestArgs()));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const togglePoll = async () => {
    try {
      if (master.polling) setMaster(await api.masterPollStop());
      else setMaster(await api.masterPoll(requestArgs()));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  return (
    <div className="slave-layout">
      <div className="card" style={{ margin: 0 }}>
        <h3>接続</h3>
        <div className="kind-tabs">
          <button className={mode === "tcp" ? "active" : ""} onClick={() => setMode("tcp")}>
            TCP
          </button>
          <button className={mode === "rtu" ? "active" : ""} onClick={() => setMode("rtu")}>
            RTU
          </button>
        </div>
        {mode === "tcp" ? (
          <>
            <div className="form-row">
              <label>ホスト</label>
              <input value={host} onChange={(e) => setHost(e.target.value)} disabled={master.connected} />
            </div>
            <div className="form-row">
              <label>ポート</label>
              <input value={port} onChange={(e) => setPort(e.target.value)} disabled={master.connected} />
            </div>
          </>
        ) : (
          <>
            <div className="form-row">
              <label>シリアルポート</label>
              <input
                value={rtuPort}
                onChange={(e) => setRtuPort(e.target.value)}
                placeholder="COM3 / /dev/ttyUSB0"
                disabled={master.connected}
              />
            </div>
            <div className="form-row">
              <label>ボーレート</label>
              <select value={baud} onChange={(e) => setBaud(e.target.value)} disabled={master.connected}>
                {BAUD.map((b) => (
                  <option key={b}>{b}</option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label>パリティ</label>
              <select value={parity} onChange={(e) => setParity(e.target.value)} disabled={master.connected}>
                {PARITY.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </div>
          </>
        )}
        <div className="toolbar">
          {master.connected ? (
            <button className="danger" onClick={disconnect}>
              切断
            </button>
          ) : (
            <button className="primary" onClick={connect}>
              接続
            </button>
          )}
        </div>
        <p className="hint">
          状態: {master.connected ? `接続中 (${master.target})` : "未接続"}
          {master.polling && " ・ ポーリング中"}
        </p>
      </div>

      <div className="card" style={{ margin: 0 }}>
        <h3>リクエスト</h3>
        <div className="form-row">
          <label>Function</label>
          <select value={fn} onChange={(e) => setFn(e.target.value)}>
            {MASTER_FUNCTIONS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label>Device ID</label>
          <input value={deviceId} onChange={(e) => setDeviceId(e.target.value)} />
        </div>
        <div className="form-row">
          <label>Addr</label>
          <input value={address} onChange={(e) => setAddress(e.target.value)} />
        </div>
        {!isWrite && (
          <div className="form-row">
            <label>個数</label>
            <input value={count} onChange={(e) => setCount(e.target.value)} />
          </div>
        )}
        {!isBitFn && (
          <>
            <div className="form-row">
              <label>Datatype</label>
              <select value={datatype} onChange={(e) => setDatatype(e.target.value as Datatype)}>
                {REG_DATATYPES.map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label>ワード順</label>
              <select value={wordOrder} onChange={(e) => setWordOrder(e.target.value)}>
                {WORD_ORDERS.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </select>
            </div>
          </>
        )}
        {isWrite && (
          <div className="form-row">
            <label>書き込む値</label>
            <input
              value={writeValues}
              onChange={(e) => setWriteValues(e.target.value)}
              placeholder="カンマ/空白区切り（例: 1, 2, 3）"
            />
          </div>
        )}
        <div className="toolbar">
          <button className="primary" onClick={send} disabled={!master.connected}>
            送信
          </button>
          <label>
            周期(ms)
            <input
              style={{ width: 70, marginLeft: 4 }}
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
            />
          </label>
          <button onClick={togglePoll} disabled={!master.connected}>
            {master.polling ? "ポーリング停止" : "ポーリング開始"}
          </button>
        </div>

        {masterResult && (
          <div className="card" style={{ marginTop: 10 }}>
            <h3>結果 {masterResult.ok ? "✓" : "✗"}</h3>
            {!masterResult.ok && (
              <p style={{ color: "var(--danger)" }}>
                {masterResult.error}
                {masterResult.exception_code != null && ` (例外コード ${masterResult.exception_code})`}
              </p>
            )}
            {masterResult.ok && (
              <>
                <div className="hint">raw: [{masterResult.raw.join(", ")}]</div>
                <div className="grid-wrap" style={{ maxHeight: "30vh" }}>
                  <table className="grid">
                    <thead>
                      <tr>
                        <th style={{ width: 60 }}>#</th>
                        <th>値</th>
                      </tr>
                    </thead>
                    <tbody>
                      {masterResult.values.map((v, i) => (
                        <tr key={i}>
                          <td>
                            <input value={i} readOnly tabIndex={-1} />
                          </td>
                          <td>
                            <input value={String(v)} readOnly tabIndex={-1} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}

        <h3 style={{ marginTop: 12 }}>マスター通信ログ</h3>
        <div className="log-view" style={{ height: "22vh" }}>
          {masterLog.length === 0 ? (
            <div className="log-line">(まだありません)</div>
          ) : (
            masterLog.map((l, i) => (
              <div key={i} className="log-line">
                {l}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
