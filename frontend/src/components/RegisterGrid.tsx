import { useEffect, useRef, useState } from "react";
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

/** サーバ値に追随しつつ、編集中（フォーカス中）は上書きしないテキストセル。 */
function EditableCell({
  value,
  readOnly,
  onCommit,
}: {
  value: string;
  readOnly?: boolean;
  onCommit: (next: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false);

  useEffect(() => {
    if (!focused.current) setDraft(value);
  }, [value]);

  return (
    <input
      value={draft}
      readOnly={readOnly}
      tabIndex={readOnly ? -1 : undefined}
      onFocus={() => {
        focused.current = true;
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        focused.current = false;
        if (draft !== value) onCommit(draft);
        else setDraft(value);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") {
          setDraft(value);
          (e.target as HTMLInputElement).blur();
        }
      }}
    />
  );
}

export function RegisterGrid({ mode, slaveId, kind, points, search, onAdvanced }: Props) {
  const { setError, refreshMode, askConfirm } = useStore();
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
    try {
      await api.upsertPoint(mode, slaveId, {
        address: p.address,
        kind: p.kind,
        datatype: patch.datatype ?? p.datatype,
        ...patch,
      });
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      await refreshMode(mode);
    }
  };

  const commitRaw = (p: PointDict, text: string) => {
    try {
      void commit(p, { raw: parseRawInput(text, p.datatype) });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const del = async (p: PointDict) => {
    if (!(await askConfirm(`Addr ${p.address} を削除しますか？`))) return;
    try {
      await api.deletePoint(mode, slaveId, p.kind, p.address);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      await refreshMode(mode);
    }
  };

  const dup = async (p: PointDict) => {
    try {
      const r = await api.duplicatePoints(mode, slaveId, [{ kind: p.kind, address: p.address }]);
      if (r.skipped.length) setError(r.skipped.join("\n"));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      await refreshMode(mode);
    }
  };

  return (
    <div className="grid-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 80 }}>Addr</th>
            <th style={{ width: 120 }}>Raw</th>
            <th style={{ width: 150 }}>Decoded</th>
            <th style={{ width: 110 }}>Datatype</th>
            <th>Tag</th>
            <th style={{ width: 150 }} />
          </tr>
        </thead>
        <tbody>
          {shown.map((p) => (
            <tr key={p.address} className={p.advanced ? "advanced" : ""}>
              <td>
                <input value={p.address} readOnly tabIndex={-1} />
              </td>
              <td>
                {isBit ? (
                  <input
                    type="checkbox"
                    checked={!!p.raw}
                    onChange={(e) => commit(p, { raw: e.target.checked ? 1 : 0 })}
                  />
                ) : (
                  <EditableCell value={String(p.raw)} onCommit={(v) => commitRaw(p, v)} />
                )}
              </td>
              <td>
                <EditableCell
                  value={p.decoded_hex}
                  readOnly={isBit}
                  onCommit={(v) => commit(p, { decoded: v })}
                />
              </td>
              <td>
                <select
                  value={p.datatype}
                  disabled={isBit}
                  onChange={(e) => commit(p, { datatype: e.target.value as Datatype })}
                >
                  {choices.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <EditableCell value={p.tag} onCommit={(v) => commit(p, { tag: v })} />
              </td>
              <td className="actions">
                {!isBit && (
                  <button
                    className="cell-btn"
                    onClick={() => onAdvanced(p)}
                    title="異常応答/遅延/自動変化"
                  >
                    詳細
                  </button>
                )}
                <button className="cell-btn" onClick={() => dup(p)}>
                  複製
                </button>
                <button className="cell-btn danger" onClick={() => del(p)}>
                  削除
                </button>
              </td>
            </tr>
          ))}
          <DraftRow
            mode={mode}
            slaveId={slaveId}
            kind={kind}
            existing={points}
            onDone={() => refreshMode(mode)}
            setError={setError}
          />
        </tbody>
      </table>
    </div>
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
  const [raw, setRaw] = useState("0");
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
        <input
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
      </td>
      <td>
        <input value={addr ? decodedPreview(datatype, kind, raw) : ""} readOnly tabIndex={-1} />
      </td>
      <td>
        <select
          value={datatype}
          disabled={isBit}
          onChange={(e) => setDatatype(e.target.value as Datatype)}
        >
          {choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
      </td>
      <td className="actions">
        <button className="cell-btn primary" onClick={add}>
          追加
        </button>
      </td>
    </tr>
  );
}

function decodedPreview(dt: Datatype, kind: KindSlug, raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return "";
  try {
    return formatDecodedDisplay(dt, kind, n);
  } catch {
    return "";
  }
}
