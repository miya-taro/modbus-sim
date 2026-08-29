# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Modbus Simulator バックエンド（FastAPI サイドカー）。

UI は Tauri（Rust シェル + React フロント）へ移行済み。このバイナリは
FastAPI + WebSocket の API サーバで、Tauri がサイドカーとして起動する。

ビルドは実行対象と同じ OS 上で行うこと（PyInstaller はクロスビルド不可）。
    pyinstaller modbus-sim.spec
生成物: dist/modbus-sim-backend(.exe)

Tauri の externalBin 命名規約に合わせ、ビルド後に
    dist/modbus-sim-backend-<target-triple>[.exe]
へリネームして src-tauri/binaries/ へ配置する（scripts/build-backend を参照）。
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("modbus_sim")
    + [
        "anyio",
        "click",
        "h11",
        "websockets",
        "websockets.legacy",
    ]
)

import os

_datas = []
if os.path.isdir("frontend/dist"):
    _datas.append(("frontend/dist", "frontend_dist"))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt6", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="modbus-sim-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # サイドカーの stdout(ポート通知) / stderr を Tauri が読む
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
