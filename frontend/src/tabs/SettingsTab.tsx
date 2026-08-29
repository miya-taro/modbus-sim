import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { IDENTITY_FIELDS, type DeviceIdentity } from "../types";

const BAUD = [9600, 19200, 38400, 115200];
const PARITY = ["None", "Even", "Odd"];
const DATABITS = [8, 7];
const STOPBITS = [1, 2];

interface Form {
  host: string;
  port: string;
  rtuPort: string;
  baud: string;
  parity: string;
  bytesize: string;
  stopbits: string;
}

const DEFAULT_FORM: Form = {
  host: "",
  port: "",
  rtuPort: "",
  baud: "9600",
  parity: "Even",
  bytesize: "8",
  stopbits: "1",
};

export function SettingsTab() {
  const { settings, identity, server, setSettings, setIdentity, setError } = useStore();
  const locked = { tcp: server.tcp_running, rtu: server.rtu_running };
  const serverRunning = server.tcp_running || server.rtu_running;

  const [ident, setIdent] = useState<DeviceIdentity>(identity);
  const identHydrated = useRef(false);
  useEffect(() => {
    if (identHydrated.current) return;
    identHydrated.current = true;
    setIdent(identity);
  }, [identity]);

  const saveIdentityField = (key: keyof DeviceIdentity, value: string) => {
    if (value === identity[key]) return;
    api
      .putIdentity({ [key]: value })
      .then(setIdentity)
      .catch((e) => setError(String(e.message ?? e)));
  };

  const [form, setForm] = useState<Form>(DEFAULT_FORM);
  const [binds, setBinds] = useState<string[]>([]);
  const [serials, setSerials] = useState<string[]>([]);
  const [exportPath, setExportPath] = useState("");

  const dirty = useRef(false);
  const hydrated = useRef(false);

  // サーバの settings をローカルフォームへ取り込むのは初回のみ。
  // 以降はユーザー入力を正とし、上書きしない（入力中に WS 更新で消えるのを防ぐ）。
  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    setForm({
      host: settings.tcp?.host ?? "",
      port: settings.tcp?.port != null ? String(settings.tcp.port) : "",
      rtuPort: settings.rtu?.port ?? "",
      baud: settings.rtu?.baudrate ? String(settings.rtu.baudrate) : DEFAULT_FORM.baud,
      parity: settings.rtu?.parity ?? DEFAULT_FORM.parity,
      bytesize: settings.rtu?.bytesize ? String(settings.rtu.bytesize) : DEFAULT_FORM.bytesize,
      stopbits: settings.rtu?.stopbits ? String(settings.rtu.stopbits) : DEFAULT_FORM.stopbits,
    });
  }, [settings]);

  useEffect(() => {
    api.bindAddresses().then(setBinds).catch(() => {});
    api.serialPorts().then(setSerials).catch(() => {});
  }, []);

  // フォーム変更を 500ms デバウンスで保存
  useEffect(() => {
    if (!dirty.current) return;
    const id = setTimeout(() => {
      const body: Parameters<typeof api.putSettings>[0] = {};
      if (form.host || form.port) {
        body.tcp = { host: form.host || null, port: form.port ? Number(form.port) : null };
      }
      body.rtu = {
        ...(form.rtuPort ? { port: form.rtuPort } : {}),
        baudrate: Number(form.baud),
        parity: form.parity,
        bytesize: Number(form.bytesize),
        stopbits: Number(form.stopbits),
      };
      api.putSettings(body).then(setSettings).catch((e) => setError(String(e.message ?? e)));
    }, 500);
    return () => clearTimeout(id);
  }, [form, setSettings, setError]);

  const update = (patch: Partial<Form>) => {
    dirty.current = true;
    setForm((f) => ({ ...f, ...patch }));
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

  const rtuSelects: [string, keyof Form, readonly (string | number)[]][] = [
    ["ボーレート", "baud", BAUD],
    ["パリティ", "parity", PARITY],
    ["Data bits", "bytesize", DATABITS],
    ["Stop bits", "stopbits", STOPBITS],
  ];

  return (
    <>
      <div className="card">
        <h3>TCP</h3>
        <div className="form-row">
          <label>IP</label>
          <div className="with-btn">
            <input
              list="bind-addrs"
              value={form.host}
              disabled={locked.tcp}
              onChange={(e) => update({ host: e.target.value })}
              placeholder="127.0.0.1"
            />
            <datalist id="bind-addrs">
              {binds.map((b) => (
                <option key={b} value={b} />
              ))}
            </datalist>
            <button disabled={locked.tcp} onClick={() => api.bindAddresses().then(setBinds).catch(() => {})}>
              IP再検出
            </button>
          </div>
        </div>
        <div className="form-row">
          <label>Port</label>
          <input
            value={form.port}
            disabled={locked.tcp}
            onChange={(e) => update({ port: e.target.value })}
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
              value={form.rtuPort}
              disabled={locked.rtu}
              onChange={(e) => update({ rtuPort: e.target.value })}
              placeholder="例: COM3 / /dev/ttyUSB0"
            />
            <datalist id="serial-ports">
              {serials.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
            <button disabled={locked.rtu} onClick={() => api.serialPorts().then(setSerials).catch(() => {})}>
              ポート再検出
            </button>
          </div>
        </div>
        {rtuSelects.map(([label, key, opts]) => (
          <div className="form-row" key={key}>
            <label>{label}</label>
            <select
              value={form[key]}
              disabled={locked.rtu}
              onChange={(e) => update({ [key]: e.target.value } as Partial<Form>)}
            >
              {opts.map((o) => (
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
        <h3>機器識別 (FC 43 / Read Device Identification)</h3>
        {IDENTITY_FIELDS.map(({ key, label }) => (
          <div className="form-row" key={key}>
            <label>{label}</label>
            <input
              value={ident[key]}
              disabled={serverRunning}
              onChange={(e) => setIdent((f) => ({ ...f, [key]: e.target.value }))}
              onBlur={(e) => saveIdentityField(key, e.target.value)}
            />
          </div>
        ))}
        <p className="hint">サーバー停止中のみ変更できます。FC 8（Diagnostics）は追加設定なしで応答します。</p>
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
              api.exportSettings(exportPath).then(() => setError(null)).catch((e) => setError(String(e.message)))
            }
            disabled={!exportPath}
          >
            エクスポート
          </button>
          <button
            onClick={() =>
              api.importSettings(exportPath).then(() => setError(null)).catch((e) => setError(String(e.message)))
            }
            disabled={!exportPath || server.tcp_running || server.rtu_running}
          >
            インポート（停止中のみ）
          </button>
        </div>
        <p className="hint">Tauri 版ではファイル選択ダイアログに置き換わります。現状はパス直接入力です。</p>
      </div>
    </>
  );
}
