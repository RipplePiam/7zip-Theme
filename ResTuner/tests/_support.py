"""测试公共设施：路径、样例文件读取、临时目录。"""
from __future__ import annotations

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
for _p in (SRC, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TARGETS = ("7z.dll", "7zFM.exe")

ASSETS = os.path.join(ROOT, "assets")
ORIG_DIR = os.path.join(ASSETS, "7z2501-x64")

#: 参考补丁（验收基线）优先用子目录自带的 assets，其次复用父仓库的
#: ``patches/7z2501-x64-patch``——这两份二进制逐字节相同，没必要在仓库里存两遍。
#: 也可以用环境变量 ``RESTUNER_REF_DIR`` 指定别的位置。
REF_CANDIDATES = (
    os.path.join(ASSETS, "7z2501-x64-patch"),
    os.path.abspath(os.path.join(ROOT, os.pardir, "patches", "7z2501-x64-patch")),
)
TMP_ROOT = os.path.join(HERE, "_tmp")


def have_assets() -> bool:
    return all(os.path.isfile(os.path.join(ORIG_DIR, name)) for name in TARGETS)


def _resolve_ref_dir() -> str:
    override = os.environ.get("RESTUNER_REF_DIR")
    if override:
        return os.path.abspath(override)
    for candidate in REF_CANDIDATES:
        if all(os.path.isfile(os.path.join(candidate, name)) for name in TARGETS):
            return candidate
    return REF_CANDIDATES[0]


REF_DIR = _resolve_ref_dir()


def have_reference() -> bool:
    """能否找到参考补丁（验收/对齐测试需要它）。"""
    return all(os.path.isfile(os.path.join(REF_DIR, name)) for name in TARGETS)


def read_bytes(name: str, directory: str = ORIG_DIR) -> bytes:
    with open(os.path.join(directory, name), "rb") as fh:
        return fh.read()


def make_temp_dir(prefix: str = "case-") -> str:
    os.makedirs(TMP_ROOT, exist_ok=True)
    path = os.path.join(TMP_ROOT, prefix.rstrip("-") + "-%d" % len(os.listdir(TMP_ROOT)))
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path)
    return path


def cleanup_temp(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def copy_targets(destination: str, directory: str = ORIG_DIR) -> None:
    for name in TARGETS:
        shutil.copy2(os.path.join(directory, name), os.path.join(destination, name))
