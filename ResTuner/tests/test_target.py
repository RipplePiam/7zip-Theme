"""体检 / 版本指纹测试。"""
from __future__ import annotations

import dataclasses
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

from restuner import target as target_mod  # noqa: E402
from restuner.theme import Theme  # noqa: E402


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class FingerprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.theme = Theme(_support.ASSETS)
        cls.info = target_mod.inspect(_support.ORIG_DIR, theme=cls.theme)

    def test_version_parsed(self) -> None:
        self.assertEqual(self.info.version.display, "25.01")
        self.assertEqual(self.info.version.product, "7-Zip")
        self.assertEqual(self.info.version.company, "Igor Pavlov")

    def test_official_matches_table(self) -> None:
        """官方 25.01 的实测结构必须与清单里记录的指纹一致。"""
        self.assertTrue(self.info.version_known)
        self.assertEqual(self.info.fingerprint_problems, [])
        self.assertTrue(self.info.verified_version)

    def test_type_map_digest_recorded(self) -> None:
        dll = self.info.files["7z.dll"]
        self.assertEqual(dll.type_map_sha1, "59592a87191f3bdc88aafda0847b3f5173d3dc11")
        self.assertEqual(dll.group_count, 27)
        self.assertEqual(dll.icon_count, 56)

    def test_tampered_structure_is_not_verified(self) -> None:
        """版本号对、结构不对 -> 必须降级为"未验证"。"""
        dll = dataclasses.replace(self.info.files["7z.dll"], icon_count=999)
        files = dict(self.info.files)
        files["7z.dll"] = dll
        tampered = dataclasses.replace(self.info, files=files)
        self.assertTrue(tampered.version_known)
        self.assertFalse(tampered.verified_version)
        self.assertTrue(any("图标数" in p for p in tampered.fingerprint_problems))
        self.assertIn("结构指纹不符", tampered.summary())

    def test_unknown_version(self) -> None:
        version = dataclasses.replace(self.info.version, strings={"FileVersion": "99.99"})
        unknown = dataclasses.replace(self.info, version=version)
        self.assertFalse(unknown.version_known)
        self.assertFalse(unknown.verified_version)
        self.assertIn("未验证版本", unknown.summary())

    def test_table_has_known_versions(self) -> None:
        for version in ("25.01", "26.05"):
            self.assertIn(version, target_mod.VERIFIED_VERSIONS)
        self.assertEqual(
            target_mod.VERIFIED_VERSIONS["25.01"].dll_type_map_sha1,
            target_mod.VERIFIED_VERSIONS["26.05"].dll_type_map_sha1,
            "两个已验证版本的结构指纹应当一致（类型表未变）",
        )


if __name__ == "__main__":
    unittest.main()
