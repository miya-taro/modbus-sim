export type Mode = "tcp" | "rtu";
export type KindSlug = "hr" | "ir" | "coil" | "di";
export type Datatype = "uint16" | "int16" | "int32" | "float32" | "float64" | "bool";
export type WordOrder = "ABCD" | "CDAB" | "BADC" | "DCBA";

export const WORD_ORDERS: { value: WordOrder; label: string }[] = [
  { value: "ABCD", label: "ABCD (ビッグエンディアン)" },
  { value: "CDAB", label: "CDAB (ワードスワップ)" },
  { value: "BADC", label: "BADC (バイトスワップ)" },
  { value: "DCBA", label: "DCBA (リトルエンディアン)" },
];
export type FaultMode = "none" | "exception" | "no_response";
export type AutoMode = "none" | "increment" | "random_walk" | "sine";
export type Activity = "off" | "idle" | "active";

export interface PointDict {
  address: number;
  kind: KindSlug;
  datatype: Datatype;
  raw: number;
  decoded_hex: string;
  decoded: number | boolean;
  tag: string;
  advanced: boolean;
  fault_mode: FaultMode;
  fault_exception: string;
  delay_min_ms: number;
  delay_max_ms: number;
  auto_mode: AutoMode;
  auto_min: number;
  auto_max: number;
  auto_step: number;
  auto_period_sec: number;
}

export interface SlaveDict {
  id: number;
  tag: string;
  word_order: WordOrder;
  activity: Activity;
}

export interface ModeState {
  mode: Mode;
  selected_slave_id: number;
  slaves: SlaveDict[];
  points: Record<string, PointDict[]>;
}

export interface ServerState {
  tcp_running: boolean;
  rtu_running: boolean;
  tcp_client_count: number;
}

export interface CommSettings {
  tcp?: { host: string | null; port: number | null };
  rtu?: {
    port?: string;
    baudrate?: number;
    parity?: string;
    bytesize?: number;
    stopbits?: number;
  };
}

export interface FullState {
  type: "state";
  server: ServerState;
  settings: CommSettings;
  tcp: ModeState;
  rtu: ModeState;
  log: { lines: string[]; total_count: number };
}

export interface TickMessage {
  type: "tick";
  server?: ServerState;
  activity?: { mode: Mode; slave_id: number; state: Activity }[];
  tcp_points?: ModeState;
  rtu_points?: ModeState;
  log?: { lines: string[]; total_count: number };
}

export const KIND_LABELS: Record<KindSlug, string> = {
  hr: "Holding Register",
  ir: "Input Register",
  coil: "Coil",
  di: "Discrete Input",
};

export const KIND_ORDER: KindSlug[] = ["hr", "ir", "coil", "di"];

export const FAULT_MODE_LABELS: Record<FaultMode, string> = {
  none: "なし",
  exception: "例外応答を返す",
  no_response: "応答しない（タイムアウト）",
};

export const FAULT_EXCEPTION_LABELS: Record<string, string> = {
  illegal_function: "01: ILLEGAL FUNCTION",
  illegal_data_address: "02: ILLEGAL DATA ADDRESS",
  illegal_data_value: "03: ILLEGAL DATA VALUE",
  device_failure: "04: SLAVE DEVICE FAILURE",
  acknowledge: "05: ACKNOWLEDGE",
  device_busy: "06: SLAVE DEVICE BUSY",
  negative_acknowledge: "07: NEGATIVE ACKNOWLEDGE",
  memory_parity_error: "08: MEMORY PARITY ERROR",
  gateway_path_unavailable: "10: GATEWAY PATH UNAVAILABLE",
  gateway_no_response: "11: GATEWAY TARGET DEVICE FAILED TO RESPOND",
};

export const AUTO_MODE_LABELS: Record<AutoMode, string> = {
  none: "なし",
  increment: "インクリメント（周期ごとに +step、上限で折り返し）",
  random_walk: "ランダムウォーク（周期ごとに ±step 内で変動）",
  sine: "サイン波（周期で下限〜上限を往復）",
};
