import { useState } from "react";
import { api } from "../api";
import { Modal } from "./Modal";
import {
  AUTO_MODE_LABELS,
  FAULT_EXCEPTION_LABELS,
  FAULT_MODE_LABELS,
  KIND_LABELS,
} from "../types";
import type { AutoMode, FaultMode, Mode, PointDict } from "../types";

const FAULT_MODES: FaultMode[] = ["none", "exception", "no_response"];
const AUTO_MODES: AutoMode[] = ["none", "increment", "random_walk", "sine"];

export function AdvancedDialog({
  mode,
  slaveId,
  point,
  onClose,
  onDone,
}: {
  mode: Mode;
  slaveId: number;
  point: PointDict;
  onClose: () => void;
  onDone: (msg: string | null) => void;
}) {
  const [faultMode, setFaultMode] = useState<FaultMode>(point.fault_mode);
  const [faultExc, setFaultExc] = useState(point.fault_exception);
  const [delayMin, setDelayMin] = useState(String(point.delay_min_ms));
  const [delayMax, setDelayMax] = useState(String(point.delay_max_ms));
  const [autoMode, setAutoMode] = useState<AutoMode>(point.auto_mode);
  const [autoMin, setAutoMin] = useState(String(point.auto_min));
  const [autoMax, setAutoMax] = useState(String(point.auto_max));
  const [autoStep, setAutoStep] = useState(String(point.auto_step));
  const [autoPeriod, setAutoPeriod] = useState(String(point.auto_period_sec));
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api.upsertPoint(mode, slaveId, {
        address: point.address,
        kind: point.kind,
        datatype: point.datatype,
        fault_mode: faultMode,
        fault_exception: faultExc,
        delay_min_ms: Number(delayMin) || 0,
        delay_max_ms: Number(delayMax) || 0,
        auto_mode: autoMode,
        auto_min: Number(autoMin) || 0,
        auto_max: Number(autoMax) || 0,
        auto_step: Number(autoStep) || 0,
        auto_period_sec: Number(autoPeriod) || 1,
      });
      onDone(null);
    } catch (e) {
      onDone(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`詳細設定 - Addr ${point.address} (${KIND_LABELS[point.kind]})`}
      onClose={onClose}
      onOk={submit}
      okDisabled={busy}
    >
      <fieldset>
        <legend>異常応答</legend>
        <div className="form-row">
          <label>動作</label>
          <select value={faultMode} onChange={(e) => setFaultMode(e.target.value as FaultMode)}>
            {FAULT_MODES.map((m) => (
              <option key={m} value={m}>{FAULT_MODE_LABELS[m]}</option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label>例外コード</label>
          <select value={faultExc} onChange={(e) => setFaultExc(e.target.value)}>
            {Object.entries(FAULT_EXCEPTION_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>
      </fieldset>

      <fieldset>
        <legend>応答遅延（ミリ秒）</legend>
        <div className="form-row">
          <label>最小</label>
          <input value={delayMin} onChange={(e) => setDelayMin(e.target.value)} />
        </div>
        <div className="form-row">
          <label>最大</label>
          <input value={delayMax} onChange={(e) => setDelayMax(e.target.value)} />
        </div>
        <p className="hint">最大 &gt; 最小 でリクエストごとにこの範囲でランダム抽選。</p>
      </fieldset>

      <fieldset>
        <legend>値の自動変化</legend>
        <div className="form-row">
          <label>動作</label>
          <select value={autoMode} onChange={(e) => setAutoMode(e.target.value as AutoMode)}>
            {AUTO_MODES.map((m) => (
              <option key={m} value={m}>{AUTO_MODE_LABELS[m]}</option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label>下限</label>
          <input value={autoMin} onChange={(e) => setAutoMin(e.target.value)} />
        </div>
        <div className="form-row">
          <label>上限</label>
          <input value={autoMax} onChange={(e) => setAutoMax(e.target.value)} />
        </div>
        <div className="form-row">
          <label>step（サイン波では未使用）</label>
          <input value={autoStep} onChange={(e) => setAutoStep(e.target.value)} />
        </div>
        <div className="form-row">
          <label>周期（秒）</label>
          <input value={autoPeriod} onChange={(e) => setAutoPeriod(e.target.value)} />
        </div>
      </fieldset>
    </Modal>
  );
}
