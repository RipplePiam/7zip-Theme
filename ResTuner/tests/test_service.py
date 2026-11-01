"""编排层（体检 / 应用 / 还原）测试。"""
from __future__ import annotations

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402

from restuner import target as target_mod  # noqa: E402
from restuner.logbus import LogBus  # noqa: E402
from restuner.service import ApplyOptions, PatcherService  # noqa: E402


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@unittest.skipUnless(_support.have_assets(), "缺少 7z2501-x64 样例")
class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = _support.make_temp_dir("service")
        _support.copy_targets(self.work)
        self.before = {n: _sha(os.path.join(self.work, n)) for n in _support.TARGETS}
        self.log = LogBus()
        self.service = PatcherService(_support.ASSETS, log=self.log)

    def tearDown(self) -> None:
        self.log.close()
        _support.cleanup_temp(self.work)

    def test_inspect_official(self) -> None:
        info = self.service.inspect(self.work)
        self.assertEqual(info.version.display, "25.01")
        self.assertTrue(info.is_plus)
        self.assertFalse(info.any_patched)
        self.assertTrue(info.verified_version)
        self.assertEqual(info.files["7z.dll"].icon_count, 56)
        self.assertEqual(info.files["7z.dll"].group_count, 27)

    def test_dry_run_does_not_write(self) -> None:
        report = self.service.apply(
            ApplyOptions(directory=self.work, theme_root=_support.ASSETS, force=True, dry_run=True)
        )
        self.assertTrue(report.ok, report.error)
        self.assertIn("7z.dll", report.outputs)
        for name in _support.TARGETS:
            self.assertEqual(_sha(os.path.join(self.work, name)), self.before[name], name)

    def test_apply_then_detect_then_restore(self) -> None:
        report = self.service.apply(
            ApplyOptions(directory=self.work, theme_root=_support.ASSETS, force=True)
        )
        self.assertTrue(report.ok, report.error)
        self.assertIsNotNone(report.backup)
        self.assertTrue(os.path.isdir(report.backup.directory))

        info = self.service.inspect(self.work)
        self.assertTrue(info.all_patched)
        self.assertEqual(info.files["7z.dll"].icon_count, 216)

        # 幂等：再打一次应被拒绝
        again = self.service.apply(
            ApplyOptions(directory=self.work, theme_root=_support.ASSETS, force=True)
        )
        self.assertFalse(again.ok)
        self.assertIn("已经是主题版", again.error or "")

        backups = self.service.backups(self.work)
        self.assertEqual(len(backups), 1)
        self.service.restore(backups[0], self.work)
        for name in _support.TARGETS:
            self.assertEqual(_sha(os.path.join(self.work, name)), self.before[name], name)

    def test_unverified_version_requires_force(self) -> None:
        saved = dict(target_mod.VERIFIED_VERSIONS)
        try:
            target_mod.VERIFIED_VERSIONS.clear()
            report = self.service.apply(
                ApplyOptions(directory=self.work, theme_root=_support.ASSETS, force=False)
            )
            self.assertFalse(report.ok)
            self.assertIn("尚未验证", report.error or "")
            for name in _support.TARGETS:
                self.assertEqual(_sha(os.path.join(self.work, name)), self.before[name], name)
        finally:
            target_mod.VERIFIED_VERSIONS.update(saved)

    def test_missing_target_files(self) -> None:
        empty = _support.make_temp_dir("empty")
        try:
            report = self.service.apply(
                ApplyOptions(directory=empty, theme_root=_support.ASSETS, force=True)
            )
            self.assertFalse(report.ok)
            self.assertIn("缺少", report.error or "")
        finally:
            _support.cleanup_temp(empty)

    def test_backup_manifest_records_hash(self) -> None:
        report = self.service.apply(
            ApplyOptions(directory=self.work, theme_root=_support.ASSETS, force=True)
        )
        self.assertTrue(report.ok, report.error)
        manifest = os.path.join(report.backup.directory, "manifest.json")
        self.assertTrue(os.path.isfile(manifest))
        import json

        with open(manifest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["version"], "25.01")
        for name in _support.TARGETS:
            self.assertEqual(data["files"][name]["sha256"], self.before[name])


if __name__ == "__main__":
    unittest.main()
