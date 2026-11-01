#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收工具：把当前主题应用到样例文件，与参考补丁做资源级比对。

用法::

    python tools/verify_parity.py                      # 用 assets/ 下的 25.01 样例
    python tools/verify_parity.py --orig DIR --ref DIR # 指定别的版本

退出码：0 = 仅存在已知缺陷差异；1 = 出现额外差异；2 = 环境不全。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from restuner import patcher, verify  # noqa: E402
from restuner.icon import parse_group  # noqa: E402
from restuner.pe import PEImage  # noqa: E402
from restuner.rsrc import parse_resources  # noqa: E402
from restuner.theme import Theme  # noqa: E402

TARGETS = ("7z.dll", "7zFM.exe")

#: 已知且**有意保留**的差异（详见 docs/7z2501-补丁分析.md）
KNOWN = {
    "7zFM.exe": {
        "changed": {(16, 1, 1033), (14, 100, 1033)},
        "missing": set(),
        "extra": set(),
    },
    "7z.dll": {
        "changed": {(16, 1, 1033), (14, 4, 1033)},
        "missing": {(3, 11, 1033), (3, 12, 1033)},
        "extra": set(),
    },
}


def describe(diff, name: str) -> bool:
    known = KNOWN[name]
    ok = True
    for label, actual, expected in (
        ("缺失", set(diff.missing), known["missing"]),
        ("多出", set(diff.extra), known["extra"]),
        ("内容不同", set(diff.changed), known["changed"]),
    ):
        unexpected = actual - expected
        missing_from_expected = expected - actual
        if unexpected:
            ok = False
            print("  ✗ %s（意外）：%s" % (label, ", ".join("%s/%s/%s" % k for k in sorted(unexpected, key=str))))
        if missing_from_expected:
            print("  ~ %s（预期内但实际没出现）：%s" % (label, ", ".join("%s/%s/%s" % k for k in sorted(missing_from_expected, key=str))))
        if actual and set(actual).issubset(expected):
            print("  ✓ %s：%d 项，全部属于已知缺陷" % (label, len(actual)))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="ResTuner 资源级验收")
    parser.add_argument("--orig", default=os.path.join(ROOT, "assets", "7z2501-x64"))
    default_ref = os.path.join(ROOT, "assets", "7z2501-x64-patch")
    if not os.path.isdir(default_ref):
        default_ref = os.path.abspath(
            os.path.join(ROOT, os.pardir, "patches", "7z2501-x64-patch")
        )
    parser.add_argument("--ref", default=default_ref)
    parser.add_argument("--theme", default=os.path.join(ROOT, "assets"))
    parser.add_argument("--save", default=None, help="把产出保存到该目录（便于人工试用）")
    args = parser.parse_args()

    for path in (args.orig, args.ref, args.theme):
        if not os.path.isdir(path):
            sys.stderr.write("目录不存在：%s\n" % path)
            return 2

    theme = Theme(args.theme)
    print("主题：%s" % theme.describe())
    overall = True

    for name in TARGETS:
        src = os.path.join(args.orig, name)
        ref = os.path.join(args.ref, name)
        if not (os.path.isfile(src) and os.path.isfile(ref)):
            sys.stderr.write("缺少样例：%s 或 %s\n" % (src, ref))
            return 2

        with open(src, "rb") as fh:
            data = fh.read()
        result = patcher.patch_file(name, data, theme)
        print("\n=== %s ===" % name)
        print("  模式：%s" % (result.edit.summary() if result.edit else "-"))
        print("  大小：%d → %d" % (len(data), len(result.data)))

        problems = verify.check_structure(result.data)
        print("  结构：%s" % ("OK" if not problems else "；".join(problems)))
        if problems:
            overall = False

        diff = verify.diff(verify.digest_of_bytes(open(ref, "rb").read()), verify.digest_of_bytes(result.data))
        if not describe(diff, name):
            overall = False
        if diff.equal:
            print("  ✓ 与参考补丁完全一致")

        if args.save:
            os.makedirs(args.save, exist_ok=True)
            with open(os.path.join(args.save, name), "wb") as fh:
                fh.write(result.data)
            print("  已保存：%s" % os.path.join(args.save, name))

    # 附加检查：参考补丁的两个已知缺陷确实存在，且我们没复刻
    print("\n=== 缺陷复核 ===")
    fm_ours = parse_group({r.key: r for r in parse_resources(PEImage(open(os.path.join(args.orig, "7zFM.exe"), "rb").read()))}[(14, 100, 1033)].data)[0]
    print("  原版 GROUP_ICON #100 尺寸：%dx%d（应为 110x63）" % (fm_ours["width"], fm_ours["height"]))
    ref_fm = parse_group({r.key: r for r in parse_resources(PEImage(open(os.path.join(args.ref, "7zFM.exe"), "rb").read()))}[(14, 100, 1033)].data)[0]
    print("  参考补丁改写成了：%dx%d ← 缺陷 ①（我们不复刻）" % (ref_fm["width"], ref_fm["height"]))

    print("\n%s" % ("全部通过：除三处已知缺陷外与参考补丁资源级等价" if overall else "存在额外差异，请检查"))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
