"""图标 / 位图 / 主题测试。"""
from __future__ import annotations

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

from restuner import bmp as bmp_mod  # noqa: E402
from restuner import icon as icon_mod  # noqa: E402
from restuner.errors import ThemeError  # noqa: E402
from restuner.theme import ALIASES, TOOLBAR_SLOTS, Theme  # noqa: E402

FILETYPE = os.path.join(_support.ASSETS, "filetype")
TOOLBAR = os.path.join(_support.ASSETS, "toolbar")


class IcoTests(unittest.TestCase):
    def test_sizes_derived_from_data(self) -> None:
        path = os.path.join(FILETYPE, "7z.ico")
        images = icon_mod.parse_ico(path)
        self.assertEqual(len(images), 8)
        self.assertEqual([i.width for i in images], [256, 64, 48, 40, 32, 24, 20, 16])
        for img in images:
            self.assertEqual(img.width, img.height)

    def test_png_detection(self) -> None:
        images = icon_mod.parse_ico(os.path.join(FILETYPE, "7z.ico"))
        self.assertTrue(images[0].is_png, "256x256 应该是 PNG 压缩")
        self.assertFalse(images[-1].is_png, "16x16 应该是 DIB")

    def test_group_entries_match_images(self) -> None:
        images = icon_mod.parse_ico(os.path.join(FILETYPE, "zip.ico"))
        ids = list(range(500, 500 + len(images)))
        group = icon_mod.make_group(images, ids)
        entries = icon_mod.parse_group(group)
        self.assertEqual(len(entries), len(images))
        for entry, img, icon_id in zip(entries, images, ids):
            self.assertEqual(entry["width"], img.width)
            self.assertEqual(entry["height"], img.height)
            self.assertEqual(entry["bytes"], len(img.data))
            self.assertEqual(entry["icon_id"], icon_id)
            self.assertEqual(entry["planes"], 1)
            self.assertEqual(entry["bit_count"], img.bit_count)

    def test_256_encoded_as_zero(self) -> None:
        images = icon_mod.parse_ico(os.path.join(FILETYPE, "7z.ico"))[:1]
        group = icon_mod.make_group(images, [1])
        width_byte, height_byte = group[6], group[7]
        self.assertEqual((width_byte, height_byte), (0, 0), "256 尺寸必须写 0")

    def test_non_square_group_entry(self) -> None:
        """回归测试：非正方形图标不能把宽写进高（参考补丁的缺陷 ①）。"""
        payload = struct.pack("<IiiHHIIiiII", 40, 110, 63, 1, 8, 0, 0, 0, 0, 0, 0) + b"\0" * 64
        image = icon_mod.IconImage(width=110, height=63, bit_count=8, data=payload)
        group = icon_mod.make_group([image], [4])
        entry = icon_mod.parse_group(group)[0]
        self.assertEqual((entry["width"], entry["height"]), (110, 63))

    def test_bad_ico_rejected(self) -> None:
        with self.assertRaises(ThemeError):
            icon_mod.parse_ico(os.path.join(_support.ASSETS, "does-not-exist.ico"))


class BmpTests(unittest.TestCase):
    def test_strip_file_header(self) -> None:
        path = os.path.join(TOOLBAR, "48x36", "Add.bmp")
        bitmap = bmp_mod.load_bmp(path)
        self.assertEqual(bitmap.width, 48)
        self.assertEqual(bitmap.height, 36)
        self.assertEqual(bitmap.bit_count, 4)
        self.assertEqual(len(bitmap.data), os.path.getsize(path) - 14)
        self.assertEqual(len(bitmap.palette), 16 * 4)

    def test_evaluate_ok(self) -> None:
        bitmap = bmp_mod.load_bmp(os.path.join(TOOLBAR, "24x24", "Add.bmp"))
        target = bmp_mod.load_bmp(os.path.join(TOOLBAR, "24x24", "Copy.bmp"))
        blocking, _warnings = bmp_mod.evaluate(target.data, bitmap)
        self.assertIsNone(blocking)

    def test_wrong_size_blocks(self) -> None:
        small = bmp_mod.load_bmp(os.path.join(TOOLBAR, "24x24", "Add.bmp"))
        big = bmp_mod.load_bmp(os.path.join(TOOLBAR, "48x36", "Add.bmp"))
        blocking, _warnings = bmp_mod.evaluate(small.data, big)
        self.assertIsNotNone(blocking)
        self.assertIn("宽度", blocking or "")

    def test_non_bmp_rejected(self) -> None:
        with self.assertRaises(ThemeError):
            bmp_mod.load_bmp(os.path.join(_support.ASSETS, "filetype", "7z.ico"))


class ThemeTests(unittest.TestCase):
    def test_slots_cover_two_sizes(self) -> None:
        self.assertEqual(len(TOOLBAR_SLOTS), 14)
        self.assertEqual(sorted(TOOLBAR_SLOTS)[:2], [100, 101])
        self.assertEqual(TOOLBAR_SLOTS[100][0], "48x36")
        self.assertEqual(TOOLBAR_SLOTS[150][0], "24x24")

    def test_assets_exist_for_all_slots(self) -> None:
        theme = Theme(_support.ASSETS)
        for resource_id in TOOLBAR_SLOTS:
            self.assertIsNotNone(theme.bitmap_path(resource_id), "缺少位图素材 #%d" % resource_id)

    def test_alias_fallback(self) -> None:
        theme = Theme(_support.ASSETS)
        self.assertEqual(theme.ico_path("txz"), theme.ico_path("xz"))
        self.assertEqual(theme.ico_path("tzst"), theme.ico_path("zst"))
        self.assertIn("txz", ALIASES)

    def test_pick_ico_prefers_available(self) -> None:
        theme = Theme(_support.ASSETS)
        ext, path = theme.pick_ico(["txz", "xz"])
        # txz 通过别名命中 xz.ico，返回的规范名应取自素材文件名
        self.assertEqual(ext, "xz")
        self.assertTrue(path and path.endswith("xz.ico"))

    def test_missing_assets_raise(self) -> None:
        with self.assertRaises(ThemeError):
            Theme(os.path.join(_support.ASSETS, "no-such-theme"))


if __name__ == "__main__":
    unittest.main()
