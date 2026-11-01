"""线程安全的日志总线：GUI 与 CLI 共用。

* 每条日志即刻回调给界面（跨线程由界面自己 ``queue`` 处理）
* 同时落盘到 ``logs/restuner_<时间戳>.log``
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Callable, List, Optional

LEVELS = {"debug": "·", "info": "·", "ok": "✓", "warn": "!", "error": "✗"}


class LogBus:
    def __init__(self, sink: Optional[Callable[[str, str], None]] = None, log_dir: Optional[str] = None) -> None:
        self._sink = sink
        self._lock = threading.Lock()
        self._lines: List[str] = []
        self._file = None
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
                name = "restuner_%s.log" % datetime.now().strftime("%Y%m%d-%H%M%S")
                self._file = open(os.path.join(log_dir, name), "w", encoding="utf-8")
            except OSError:
                self._file = None

    @property
    def lines(self) -> List[str]:
        with self._lock:
            return list(self._lines)

    def log(self, level: str, message: str) -> None:
        symbol = LEVELS.get(level, "·")
        text = "%s %s" % (symbol, message)
        with self._lock:
            self._lines.append(text)
            if self._file is not None:
                try:
                    self._file.write("[%s] %s\n" % (level.upper(), message))
                    self._file.flush()
                except OSError:
                    pass
        if self._sink is not None:
            try:
                self._sink(level, message)
            except Exception:  # noqa: BLE001 - 界面异常不能影响主流程
                pass

    def debug(self, message: str) -> None:
        self.log("debug", message)

    def info(self, message: str) -> None:
        self.log("info", message)

    def ok(self, message: str) -> None:
        self.log("ok", message)

    def warn(self, message: str) -> None:
        self.log("warn", message)

    def error(self, message: str) -> None:
        self.log("error", message)

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                finally:
                    self._file = None
