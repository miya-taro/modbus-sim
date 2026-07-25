# Modbus TCP/RTU シミュレータ

Modbus 通信の開発・テスト向けに、**TCP / RTU スレーブを同時に模擬**できる GUI ツールです。

## 機能

- **TCP / RTU 同時待受**: 右上のボタンでそれぞれ独立に開始・停止
- **経路別スレーブ**: 「TCP スレーブ」「RTU スレーブ」タブでデータを完全分離（同じ Slave ID でも中身は独立）
- **複数 Slave ID**: 1〜247。機器名（タグ）付き。通信状態丸（緑=直近通信 / 灰=待受中未通信 / 薄灰=停止中）
- **レジスタ編集**: Addr / Raw / Decoded / Datatype / Tag を表内で編集。Datatype は `uint16` / `int16` / `int32` のリスト選択
- **Raw / Decoded 連動**: Raw は10進、Decoded は16進（`0x` あり・なし両方可）。負数も16進往復可能
- **アドレス**: 0〜65535（`int32` は 0〜65534）。設定済みアドレスのみサーバ側に構築するため、高アドレスでも起動は高速
- **通信設定**: TCP（IPv4/IPv6）と RTU（ポート・ボーレート・パリティ・Data bits・Stop bits）を常時表示。待受中は該当側のみロック
- **通信ログ**: device / FC / アドレス / 値の要約 + 生パケット（16進）。不正 TCP は `INVALID` 行
- **設定の永続化**: `~/.modbus_sim/settings.json`（Windows は `%USERPROFILE%\.modbus_sim\settings.json`）

## 必要環境

- Python 3.10 以上
- OS: Windows / Linux / WSL2
- 依存: `pymodbus` / `PySide6` / `pyserial`（`requirements.txt` 参照）

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

GUI ウィンドウが開きます（ターミナルには起動メッセージのみ出ます）。閉じるとプロンプトに戻ります。

### Windows

- 通常はそのまま動作します
- TCP ポート **502** も利用可能です（一般ユーザーで bind 可）
- RTU は実 COM ポート（例: `COM3`）を選択してください。未検出時は空欄のままなので、手動入力か「ポート再検出」を使います

### WSL2

- 起動時に Qt は可能な範囲で **xcb** を優先します
- 日本語フォントが無い場合、ユーザー領域への取得を自動試行します（`sudo` 不要）
- ウィンドウが出ない・不安定な場合のみ:

```bash
sudo apt install -y libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxkbcommon-x11-0
export QT_QPA_PLATFORM=xcb
python main.py
```

- Linux/WSL では **1024 未満の TCP ポートは特権ポート**のため UI で拒否します（例: 502 → **5020** などを使用）
- WSLg でタイトルに `WARN: COPY MODE` が付くことがあります（表示経路の警告で、アプリ自体のエラーではありません）

## 画面構成

| タブ | 内容 |
|------|------|
| 通信設定 | TCP / RTU パラメータ、「現在の設定」サマリ |
| TCP スレーブ | TCP 専用の Slave 一覧とレジスタ表 |
| RTU スレーブ | RTU（シリアル）専用の Slave 一覧とレジスタ表 |
| 通信ログ | 要約 + 16進ダンプ、クリアボタン |

画面右上: TCP / RTU それぞれの状態（●）と開始/停止ボタン。

### スレーブタブ

- **左**: Slave ID 一覧（状態丸 + ID + 機器名）、機器名編集、`+` で追加
- **右**: 選択中スレーブの設定値グリッド

### Raw / Decoded / Datatype

| 列 | 意味 | 例 |
|---|---|---|
| **Raw** | メモリ上の10進 | `4660` / `-1`（int16/int32） |
| **Decoded** | 同じ値の16進表示 | `0x1234` / `0xFFFF`（-1 の int16） |
| **Datatype** | `uint16` / `int16` / `int32` | コンボで選択 |

