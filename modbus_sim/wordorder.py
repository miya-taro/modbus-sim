"""多レジスタ値のワード/バイト順（エンディアン）変換。

32bit 値のバイトを ABCD（A=MSB）とすると、実機でよく使われる並びは:
  ABCD  ビッグエンディアン（既定）
  CDAB  ワードスワップ（ビッグエンディアン・バイトスワップ）
  BADC  各ワード内でバイトスワップ
  DCBA  リトルエンディアン
64bit（float64）も同じ規則を 4 ワードへ一般化する。

内部表現（RegisterPoint.raw / メモリ配列）は常に「正規のビッグエンディアン
バイト列」を基準とし、ここでワイヤ上の並びへ相互変換する。4 つの並びはいずれも
自己反転（同じ変換を2回で元に戻る）なので、エンコード・デコードで同じ関数を使える。
"""

from __future__ import annotations

import struct
from enum import Enum

_FMT = {2: ">HH", 4: ">HHHH"}


class WordOrder(str, Enum):
    ABCD = "ABCD"
    CDAB = "CDAB"
    BADC = "BADC"
    DCBA = "DCBA"

    @property
    def label(self) -> str:
        return {
            "ABCD": "ABCD (ビッグエンディアン)",
            "CDAB": "CDAB (ワードスワップ)",
            "BADC": "BADC (バイトスワップ)",
            "DCBA": "DCBA (リトルエンディアン)",
        }[self.value]


def reorder(data: bytes, order: WordOrder) -> bytes:
    """正規 BE バイト列 <-> ワイヤ並び（自己反転）。"""
    if order == WordOrder.ABCD:
        return data
    if order == WordOrder.DCBA:
        return data[::-1]
    words = [data[i : i + 2] for i in range(0, len(data), 2)]
    if order == WordOrder.CDAB:
        return b"".join(reversed(words))
    # BADC
    return b"".join(w[::-1] for w in words)


def pack_words(canonical_be: bytes, order: WordOrder) -> list[int]:
    """正規 BE バイト列 -> 指定並びの 16bit ワード列。"""
    wire = reorder(canonical_be, order)
    return list(struct.unpack(_FMT[len(wire) // 2], wire))


def unpack_bytes(words: list[int], order: WordOrder) -> bytes:
    """指定並びの 16bit ワード列 -> 正規 BE バイト列。"""
    wire = struct.pack(_FMT[len(words)], *(w & 0xFFFF for w in words))
    return reorder(wire, order)
