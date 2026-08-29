// modbus_sim/datastore.py + wordorder.py の decode/encode 相当を TypeScript へ移植。
// 表示・入力の即時変換に使い、確定時はバックエンドが最終的な正とする。
import type { Datatype, KindSlug, WordOrder } from "./types";

export const REGISTER_COUNT = 65536;

const _buf = new ArrayBuffer(8);
const _dv = new DataView(_buf);

/** 正規 BE バイト列 <-> ワイヤ並び（自己反転）。 */
function reorder(bytes: Uint8Array, order: WordOrder): Uint8Array {
  if (order === "ABCD") return bytes;
  if (order === "DCBA") return bytes.slice().reverse();
  const out = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i += 2) {
    if (order === "CDAB") {
      // ワード順を反転
      out[i] = bytes[bytes.length - 2 - i];
      out[i + 1] = bytes[bytes.length - 1 - i];
    } else {
      // BADC: 各ワード内のバイトを入れ替え
      out[i] = bytes[i + 1];
      out[i + 1] = bytes[i];
    }
  }
  return out;
}

export function datatypeSpan(dt: Datatype): number {
  if (dt === "float64") return 4;
  if (dt === "int32" || dt === "float32") return 2;
  return 1;
}

export function isFloat(dt: Datatype): boolean {
  return dt === "float32" || dt === "float64";
}

export function datatypeBounds(dt: Datatype): [number, number] {
  switch (dt) {
    case "int16":
      return [-32768, 32767];
    case "int32":
      return [-2147483648, 2147483647];
    case "float32":
    case "float64":
      return [-1_000_000, 1_000_000];
    case "bool":
      return [0, 1];
    default:
      return [0, 65535];
  }
}

function hex(n: number, digits: number): string {
  return "0x" + (n >>> 0).toString(16).toUpperCase().padStart(digits, "0");
}

/** 多レジスタ型 raw -> 正規 BE バイト列。1 レジスタ型は null。 */
function canonicalBytes(dt: Datatype, raw: number): Uint8Array | null {
  if (dt === "int32") {
    _dv.setInt32(0, raw | 0, false);
    return new Uint8Array(_buf.slice(0, 4));
  }
  if (dt === "float32") {
    _dv.setFloat32(0, raw, false);
    return new Uint8Array(_buf.slice(0, 4));
  }
  if (dt === "float64") {
    _dv.setFloat64(0, raw, false);
    return new Uint8Array(_buf.slice(0, 8));
  }
  return null;
}

const toHex = (bytes: Uint8Array): string =>
  "0x" + Array.from(bytes, (b) => b.toString(16).toUpperCase().padStart(2, "0")).join("");

export function formatDecodedDisplay(
  dt: Datatype,
  kind: KindSlug,
  raw: number,
  wordOrder: WordOrder = "ABCD",
): string {
  if (kind === "coil" || kind === "di") return hex(raw ? 1 : 0, 2);
  const canonical = canonicalBytes(dt, raw);
  if (canonical) return toHex(reorder(canonical, wordOrder));
  return hex(raw & 0xffff, 4);
}

function parseHexBigInt(text: string): bigint {
  let t = text.trim();
  if (t === "") return 0n;
  if (t.toLowerCase().startsWith("0x")) t = t.slice(2);
  else if (t.length > 1 && t[t.length - 1].toLowerCase() === "h") t = t.slice(0, -1);
  if (!/^[0-9a-fA-F]+$/.test(t)) throw new Error(`16進として解釈できません: ${text}`);
  return BigInt("0x" + t);
}

// Decoded 欄の入力（ワイヤ上のバイト列の16進）を raw へ復元。
export function parseDecodedInput(text: string, dt: Datatype, wordOrder: WordOrder = "ABCD"): number {
  const s = text.trim();
  if (s === "") return 0;
  const parsed = parseHexBigInt(s);
  if (dt === "bool") return parsed !== 0n ? 1 : 0;
  if (dt === "uint16" || dt === "int16") return Number(parsed & 0xffffn);

  const nbytes = datatypeSpan(dt) * 2;
  const wire = new Uint8Array(nbytes);
  let v = parsed & ((1n << BigInt(nbytes * 8)) - 1n);
  for (let i = nbytes - 1; i >= 0; i--) {
    wire[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  const canonical = reorder(wire, wordOrder);
  canonical.forEach((b, i) => _dv.setUint8(i, b));
  if (dt === "float32") return _dv.getFloat32(0, false);
  if (dt === "float64") return _dv.getFloat64(0, false);
  return _dv.getInt32(0, false); // int32
}

export function parseRawInput(text: string, dt: Datatype): number {
  const s = text.trim();
  if (s === "") return 0;
  if (isFloat(dt)) {
    const v = Number(s);
    if (!Number.isFinite(v)) throw new Error("数値で入力してください");
    return v;
  }
  if (!/^-?\d+$/.test(s)) throw new Error("整数で入力してください");
  return parseInt(s, 10);
}

export function validateAddress(address: number, dt: Datatype): void {
  if (!Number.isInteger(address) || address < 0 || address >= REGISTER_COUNT) {
    throw new Error(`Addr は 0-${REGISTER_COUNT - 1} です`);
  }
  const span = datatypeSpan(dt);
  if (span >= 2 && address + span - 1 >= REGISTER_COUNT) {
    throw new Error(`${dt} は Addr が ${REGISTER_COUNT - span} 以下である必要があります`);
  }
}

// グリッド表示用: raw（メモリ表現）を人間可読の値へ。
export function decodeForDisplay(dt: Datatype, kind: KindSlug, raw: number): string {
  if (kind === "coil" || kind === "di") return raw ? "1" : "0";
  if (dt === "int16") {
    const v = raw & 0xffff;
    return String(v >= 0x8000 ? v - 0x10000 : v);
  }
  if (isFloat(dt)) return String(raw);
  return String(raw);
}
