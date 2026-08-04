"""xcb ライブラリ検出・用意のテスト。"""

from __future__ import annotations

from modbus_sim.xcb_util import ensure_xcb_libs, user_xcb_lib_dir, xcb_libs_available


def test_ensure_xcb_libs_makes_libs_available() -> None:
    assert ensure_xcb_libs(quiet=True) is True
    assert xcb_libs_available() is True
    lib_dir = user_xcb_lib_dir()
    # システムに全部ある場合はローカル配置が空でもよいが、
    # 不足していた環境では配置済みのはず。
    assert lib_dir.is_dir() or xcb_libs_available()
