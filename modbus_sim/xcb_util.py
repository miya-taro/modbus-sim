"""Qt xcb (X11) プラグイン用ライブラリの自動用意（主に WSL）。"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from modbus_sim.platform_util import is_linux

# PySide6 の xcb プラグインが参照しやすい依存
_XCB_LIBS = (
    "libxcb-cursor.so.0",
    "libxcb-icccm.so.4",
    "libxcb-keysyms.so.1",
    "libxcb-shape.so.0",
    "libxkbcommon-x11.so.0",
)
_APT_PACKAGES = (
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-keysyms1",
    "libxcb-shape0",
    "libxkbcommon-x11-0",
)


def user_xcb_lib_dir() -> Path:
    return Path.home() / ".local" / "lib" / "modbus-sim-xcb"


def _prepend_ld_library_path(directory: Path) -> None:
    current = os.environ.get("LD_LIBRARY_PATH", "")
    prefix = str(directory)
    parts = [p for p in current.split(":") if p]
    if prefix not in parts:
        os.environ["LD_LIBRARY_PATH"] = ":".join([prefix, *parts]) if parts else prefix


def _lib_loadable(name: str) -> bool:
    try:
        ctypes.CDLL(name)
        return True
    except OSError:
        pass
    local = user_xcb_lib_dir() / name
    if local.is_file() or local.is_symlink():
        try:
            ctypes.CDLL(str(local.resolve() if local.is_symlink() else local))
            return True
        except OSError:
            return False
    return False


def _preload_user_xcb_libs() -> None:
    """LD_LIBRARY_PATH 変更だけでは足りない環境向けに、ユーザー領域の .so を先読みする。"""
    lib_dir = user_xcb_lib_dir()
    if not lib_dir.is_dir():
        return
    for path in sorted(lib_dir.glob("*.so*")):
        if path.is_symlink() or path.suffixes == [".so"] or ".so." in path.name:
            try:
                ctypes.CDLL(str(path.resolve()))
            except OSError:
                continue


def xcb_libs_available() -> bool:
    if user_xcb_lib_dir().is_dir():
        _prepend_ld_library_path(user_xcb_lib_dir())
        _preload_user_xcb_libs()
    return all(_lib_loadable(name) for name in _XCB_LIBS)


def ensure_xcb_libs(*, quiet: bool = False) -> bool:
    """xcb 依存が無ければユーザー領域へ取得を試みる。成功なら True。"""
    lib_dir = user_xcb_lib_dir()
    if lib_dir.is_dir():
        _prepend_ld_library_path(lib_dir)
        _preload_user_xcb_libs()

    if xcb_libs_available():
        return True
    if not is_linux():
        return False
    if shutil.which("apt-get") is None or shutil.which("dpkg-deb") is None:
        return False

    lib_dir.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(
            "Qt xcb 用ライブラリが見つからないため、ユーザー領域へ取得を試みます"
            "（sudo 不要、初回のみ）…",
            flush=True,
        )
    try:
        with tempfile.TemporaryDirectory(prefix="modbus-sim-xcb-") as tmp:
            tmp_path = Path(tmp)
            subprocess.run(
                ["apt-get", "download", *_APT_PACKAGES],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            )
            extract_dir = tmp_path / "extract"
            for deb in tmp_path.glob("*.deb"):
                subprocess.run(
                    ["dpkg-deb", "-x", str(deb), str(extract_dir)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            copied = 0
            for so_path in extract_dir.rglob("*.so*"):
                if not so_path.is_file() and not so_path.is_symlink():
                    continue
                dest = lib_dir / so_path.name
                if dest.exists() or dest.is_symlink():
                    dest.unlink()
                if so_path.is_symlink():
                    dest.symlink_to(os.readlink(so_path))
                else:
                    shutil.copy2(so_path, dest)
                copied += 1
            if copied == 0:
                return False
        _prepend_ld_library_path(lib_dir)
        _preload_user_xcb_libs()
        ok = xcb_libs_available()
        if ok and not quiet:
            print(f"xcb ライブラリを配置しました: {lib_dir}", flush=True)
        return ok
    except (OSError, subprocess.CalledProcessError) as exc:
        if not quiet:
            print(
                f"xcb ライブラリ自動取得に失敗しました ({exc})。"
                " 手動: sudo apt install -y libxcb-cursor0 libxcb-icccm4 "
                "libxcb-keysyms1 libxcb-shape0 libxkbcommon-x11-0",
                flush=True,
            )
        return False
