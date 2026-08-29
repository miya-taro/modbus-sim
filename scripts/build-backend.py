"""バックエンド exe を PyInstaller でビルドし、Tauri のサイドカー命名規約に
合わせて src-tauri/binaries/ へ配置する。

    python scripts/build-backend.py

- frontend/dist が無ければ先に `npm --prefix frontend run build` を実行すること
  （modbus-sim.spec が frontend/dist を同梱する）。
- PyInstaller はクロスコンパイル不可。ターゲット OS 上で実行する。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def target_triple() -> str:
    out = subprocess.run(
        ["rustc", "-vV"], capture_output=True, text=True, check=True
    ).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("rustc -vV から host triple を取得できませんでした")


def main() -> int:
    triple = target_triple()
    ext = ".exe" if sys.platform.startswith("win") else ""

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "modbus-sim.spec", "--noconfirm"],
        cwd=ROOT,
        check=True,
    )

    src = ROOT / "dist" / f"modbus-sim-backend{ext}"
    dst_dir = ROOT / "src-tauri" / "binaries"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"modbus-sim-backend-{triple}{ext}"
    shutil.copy2(src, dst)
    print(f"OK: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
