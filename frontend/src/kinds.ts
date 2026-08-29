import type { Datatype, KindSlug } from "./types";

const BIT: Datatype[] = ["bool"];
const REG: Datatype[] = ["uint16", "int16", "int32", "float32", "float64"];

export function datatypeChoicesFor(kind: KindSlug): Datatype[] {
  return kind === "coil" || kind === "di" ? BIT : REG;
}

export function defaultDatatypeFor(kind: KindSlug): Datatype {
  return datatypeChoicesFor(kind)[0];
}
