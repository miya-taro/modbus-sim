import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { datatypeChoicesFor, defaultDatatypeFor } from "../kinds";
import { datatypeSpan, formatDecodedDisplay, parseRawInput, validateAddress } from "../datatype";
import type { Datatype, KindSlug, Mode, PointDict } from "../types";

interface Props {
  mode: Mode;
  slaveId: number;
  kind: KindSlug;
  points: PointDict[];
  search: string;
  onAdvanced: (p: PointDict) => void;
}

export function RegisterGrid({ mode, slaveId, kind, points, search, onAdvanced }: Props) {
  const { setError, refreshMode, askConfirm } = useStore();
  const [cellErr, setCellErr] = useState<string | null>(null);
  const isBit = kind === "coil" || kind === "di";
  const choices = datatypeChoicesFor(kind);

  const q = search.trim().toLowerCase();
  const shown = q
    ? points.filter((p) => `${p.address} ${p.tag}`.toLowerCase().includes(q))
    : points;

  const commit = async (
    p: PointDict,
    patch: { raw?: number; decoded?: string; datatype?: Datatype; tag?: string },
  ) => {
    setCellErr(null);
    try {
      await api.upsertPoint(mode, slaveId, {
        address: p.address,
        kind: p.kind,
        datatype: patch.datatype ?? p.datatype,
        ...patch,
      });
      await refreshMode(mode);
    } catch (e) {
      setCellErr(String((e as Error).message ?? e));
      setError(String((e as Error).message ?? e));
      await refreshMode(mode);
    }
  };

  const del = async (p: PointDict) => {
    if (!(await askConfirm(`Addr ${p.address} を削除しますか？`))) return;
    try {
      await api.deletePoint(mode, slaveId, p.kind, p.address);
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const dup = async (p: PointDict) => {
    try {
      const r = await api.duplicatePoints(mode, slaveId, [{ kind: p.kind, address: p.address }]);
      if (r.skipped.length) setError(r.skipped.join("\n"));
      await refreshMode(mode);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  return (
    <>
      {cellErr && <div className="hint" style={{ color: "var(--danger)" }}>{cellErr}</div>}
      <div className="grid-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 80 }}>Addr</th>
              <th style={{ width: 120 }}>Raw</th>
              <th style={{ width: 150 }}>Decoded</th>
              <th style={{ width: 110 }}>Datatype</th>
              <th>Tag</th>
              <th style={{ width: 150 }}></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((p) => (
              <tr key={`${p.address}-${p.datatype}-${p.raw}-${p.tag}-${p.advanced}`} className={p.advanced ? "advanced" : ""}>
                <td><input value={p.address} readOnly tabIndex={-1} /></td>
                <td>
                  {isBit ? (
                    <input
                      type="checkbox"
                      checked={!!p.raw}
                      onChange={(e) => commit(p, { raw: e.target.checked ? 1 : 0 })}
                    />
                  ) : (
                    <input
                      defaultValue={String(p.raw)}
                      onBlur={(e) => {
                        if (e.target.value === String(p.raw)) return;
                        try {
                          commit(p, { raw: parseRawInput(e.target.value, p.datatype) });
                        } catch (err) {
                          setCellErr((err as Error).message);
                        }
                      }}
                      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                    />
                  )}
                </td>
                <td>
                  <input
                    defaultValue={p.decoded_hex}
                    readOnly={isBit}
                    onBlur={(e) => {
                      if (e.target.value === p.decoded_hex) return;
                      commit(p, { decoded: e.target.value });
                    }}
                    onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                  />
                </td>
                <td>
                  <select
                    value={p.datatype}
                    disabled={isBit}
                    onChange={(e) => commit(p, { datatype: e.target.value as Datatype })}
                  >
                    {choices.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    defaultValue={p.tag}
                    onBlur={(e) => e.target.value !== p.tag && commit(p, { tag: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                  />
                </td>
                <td className="actions">
                  {!isBit && (
                    <button className="cell-btn" onClick={() => onAdvanced(p)} title="異常応答/遅延/自動変化">
                      詳細
                    </button>
                  )}
                  <button className="cell-btn" onClick={() => dup(p)}>複製</button>
                  <button className="cell-btn danger" onClick={() => del(p)}>削除</button>
                </td>
              </tr>
            ))}
            <DraftRow mode={mode} slaveId={slaveId} kind={kind} existing={points} onDone={() => refreshMode(mode)} setError={setError} />
          </tbody>
        </table>
      </div>
    </>
  );
}

function DraftRow({
  mode,
  slaveId,
  kind,
  existing,
  onDone,
  setError,
}: {
  mode: Mode;
  slaveId: number;
  kind: KindSlug;
  existing: PointDict[];
  onDone: () => void;
  setError: (e: string) => void;
}) {
  const isBit = kind === "coil" || kind === "di";
  const [addr, setAddr] = useState("");
  const [raw, setRaw] = useState(isBit ? "0" : "0");
  const [datatype, setDatatype] = useState<Datatype>(defaultDatatypeFor(kind));
  const [tag, setTag] = useState("");
  const choices = datatypeChoicesFor(kind);

  const add = async () => {
    const a = Number(addr);
    try {
      if (!addr.trim() || !Number.isInteger(a)) throw new Error("Addr を整数で入力してください");
      validateAddress(a, datatype);
      const span = datatypeSpan(datatype);
      const clash = existing.find(
        (p) => a < p.address + datatypeSpan(p.datatype) && p.address < a + span,
      );
      if (clash) {
        throw new Error(
          clash.address === a
            ? `Addr ${a} は既にあります`
            : `Addr ${a} は Addr ${clash.address} (${clash.datatype}) と重複します`,
        );
      }
      await api.upsertPoint(mode, slaveId, {
        address: a,
        kind,
        datatype,
        raw: parseRawInput(raw, datatype),
        tag,
      });
      setAddr("");
      setRaw("0");
      setTag("");
      onDone();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  return (
    <tr className="draft">
      <td>
        <input
          value={addr}
          placeholder="新規"
          onChange={(e) => setAddr(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
      </td>
      <td>
        <input value={raw} onChange={(e) => setRaw(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
      </td>
      <td>
        <input
          value={addr ? formatDecodedDisplaySafe(datatype, kind, raw) : ""}
          readOnly
          tabIndex={-1}
        />
      </td>
      <td>
        <select value={datatype} disabled={isBit} onChange={(e) => setDatatype(e.target.value as Datatype)}>
          {choices.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </td>
      <td>
        <input value={tag} onChange={(e) => setTag(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
      </td>
      <td className="actions">
        <button className="cell-btn primary" onClick={add}>追加</button>
      </td>
    </tr>
  );
}

function formatDecodedDisplaySafe(dt: Datatype, kind: KindSlug, raw: string): string {
  try {
    return formatDecodedDisplay(dt, kind, Number(raw) || 0);
  } catch {
    return "";
  }
}
