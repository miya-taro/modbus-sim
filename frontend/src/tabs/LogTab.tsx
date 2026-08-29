import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { TXT_FILTER, isDesktop, pickSavePath } from "../platform";

const PLACEHOLDER = [
  "# ログ出力例",
  "[2026-07-07 22:00:01] TCP RX device=1 FC=03 ReadHoldingRegisters addr=0 count=10 | 00 01 00 00 00 06 01 03 00 00 00 0A",
  "[2026-07-07 22:00:01] TCP TX device=1 FC=03 ReadHoldingRegisters values=[0,0,...] | 00 01 00 00 00 17 01 03 14 ...",
  "[2026-07-07 22:00:03] TCP INVALID Unable to decode request: FF FF 00 01 00 00",
];

function category(line: string): string {
  if (line.includes(" INVALID ")) return "invalid";
  if (line.includes(" TX ")) return "tx";
  return "";
}

export function LogTab() {
  const { log, setError } = useStore();
  const [modeFilter, setModeFilter] = useState<"すべて" | "TCP" | "RTU">("すべて");
  const [search, setSearch] = useState("");
  const [autoscroll, setAutoscroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<string[] | null>(null);
  const viewRef = useRef<HTMLDivElement>(null);

  const raw = paused && frozen ? frozen : log.lines;

  const lines = useMemo(() => {
    const src = raw.length ? raw : PLACEHOLDER;
    if (!raw.length) return src;
    const q = search.trim().toLowerCase();
    return src.filter(
      (l) =>
        (modeFilter === "すべて" || l.includes(`] ${modeFilter} `)) &&
        (!q || l.toLowerCase().includes(q)),
    );
  }, [raw, modeFilter, search]);

  useEffect(() => {
    if (autoscroll && !paused && viewRef.current) {
      viewRef.current.scrollTop = viewRef.current.scrollHeight;
    }
  }, [lines, autoscroll, paused]);

  const togglePause = () => {
    if (!paused) setFrozen(log.lines);
    else setFrozen(null);
    setPaused(!paused);
  };

  const save = async () => {
    if (isDesktop()) {
      const path = await pickSavePath("modbus_sim_log.txt", TXT_FILTER);
      if (!path) return;
      api.saveLog(path, lines).catch((e) => setError(String((e as Error).message ?? e)));
      return;
    }
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "modbus_sim_log.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card" style={{ margin: 0 }}>
      <div className="toolbar">
        <span>表示:</span>
        <select value={modeFilter} onChange={(e) => setModeFilter(e.target.value as typeof modeFilter)}>
          <option>すべて</option>
          <option>TCP</option>
          <option>RTU</option>
        </select>
        <input
          className="search"
          placeholder="絞り込み（例: FC=03 / device=1 / addr=100）"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label>
          <input type="checkbox" checked={autoscroll} onChange={(e) => setAutoscroll(e.target.checked)} /> 自動スクロール
        </label>
        <button onClick={togglePause}>{paused ? "再開" : "一時停止"}</button>
        <button onClick={save}>保存</button>
        <button
          className="danger"
          onClick={() => api.clearLog().catch((e) => setError(String(e.message)))}
        >
          クリア
        </button>
      </div>
      <div className="log-view" ref={viewRef}>
        {lines.map((l, i) => (
          <div key={i} className={`log-line ${category(l)}`}>
            {l}
          </div>
        ))}
      </div>
    </div>
  );
}
