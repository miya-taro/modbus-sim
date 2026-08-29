# Tauri 移行計画

PySide6 製の UI を廃止し、**Tauri（Rust シェル）+ React/TypeScript フロントエンド + Python サイドカー**構成へ移行するための計画書。

## 0. 方針の要約

- **コアの Modbus シミュレーションロジックは Python のまま残す。** `pymodbus` ベースの
  `datastore.py` / `server_manager.py` / `logging_handler.py` / `packet_log.py` は
  異常応答・遅延・NO_RESPONSE ハング・INT32 2レジスタ BE・コイルのビットパック・MBAP 異常検知など
  積み上げた挙動とテスト資産が大きく、書き直しは高コスト・高リスク。
- Python 側に **ローカル API サーバ層（新規）** を足し、`modbus_sim/ui/` を丸ごと廃止する。
- フロントは **React + TypeScript + Vite**。PySide の4タブ（通信設定 / TCP スレーブ / RTU スレーブ / 通信ログ）を再実装。
- Tauri（v2）は Python サイドカーを起動し、`localhost` の WebView を表示するだけの薄いシェル。
- 配布物は `tauri build` により Windows 向けインストーラ（NSIS/MSI）。Python サイドカーは PyInstaller で onefile 化して同梱。

```
┌─ Tauri (Rust) ─────────────────────────────┐
│  ウィンドウ / WebView / サイドカー起動・監視 │
│                                            │
│  ┌─ WebView: React + TS (Vite build) ───┐  │
│  │  設定 / スレーブ編集 / ログ表示        │  │
│  └──────────┬───────────────────────────┘  │
│             │ HTTP (REST) + WebSocket        │
│  ┌─ Python サイドカー (PyInstaller onefile)┐ │
│  │  FastAPI + 単一 asyncio ループ          │ │
│  │  modbus_sim.datastore / server_manager │ │
│  │  pymodbus TCP/RTU サーバ               │ │
│  └───────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

## 1. 現状の依存関係と分類

### 1.1 そのまま残す（UI 非依存のコア）

| ファイル | 役割 | 備考 |
|---|---|---|
| `modbus_sim/config.py` | Enum / 定数 / TcpConfig / RtuConfig | 変更なし |
| `modbus_sim/models.py` | `RegisterPoint` / `CommSettings` | 変更なし（`CommSettings` は API 層で流用） |
| `modbus_sim/datastore.py` | コア。レジストリ / データストア / decode・encode 関数群 | 変更なし。モジュールグローバル `tcp_registry` / `rtu_registry` は API 層から参照 |
| `modbus_sim/server_manager.py` | サーバ起動・停止・トレース・ログバッファ | コールバックを API 層の WebSocket ブロードキャストに繋ぐ |
| `modbus_sim/logging_handler.py` | 不正フレーム検知付きサーバ | 変更なし |
| `modbus_sim/packet_log.py` | ADU 要約・不正フレーム検知 | 変更なし |
| `modbus_sim/network.py` | bind アドレス列挙 / host 正規化 | 変更なし。API から利用 |
| `modbus_sim/platform_util.py` | OS 判定 / 特権ポート制限 | 変更なし。API から利用 |
| `modbus_sim/error_messages.py` | 例外→日本語メッセージ | 変更なし。API のエラーレスポンスで利用 |

### 1.2 リファクタが必要

| ファイル | 問題 | 対応 |
|---|---|---|
| `modbus_sim/settings_store.py` | 冒頭で `from modbus_sim.ui.settings_panel import SettingsPanel` を import。`save()` / `apply()` が `SettingsPanel` インスタンスを引数に取る | `SettingsPanel` 依存を切る。設定は `dict`（または `CommSettings`）だけで load/save/apply/export/import できる純粋関数群に変更 |

### 1.3 破棄する

- `modbus_sim/ui/` 全体（`app.py` / `slave_panel.py` / `settings_panel.py` / `log_panel.py` / `async_runner.py` / `common.py`）
- `modbus_sim/fonts_util.py` / `modbus_sim/xcb_util.py`（WSL の Qt フォント / xcb 対策。ネイティブ WebView では不要）
- `main.py` の GUI 起動部分（サイドカー起動用の新 `main.py` に置換）
- `modbus-sim.spec` は Tauri サイドカー用に書き換え

### 1.4 依存パッケージの変化

- 追加: `fastapi`, `uvicorn[standard]`（または `starlette` + `websockets`）
- 削除: `PySide6`
- 維持: `pymodbus`, `pyserial`
- Node 側: `react`, `react-dom`, `vite`, `@vitejs/plugin-react`, `typescript`, グリッド用ライブラリ（後述）、`zustand`（軽量状態管理）、`vitest`
- Rust 側: Tauri v2 + `tauri-plugin-shell`

## 2. バックエンド作業（Python）

### Phase B1: `settings_store.py` の UI 依存除去

- `SettingsPanel.to_dict()` / `apply_settings()` が担っていた「画面値 ⇔ dict」変換を、
  `CommSettings` ベースの純粋関数へ移す（例: `modbus_sim/settings_model.py`）。
  - `comm_settings_to_dict(comm) -> dict`
  - `apply_dict_to_comm_settings(data, comm) -> None`（`network.normalize_host` によるバリデーションを含む）
- `SettingsStore.save/apply/apply_from_path` の引数を `SettingsPanel` から `CommSettings`（または生 dict）に変更。
- 既存 `test_settings_robustness.py` が壊れる想定 → API 層のテストへ置換（後述）。
- 完了条件: `QT_QPA_PLATFORM=offscreen` 抜きで `pytest tests/` のコア分が緑（UI テストは一時 skip 可）。

### Phase B2: API サーバ層の新規追加（`modbus_sim/api/`）

単一の `asyncio` イベントループ上で FastAPI（uvicorn）と pymodbus サーバを同居させる。
現行の `AsyncRunner`（UI スレッド + 別スレッドの asyncio ループ）は不要になり、プロセス全体が 1 つの asyncio ループになる。

**アプリ状態**
- `tcp_registry` / `rtu_registry`（`datastore.py` のモジュールグローバルをそのまま利用）
- `ModbusServerManager`（`slave_registry` は使わず TCP/RTU 別レジストリ構成）
- `CommSettings` インスタンス
- `SettingsStore`（`~/.modbus_sim/settings.json`）

**バックグラウンドタスク（現行 `MainWindow._poll_ui` 相当、500ms 周期）**
- `tcp_registry.tick_auto_values(0.5)` / `rtu_registry.tick_auto_values(0.5)`
- `registry.sync_from_server()`
- activity 状態の再計算
- 変化があれば WebSocket でブロードキャスト（差分）

**REST エンドポイント（案）**

| メソッド / パス | 対応する現行操作 |
|---|---|
| `GET /api/state` | 初期スナップショット（サーバ状態 / 設定 / 両レジストリの slaves+points / ログ） |
| `GET /api/settings` / `PUT /api/settings` | 通信設定の取得・更新（debounce 保存） |
| `POST /api/settings/export` / `POST /api/settings/import` | エクスポート / インポート（サーバ停止中のみ） |
| `GET /api/bind-addresses` | `network.list_bind_addresses()` |
| `GET /api/serial-ports` | `serial.tools.list_ports` |
| `GET /api/slaves/{mode}` | Slave ID 一覧 + tag + activity |
| `POST /api/slaves/{mode}` / `DELETE /api/slaves/{mode}/{id}` | Slave 追加 / 削除（1〜247、最後の1件は不可） |
| `PATCH /api/slaves/{mode}/{id}` | tag 更新 / 選択中スレーブ更新 |
| `GET /api/slaves/{mode}/{id}/points?kind=` | Kind 別のレジスタ点一覧 |
| `PUT /api/slaves/{mode}/{id}/points/{kind}/{addr}` | 1点の upsert（raw / decoded / datatype / tag / 詳細設定） |
| `DELETE /api/slaves/{mode}/{id}/points/{kind}/{addr}` | 1点削除 |
| `POST /api/slaves/{mode}/{id}/points:range` | 範囲追加（`RangeAddDialog` 相当） |
| `POST /api/slaves/{mode}/{id}/points:import` | CSV/TSV/貼り付けテキスト取込（`_import_register_map_text` を関数化して共用） |
| `POST /api/slaves/{mode}/{id}/points:duplicate` | 行複製（空きアドレス探索を含む） |
| `POST /api/server/{mode}:start` / `:stop` | サーバ起動 / 停止。失敗時は `error_messages.friendly_server_error` を 400 で返す |
| `POST /api/log:clear` | ログバッファクリア |

`{mode}` = `tcp` | `rtu`、`{kind}` = `hr` | `ir` | `coil` | `di`。

**WebSocket `/ws`（push）**
- `log`: 追加ログ行（増分。`total_log_count` も送り、フロントで drop 件数を計算） 
- `server_state`: `{ tcp_running, rtu_running, tcp_client_count }`
- `activity`: `{ mode, slave_id, state }` の配列
- `points_changed`: auto-change / クライアント書込で変わった点（`{ mode, slave_id, kind, addr, raw, decoded }`）

**共通化するロジック（`slave_panel.py` から抽出してサーバ側の純粋関数へ）**
- `_import_register_map_text`（CSV/TSV パース + バリデーション）
- `_next_free_address` / 複製ロジック
- 範囲追加のアドレス採番と `validate_address`
- 詳細設定（fault/delay/auto）の検証（`RegisterAdvancedDialog._on_accept` の条件）

### Phase B3: サイドカー実行形態

- 新 `main.py`（または `modbus_sim/__main__.py`）: 引数 `--host 127.0.0.1 --port <n>` を受け、
  uvicorn を起動。`--port 0` で OS 採番し、採番結果を stdout に 1 行 JSON で出力（Tauri 側が読む）。
- `GET /api/health` を用意（Tauri が起動完了検知に使う）。
- PyInstaller onefile 化。pymodbus / uvicorn の hidden import は spec で調整（`uvicorn.loops`, `uvicorn.protocols`, `pymodbus` のサブモジュール等）。
- 生成物名は Tauri の外部バイナリ命名規約に合わせる（`modbus-sim-backend-<target-triple>[.exe]`）。

## 3. フロントエンド作業（React + TypeScript + Vite）

配置: リポジトリ直下 `frontend/`。

### 3.1 技術選定

- 状態管理: `zustand`（グローバルストア）+ WebSocket 受信で更新。REST 呼び出しは薄い `api.ts`。
- レジスタグリッド: 候補
  1. **TanStack Table + 自前セル編集**（依存が軽く、キーボード移動を自作できる。推奨）
  2. Glide Data Grid（大量行・Excel 風だが導入コスト高）
  3. AG Grid Community（高機能だがバンドル大）
  - 実データは疎（`points` のみ、65536 全域は持たない）なので重量級グリッドは不要。**候補1 を推奨**。
- ダイアログ: Radix UI Primitives か自前。日本語固定なので i18n ライブラリは不要（文言は `strings.ts` に集約）。

### 3.2 decode / encode ロジックの移植

`datastore.py` の以下を **TypeScript へ移植**し、`vitest` で Python 側テストと同じケースを移植する
（毎キーストロークでサーバ往復させないため）。

- `format_decoded_display`（raw → 16進表示）
- `parse_decoded_input`（`0x1234` / `1234h` / 素の `1234` を全て16進として解釈）
- `parse_raw_input`（float32 のみ小数可）
- `datatype_bounds`
- `decode_value` / `raw_from_memory` の表示相当
- `validate_address`（INT32/FLOAT32 は addr ≤ 65534）
- INT16 の `-1` と `0xFFFF` の等価判定

移植対象の参照テスト: `tests/test_datatypes.py`, `tests/test_strict.py`。

### 3.3 画面構成（PySide タブとの対応）

**ヘッダ（常時表示）**
- タイトル「Modbus TCP/RTU シミュレータ」
- TCP: 状態ランプ（緑=待受中 / 赤=停止）+「(N台接続中)」+ 開始/停止ボタン
- RTU: 状態ランプ + 開始/停止ボタン
- エラーメッセージ行（`friendly_server_error` の文言をそのまま表示）
- 起動中は該当ボタンを無効化（現行 `_tcp_busy` / `_rtu_busy` 相当）

**タブ1: 通信設定**
- TCP: IP（コンボ + 手入力、`GET /api/bind-addresses` で再検出ボタン）、Port
- RTU: シリアルポート（`GET /api/serial-ports` で再検出）、ボーレート / パリティ / Data bits / Stop bits
- 「現在の設定」サマリ（入力済み項目のみ表示、`CommSettings.summary_lines` 相当）
- 設定エクスポート / インポート（インポートはサーバ停止中のみ活性）
- サーバ稼働中は該当セクションを read-only

**タブ2/3: TCP スレーブ / RTU スレーブ**（共通コンポーネント、`mode` prop で切替）
- 左ペイン: Slave ID
  - 検索（ID / 機器名）、activity ドット（green/gray/薄灰）
  - 追加（ID 入力 + `+`）、「選択中の Slave を削除」（確認ダイアログ、Delete キー）
  - 機器名（tag）入力
- 右ペイン:
  - Kind タブ（Holding Register / Input Register / Coil / Discrete Input）
  - ツールバー: 検索（Addr / Tag）、範囲追加、CSV/TSV取込
  - グリッド列 `Addr | Raw | Decoded | Datatype | Tag`
    - Coil/DI は datatype = `bool` 固定・非活性
    - HR/IR は `uint16 / int16 / int32 / float32`
    - Raw ⇔ Decoded 相互反映、addr バリデーション、エラーセルの赤ハイライト + tooltip
    - 詳細設定済みの行は背景色（`#eef2ff` 相当）
    - キーボードで Addr→Raw→Decoded→Datatype→Tag 移動
    - 末尾に空のドラフト行（新規追加用）
  - 右クリックメニュー: コピー / 複製 / 貼り付け / 詳細設定 / 削除（複数選択対応）
  - 詳細設定ダイアログ: 異常応答（なし / 例外応答 / 応答しない）+ 例外コード、応答遅延（min/max ms）、
    値の自動変化（なし / インクリメント / ランダムウォーク / サイン波）+ 下限・上限・step・周期
    （Coil/DI では自動変化セクション非活性）
  - 詳細設定 / 遅延 / 自動変化は **Holding/Input Register のみ**（現行仕様どおり）
