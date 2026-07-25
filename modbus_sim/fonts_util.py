"""CJK フォントの自動用意（主に WSL / 最小 Linux）。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from modbus_sim.platform_util import is_linux


def _user_font_dir() -> Path:
    return Path.home() / ".local" / "share" / "fonts" / "noto-cjk"


def cjk_font_files_present() -> bool:
    font_dir = _user_font_dir()
    if font_dir.is_dir() and any(font_dir.glob("NotoSansCJK*.ttc")):
        return True
    system_roots = (
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    )
    for root in system_roots:
        if not root.is_dir():
            continue
        if any(root.rglob("NotoSansCJK*.ttc")) or any(root.rglob("*Noto*CJK*JP*")):
            return True
    return False


def ensure_cjk_fonts(*, quiet: bool = False) -> bool:
    """日本語フォントが無ければユーザー領域へ取得を試みる。成功なら True。"""
    if cjk_font_files_present():
        return True
    if not is_linux():
        return False
    if shutil.which("apt-get") is None or shutil.which("dpkg-deb") is None:
        return False

    target = _user_font_dir()
    target.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(
            "日本語フォントが見つからないため、ユーザー領域へ取得を試みます"
            "（sudo 不要、初回のみ）…",
            flush=True,
        )
    try:
        with tempfile.TemporaryDirectory(prefix="modbus-sim-fonts-") as tmp:
            tmp_path = Path(tmp)
            subprocess.run(
                ["apt-get", "download", "fonts-noto-cjk"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            )
            debs = list(tmp_path.glob("fonts-noto-cjk*.deb"))
            if not debs:
                return False
            extract_dir = tmp_path / "extract"
            subprocess.run(
                ["dpkg-deb", "-x", str(debs[0]), str(extract_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            src = extract_dir / "usr" / "share" / "fonts" / "opentype" / "noto"
            copied = 0
            for path in src.glob("NotoSansCJK-*.ttc"):
                shutil.copy2(path, target / path.name)
                copied += 1
            if copied == 0:
                return False
        subprocess.run(
            ["fc-cache", "-f", str(Path.home() / ".local" / "share" / "fonts")],
            check=False,
            capture_output=True,
        )
        if not quiet:
            print(f"フォントを配置しました: {target}", flush=True)
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        if not quiet:
            print(
                f"フォント自動取得に失敗しました ({exc})。"
                " 手動: sudo apt install -y fonts-noto-cjk",
                flush=True,
            )
        return False
