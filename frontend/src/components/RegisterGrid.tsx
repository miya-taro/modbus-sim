import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api } from "../api";
import { useStore } from "../store";
import { datatypeChoicesFor, defaultDatatypeFor } from "../kinds";
import { datatypeSpan, formatDecodedDisplay, parseRawInput, validateAddress } from "../datatype";
import type { Datatype, KindSlug, Mode, PointDict, WordOrder } from "../types";

interface Props {
  mode: Mode;
  slaveId: number;
  kind: KindSlug;
  points: PointDict[];
  search: string;
  wordOrder: WordOrder;
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

export function RegisterGrid({ mode, slaveId, kind, points, search, wordOrder, onAdvanced }: Props) {
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

  const scrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: shown.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });
  const virtualItems = rowVirtualizer.getVirtualItems();
  const padTop = virtualItems.length ? virtualItems[0].start : 0;
  const padBottom = virtualItems.length
    ? rowVirtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
    : 0;

  return (
    <div className="grid-wrap" ref={scrollRef}>
      <div className="grid-count muted">{shown.length} 点</div>
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
          {padTop > 0 && (
            <tr aria-hidden style={{ height: padTop }}>
              <td colSpan={6} style={{ padding: 0, border: "none" }} />
            </tr>
          )}
          {virtualItems.map((vi) => {
            const p = shown[vi.index];
            return (
              <GridRow
                key={p.address}
                point={p}
                isBit={isBit}
                choices={choices}
                onCommit={commit}
                onCommitRaw={commitRaw}
                onAdvanced={onAdvanced}
                onDup={dup}
                onDel={del}
              />
            );
          })}
          {padBottom > 0 && (
            <tr aria-hidden style={{ height: padBottom }}>
              <td colSpan={6} style={{ padding: 0, border: "none" }} />
            </tr>
          )}
          <DraftRow
            mode={mode}
            slaveId={slaveId}
            kind={kind}
            existing={points}
            wordOrder={wordOrder}
            onDone={() => refreshMode(mode)}
            setError={setError}
          />
        </tbody>
      </table>
    </div>
  );
}

const ROW_HEIGHT = 30;

function GridRow({
  point: p,
  isBit,
  choices,
  onCommit,
  onCommitRaw,
  onAdvanced,
  onDup,
  onDel,
}: {
  point: PointDict;
  isBit: boolean;
  choices: Datatype[];
  onCommit: (p: PointDict, patch: { decoded?: string; datatype?: Datatype; tag?: string; raw?: number }) => void;
  onCommitRaw: (p: PointDict, text: string) => void;
  onAdvanced: (p: PointDict) => void;
  onDup: (p: PointDict) => void;
  onDel: (p: PointDict) => void;
}) {
  return (
    <tr className={p.advanced ? "advanced" : ""} style={{ height: ROW_HEIGHT }}>
      <td>
        <input value={p.address} readOnly tabIndex={-1} />
      </td>
      <td>
        {isBit ? (
          <input
            type="checkbox"
            checked={!!p.raw}
            onChange={(e) => onCommit(p, { raw: e.target.checked ? 1 : 0 })}
          />
        ) : (
          <EditableCell value={String(p.raw)} onCommit={(v) => onCommitRaw(p, v)} />
        )}
      </td>
      <td>
        <EditableCell value={p.decoded_hex} readOnly={isBit} onCommit={(v) => onCommit(p, { decoded: v })} />
      </td>
      <td>
        <select
          value={p.datatype}
          disabled={isBit}
          onChange={(e) => onCommit(p, { datatype: e.target.value as Datatype })}
        >
          {choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </td>
      <td>
        <EditableCell value={p.tag} onCommit={(v) => onCommit(p, { tag: v })} />
      </td>
      <td className="actions">
        {!isBit && (
          <button className="cell-btn" onClick={() => onAdvanced(p)} title="異常応答/遅延/自動変化">
            詳細
          </button>
        )}
        <button className="cell-btn" onClick={() => onDup(p)}>
          複製
        </button>
        <button className="cell-btn danger" onClick={() => onDel(p)}>
          削除
        </button>
      </td>
    </tr>
  );
}

function DraftRow({
  mode,
  slaveId,
  kind,
  existing,
  wordOrder,
  onDone,
  setError,
}: {
  mode: Mode;
  slaveId: number;
  kind: KindSlug;
  existing: PointDict[];
  wordOrder: WordOrder;
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
        <input value={addr ? decodedPreview(datatype, kind, raw, wordOrder) : ""} readOnly tabIndex={-1} />
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

function decodedPreview(dt: Datatype, kind: KindSlug, raw: string, wordOrder: WordOrder): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return "";
  try {
    return formatDecodedDisplay(dt, kind, n, wordOrder);
  } catch {
    return "";
  }
}
