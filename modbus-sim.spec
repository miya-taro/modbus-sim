# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Modbus TCP/RTU シミュレータ.

ビルドは実行対象と同じ OS 上で行うこと（PyInstaller はクロスビルド不可）。
Windows で .exe が欲しい場合は Windows 上で
    pyinstaller modbus-sim.spec
を実行する。詳細は README の「exe 化 (PyInstaller)」を参照。
"""

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onefile: 単一の実行ファイルにまとめる（起動時に一時ディレクトリへ自己展開するため
# onedir よりわずかに起動が遅いが、配布は 1 ファイルで済み扱いやすい）。
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ModbusSim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI アプリなのでコンソールは出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