- サーバ稼働中もグリッド編集は可能（現行どおり）。稼働中はインポートのみ不可。

**タブ4: 通信ログ**
- ヘッダ: 「クリア」
- ツールバー: 表示フィルタ（すべて / TCP / RTU）、絞り込み検索、自動スクロール、一時停止 / 再開、保存
- 本文: 等幅フォント、行種別で色分け（INVALID = 赤太字 / TX = 灰 / RX = 通常）
- 一時停止中に保持上限（2000 行）超過で破棄された件数の警告
- 未接続時はログ出力例をプレースホルダ表示
- 保存はブラウザ的なダウンロードではなく、サーバ側 `POST` かフロントで Blob 生成（Tauri のファイル保存ダイアログ経由が自然）

### 3.4 更新モデル

- 起動時に `GET /api/state` で全体スナップショット。
- 以後は WebSocket の増分で更新。切断時は指数バックオフで再接続 → 再接続後に `GET /api/state` で再同期。
- レジスタ編集は楽観的更新 → `PUT` 応答 or `points_changed` で確定。エラー時はロールバック + セル赤表示。

## 4. Tauri シェル作業（Rust, `src-tauri/`）

- **Tauri v2** 前提。`tauri-plugin-shell` の sidecar 機能で Python バックエンドを起動。
- `tauri.conf.json`:
  - `productName` / window: `title = "Modbus Simulator"`, `width 900 / height 640`, `minWidth 800 / minHeight 560`
  - `bundle.externalBin` に PyInstaller 生成物を登録
  - `app.security.csp`: `connect-src` に `http://127.0.0.1:* ws://127.0.0.1:*` を許可、他は自己ホストのみ
  - `beforeDevCommand`: `npm --prefix frontend run dev`、`devUrl`: `http://localhost:5173`
  - `beforeBuildCommand`: `npm --prefix frontend run build`（+ PyInstaller は CI / スクリプトで先行実行）、`frontendDist`: `../frontend/dist`
