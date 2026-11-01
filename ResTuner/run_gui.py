#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ResTuner 启动器（双击 or `py -3 run_gui.py`）。

把 ``src`` 加进 sys.path，因此不依赖当前工作目录、也不需要 pip install。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def main() -> int:
    if sys.version_info < (3, 9):
        sys.stderr.write("需要 Python 3.9 或更高版本，当前为 %s\n" % sys.version.split()[0])
        return 2
    from restuner.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
