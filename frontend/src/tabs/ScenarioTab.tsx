import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import type { ScenarioResult } from "../types";

const EXAMPLE = {
  name: "float32 CDAB 読み取り + フレーム破棄の確認",
  reset: true,
  steps: [
    { type: "set_point", mode: "tcp", slave_id: 1, kind: "hr", address: 0, datatype: "float32", raw: 3.5 },
    { type: "set_word_order", mode: "tcp", slave_id: 1, order: "CDAB" },
    { type: "start_server", mode: "tcp", host: "127.0.0.1", port: 15599 },
    { type: "master_connect", mode: "tcp", host: "127.0.0.1", port: 15599 },
    {
      type: "master_request",
      function: "read_holding_registers",
      address: 0,
      count: 1,
      datatype: "float32",
      word_order: "CDAB",
      expect: { ok: true, values: [3.5] },
    },
    { type: "set_frame_fault", mode: "tcp", slave_id: 1, fault: "drop", rate: 1.0 },
    {
      type: "master_request",
      function: "read_holding_registers",
      address: 0,
      count: 1,
      datatype: "float32",
      word_order: "CDAB",
      expect: { ok: false },
    },
    { type: "set_frame_fault", mode: "tcp", slave_id: 1, fault: "none" },
    { type: "master_disconnect" },
    { type: "stop_server", mode: "tcp" },
  ],
};

export function ScenarioTab() {
  const { setError } = useStore();
  const [text, setText] = useState(JSON.stringify(EXAMPLE, null, 2));
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    let scenario: unknown;
    try {
      scenario = JSON.parse(text);
    } catch (e) {
      setError(`JSON が不正です: ${(e as Error).message}`);
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      setResult(await api.runScenario(scenario));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="slave-layout" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <div className="card" style={{ margin: 0 }}>
        <h3>シナリオ</h3>
        <p className="hint">
          スレーブ値変更 / サーバ起動停止 / マスターリクエスト＋期待値アサートを順に実行します。
          <code>reset: true</code> で実行前にレジスタを初期化します（現在の設定は破棄）。
        </p>
        <textarea
          rows={22}
          style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="toolbar">
          <button className="primary" onClick={run} disabled={running}>
            {running ? "実行中…" : "実行"}
          </button>
          <button onClick={() => setText(JSON.stringify(EXAMPLE, null, 2))}>サンプルに戻す</button>
        </div>
        <p className="hint">
          CLI: <code>python main.py --scenario path.json</code>（成功で終了コード 0）
        </p>
      </div>

      <div className="card" style={{ margin: 0 }}>
        <h3>
          結果{" "}
          {result && (
            <span style={{ color: result.ok ? "var(--ok)" : "var(--danger)" }}>
              {result.ok ? "✓ PASS" : "✗ FAIL"} ({result.summary.passed}/{result.summary.total})
            </span>
          )}
        </h3>
        {!result && <p className="hint">（未実行）</p>}
        {result && (
          <div className="grid-wrap" style={{ maxHeight: "60vh" }}>
            <table className="grid">
              <thead>
                <tr>
                  <th style={{ width: 36 }}>#</th>
                  <th style={{ width: 130 }}>type</th>
                  <th style={{ width: 44 }}>ok</th>
                  <th style={{ width: 70 }}>ms</th>
                  <th>detail</th>
                </tr>
              </thead>
              <tbody>
                {result.steps.map((s) => (
                  <tr key={s.index} className={s.ok ? "" : "advanced"}>
                    <td>
                      <input value={s.index} readOnly tabIndex={-1} />
                    </td>
                    <td>
                      <input value={s.type} readOnly tabIndex={-1} />
                    </td>
                    <td style={{ textAlign: "center", color: s.ok ? "var(--ok)" : "var(--danger)" }}>
                      {s.ok ? "✓" : "✗"}
                    </td>
                    <td>
                      <input value={s.elapsed_ms.toFixed(1)} readOnly tabIndex={-1} />
                    </td>
                    <td>
                      <input value={s.detail} readOnly tabIndex={-1} title={s.detail} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