- `src-tauri/src/lib.rs`（`run()`）:
  1. 空きポートを確保（`TcpListener::bind(127.0.0.1:0)` → ポート取得 → drop）
  2. sidecar を `--host 127.0.0.1 --port <n>` で spawn、stdout/stderr をログへ
  3. `GET /api/health` を ~10 秒ポーリングして ready 検知 → フロントに `window.__BACKEND_PORT__` を注入（`initialization_script`）
  4. `WindowEvent::CloseRequested` で sidecar を kill（`CommandChild::kill`）してからウィンドウを閉じる
  5. sidecar が異常終了したらエラーダイアログを出して終了
- dev では sidecar を Tauri から起動せず、`python -m modbus_sim --port 8000` を別ターミナルで動かして固定ポート、という切替も用意すると開発が楽。

## 5. ビルドと配布

- **開発**: `npm --prefix frontend run dev` + `python -m modbus_sim --port 8000` + `cargo tauri dev`
  （または `cargo tauri dev` に集約）。
- **リリース（Windows）**:
  1. `pip install -e ".[build]"` → `pyinstaller modbus-sim.spec`（backend onefile 生成）
  2. 生成物を `src-tauri/binaries/modbus-sim-backend-x86_64-pc-windows-msvc.exe` へ配置
  3. `cargo tauri build` → NSIS / MSI インストーラ
