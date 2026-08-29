export type Mode = "tcp" | "rtu";
export type KindSlug = "hr" | "ir" | "coil" | "di";
export type Datatype = "uint16" | "int16" | "int32" | "float32" | "float64" | "bool";
export type WordOrder = "ABCD" | "CDAB" | "BADC" | "DCBA";
export type FrameFault = "none" | "bad_crc" | "truncate" | "drop";

export const FRAME_FAULTS: { value: FrameFault; label: string }[] = [
  { value: "none", label: "なし" },
  { value: "bad_crc", label: "CRC/長さ破壊" },
  { value: "truncate", label: "フレーム切断" },
  { value: "drop", label: "無応答（フレーム破棄）" },
];

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
  frame_fault: FrameFault;
  frame_fault_rate: number;
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

export interface DeviceIdentity {
  vendor_name: string;
  product_code: string;
  major_minor_revision: string;
  vendor_url: string;
  product_name: string;
  model_name: string;
  user_application_name: string;
}

export const IDENTITY_FIELDS: { key: keyof DeviceIdentity; label: string }[] = [
  { key: "vendor_name", label: "VendorName" },
  { key: "product_code", label: "ProductCode" },
  { key: "major_minor_revision", label: "MajorMinorRevision" },
  { key: "vendor_url", label: "VendorUrl" },
  { key: "product_name", label: "ProductName" },
  { key: "model_name", label: "ModelName" },
  { key: "user_application_name", label: "UserApplicationName" },
];

export interface MasterState {
  connected: boolean;
  mode: Mode | null;
  target: string;
  polling: boolean;
  poll: Record<string, unknown> | null;
}

export interface MasterResult {
  ok: boolean;
  error?: string;
  exception_code?: number | null;
  raw: number[];
  values: (number | boolean)[];
}

export const MASTER_FUNCTIONS: { value: string; label: string; write: boolean }[] = [
  { value: "read_coils", label: "01 Read Coils", write: false },
  { value: "read_discrete_inputs", label: "02 Read Discrete Inputs", write: false },
  { value: "read_holding_registers", label: "03 Read Holding Registers", write: false },
  { value: "read_input_registers", label: "04 Read Input Registers", write: false },
  { value: "write_coil", label: "05 Write Single Coil", write: true },
  { value: "write_register", label: "06 Write Single Register", write: true },
  { value: "write_coils", label: "15 Write Multiple Coils", write: true },
  { value: "write_registers", label: "16 Write Multiple Registers", write: true },
];

export interface FullState {
  type: "state";
  server: ServerState;
  settings: CommSettings;
  identity: DeviceIdentity;
  master: MasterState;
  master_log: { lines: string[] };
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
  master?: MasterState;
  master_log?: { lines: string[] };
}

export interface MasterResultMessage {
  type: "master_result";
  result: MasterResult;
  poll: boolean;
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
