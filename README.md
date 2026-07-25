# Modbus TCP/RTU シミュレータ

Modbus 通信の開発・テスト向けに、**複数スレーブ**を模擬できるツールです。

## 機能

- **スレーブ模擬**: Modbus TCP / RTU を**同時に**待受可能。外部マスタからの Read/Write に応答
- **独立起動**: 画面右上の TCP / RTU ボタンでそれぞれ個別に開始・停止
- **経路別スレーブ**: TCP 用と RTU 用のスレーブを**別タブ・別データ**で管理（同じ Slave ID でも中身は独立）
- **設定の永続化**: 通信設定・スレーブ設定を `~/.modbus_sim/settings.json` に自動保存し、次回起動時に復元
- **複数 Slave ID**: 各経路タブの左ペインで ID を切り替え、各スレーブに機器名（タグ）を付与可能
- **通信状態表示**: 各 Slave ID 横の色付き丸（緑=直近通信あり / 灰=待受中だが未通信 / 薄灰=停止中）
- **インライン編集**: Addr / Raw / Decoded / Datatype / Tag を表内で直接編集
- **Raw/Decoded 連動**: Raw 編集で Decoded が自動更新、Decoded 編集で Raw が自動更新
- **型指定**: uint16 / int16 / int32（2レジスタ）に対応
- **アドレス範囲**: UI では 0 〜 65535 を設定可能。通信サーバーは**設定済みアドレスのみ**を個別に構築するため、アドレスが高くても待受開始は即座です
- **通信設定**: TCP / RTU 両方の設定を常時表示。TCP IP はローカルアドレスから選択可能（IPv4/IPv6）
- **待受中編集**: TCP/RTU 待受中でもスレーブ値・機器名を編集可能
- **通信ログ**: RX/TX の生パケット（16進）を専用タブで表示。デコード失敗時は `INVALID` 行に内容を表示

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

GUI ウィンドウが開きます。閉じるとプロンプトに戻ります。

GUI は **PySide6 (Qt)** で構築されています。

### WSL でウィンドウが出ない場合

WSLg 利用時は次のパッケージを入れてから、もう一度起動してください。

```bash
sudo apt install -y libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxkbcommon-x11-0
export QT_QPA_PLATFORM=xcb
python main.py
```

それでも見えない場合は、Windows 側タスクバーの **python3** を確認してください（別仮想ディスプレイに出ることがあります）。

### 日本語が □□□ になる場合

WSL に日本語フォントが入っていないとラベルが四角になります。

```bash
sudo apt install -y fonts-noto-cjk
```

入れたあと `python main.py` を再起動してください。

## 画面構成

| タブ | 内容 |
|------|------|
| 通信設定 | TCP / RTU パラメータ入力、設定済み項目の確認 |
| TCP スレーブ | TCP 経路専用の Slave ID 一覧・設定値テーブル |
| RTU スレーブ | RTU（シリアル）経路専用の Slave ID 一覧・設定値テーブル |
| 通信ログ | RX/TX パケットの16進ダンプ |

画面右上に TCP / RTU それぞれの待受状態（●）と開始/停止ボタンがあります。

### スレーブタブのレイアウト

TCP / RTU とも同じレイアウトです（データは独立）。

- **左**: Slave ID 一覧（通信状態丸 + ID + 機器名タグ）、機器名編集、`+` で新規 Slave 追加
- **右**: 選択中スレーブの設定値グリッド

### Raw と Decoded の違い

| 列 | 意味 | 例（値=4660） |
|---|---|---|
| **Raw** | Modbus メモリの10進値（0〜65535） | `4660` |
| **Decoded** | 同じ値の16進表示 | `0x1234` |

どちらを編集しても内部の Raw 値に反映され、相手列が自動更新されます。Decoded は `0x1234` / `1234` のどちらでも入力できます（いずれも16進）。Datatype は `uint16` / `int16` / `int32` から選択します。

## デフォルト

- TCP / RTU それぞれに Slave ID `1` が最初から登録されています
- TCP/RTU の各パラメータは未入力のままでは「現在の設定」に表示されません

## 通信ログ出力例

```
[2026-07-07 22:00:01] TCP RX 00 01 00 00 00 06 01 03 00 00 00 0A
[2026-07-07 22:00:01] TCP TX 00 01 00 00 00 17 01 03 14 00 00 ...
[2026-07-07 22:00:02] RTU RX 01 03 00 00 00 0A C5 CD
[2026-07-07 22:00:03] TCP INVALID Unable to decode request: FF FF 00 01 00 00
```

## 設定ファイル

通信設定（TCP/RTU）とスレーブ設定（Slave ID・機器名・レジスタ表）は次のファイルに保存されます。

- Windows: `%USERPROFILE%\.modbus_sim\settings.json`
- Linux/macOS: `~/.modbus_sim/settings.json`

## 動作確認（TCP）

1. アプリ起動 → 「通信設定」で IP/Port を入力
2. 「TCP スレーブ」タブで設定値を表に追加
3. 右上「TCP 開始」で待受
4. 外部クライアントから Read/Write → 「通信ログ」タブでパケット確認、TCP スレーブ一覧の丸が緑に変化

RTU も同様に、「RTU スレーブ」で値を設定してから「RTU 開始」します。TCP と RTU は同時に待受でき、スレーブデータは互いに独立です。

### 自動テスト（厳密）

アドレス境界・全データ型・負数の16進往復・特権ポート拒否・代表 TCP ポート待受などをまとめて検証します。

```bash
pip install pytest pytest-asyncio
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
```

```python
import asyncio
from pymodbus.client import AsyncModbusTcpClient

async def main():
    client = AsyncModbusTcpClient("127.0.0.1", port=5020)
    await client.connect()
    result = await client.read_holding_registers(0, count=10, device_id=1)
    print("read:", result.registers)
    await client.write_register(0, 1234, device_id=1)
    client.close()

asyncio.run(main())
```

## int32 の扱い

HR で型を `int32` にすると、指定アドレスと次アドレスの2レジスタを big-endian 32bit 整数として解釈します。アドレスは 65534 以下である必要があります。

## プロジェクト構成

```
modbus_sim/
├── config.py
├── models.py
├── datastore.py
├── settings_store.py
├── logging_handler.py
├── server_manager.py
└── ui/
    ├── app.py
    ├── settings_panel.py
    ├── slave_panel.py
    └── log_panel.py
```