- PyInstaller はクロスビルド不可（既存の `modbus-sim.spec` 冒頭コメントどおり）。**ターゲット OS 上でビルド。**
- サイズ見積り: Python ランタイム同梱で **40〜70MB** 程度。
- CI（任意）: GitHub Actions の `windows-latest` で PyInstaller → `tauri-action` でインストーラ生成。

## 6. テスト戦略

### 6.1 Python

| 既存テスト | 移行後 |
|---|---|
| `test_datatypes.py` / `test_strict.py` | 維持（コアの decode/encode） |
| `test_comm_log.py` | 維持（`packet_log`） |
| `test_rtu.py` | 維持（pymodbus `NULLMODEM_HOST`） |
| `test_server_manager_robustness.py` | 維持 |
| `test_live_register_updates.py` | 維持（datastore 直叩き部分）。UI 参照があれば API テストへ |
| `test_settings_robustness.py` | `settings_store` リファクタに合わせて書き換え（dict ベース） |
| `test_ui_smoke.py` / `test_register_kind_ui.py` / `test_bulk_register_operations.py` / `test_delete_operations.py` / `test_register_advanced_settings.py` | **API レベルテストへ置換**（FastAPI `TestClient`）。範囲追加 / CSV取込 / 複製 / 削除 / 詳細設定バリデーションを HTTP 経由で検証 |
| `test_xcb_util.py` | 削除 |

