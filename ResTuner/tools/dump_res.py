#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源树打印工具（调试 / 对照用）。

用法::

    python tools/dump_res.py assets/7z2501-x64/7z.dll
    python tools/dump_res.py assets/7z2501-x64/7zFM.exe --type 14
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from restuner.icon import parse_group  # noqa: E402
from restuner.pe import PEImage  # noqa: E402
from restuner.rsrc import RT_GROUP_ICON, RT_ICON, parse_resources  # noqa: E402
from restuner.target import read_version_info  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="打印 PE 资源树")
    parser.add_argument("path", help="PE 文件路径")
    parser.add_argument("--type", type=int, default=None, help="只显示某个资源类型（数字，如 14）")
    parser.add_argument("--limit", type=int, default=0, help="每个类型最多显示多少项（0=全部）")
    args = parser.parse_args()

    if not os.path.isfile(args.path):
        sys.stderr.write("文件不存在：%s\n" % args.path)
        return 2

    image = PEImage.from_path(args.path)
    print("PE              : %s" % ("PE32+ (x64)" if image.is_plus else "PE32"))
    print("文件大小        : %d 字节" % len(image.data))
    print("SizeOfImage     : 0x%X" % image.size_of_image)
    print("CheckSum        : 0x%08X" % image.checksum)
    print("节区            :")
    for section in image.sections:
        print(
            "  %-8s VA=0x%08X VSize=0x%08X Raw=0x%08X/0x%08X"
            % (section.name, section.virtual_address, section.virtual_size, section.raw_ptr, section.raw_size)
        )

    resources = parse_resources(image)
    print("\n资源总数        : %d" % len(resources))

    by_type = {}
    for res in resources:
        by_type.setdefault(res.type, []).append(res)

    for rtype in sorted(by_type, key=lambda v: (isinstance(v, str), str(v))):
        items = by_type[rtype]
        label = items[0].type_label()
        print("\n%s  （%d 项）" % (label, len(items)))
        shown = items if args.limit <= 0 else items[: args.limit]
        for res in shown:
            detail = ""
            if rtype == RT_GROUP_ICON:
                try:
                    entries = parse_group(res.data)
                    detail = " %d 项尺寸=[%s] ids=%s" % (
                        len(entries),
                        ",".join(str(e["width"]) for e in entries),
                        ",".join(str(e["icon_id"]) for e in entries),
                    )
                except Exception:  # noqa: BLE001
                    detail = " (无法解析)"
            elif rtype == RT_ICON:
                detail = " %d 字节" % len(res.data)
            if args.type is not None and rtype != args.type:
                break
            print("  %-12s lang=%-5d %6d 字节%s" % (res.name, res.lang, len(res.data), detail))
        if args.limit and len(items) > args.limit:
            print("  … 其余 %d 项省略" % (len(items) - args.limit))

    for res in resources:
        if rtype and res.type == 16:
            info = read_version_info(res.data)
            print("\n版本信息        : %s" % info.display)
            for key, value in info.strings.items():
                print("  %-18s %s" % (key + ":", value))
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
