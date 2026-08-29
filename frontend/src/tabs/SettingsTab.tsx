import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";

const BAUD = [9600, 19200, 38400, 115200];
const PARITY = ["None", "Even", "Odd"];
const DATABITS = [8, 7];
const STOPBITS = [1, 2];

export function SettingsTab() {
  const { settings, server, setSettings, setError } = useStore();
  const locked = { tcp: server.tcp_running, rtu: server.rtu_running };

  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [rtuPort, setRtuPort] = useState("");
  const [baud, setBaud] = useState("9600");
  const [parity, setParity] = useState("Even");
  const [bytesize, setBytesize] = useState("8");
  const [stopbits, setStopbits] = useState("1");

  const [binds, setBinds] = useState<string[]>([]);
  const [serials, setSerials] = useState<string[]>([]);
  const [exportPath, setExportPath] = useState("");

  useEffect(() => {
    setHost(settings.tcp?.host ?? "");
    setPort(settings.tcp?.port != null ? String(settings.tcp.port) : "");
    setRtuPort(settings.rtu?.port ?? "");
    if (settings.rtu?.baudrate) setBaud(String(settings.rtu.baudrate));
    if (settings.rtu?.parity) setParity(settings.rtu.parity);
    if (settings.rtu?.bytesize) setBytesize(String(settings.rtu.bytesize));
    if (settings.rtu?.stopbits) setStopbits(String(settings.rtu.stopbits));
  }, [settings]);

  useEffect(() => {
    api.bindAddresses().then(setBinds).catch(() => {});
    api.serialPorts().then(setSerials).catch(() => {});
  }, []);

  const save = async () => {
    try {
      const body: Parameters<typeof api.putSettings>[0] = {};
      if (host || port) body.tcp = { host: host || null, port: port ? Number(port) : null };
      body.rtu = {
        ...(rtuPort ? { port: rtuPort } : {}),
        baudrate: Number(baud),
        parity,
        bytesize: Number(bytesize),
        stopbits: Number(stopbits),
      };
      const next = await api.putSettings(body);
      setSettings(next);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const summary = useMemo(() => {
    const lines: string[] = [];
    if (settings.tcp?.host) lines.push(`TCP IP: ${settings.tcp.host}`);
    if (settings.tcp?.port != null) lines.push(`TCP Port: ${settings.tcp.port}`);
    const r = settings.rtu ?? {};
    if (r.port) lines.push(`RTU Port: ${r.port}`);
    if (r.baudrate) lines.push(`RTU Baud: ${r.baudrate}`);
    if (r.parity) lines.push(`RTU Parity: ${r.parity}`);
    if (r.bytesize) lines.push(`RTU Data bits: ${r.bytesize}`);
    if (r.stopbits) lines.push(`RTU Stop bits: ${r.stopbits}`);
    return lines.length ? lines.join("\n") : "(未設定)";
  }, [settings]);

  return (
    <>
      <div className="card">
        <h3>TCP</h3>
        <div className="form-row">
          <label>IP</label>
          <div className="with-btn">
            <input
              list="bind-addrs"
              value={host}
              disabled={locked.tcp}
              onChange={(e) => setHost(e.target.value)}
              onBlur={save}
              placeholder="127.0.0.1"
            />
            <datalist id="bind-addrs">
              {binds.map((b) => (
                <option key={b} value={b} />
              ))}
            </datalist>
            <button
              disabled={locked.tcp}
              onClick={() => api.bindAddresses().then(setBinds).catch(() => {})}
            >
              IP再検出
            </button>
          </div>
        </div>
        <div className="form-row">
          <label>Port</label>
          <input
            value={port}
            disabled={locked.tcp}
            onChange={(e) => setPort(e.target.value)}
            onBlur={save}
            placeholder="例: 5020"
          />
        </div>
      </div>

      <div className="card">
        <h3>RTU</h3>
        <div className="form-row">
          <label>シリアルポート</label>
          <div className="with-btn">
            <input
              list="serial-ports"
              value={rtuPort}
              disabled={locked.rtu}
              onChange={(e) => setRtuPort(e.target.value)}
              onBlur={save}
              placeholder="例: COM3 / /dev/ttyUSB0"
            />
            <datalist id="serial-ports">
              {serials.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
            <button
              disabled={locked.rtu}
              onClick={() => api.serialPorts().then(setSerials).catch(() => {})}
            >
              ポート再検出
            </button>
          </div>
        </div>
        {(
          [
            ["ボーレート", baud, setBaud, BAUD],
            ["パリティ", parity, setParity, PARITY],
            ["Data bits", bytesize, setBytesize, DATABITS],
            ["Stop bits", stopbits, setStopbits, STOPBITS],
          ] as const
        ).map(([label, val, setter, opts]) => (
          <div className="form-row" key={label}>
            <label>{label}</label>
            <select
              value={val}
              disabled={locked.rtu}
              onChange={(e) => {
                (setter as (v: string) => void)(e.target.value);
              }}
              onBlur={save}
            >
              {(opts as readonly (string | number)[]).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>現在の設定</h3>
        <pre style={{ margin: 0 }}>{summary}</pre>
      </div>

      <div className="card">
        <h3>エクスポート / インポート</h3>
        <div className="form-row" style={{ gridTemplateColumns: "1fr" }}>
          <input
            value={exportPath}
            onChange={(e) => setExportPath(e.target.value)}
            placeholder="ファイルパス（例: C:\\Users\\me\\modbus_sim_settings.json）"
          />
        </div>
        <div className="toolbar">
          <button
            onClick={() =>
              api
                .exportSettings(exportPath)
                .then(() => setError(null))
                .catch((e) => setError(String(e.message)))
            }
            disabled={!exportPath}
          >
            エクスポート
          </button>
          <button
            onClick={() =>
              api
                .importSettings(exportPath)
                .then(() => setError(null))
                .catch((e) => setError(String(e.message)))
            }
            disabled={!exportPath || server.tcp_running || server.rtu_running}
          >
            インポート（停止中のみ）
          </button>
        </div>
        <p className="hint">
          Tauri 版ではファイル選択ダイアログに置き換わります。現状はパス直接入力です。
        </p>
      </div>
    </>
  );
}
