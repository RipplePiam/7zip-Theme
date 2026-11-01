"""PE 解析层测试。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

from restuner.checksum import compute_checksum  # noqa: E402
from restuner.errors import PEError  # noqa: E402
from restuner.pe import PEImage, align_up  # noqa: E402


class AlignTests(unittest.TestCase):
    def test_align_up(self) -> None:
        self.assertEqual(align_up(0, 0x200), 0)
        self.assertEqual(align_up(1, 0x200), 0x200)
        self.assertEqual(align_up(0x200, 0x200), 0x200)
        self.assertEqual(align_up(0x201, 0x200), 0x400)


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class ParseTests(unittest.TestCase):
    def test_headers(self) -> None:
        image = PEImage.from_path(os.path.join(_support.ORIG_DIR, "7z.dll"))
        self.assertTrue(image.is_plus)
        self.assertEqual(image.magic, 0x20B)
        self.assertEqual(image.number_of_sections, 6)
        self.assertEqual(image.section_alignment, 0x1000)
        self.assertEqual(image.file_alignment, 0x200)
        self.assertEqual([s.name for s in image.sections],
                         [".text", ".rdata", ".data", ".pdata", ".rsrc", ".reloc"])

    def test_sanity_clean(self) -> None:
        for name in _support.TARGETS:
            image = PEImage.from_path(os.path.join(_support.ORIG_DIR, name))
            self.assertEqual(image.sanity_check(), [], "%s 结构不一致" % name)

    def test_rva_roundtrip(self) -> None:
        image = PEImage.from_path(os.path.join(_support.ORIG_DIR, "7z.dll"))
        for section in image.sections:
            if not section.raw_size:
                continue
            rva = section.virtual_address
            offset = image.rva_to_offset(rva)
            self.assertIsNotNone(offset)
            self.assertEqual(offset, section.raw_ptr)
            self.assertEqual(image.offset_to_rva(offset), rva)

    def test_resource_dir_points_at_rsrc(self) -> None:
        image = PEImage.from_path(os.path.join(_support.ORIG_DIR, "7z.dll"))
        rsrc = image.section_by_name(".rsrc")
        self.assertEqual(image.get_dir(2)[0], rsrc.virtual_address)

    def test_reject_non_pe(self) -> None:
        with self.assertRaises(PEError):
            PEImage(b"MZ" + b"\0" * 200)

    def test_reject_tiny(self) -> None:
        with self.assertRaises(PEError):
            PEImage(b"ab")


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class ChecksumTests(unittest.TestCase):
    def test_matches_reference_patch(self) -> None:
        """校验和算法必须能复现参考补丁里记录的 CheckSum。"""
        if not _support.have_reference():
            self.skipTest("找不到参考补丁")
        for name in _support.TARGETS:
            image = PEImage.from_path(os.path.join(_support.REF_DIR, name))
            self.assertNotEqual(image.checksum, 0, "%s 的参考补丁应有校验和" % name)
            calc = compute_checksum(bytes(image.data), image.checksum_offset)
            self.assertEqual(calc, image.checksum, "%s 校验和算法不一致" % name)

    def test_original_has_no_checksum(self) -> None:
        image = PEImage.from_path(os.path.join(_support.ORIG_DIR, "7z.dll"))
        self.assertEqual(image.checksum, 0)


if __name__ == "__main__":
    unittest.main()
