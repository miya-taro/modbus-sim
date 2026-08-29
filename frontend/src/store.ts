import { create } from "zustand";
import { api } from "./api";
import type {
  CommSettings,
  DeviceIdentity,
  FullState,
  MasterResult,
  MasterResultMessage,
  MasterState,
  Mode,
  ModeState,
  ServerState,
  TickMessage,
} from "./types";

const DEFAULT_MASTER: MasterState = {
  connected: false,
  mode: null,
  target: "",
  polling: false,
  poll: null,
  stats: { count: 0, errors: 0, last_ms: null, min_ms: null, max_ms: null, avg_ms: null, elapsed_s: 0 },
};

const DEFAULT_IDENTITY: DeviceIdentity = {
  vendor_name: "",
  product_code: "",
  major_minor_revision: "",
  vendor_url: "",
  product_name: "",
  model_name: "",
  user_application_name: "",
};

export type TabKey = "settings" | "tcp" | "rtu" | "master" | "scenario" | "log";

interface State {
  connected: boolean;
  server: ServerState;
  settings: CommSettings;
  identity: DeviceIdentity;
  master: MasterState;
  masterLog: string[];
  masterResult: MasterResult | null;
  tcp: ModeState;
  rtu: ModeState;
  log: { lines: string[]; total_count: number };
  error: string | null;
  activeTab: TabKey;
  confirmState: { message: string; resolve: (v: boolean) => void } | null;

  setActiveTab: (t: TabKey) => void;
  setError: (e: string | null) => void;
  askConfirm: (message: string) => Promise<boolean>;
  resolveConfirm: (v: boolean) => void;
  connect: () => void;
  applyFullState: (s: FullState) => void;
  refreshMode: (mode: Mode) => Promise<void>;
  setModeState: (mode: Mode, ms: ModeState) => void;
  setSettings: (s: CommSettings) => void;
  setIdentity: (i: DeviceIdentity) => void;
  setServer: (s: ServerState) => void;
  setMaster: (m: MasterState) => void;
  setMasterResult: (r: MasterResult) => void;
}

const emptyMode = (mode: Mode): ModeState => ({
  mode,
  selected_slave_id: 1,
  slaves: [
    { id: 1, tag: "", word_order: "ABCD", frame_fault: "none", frame_fault_rate: 1, activity: "off" },
  ],
  points: { "1": [] },
});

let ws: WebSocket | null = null;
let reconnectTimer: number | undefined;

export const useStore = create<State>((set, get) => ({
  connected: false,
  server: { tcp_running: false, rtu_running: false, tcp_client_count: 0 },
  settings: {},
  identity: DEFAULT_IDENTITY,
  master: DEFAULT_MASTER,
  masterLog: [],
  masterResult: null,
  tcp: emptyMode("tcp"),
  rtu: emptyMode("rtu"),
  log: { lines: [], total_count: 0 },
  error: null,
  activeTab: "settings",
  confirmState: null,

  setActiveTab: (t) => set({ activeTab: t }),
  setError: (e) => set({ error: e }),
  askConfirm: (message) =>
    new Promise<boolean>((resolve) => set({ confirmState: { message, resolve } })),
  resolveConfirm: (v) => {
    const cs = get().confirmState;
    if (cs) cs.resolve(v);
    set({ confirmState: null });
  },

  applyFullState: (s) =>
    set({
      server: s.server,
      settings: s.settings ?? {},
      identity: s.identity ?? DEFAULT_IDENTITY,
      master: s.master ?? DEFAULT_MASTER,
      masterLog: s.master_log?.lines ?? [],
      tcp: s.tcp,
      rtu: s.rtu,
      log: s.log,
    }),

  setModeState: (mode, ms) => set({ [mode]: ms } as Pick<State, "tcp" | "rtu">),
  setSettings: (s) => set({ settings: s }),
  setIdentity: (i) => set({ identity: i }),
  setServer: (s) => set({ server: s }),
  setMaster: (m) => set({ master: m }),
  setMasterResult: (r) => set({ masterResult: r }),

  refreshMode: async (mode) => {
    try {
      const snap = await api.listSlaves(mode);
      const pts = await api.listAllPoints(mode, snap.selected_slave_id);
      set({
        [mode]: { ...snap, points: { [String(snap.selected_slave_id)]: pts } },
      } as Pick<State, "tcp" | "rtu">);
    } catch (e) {
      set({ error: String((e as Error).message ?? e) });
    }
  },

  connect: () => {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
      set({ connected: true });
      // 再同期
      api.getState().then((s) => get().applyFullState(s)).catch(() => {});
    };
    ws.onclose = () => {
      set({ connected: false });
      window.clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(() => get().connect(), 1500);
    };
    ws.onerror = () => ws?.close();
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as FullState | TickMessage | MasterResultMessage;
      if (msg.type === "state") {
        get().applyFullState(msg);
        return;
      }
      if (msg.type === "master_result") {
        set({ masterResult: msg.result, ...(msg.master ? { master: msg.master } : {}) });
        return;
      }
      const patch: Partial<State> = {};
      if (msg.server) patch.server = msg.server;
      if (msg.log) patch.log = msg.log;
      if (msg.master) patch.master = msg.master;
      if (msg.master_log) patch.masterLog = msg.master_log.lines;
      // tick の *_points は選択中スレーブ分しか含まないので points はマージする
      const mergePoints = (prev: ModeState, next: ModeState): ModeState => ({
        ...next,
        points: { ...prev.points, ...next.points },
      });
      if (msg.tcp_points) patch.tcp = mergePoints(get().tcp, msg.tcp_points);
      if (msg.rtu_points) patch.rtu = mergePoints(get().rtu, msg.rtu_points);
      if (msg.activity) {
        const bump = (ms: ModeState): ModeState => ({
          ...ms,
          slaves: ms.slaves.map((sl) => {
            const a = msg.activity!.find((x) => x.mode === ms.mode && x.slave_id === sl.id);
            return a ? { ...sl, activity: a.state } : sl;
          }),
        });
        patch.tcp = bump(patch.tcp ?? get().tcp);
        patch.rtu = bump(patch.rtu ?? get().rtu);
      }
      if (Object.keys(patch).length) set(patch);
    };
  },
}));
