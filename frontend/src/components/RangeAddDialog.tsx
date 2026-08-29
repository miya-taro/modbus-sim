import { useState } from "react";
import { api } from "../api";
import { Modal } from "./Modal";
import { datatypeChoicesFor, defaultDatatypeFor } from "../kinds";
import { KIND_LABELS } from "../types";
import type { Datatype, KindSlug, Mode } from "../types";

export function RangeAddDialog({
  mode,
  slaveId,
  kind,
  onClose,
  onDone,
}: {
  mode: Mode;
  slaveId: number;
  kind: KindSlug;
  onClose: () => void;
  onDone: (msg: string) => void;
}) {
  const [start, setStart] = useState("0");
  const [count, setCount] = useState("1");
  const [datatype, setDatatype] = useState<Datatype>(defaultDatatypeFor(kind));
  const [raw, setRaw] = useState("0");
  const [tagPrefix, setTagPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const isBit = kind === "coil" || kind === "di";

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.addRange(mode, slaveId, {
        start: Number(start),
        count: Number(count),
        kind,
        datatype,
        raw: isBit ? Number(raw) : raw,
        tag_prefix: tagPrefix,
      });
      onDone(
        r.errors.length
          ? `${r.added} 件追加。失敗:\n${r.errors.slice(0, 20).join("\n")}`
          : `${r.added} 件追加しました。`,
      );
    } catch (e) {
      onDone(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="範囲追加" onClose={onClose} onOk={submit} okDisabled={busy}>
      <div className="form-row">
        <label>Kind</label>
        <span>{KIND_LABELS[kind]}</span>
      </div>
      <div className="form-row">
        <label>開始アドレス</label>
        <input value={start} onChange={(e) => setStart(e.target.value)} />
      </div>
      <div className="form-row">
        <label>件数</label>
        <input value={count} onChange={(e) => setCount(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Datatype</label>
        <select value={datatype} disabled={isBit} onChange={(e) => setDatatype(e.target.value as Datatype)}>
          {datatypeChoicesFor(kind).map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>
      <div className="form-row">
        <label>初期値 (10進)</label>
        <input value={raw} onChange={(e) => setRaw(e.target.value)} />
      </div>
      <div className="form-row">
        <label>タグ接頭辞</label>
        <input value={tagPrefix} onChange={(e) => setTagPrefix(e.target.value)} placeholder="空欄可（Sensor → Sensor0, Sensor1, …）" />
      </div>
      <p className="hint">int32 / float32 は2、float64 は4アドレスずつ進みます。</p>
    </Modal>
  );
}
