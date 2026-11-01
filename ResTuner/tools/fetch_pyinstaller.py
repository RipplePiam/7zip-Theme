"""把 PyInstaller 及其依赖下载并解包到本地目录（不经过 pip 的临时目录流程）。

仅供在没有 pip 权限的沙箱里准备打包环境使用；正常机器上直接
``pip install pyinstaller`` 即可，不需要这个脚本。

用法::

    python tools/fetch_pyinstaller.py --dest ..\\pylibs
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

MIRROR = "https://pypi.tuna.tsinghua.edu.cn"
PACKAGES = [
    # (包名, 允许的文件名后缀模式，按优先级)
    ("pyinstaller", ("win_amd64.whl", "py3-none-any.whl")),
    ("pyinstaller-hooks-contrib", ("py3-none-any.whl",)),
    ("altgraph", ("py3-none-any.whl",)),
    ("pefile", ("py3-none-any.whl",)),
    ("pywin32-ctypes", ("py3-none-any.whl",)),
    ("packaging", ("py3-none-any.whl",)),
    ("setuptools", ("py3-none-any.whl",)),
]
_VERSION = re.compile(r"-(\d+(?:\.\d+)*)(?:[-.]|$)")


def _version_of(filename: str):
    match = _VERSION.search(filename)
    if not match:
        return (0,)
    return tuple(int(x) for x in match.group(1).split("."))


def pick(package: str, suffixes) -> dict:
    url = "%s/pypi/%s/json" % (MIRROR, package)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = json.load(response)
    candidates = []
    for item in data.get("urls", []):
        name = item["filename"]
        if not name.endswith(".whl"):
            continue
        if any(name.endswith(suffix) for suffix in suffixes):
            candidates.append(item)
    if not candidates:
        raise SystemExit("下载失败：%s 没有匹配的 wheel" % package)
    candidates.sort(key=lambda item: _version_of(item["filename"]), reverse=True)
    return candidates[0]


def install(item: dict, destination: str) -> None:
    print("  %-46s %8.1f KB" % (item["filename"], item["size"] / 1024))
    with urllib.request.urlopen(item["url"], timeout=120) as response:
        blob = response.read()
    archive = zipfile.ZipFile(io.BytesIO(blob))
    archive.extractall(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()
    destination = os.path.abspath(args.dest)
    os.makedirs(destination, exist_ok=True)
    print("下载 PyInstaller 及其依赖 → %s" % destination)
    for package, suffixes in PACKAGES:
        item = pick(package, suffixes)
        install(item, destination)
    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
