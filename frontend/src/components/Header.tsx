import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import type { Mode } from "../types";

function ServerControl({ mode }: { mode: Mode }) {
  const { server, setError, setServer } = useStore();
  const [busy, setBusy] = useState(false);
  const running = mode === "tcp" ? server.tcp_running : server.rtu_running;
  const label = mode.toUpperCase();

  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = running ? await api.stopServer(mode) : await api.startServer(mode);
      setServer(s);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grp">
      <span className={`dot ${running ? "on" : "off"}`}>●</span>
      <span style={{ color: running ? "var(--ok)" : "var(--danger)" }}>
        {label} {running ? "待受中" : "停止"}
      </span>
      {mode === "tcp" && running && server.tcp_client_count > 0 && (
        <span className="muted">({server.tcp_client_count}台接続中)</span>
      )}
      <button onClick={toggle} disabled={busy}>
        {running ? `${label} 停止` : `${label} 開始`}
      </button>
    </div>
  );
}

export function Header() {
  return (
    <div className="header">
      <span className="title">Modbus TCP/RTU シミュレータ</span>
      <ServerControl mode="tcp" />
      <ServerControl mode="rtu" />
    </div>
  );
}
