"""打补丁引擎测试。"""
from __future__ import annotations

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

from restuner import patcher, verify  # noqa: E402
from restuner.errors import ResourceError  # noqa: E402
from restuner.icon import parse_group  # noqa: E402
from restuner.pe import PEImage  # noqa: E402
from restuner.rsrc import RT_ICON, parse_resources, resource_map  # noqa: E402
from restuner.theme import Theme  # noqa: E402


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class SevenZipFmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.theme = Theme(_support.ASSETS)
        cls.data = _support.read_bytes("7zFM.exe")
        cls.result = patcher.patch_fm(cls.data, cls.theme)

    def test_inplace_mode(self) -> None:
        """位图尺寸一致 -> 必须走原地覆盖，不得改动任何 PE 结构。"""
        self.assertEqual(self.result.edit.mode, "inplace")
        self.assertEqual(len(self.result.data), len(self.data))

    def test_same_section_headers(self) -> None:
        before = PEImage(self.data)
        after = PEImage(self.result.data)
        self.assertEqual(before.size_of_image, after.size_of_image)
        for a, b in zip(before.sections, after.sections):
            self.assertEqual((a.name, a.virtual_address, a.raw_ptr, a.raw_size, a.virtual_size),
                             (b.name, b.virtual_address, b.raw_ptr, b.raw_size, b.virtual_size))

    def test_fourteen_bitmaps_replaced(self) -> None:
        replaced = [k for k in self.result.changed]
        self.assertEqual(len(replaced), 14)
        self.assertTrue(all(k[0] == 2 for k in replaced))

    def test_structure_and_expected(self) -> None:
        self.assertEqual(verify.check_structure(self.result.data), [])
        original = parse_resources(PEImage(self.data))
        verify.verify_output(self.result.data, original, self.result.expected, self.result.changed)

    def test_other_resources_untouched(self) -> None:
        """RT_VERSION / RT_GROUP_ICON / RT_DIALOG 等必须逐字节保留。"""
        before = resource_map(parse_resources(PEImage(self.data)))
        after = resource_map(parse_resources(PEImage(self.result.data)))
        for key, res in before.items():
            if key in self.result.changed:
                continue
            self.assertEqual(res.data, after[key].data, "资源被意外修改：%r" % (key,))

    def test_checksum_written(self) -> None:
        self.assertNotEqual(PEImage(self.result.data).checksum, 0)


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class SevenZipDllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.theme = Theme(_support.ASSETS)
        cls.data = _support.read_bytes("7z.dll")
        cls.result = patcher.patch_dll(cls.data, cls.theme)

    def test_rebuild_mode(self) -> None:
        self.assertEqual(self.result.edit.mode, "rebuild")
        self.assertGreater(len(self.result.data), len(self.data))
        self.assertIn(".reloc", self.result.edit.sections_moved)

    def test_icon_set(self) -> None:
        resources = parse_resources(PEImage(self.result.data))
        icons = [r for r in resources if r.type == RT_ICON]
        groups = [r for r in resources if r.type == 14]
        self.assertEqual(len(icons), 216)
        self.assertEqual(len(groups), 27)
        self.assertEqual(sorted(int(r.name) for r in icons)[0], 57)
        self.assertEqual(sorted(int(r.name) for r in icons)[-1], 272)

    def test_group_four_has_no_stale_icons(self) -> None:
        """缺陷 ③：arj 组不得残留旧的 8bpp 图标。"""
        resources = resource_map(parse_resources(PEImage(self.result.data)))
        entries = parse_group(resources[(14, 4, 1033)].data)
        self.assertEqual(len(entries), 8)
        self.assertEqual([e["icon_id"] for e in entries], list(range(89, 97)))
        self.assertTrue(all(e["bit_count"] == 32 for e in entries))

    def test_group_zero_keeps_its_string_name(self) -> None:
        """原版第一个图标组的名字是字符串 "0"，替换后必须仍然是字符串 "0"。"""
        resources = resource_map(parse_resources(PEImage(self.result.data)))
        self.assertIn((14, "0", 1033), resources)
        self.assertNotIn((14, 0, 1033), resources)

    def test_all_executable_sections_untouched(self) -> None:
        before = PEImage(self.data)
        after = PEImage(self.result.data)
        for name in (".text", ".rdata", ".data", ".pdata"):
            a = before.section_by_name(name)
            b = after.section_by_name(name)
            self.assertEqual(a.virtual_address, b.virtual_address, name)
            self.assertEqual(bytes(before.data[a.raw_ptr : a.raw_end]),
                             bytes(after.data[b.raw_ptr : b.raw_end]), "%s 内容被改" % name)

    def test_structure_valid(self) -> None:
        self.assertEqual(verify.check_structure(self.result.data), [])
        original = parse_resources(PEImage(self.data))
        verify.verify_output(self.result.data, original, self.result.expected, self.result.changed)

    def test_data_directories_follow_reloc(self) -> None:
        image = PEImage(self.result.data)
        reloc = image.section_by_name(".reloc")
        self.assertEqual(image.get_dir(5)[0], reloc.virtual_address)
        self.assertEqual(image.get_dir(2)[0], image.section_by_name(".rsrc").virtual_address)

    def test_size_of_image_recomputed(self) -> None:
        image = PEImage(self.result.data)
        last = max(image.sections, key=lambda s: s.virtual_end)
        from restuner.pe import align_up

        self.assertEqual(image.size_of_image, align_up(last.virtual_end, 0x1000))


class EmptyThemeTests(unittest.TestCase):
    def test_no_material_is_noop(self) -> None:
        """素材缺失时必须整组跳过，绝不产出半成品。"""
        if not _support.have_assets():
            self.skipTest("缺少样例")
        directory = _support.make_temp_dir("theme-empty")
        try:
            os.makedirs(os.path.join(directory, "filetype"))
            os.makedirs(os.path.join(directory, "toolbar", "48x36"))
            os.makedirs(os.path.join(directory, "toolbar", "24x24"))
            theme = Theme(directory)
            for name in _support.TARGETS:
                result = patcher.patch_file(name, _support.read_bytes(name), theme)
                self.assertEqual(result.edit.mode, "noop", name)
                self.assertEqual(result.data, _support.read_bytes(name), "%s 不应被改动" % name)
                self.assertTrue(any("跳过" in c.detail or "未改动" in c.detail for c in result.changes))
        finally:
            _support.cleanup_temp(directory)


class DispatchTests(unittest.TestCase):
    def test_unsupported_file(self) -> None:
        with self.assertRaises(ResourceError):
            patcher.patch_file("7zG.exe", b"MZ", Theme(_support.ASSETS))


if __name__ == "__main__":
    unittest.main()
