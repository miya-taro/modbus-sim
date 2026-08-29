import type {
  AutoMode,
  CommSettings,
  Datatype,
  FaultMode,
  FullState,
  KindSlug,
  Mode,
  ModeState,
  PointDict,
  ServerState,
} from "./types";

export interface UpsertBody {
  address: number;
  kind: KindSlug;
  datatype: Datatype;
  raw?: number;
  decoded?: string;
  tag?: string;
  fault_mode?: FaultMode;
  fault_exception?: string;
  delay_min_ms?: number;
  delay_max_ms?: number;
  auto_mode?: AutoMode;
  auto_min?: number;
  auto_max?: number;
  auto_step?: number;
  auto_period_sec?: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const jsonBody = (data: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(data) });

export const api = {
  getState: () => req<FullState>("/api/state"),

  bindAddresses: () => req<string[]>("/api/bind-addresses"),
  serialPorts: () => req<string[]>("/api/serial-ports"),

  getSettings: () => req<CommSettings>("/api/settings"),
  putSettings: (s: CommSettings) => req<CommSettings>("/api/settings", { method: "PUT", body: JSON.stringify(s) }),

  listSlaves: (mode: Mode) => req<ModeState>(`/api/slaves/${mode}`),
  addSlave: (mode: Mode, id: number) => req<ModeState>(`/api/slaves/${mode}`, jsonBody({ id })),
  removeSlave: (mode: Mode, id: number) => req<ModeState>(`/api/slaves/${mode}/${id}`, { method: "DELETE" }),
  patchSlave: (
    mode: Mode,
    id: number,
    patch: { tag?: string; selected?: boolean; word_order?: string },
  ) => req<ModeState>(`/api/slaves/${mode}/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  listPoints: (mode: Mode, id: number, kind: KindSlug) =>
    req<PointDict[]>(`/api/slaves/${mode}/${id}/points?kind=${kind}`),

  listAllPoints: (mode: Mode, id: number) => req<PointDict[]>(`/api/slaves/${mode}/${id}/points`),

  upsertPoint: (mode: Mode, id: number, body: UpsertBody) =>
    req<PointDict>(`/api/slaves/${mode}/${id}/points`, { method: "PUT", body: JSON.stringify(body) }),

  deletePoint: (mode: Mode, id: number, kind: KindSlug, address: number) =>
    req<{ ok: boolean }>(`/api/slaves/${mode}/${id}/points/${kind}/${address}`, { method: "DELETE" }),

  addRange: (
    mode: Mode,
    id: number,
    body: { start: number; count: number; kind: KindSlug; datatype: string; raw: number | string; tag_prefix: string },
  ) => req<{ added: number; errors: string[] }>(`/api/slaves/${mode}/${id}/points/range`, jsonBody(body)),

  importPoints: (mode: Mode, id: number, text: string, active_kind: KindSlug) =>
    req<{ added: number; errors: string[]; first_kind: string | null }>(
      `/api/slaves/${mode}/${id}/points/import`,
      jsonBody({ text, active_kind }),
    ),

  duplicatePoints: (mode: Mode, id: number, points: { kind: KindSlug; address: number }[]) =>
    req<{ added: number; skipped: string[] }>(`/api/slaves/${mode}/${id}/points/duplicate`, jsonBody({ points })),

  startServer: (mode: Mode) => req<ServerState>(`/api/server/${mode}/start`, { method: "POST" }),
  stopServer: (mode: Mode) => req<ServerState>(`/api/server/${mode}/stop`, { method: "POST" }),

  clearLog: () => req<{ ok: boolean }>("/api/log/clear", { method: "POST" }),

  exportSettings: (path: string) => req<{ ok: boolean }>("/api/settings/export", jsonBody({ path })),
  importSettings: (path: string) => req<{ ok: boolean }>("/api/settings/import", jsonBody({ path })),
};
