// modbus_sim/datastore.py の decode/encode 相当を TypeScript へ移植。
// 表示・入力の即時変換に使い、確定時はバックエンドが最終的な正とする。
import type { Datatype, KindSlug } from "./types";

export const REGISTER_COUNT = 65536;

const _buf = new ArrayBuffer(8);
const _dv = new DataView(_buf);

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

function float32Bits(raw: number): number {
  _dv.setFloat32(0, raw, false);
  return _dv.getUint32(0, false);
}

function float64BitsHex(raw: number): string {
  _dv.setFloat64(0, raw, false);
  return "0x" + _dv.getBigUint64(0, false).toString(16).toUpperCase().padStart(16, "0");
}

export function formatDecodedDisplay(dt: Datatype, kind: KindSlug, raw: number): string {
  if (kind === "coil" || kind === "di") return hex(raw ? 1 : 0, 2);
  if (dt === "float32") return hex(float32Bits(raw), 8);
  if (dt === "float64") return float64BitsHex(raw);
  if (dt === "int32") return hex(raw & 0xffffffff, 8);
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

// Decoded 欄の入力（すべて16進）を datatype に応じた raw（メモリ表現 or float 値）へ。
export function parseDecodedInput(text: string, dt: Datatype): number {
  const s = text.trim();
  if (s === "") return isFloat(dt) ? 0 : 0;
  const parsed = parseHexBigInt(s);
  switch (dt) {
    case "bool":
      return parsed !== 0n ? 1 : 0;
    case "uint16":
    case "int16":
      return Number(parsed & 0xffffn);
    case "float32": {
      _dv.setUint32(0, Number(parsed & 0xffffffffn), false);
      return _dv.getFloat32(0, false);
    }
    case "float64": {
      _dv.setBigUint64(0, parsed & 0xffffffffffffffffn, false);
      return _dv.getFloat64(0, false);
    }
    default: {
      // int32
      let v = Number(parsed & 0xffffffffn);
      if (v >= 0x80000000) v -= 0x100000000;
      return v;
    }
  }
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