- `pyproject.toml` から PySide6 依存を外し、`QT_QPA_PLATFORM=offscreen` 前提も撤廃。
- `httpx` / `pytest` を test 依存に追加。

### 6.2 フロントエンド

- `vitest`: decode/encode ユーティリティのユニットテスト（Python テストケースを移植）。
- `@playwright/test`（任意）: スモーク（設定入力 → サーバ起動 → レジスタ追加 → ログ表示 → 停止）。モックまたは実バックエンドに対して。

### 6.3 Rust

- sidecar ライフサイクルは手動確認中心（起動待ち / 終了時 kill / 異常終了ダイアログ）。

## 7. 段階的な進め方（ブランチ `feature/tauri-ui`）

| Step | 内容 | 完了条件 |
|---|---|---|
| 0 | ブランチ作成、この計画を doc に追加 | — |
| 1 | `settings_store.py` の `SettingsPanel` 依存除去（B1） | コアの pytest 緑（UI テストは一時 skip） |
| 2 | API サーバ層追加（B2）。既存 PySide UI は残したまま並行 | `GET /api/state` / サーバ起動停止 / レジスタ CRUD / WebSocket が curl・pytest で動作 |
| 3 | React フロント実装（vite dev + Step2 の API） | PySide 版と機能パリティ（4タブすべて） |
| 4 | Tauri シェル統合（B3 + 第4章）。sidecar 起動 / 終了 | `cargo tauri dev` で全機能動作、閉じたら sidecar も終了 |
| 5 | PyInstaller + `tauri build`、Windows で動作確認 | インストーラから起動して全機能動作 |
| 6 | `modbus_sim/ui/` / `fonts_util` / `xcb_util` / PySide6 依存 / 旧 `main.py` を削除。`CLAUDE.md` / `README.md` / `modbus-sim.spec` 更新、UI テスト置換完了 | pytest 緑、`grep -r PySide6` が 0 件 |

Step 2〜3 の間は PySide 版と API 版が同じ `datastore` グローバルを共有して並行稼働できるため、
機能比較しながら進められる。

## 8. リスク・未確定事項

- **Tauri のバージョン**: v2 を想定（sidecar・plugin 体系が v1 と異なる）。v1 を使う理由があれば要再検討。
- **API フレームワーク**: FastAPI + uvicorn を想定。より軽くしたいなら `starlette` 直、または `aiohttp`。
- **グリッドライブラリ**: TanStack Table + 自前編集を推奨。体感速度が要件なら早めにプロトタイプ。
- **PyInstaller の hidden import**: uvicorn / pymodbus のサブモジュール取りこぼしに注意（現行 spec は `hiddenimports=[]`）。
- **RTU シリアル**: 現行同様 Windows ネイティブでのみ実用。WSL/Linux は制約あり。
- **ポート衝突 / ファイアウォール**: `127.0.0.1` 固定 + OS 採番ポートで回避。Windows Defender のプロンプトが出る可能性。
- **単一 asyncio 化**: uvicorn のイベントループ上で pymodbus サーバを `serve_forever(background=True)` する構成の検証が必要（現行は専用ループ）。
- **日本語フォント**: ネイティブ WebView は OS フォントで表示できるため `fonts_util` / `xcb_util` は不要になる見込み。
- **設定ファイル互換**: `~/.modbus_sim/settings.json` のキー（`tcp` / `rtu` / `tcp_slaves` / `rtu_slaves` / `*_selected_slave_id` / 旧 `slaves`）はそのまま踏襲し、既存ユーザー設定を引き継ぐ。

## 9. 作業量の目安（粗い見積り）

| フェーズ | 目安 |
|---|---|
| B1: settings_store リファクタ | 0.5 日 |
| B2: API サーバ層 + WebSocket | 2〜3 日 |
| フロント: React 4タブ + グリッド + ダイアログ | 4〜6 日 |
| Tauri シェル + sidecar 統合 | 1〜2 日 |
| PyInstaller / tauri build / CI | 1 日 |
| テスト移行（API テスト + vitest） | 1〜2 日 |
| 旧 UI 削除・ドキュメント整理 | 0.5 日 |
| **合計** | **およそ 2 週間** |

## 10. 次のアクション

1. この計画のうち **Tauri v2 / FastAPI / グリッド= TanStack** の3点を確定（別案があればここで差し替え）。
2. `feature/tauri-ui` ブランチを作成。
3. Step 1（`settings_store.py` の UI 依存除去）から着手。

## 11. 進捗ログ

