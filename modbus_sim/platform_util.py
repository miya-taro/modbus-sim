"""OS / 実行環境ヘルパー。"""

from __future__ import annotations

import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_wsl() -> bool:
    if not is_linux():
        return False
    try:
        if Path("/mnt/wslg").exists():
            return True
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def privileged_tcp_ports_restricted() -> bool:
    """Linux/WSL では 1024 未満の bind に root が必要なため UI で制限する。

    ネイティブ Windows では 502 なども一般ユーザーで待受可能なので制限しない。
    """
    return is_linux()
