import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { RegisterGrid } from "../components/RegisterGrid";
import { RangeAddDialog } from "../components/RangeAddDialog";
import { AdvancedDialog } from "../components/AdvancedDialog";
import { KIND_LABELS, KIND_ORDER, WORD_ORDERS } from "../types";
import type { KindSlug, Mode, PointDict, WordOrder } from "../types";

export function SlaveTab({ mode }: { mode: Mode }) {
  const ms = useStore((s) => s[mode]);
  const { setError, refreshMode, askConfirm } = useStore();
  const [kind, setKind] = useState<KindSlug>("hr");
  const [slaveSearch, setSlaveSearch] = useState("");
  const [regSearch, setRegSearch] = useState("");
  const [newId, setNewId] = useState("");
  const [showRange, setShowRange] = useState(false);
  const [advPoint, setAdvPoint] = useState<PointDict | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState("");

  useEffect(() => {
    refreshMode(mode);
  }, [mode, refreshMode]);

  const selId = ms.selected_slave_id;
  const allPoints = ms.points[String(selId)] ?? [];
  const kindPoints = useMemo(
    () => allPoints.filter((p) => p.kind === kind).sort((a, b) => a.address - b.address),
    [allPoints, kind],
  );

  const selectSlave = async (id: number) => {
    try {
      await api.patchSlave(mode, id, { selected: true });
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const addSlave = async () => {
    const id = Number(newId);
    try {
      await api.addSlave(mode, id);
      setNewId("");
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const removeSlave = async () => {
    if (!(await askConfirm(`Slave ${selId} を削除しますか？（レジスタ設定も消えます）`))) return;
    try {
      await api.removeSlave(mode, selId);
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const saveTag = async (tag: string) => {
    try {
      await api.patchSlave(mode, selId, { tag });
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const setWordOrder = async (word_order: WordOrder) => {
    try {
      await api.patchSlave(mode, selId, { word_order });
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const runImport = async () => {
    try {
      const r = await api.importPoints(mode, selId, importText, kind);
      setShowImport(false);
      setImportText("");
      if (r.errors.length) setError(`${r.added} 件取込。失敗:\n${r.errors.slice(0, 20).join("\n")}`);
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const sq = slaveSearch.trim().toLowerCase();
  const slaves = sq
    ? ms.slaves.filter((s) => `${s.id} ${s.tag}`.toLowerCase().includes(sq))
    : ms.slaves;
  const selSlave = ms.slaves.find((s) => s.id === selId);
  const selTag = selSlave?.tag ?? "";
  const selWordOrder: WordOrder = selSlave?.word_order ?? "ABCD";

  return (
    <div className="slave-layout">
      <div className="card" style={{ margin: 0 }}>
        <h3>Slave ID</h3>
        <div className="toolbar">
          <input
            style={{ width: 60 }}
            placeholder="ID"
            value={newId}
            onChange={(e) => setNewId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addSlave()}
          />
          <button onClick={addSlave}>+</button>
        </div>
        <input
          className="search"
          style={{ width: "100%", marginBottom: 6 }}
          placeholder="検索 (ID / 機器名)"
          value={slaveSearch}
          onChange={(e) => setSlaveSearch(e.target.value)}
        />
        <div className="slave-list">
          {slaves.map((s) => (
            <div
              key={s.id}
              className={`slave-item ${s.id === selId ? "sel" : ""}`}
              onClick={() => selectSlave(s.id)}
            >
              <span className={`dot ${s.activity === "active" ? "active" : s.activity === "idle" ? "idle" : "off-activity"}`}>●</span>
              <span className="id">{s.id}</span>
              <span className="tag">{s.tag || "(未設定)"}</span>
            </div>
          ))}
        </div>
        <button className="danger" style={{ width: "100%", marginTop: 6 }} onClick={removeSlave} disabled={ms.slaves.length <= 1}>
          選択中の Slave を削除
        </button>
        <input
          style={{ width: "100%", marginTop: 6 }}
          placeholder="機器名"
          key={`tag-${selId}-${selTag}`}
          defaultValue={selTag}
          onBlur={(e) => e.target.value !== selTag && saveTag(e.target.value)}
        />
        <label style={{ display: "block", marginTop: 8 }}>
          <span className="muted">ワード/バイト順（int32/float）</span>
          <select
            style={{ width: "100%", marginTop: 2 }}
            value={selWordOrder}
            onChange={(e) => setWordOrder(e.target.value as WordOrder)}
          >
            {WORD_ORDERS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="card" style={{ margin: 0 }}>
        <div className="kind-tabs">
          {KIND_ORDER.map((k) => (
            <button key={k} className={kind === k ? "active" : ""} onClick={() => setKind(k)}>
              {KIND_LABELS[k]}
            </button>
          ))}
        </div>
        <div className="toolbar">
          <input
            className="search"
            placeholder="検索 (Addr / Tag)"
            value={regSearch}
            onChange={(e) => setRegSearch(e.target.value)}
          />
          <button onClick={() => setShowRange(true)}>範囲追加…</button>
          <button onClick={() => setShowImport(true)}>CSV/TSV取込…</button>
        </div>
        <RegisterGrid
          mode={mode}
          slaveId={selId}
          kind={kind}
          points={kindPoints}
          search={regSearch}
          wordOrder={selWordOrder}
          onAdvanced={setAdvPoint}
        />
      </div>

      {showRange && (
        <RangeAddDialog
          mode={mode}
          slaveId={selId}
          kind={kind}
          onClose={() => setShowRange(false)}
          onDone={(msg) => {
            setShowRange(false);
            setError(msg);
            refreshMode(mode);
          }}
        />
      )}
      {advPoint && (
        <AdvancedDialog
          mode={mode}
          slaveId={selId}
          point={advPoint}
          onClose={() => setAdvPoint(null)}
          onDone={(msg) => {
            setAdvPoint(null);
            if (msg) setError(msg);
            refreshMode(mode);
          }}
        />
      )}
      {showImport && (
        <div className="modal-backdrop" onMouseDown={() => setShowImport(false)}>
          <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
            <h3>CSV / TSV 取込</h3>
            <p className="hint">
              1行 = <code>Addr,Kind,Datatype,Raw[,Tag]</code> または <code>Addr,Raw[,Tag]</code>（現在の Kind: {KIND_LABELS[kind]}）。
              タブ区切りも可。
            </p>
            <textarea
              rows={10}
              style={{ width: "100%" }}
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder={"0,hr,uint16,100,温度\n1,hr,int32,-1,オフセット"}
            />
            <div className="actions">
              <button onClick={() => setShowImport(false)}>キャンセル</button>
              <button className="primary" onClick={runImport} disabled={!importText.trim()}>
                取込
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
