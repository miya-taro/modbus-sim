// Tauri（withGlobalTauri）配下ではネイティブのファイルダイアログを使う。
// ブラウザ単体ではダイアログが無いので呼び出し側がフォールバックする。

type DialogFilter = { name: string; extensions: string[] };

interface TauriDialog {
  open: (opts?: {
    multiple?: boolean;
    directory?: boolean;
    defaultPath?: string;
    filters?: DialogFilter[];
  }) => Promise<string | string[] | null>;
  save: (opts?: { defaultPath?: string; filters?: DialogFilter[] }) => Promise<string | null>;
}

function tauriDialog(): TauriDialog | null {
  const g = typeof window !== "undefined" ? (window as unknown as Record<string, any>) : undefined;
  return (g && g.__TAURI__ && g.__TAURI__.dialog) || null;
}

export function isDesktop(): boolean {
  return tauriDialog() != null;
}

export async function pickSavePath(
  defaultName: string,
  filters?: DialogFilter[],
): Promise<string | null> {
  const d = tauriDialog();
  if (!d) return null;
  return (await d.save({ defaultPath: defaultName, filters })) ?? null;
}

export async function pickOpenPath(filters?: DialogFilter[]): Promise<string | null> {
  const d = tauriDialog();
  if (!d) return null;
  const r = await d.open({ multiple: false, filters });
  return typeof r === "string" ? r : null;
}

export const JSON_FILTER: DialogFilter[] = [{ name: "JSON", extensions: ["json"] }];
export const TXT_FILTER: DialogFilter[] = [{ name: "テキスト", extensions: ["txt"] }];
