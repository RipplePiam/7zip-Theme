"""工程内固定路径的解析（不依赖当前工作目录）。

同时兼容两种运行形态：
* 源码运行：资源在仓库的 ``assets/``，日志在仓库的 ``logs/``；
* PyInstaller 单文件 exe：资源被解包到 ``sys._MEIPASS``，日志写到 ``%LOCALAPPDATA%\\ResTuner\\logs``
  （那里是临时目录，不能用来存日志）。

注意：``logs_dir()`` **绝不抛异常**。日志目录不可写是很常见的情况（受限账户、被安全软件
拦截的 AppData、只读环境），不能因为它把整个操作流程打断。
"""
from __future__ import annotations

import os
import sys
from typing import Optional


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出来的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def project_root() -> str:
    """仓库根目录（``src/restuner/paths.py`` 往上三层）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_dir() -> str:
    """只读资源的根目录。"""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return project_root()


def assets_dir() -> str:
    return os.path.join(resource_dir(), "assets")


def data_dir() -> str:
    """可写数据目录（日志等）。"""
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ResTuner")
    return project_root()


def _first_writable(candidates) -> Optional[str]:
    """返回第一个真正可写的目录；全都不可写时返回 ``None``。"""
    for path in candidates:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".restuner-write-test")
            with open(probe, "wb") as fh:
                fh.write(b"x")
            os.remove(probe)
            return path
        except OSError:
            continue
    return None


def logs_dir() -> Optional[str]:
    """日志目录；一处都写不了就返回 ``None``（调用方静默跳过落盘）。"""
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        temp = os.environ.get("TEMP") or os.environ.get("TMP")
        candidates = [
            os.path.join(local, "ResTuner", "logs"),
            os.path.join(temp, "ResTuner", "logs") if temp else "",
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "logs"),
        ]
    else:
        candidates = [os.path.join(project_root(), "logs")]
    return _first_writable(candidates)


def backup_dir(install_dir: str) -> str:
    from .backup import backup_root

    return backup_root(install_dir)