### 2026-08-28 〜 29（1回目）

完了:
- **float64 型の追加**（`config.py` / `datastore.py` / `ui/slave_panel.py`）。
  IEEE754 倍精度・4 レジスタ・ビッグエンディアン。encode/decode/同期/バリデーション/
  自動変化/永続化すべて対応。既存 193 テスト緑（float64 の往復・アドレス上限は手動確認済み）。
- **`modbus_sim/settings_model.py`**: `CommSettings` ⇔ dict の UI 非依存変換（`ui/settings_panel.py` の
  `to_dict` / `apply_settings` 相当）+ `comm_to_tcp_config` / `comm_to_rtu_config`。
- **`modbus_sim/registry_ops.py`**: 範囲追加 / CSV・TSV 取込 / 複製 / 空きアドレス探索を
  `ui/slave_panel.py` から抽出した純粋関数群。
- **`modbus_sim/api/`**（FastAPI + WebSocket）:
  - `state.py` … `AppState`（レジストリ / `ModbusServerManager` / `CommSettings` / 設定保存デバウンス / dirty フラグ / スナップショット生成）
  - `hub.py` … WebSocket 接続管理・ブロードキャスト
  - `server.py` … REST 全エンドポイント（health / state / settings / bind-addresses / serial-ports /
    slaves CRUD / points CRUD / range / import / duplicate / server start-stop / log clear）+ `/ws` +
    0.4 秒周期のバックグラウンド poller（`tick_auto_values` / `sync_from_server` / 差分ブロードキャスト）
  - `__init__.py` … `create_app` を公開
- **`modbus_sim/__main__.py`**: サイドカー起動エントリ。`--host` / `--port`（0 で OS 採番）、
  待受ポートを stdout へ 1 行 JSON 出力、フロント `dist` があれば `/` で配信。
- **`tests/test_api.py`**（8 ケース、緑）: 旧 UI テストの代替。health/state、slave 追加削除、
  point upsert（raw / decoded / float64）、範囲追加＆削除、CSV 取込、詳細設定バリデーション、
  TCP サーバ起動停止。
- 依存追加: `fastapi` / `uvicorn`（`requirements.txt` / `pyproject.toml`）、test extras に `httpx`。
- 手動確認: `python -m modbus_sim --port 0` でサイドカーが起動し `/api/health`・`/api/state` 応答。

未着手（次回以降）:
- フロントエンド `frontend/`（React + TS + Vite、4タブ + グリッド + ダイアログ、decode/encode の TS 移植 + vitest）
- Tauri シェル `src-tauri/`（v2、サイドカー spawn/kill、ポート注入、health 待ち）
- Tauri CLI 導入、`modbus-sim.spec` をバックエンド用に書き換え、`cargo tauri build`
- 旧 `modbus_sim/ui/` / `fonts_util.py` / `xcb_util.py` / PySide6 依存の削除、`main.py` 置換
- `settings_store.py` の `from modbus_sim.ui.settings_panel import SettingsPanel` 除去（UI 削除と同時）
- `test_settings_robustness.py` / `test_register_advanced_settings.py` 等の UI 依存部分を API テストへ移植
- `CLAUDE.md` / `README.md` 更新

既知の無関係な失敗（この作業前から）:
- `test_server_manager_robustness.py::test_tcp_running_state_recovers_after_bind_failure`（Windows の二重 bind 挙動）
- `test_xcb_util.py::test_ensure_xcb_libs_makes_libs_available`（WSL 専用、Windows では常に失敗。`xcb_util` は削除予定）

### 2026-08-29（2回目）— PySide6 削除

完了:
- **`modbus_sim/ui/` を全削除**（`app.py` / `slave_panel.py` / `settings_panel.py` / `log_panel.py` /
  `async_runner.py` / `common.py`）。`fonts_util.py` / `xcb_util.py` も削除。
- `settings_store.py`: `SettingsPanel` import と panel 結合メソッド（`save` / `apply` / `apply_from_path`）を除去。
  JSON の `load` / `write_payload` のみの薄いラッパに。
- `main.py`: `modbus_sim.__main__:main`（バックエンド起動）へ差し替え。
- `pyproject.toml` / `requirements.txt`: `PySide6` 依存を削除。`[project.scripts]` を `modbus_sim.__main__:main` に。
- `modbus-sim.spec`: バックエンドサイドカー用に書き換え（`main.py` エントリ、uvicorn の hidden import、
  `PySide6` を excludes、`console=True`、生成物名 `modbus-sim-backend`）。
