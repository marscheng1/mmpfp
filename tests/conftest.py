"""测试环境的临时目录适配。

`pytest` 默认把 `tmp_path` 建在系统 TEMP 下的随机子目录。本项目的开发环境用
文件沙箱运行测试，系统 TEMP 只有读权限，`tmp_path` fixture 会在 `iterdir` /
`rmtree` 阶段抛 `PermissionError`。这里把 `tmp_path` / `tmp_path_factory` 固定到
工作区内的 `.pytest-run/`，让测试无论在沙箱内还是普通环境都可运行。
"""
from __future__ import annotations

import itertools
import shutil
from pathlib import Path

import pytest

#: 刻意避开 `.pytest_tmp`：pytest 的 `--basetemp` 曾在它上面留下不可枚举的残留。
_BASE = Path(__file__).resolve().parents[1] / ".pytest-run"
_counter = itertools.count()


@pytest.fixture()
def tmp_path() -> Path:
    _BASE.mkdir(parents=True, exist_ok=True)
    path = _BASE / f"t{next(_counter)}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path
