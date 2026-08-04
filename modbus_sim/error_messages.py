"""サーバ起動時の例外を分かりやすい日本語メッセージへ変換する。"""

from __future__ import annotations

import errno

_WINERROR_ADDRESS_IN_USE = 10048
_WINERROR_ACCESS_DENIED = 10013


def friendly_server_error(exc: Exception) -> str:
    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        if exc.errno == errno.EADDRINUSE or winerror == _WINERROR_ADDRESS_IN_USE:
            return (
                "ポート/アドレスが既に使用されています。"
                "別のポート番号を指定するか、使用中のプロセスを終了してください。"
                f"（詳細: {exc}）"
            )
        if exc.errno == errno.EACCES or winerror == _WINERROR_ACCESS_DENIED:
            return (
                "権限がありません。1024未満のポートは root/管理者権限が必要です。"
                f"（詳細: {exc}）"
            )
        if exc.errno in (errno.ENOENT, errno.ENODEV):
            return (
                "指定したシリアルポートが見つかりません。設定画面でポートを"
                f"選び直してください。（詳細: {exc}）"
            )
    try:
        from serial import SerialException

        if isinstance(exc, SerialException):
            return f"シリアルポートを開けませんでした。他のアプリが使用中の可能性があります。（詳細: {exc}）"
    except ImportError:
        pass
    return str(exc)