- テスト移植:
  - 削除: `test_ui_smoke.py` / `test_xcb_util.py` / `test_register_kind_ui.py`（純粋 UI）
  - `test_comm_log.py`: `LogPanel` 部分を除去、`packet_log` / サーバ連携テストのみ残す
  - `test_strict.py`: `TestTcpPortPolicy` を `settings_model.comm_to_tcp_config` ベースへ、
    `TestRtuDefaults` を `RtuConfig()` の既定値チェックへ
  - `test_settings_robustness.py`: `SettingsPanel` → `settings_model.apply_dict_to_comm` / `SettingsStore.load`
  - `test_bulk_register_operations.py`: `SlavePanel` → `registry_ops`（複製 / 範囲追加 / CSV取込）のユニットテスト
  - `test_delete_operations.py`: UI クラスを除去、datastore レベルの `remove_point` / `remove_slave` のみ
  - `test_register_advanced_settings.py`: fault/delay/no-response/tick は維持、`RegisterAdvancedDialog` /
    グリッド編集テストを API（`TestClient`）ベースの `TestAdvancedViaApi` へ（部分編集で詳細設定が保持されることも検証）
- `CLAUDE.md` 全面改訂、`README.md` に移行中バナー追加。
- 結果: `python -m pytest tests/` → 163 passed / 6 skipped / 1 deselected（既知の Windows bind 失敗のみ）。
  `grep -rn "PySide6|modbus_sim.ui"` は 0 件。`python main.py --help` OK。

### 2026-08-29（3回目）— バックエンド exe + フロントエンド実装

完了:
- **バックエンド exe**: `pyinstaller modbus-sim.spec` → `dist/modbus-sim-backend.exe`（約 40MB, onefile）。
  起動・`/api/health`・`/api/state`・pydantic ボディ・float64 upsert・TCP サーバ起動停止を実機で確認。
- **`frontend/`（React 18 + TypeScript + Vite）実装**:
  - `src/datatype.ts` … Python の decode/encode 移植（`formatDecodedDisplay` / `parseDecodedInput` /
    `parseRawInput` / `validateAddress` / `datatypeBounds`）。`src/datatype.test.ts`（vitest 17 ケース緑、
    float64 IEEE754 も Python と一致）。
  - `src/api.ts` … REST クライアント（同一オリジン相対 `/api`）。`src/store.ts` … zustand + 再接続付き WebSocket。
  - `src/App.tsx` + `Header` + タブ3種:
    - `SettingsTab` … TCP/RTU フォーム、bind-addresses / serial-ports 再検出、サマリ、エクスポート/インポート
    - `SlaveTab`（mode prop）… Slave ID リスト（検索・activity ドット・追加・削除・機器名）、
      Kind タブ、レジスタグリッド（`RegisterGrid`）、`RangeAddDialog`、CSV/TSV 取込、`AdvancedDialog`
    - `LogTab` … mode フィルタ・検索・自動スクロール・一時停止・保存・クリア・行色分け
  - `vite.config.ts` … dev は `/api` `/ws` を `127.0.0.1:8000` へプロキシ。本番は同一オリジン。
  - `npm run build` → `frontend/dist`。`modbus_sim/__main__.py` が存在すれば `/` で配信。
- **ブラウザ実機確認**（`python -m modbus_sim --port 8130` に対して）: 4タブ描画、レジスタ追加、
  レジスタ削除、Slave 削除、設定の永続化、WebSocket 初期同期。すべて動作。
- **不具合修正**: `window.confirm()` は WebView をフリーズさせるため、`store.askConfirm()` +
  `<Modal>` のカスタム確認ダイアログへ置換（`RegisterGrid` / `SlaveTab` の削除確認）。
- `frontend/.gitignore` 追加（`node_modules` / `dist`）。`CLAUDE.md` に frontend の手順とアーキ追記。
- Python テスト: 163 passed（既知の Windows bind 失敗のみ deselect）。

### 2026-08-29（4回目）— Tauri シェル実装（ビルドは CI 待ち）

完了:
- ルート `package.json` + `@tauri-apps/cli` 2.11、`npx tauri init` で `src-tauri/` を生成。
- **`src-tauri/` を実装**:
  - `tauri.conf.json` … v2、`productName` "Modbus Simulator"、`identifier` `jp.rtrdevelop.modbussim`、
    `externalBin: ["binaries/modbus-sim-backend"]`、`bundle.targets: ["nsis"]`、`app.windows: []`
    （ウィンドウは Rust 側で動的生成）。`frontendDist: ../frontend/dist`。
  - `Cargo.toml` … `tauri` 2 / `tauri-plugin-shell` 2 / `tauri-plugin-log` 2。
  - `src/lib.rs` … 起動時に空きポート確保 → サイドカー（`modbus-sim-backend`）を `--host 127.0.0.1
    --port <n>` で spawn → stdout/stderr をログへ → 待受開始を TCP connect でポーリング（最長30秒）→
    `WebviewWindowBuilder` で `http://127.0.0.1:<n>/` を開く（980×680, min 800×560）。
    `RunEvent::ExitRequested` でサイドカーを `child.kill()`。
  - `capabilities/default.json` … `shell:allow-execute` をサイドカーにスコープ付与。
