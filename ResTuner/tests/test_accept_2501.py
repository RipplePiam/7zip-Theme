"""验收测试 A1：产出必须与 patches/7z2501-x64-patch 资源级等价。

允许的差异只有三处（我们主动修掉的缺陷）：
1. ``7zFM.exe`` 的 ``RT_GROUP_ICON #100``：参考补丁把高度写成了宽度；
2. 两个文件的 ``RT_VERSION``：参考补丁被"重新编译"过，我们原样保留；
3. ``7z.dll`` 的 ``RT_GROUP_ICON "4"`` 及 ``RT_ICON 11/12``：参考补丁漏删旧图标。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

from restuner import patcher, verify  # noqa: E402
from restuner.icon import parse_group  # noqa: E402
from restuner.pe import PEImage  # noqa: E402
from restuner.rsrc import parse_resources  # noqa: E402
from restuner.theme import Theme  # noqa: E402

VERSION = (16, 1, 1033)
FM_GROUP = (14, 100, 1033)
#: 注意：7z.dll 里第一个图标组的名字是**字符串** "0"，其余 26 个是整数 ID
DLL_GROUP0 = (14, "0", 1033)
DLL_GROUP4 = (14, 4, 1033)
DLL_STALE_ICONS = {(3, 11, 1033), (3, 12, 1033)}


@unittest.skipUnless(
    _support.have_assets() and _support.have_reference(), "缺少 7z2501-x64 样例或参考补丁"
)
class ReferenceParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.theme = Theme(_support.ASSETS)
        cls.outputs = {
            name: patcher.patch_file(name, _support.read_bytes(name), cls.theme).data
            for name in _support.TARGETS
        }
        cls.reference = {name: _support.read_bytes(name, _support.REF_DIR) for name in _support.TARGETS}

    # ---------------------------------------------------------------- 7zFM

    def test_fm_diff_is_only_known_defects(self) -> None:
        diff = verify.diff(
            verify.digest_of_bytes(self.reference["7zFM.exe"]),
            verify.digest_of_bytes(self.outputs["7zFM.exe"]),
        )
        self.assertEqual(diff.missing, [])
        self.assertEqual(diff.extra, [])
        self.assertEqual(set(diff.changed), {VERSION, FM_GROUP},
                         "与参考补丁的差异超出了已知缺陷范围")

    def test_fm_version_resource_preserved(self) -> None:
        """参考补丁把 RT_VERSION 重编译了 4 个字节，我们必须原样保留。"""
        before = verify.digest_of_bytes(_support.read_bytes("7zFM.exe"))[VERSION]
        after = verify.digest_of_bytes(self.outputs["7zFM.exe"])[VERSION]
        self.assertEqual(before, after)

    def test_fm_group_icon_100_dimensions(self) -> None:
        """参考补丁的 GROUP_ICON #100 是 110x110，实际图标是 110x63；我们不动它。"""
        ref = parse_group(
            {r.key: r for r in parse_resources(PEImage(self.reference["7zFM.exe"]))}[FM_GROUP].data
        )[0]
        ours = parse_group(
            {r.key: r for r in parse_resources(PEImage(self.outputs["7zFM.exe"]))}[FM_GROUP].data
        )[0]
        self.assertEqual((ref["width"], ref["height"]), (110, 110))
        self.assertEqual((ours["width"], ours["height"]), (110, 63))

    # --------------------------------------------------------------- 7z.dll

    def test_dll_diff_is_only_known_defects(self) -> None:
        diff = verify.diff(
            verify.digest_of_bytes(self.reference["7z.dll"]),
            verify.digest_of_bytes(self.outputs["7z.dll"]),
        )
        self.assertEqual(set(diff.missing), DLL_STALE_ICONS)
        self.assertEqual(diff.extra, [])
        self.assertEqual(set(diff.changed), {VERSION, DLL_GROUP4})

    def test_dll_every_other_group_identical(self) -> None:
        """除 arj 组外，其余 26 个图标组必须与参考补丁逐字节一致。"""
        ref = {r.key: r for r in parse_resources(PEImage(self.reference["7z.dll"]))}
        ours = {r.key: r for r in parse_resources(PEImage(self.outputs["7z.dll"]))}
        compared = 0
        for key, res in ref.items():
            if key[0] != 14 or key == DLL_GROUP4:
                continue
            self.assertIn(key, ours)
            self.assertEqual(res.data, ours[key].data, "图标组 %r 与参考不一致" % (key,))
            compared += 1
        self.assertEqual(compared, 26)

    def test_dll_icons_identical(self) -> None:
        ref = verify.digest_of_bytes(self.reference["7z.dll"])
        ours = verify.digest_of_bytes(self.outputs["7z.dll"])
        for key, value in ours.items():
            if key[0] == 3:
                self.assertEqual(ref[key], value, "图标 %r 内容与参考不一致" % (key,))

    # --------------------------------------------------------------- 通用

    def test_outputs_are_valid(self) -> None:
        for name, data in self.outputs.items():
            self.assertEqual(verify.check_structure(data), [], name)

    def test_dll_size_close_to_reference(self) -> None:
        """我们的 .rsrc 布局更紧凑，体积应略小于参考补丁。"""
        ours = len(self.outputs["7z.dll"])
        ref = len(self.reference["7z.dll"])
        self.assertLess(abs(ours - ref), 4096, "与参考补丁体积差异过大")


if __name__ == "__main__":
    unittest.main()
