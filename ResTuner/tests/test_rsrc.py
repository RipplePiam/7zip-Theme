"""资源目录解析 / 重建测试。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

from restuner.pe import PEImage  # noqa: E402
from restuner.rsrc import (  # noqa: E402
    RT_BITMAP,
    RT_GROUP_ICON,
    RT_ICON,
    RT_STRING,
    RT_VERSION,
    build_rsrc,
    parse_resources,
    resource_map,
)


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class ParseTests(unittest.TestCase):
    def test_counts(self) -> None:
        fm = parse_resources(PEImage(_support.read_bytes("7zFM.exe")))
        dll = parse_resources(PEImage(_support.read_bytes("7z.dll")))
        self.assertEqual(len(fm), 88)
        self.assertEqual(len(dll), 85)

    def test_types(self) -> None:
        dll = parse_resources(PEImage(_support.read_bytes("7z.dll")))
        counts = {}
        for res in dll:
            counts[res.type] = counts.get(res.type, 0) + 1
        self.assertEqual(counts[RT_ICON], 56)
        self.assertEqual(counts[RT_GROUP_ICON], 27)
        self.assertEqual(counts[RT_STRING], 1)
        self.assertEqual(counts[RT_VERSION], 1)

    def test_named_group_icons(self) -> None:
        """7z.dll 的第一个图标组名字是字符串 "0"，其余 26 个是整数 ID。"""
        dll = parse_resources(PEImage(_support.read_bytes("7z.dll")))
        names = sorted(r.name for r in dll if r.type == RT_GROUP_ICON and isinstance(r.name, str))
        self.assertEqual(names, ["0"])
        ints = sorted(r.name for r in dll if r.type == RT_GROUP_ICON and isinstance(r.name, int))
        self.assertEqual(ints, list(range(1, 27)))

    def test_lang_is_1033(self) -> None:
        dll = parse_resources(PEImage(_support.read_bytes("7z.dll")))
        self.assertEqual({r.lang for r in dll}, {1033})


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class RebuildTests(unittest.TestCase):
    def _blob(self, name: str, directory: str = _support.ORIG_DIR):
        image = PEImage.from_path(os.path.join(directory, name))
        resources = parse_resources(image)
        section = image.section_by_name(".rsrc")
        return build_rsrc(resources, section.virtual_address), resources, section

    def test_roundtrip_payloads(self) -> None:
        """重建后再解析，资源必须逐字节还原。"""
        for name in _support.TARGETS:
            blob, resources, section = self._blob(name)
            image = PEImage.from_path(os.path.join(_support.ORIG_DIR, name))
            image.data[section.raw_ptr : section.raw_ptr + len(blob)] = blob
            image.set_u32(section.header_offset + 8, len(blob))
            image.set_dir(2, section.virtual_address, len(blob))
            again = resource_map(parse_resources(image))
            before = resource_map(resources)
            self.assertEqual(set(before), set(again))
            for key, res in before.items():
                self.assertEqual(res.data, again[key].data, "资源内容不一致：%r" % (key,))

    def test_deterministic(self) -> None:
        image = PEImage.from_path(os.path.join(_support.ORIG_DIR, "7z.dll"))
        resources = parse_resources(image)
        section = image.section_by_name(".rsrc")
        first = build_rsrc(resources, section.virtual_address)
        second = build_rsrc(list(reversed(resources)), section.virtual_address)
        self.assertEqual(first, second)

    def test_matches_reference_layout_for_7zfm(self) -> None:
        """7zFM.exe 的重建结果应与参考补丁的 .rsrc 完全一致（说明布局规则一致）。"""
        if not _support.have_reference():
            self.skipTest("找不到参考补丁")
        blob, _resources, _section = self._blob("7zFM.exe", _support.REF_DIR)
        image = PEImage.from_path(os.path.join(_support.REF_DIR, "7zFM.exe"))
        section = image.section_by_name(".rsrc")
        actual = bytes(image.data[section.raw_ptr : section.raw_ptr + section.virtual_size])
        self.assertEqual(len(blob), len(actual))
        self.assertEqual(blob, actual)

    def test_blob_smaller_than_msvc_layout(self) -> None:
        """我们的布局比 MSVC 原版更紧凑（参考补丁同样如此）。"""
        blob, _resources, section = self._blob("7zFM.exe")
        self.assertLess(len(blob), section.virtual_size)
        self.assertEqual(len(blob) % 4, 0)


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class EditTests(unittest.TestCase):
    def test_bitmaps_present(self) -> None:
        fm = parse_resources(PEImage(_support.read_bytes("7zFM.exe")))
        ids = sorted(r.name for r in fm if r.type == RT_BITMAP)
        expected = list(range(100, 107)) + list(range(150, 157)) + [190]
        self.assertEqual(ids, expected)


if __name__ == "__main__":
    unittest.main()