- Decoded は `0x1234` でも `1234` でも可（どちらも16進）
- `int32` は指定アドレスと次アドレスの 2 レジスタ（big-endian）。Addr は **65534 以下**

## デフォルト

| 項目 | 初期値 |
|------|--------|
| TCP / RTU Slave ID | それぞれ `1` |
| RTU ボーレート | `9600` |
| RTU パリティ | `Even` |
| RTU Data bits | `8`（7 も選択可） |
| RTU Stop bits | `1`（2 も選択可） |
| TCP Port 例 | プレースホルダ `5020`（要入力） |

シリアルポートが OS 上で見つからない場合は **空欄**です（存在しない `COM1` 等は仮置きしません）。

## 使い方（TCP 動作確認）

1. 「通信設定」で IP（例: `127.0.0.1`）と Port（例: `5020`）を入力
2. 「TCP スレーブ」で Addr / 値を追加
3. 右上「TCP 開始」→「TCP 待受中」になること
4. 別ターミナルからクライアントで Read/Write
5. 「通信ログ」に RX/TX が出ること、Slave の丸が緑になること

```python
import asyncio
from pymodbus.client import AsyncModbusTcpClient

async def main():
    client = AsyncModbusTcpClient("127.0.0.1", port=5020)
    assert await client.connect()
    result = await client.read_holding_registers(0, count=1, device_id=1)
    print("read:", None if result.isError() else result.registers)
    await client.write_register(0, 1234, device_id=1)
    client.close()

asyncio.run(main())
```

### RTU

1. 「RTU スレーブ」で値を設定
2. 「通信設定」で実シリアルポートとフレーミングを確認（既定: 9600 Even 8 1）
3. 「RTU 開始」

TCP と同時待受可能。スレーブデータは互いに独立です。

## 通信ログ例

```
[2026-07-07 22:00:01] TCP RX device=1 FC=03 ReadHoldingRegisters addr=0 count=10 | 00 01 00 00 00 06 01 03 00 00 00 0A
[2026-07-07 22:00:01] TCP TX device=1 FC=03 ReadHoldingRegisters values=[0,0,...] | 00 01 00 00 00 17 01 03 14 ...
[2026-07-07 22:00:02] RTU RX device=1 FC=03 ReadHoldingRegisters addr=0 count=10 | 01 03 00 00 00 0A C5 CD
[2026-07-07 22:00:03] TCP INVALID Invalid Modbus protocol id: 65535: FF FF ...
```

## 設定ファイル

保存先:

- Windows: `%USERPROFILE%\.modbus_sim\settings.json`
- Linux / macOS / WSL: `~/.modbus_sim/settings.json`

主なキー: `tcp` / `rtu` / `tcp_slaves` / `rtu_slaves` / 各 `*_selected_slave_id`  
（旧形式の共通 `slaves` は TCP 側へ移行されます）

## テスト

```bash
pip install pytest pytest-asyncio
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
```

カバー例:

- アドレス境界・全データ型・負数の16進往復
- TCP 代表ポート待受、特権ポート制限（Linux）
- 通信ログ（要約 / INVALID / クリア）
- RTU（pymodbus nullmodem による仮想シリアル）

## プロジェクト構成

```
modbus-simulator/
├── main.py
├── requirements.txt
├── pyproject.toml
├── README.md
├── doc/
│   └── 要求仕様.md
├── tests/
│   ├── test_datatypes.py
│   ├── test_strict.py
│   ├── test_comm_log.py
│   ├── test_rtu.py
│   └── test_ui_smoke.py
└── modbus_sim/
    ├── config.py
    ├── models.py
    ├── network.py
    ├── datastore.py
    ├── settings_store.py
    ├── server_manager.py
    ├── logging_handler.py
    ├── packet_log.py
    ├── platform_util.py
    ├── fonts_util.py
    └── ui/
        ├── app.py
        ├── settings_panel.py
        ├── slave_panel.py
        ├── log_panel.py
        └── async_runner.py
```