- **バックエンド exe に frontend/dist を同梱**（`modbus-sim.spec` の `datas`）→ サイドカー単体で
  `/`（SPA）と `/api` を同一オリジン配信。再ビルドして実機で確認済み。
- `scripts/build-backend.py` … PyInstaller ビルド → `src-tauri/binaries/modbus-sim-backend-<triple>.exe` へ配置。
- `.github/workflows/build-desktop.yml` … `windows-latest` で frontend → backend(PyInstaller) → `tauri build`
  → NSIS インストーラを artifact 出力。

ブロッカー（このマシン固有）:
- **Windows Smart App Control が有効（enforced）**。`cargo build` が多数の未署名ビルドスクリプト
  （`serde_core` / `icu_*` など）を実行できず `os error 4551`（アプリケーション制御ポリシーで
  ブロック）で失敗する。`CARGO_TARGET_DIR` を変えても回避不可。
  → ローカルで `tauri build` するには **Smart App Control を OFF**（Windows セキュリティ →
  アプリとブラウザー制御。再有効化には Windows リセットが必要）にするか、上記 **GitHub Actions**
  もしくは SAC 無効な別 Windows でビルドする。
- Python バックエンド exe（`pyinstaller modbus-sim.spec`）は SAC 下でも問題なくビルド・実行できる
  （ブートローダが署名済みのため）。

暫定対応: エクスポート/インポートのファイル指定はパス直接入力（将来 Tauri のダイアログに置換）。

### 2026-08-29（6回目）— レビュー修正 + シミュレータ強化 4 点

レビュー指摘の修正:
- グリッドが poller tick ごとに行を再マウントし編集内容が消える問題 →
  key を addr で安定化、フォーカス中は上書きしない EditableCell に。
- 通信設定タブも同種の上書き → 初回のみ hydrate + デバウンス保存。
- int 型に非整数 JSON 数値を渡すと黙って切り捨て → 400。
- poller が AppState の非公開属性を直接操作 → build_tick / clear_log へ集約。
  tick の *_points は選択中スレーブ分のみ送信。

機能強化（`doc/評価` の 1〜4）:
1. **ワード/バイト順**（ABCD/CDAB/BADC/DCBA）をスレーブ単位で。int32/float32/
   float64 の encode/decode/Decoded/入力に反映。`modbus_sim/wordorder.py`。
2. **グリッド仮想化**（`@tanstack/react-virtual`）。2000 点でも DOM 行 ~30。
3. **FC 43（機器識別）**: `DeviceIdentity` を identity としてサーバへ。
   **FC 8（診断）** は pymodbus 標準応答。`GET/PUT /api/identity`。
4. **パケットレベル異常注入**（CRC/長さ破壊・フレーム切断・破棄）をスレーブ単位・
   発生率付きで。`packet_log.corrupt_frame` + `server_manager` の TX フック。

テスト: backend 207 passed（wordorder 20 / identity 10 / frame_fault 15 追加）、
frontend vitest 22、build OK。settings.json のキー増分: スレーブごとに
`word_order` / `frame_fault` / `frame_fault_rate`、トップレベルに `identity`。

### 2026-08-29（5回目）— CI ビルド成功 + 不具合修正

- CI（`v0.1.1`）でインストーラ生成成功。`release/bundle/nsis/Modbus Simulator_0.1.0_x64-setup.exe`。
  ※ 1回目 `v0.1.0` は `pip install -e .` が `frontend/` を top-level パッケージと誤検出して失敗
  → `pyproject.toml` に `[tool.setuptools.packages.find] include=["modbus_sim*"]` を追加。
- **不具合修正**（ユーザー報告）:
  - float32 に有限で大きすぎる値（例 1e40）を入れると `struct.pack(">f")` が OverflowError →
    未処理の 500。`validate_datatype_value()` を追加し API/範囲追加/取込で 400 として弾く
    （inf/nan はビットパターンとして格納可なので許可）。
  - int32/float32（2レジスタ）・float64（4レジスタ）の**継続アドレスに別の点を置ける**問題。
    `registry_ops.find_overlap()` / `occupied_addresses()` を追加し、
    upsert（datatype 変更含む）・範囲追加・CSV取込・`next_free_address`（複製）で重複を禁止。
    別 kind の同一 addr は従来どおり独立。フロントの追加行にも即時チェックを実装。
- テスト: 168 passed（+5）。frontend vitest 17 / build OK。
- float 変換自体は総点検済み（float32/float64 の memory ワード・decoded hex・往復・
  負数・inf・nan すべて Python/TS 一致）。
