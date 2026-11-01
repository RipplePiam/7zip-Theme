"""编排层：把体检、打补丁、自检、备份、写回串成一次完整操作。

这一层不碰 tkinter，也不直接 ``print``，只通过 :class:`~restuner.logbus.LogBus` 汇报，
所以 GUI 与后续可能加的 CLI 共用同一套逻辑。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import __version__, patcher, verify
from .backup import Backup, create_backup, list_backups, restore, verify_backup
from .errors import ResTunerError, TargetError, VerifyError
from .logbus import LogBus
from .rsrc import ResourceKey, parse_resources
from .pe import PEImage
from .target import REQUIRED_FILES, TargetInfo, inspect
from .theme import Theme


@dataclass
class ApplyOptions:
    directory: str
    theme_root: str
    force: bool = False
    make_backup: bool = True
    dry_run: bool = False


@dataclass
class ApplyReport:
    ok: bool = False
    version: str = ""
    directory: str = ""
    backup: Optional[Backup] = None
    changes: List[patcher.Change] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    outputs: Dict[str, bytes] = field(default_factory=dict)
    elapsed: float = 0.0
    error: Optional[str] = None

    def summary(self) -> str:
        if not self.ok:
            return "失败：%s" % (self.error or "未知原因")
        return "完成：%s，共 %d 条变更，用时 %.1fs" % (self.version, len(self.changes), self.elapsed)


class PatcherService:
    """对外只暴露 3 个动作：体检、应用、还原。"""

    def __init__(self, theme_root: str, log: Optional[LogBus] = None) -> None:
        self.theme = Theme(theme_root)
        self.log = log or LogBus()

    # ------------------------------------------------------------------ 体检

    def inspect(self, directory: str) -> TargetInfo:
        self.log.info("体检目标目录：%s" % directory)
        info = inspect(directory, theme=self.theme)
        self.log.info(info.summary())
        self.log.info(
            "  7z.dll：%d 个资源（%d 个图标 / %d 个图标组，最多 %d 项/组）"
            % (
                info.files["7z.dll"].resource_count,
                info.files["7z.dll"].icon_count,
                info.files["7z.dll"].group_count,
                info.files["7z.dll"].max_group_entries,
            )
        )
        self.log.info("  7zFM.exe：%d 个位图资源" % len(info.files["7zFM.exe"].bitmap_ids))
        for warning in info.warnings:
            self.log.warn(warning)
        if info.all_patched:
            self.log.info("版本 %s（文件已是主题版）" % info.version.display)
        elif not info.verified_version:
            if info.version_known:
                self.log.warn(
                    "版本号 %s 已记录，但结构指纹对不上：%s"
                    % (info.version.display, "；".join(info.fingerprint_problems))
                )
            else:
                self.log.warn(
                    "版本 %s 不在已验证清单里，将按结构自适应处理；建议先备份后再确认效果"
                    % (info.version.display or "未知")
                )
        else:
            self.log.info("版本 %s 已验证（结构指纹吻合）" % info.version.display)
        return info

    # ------------------------------------------------------------------ 应用

    def apply(self, options: ApplyOptions) -> ApplyReport:
        started = time.time()
        report = ApplyReport(directory=options.directory)
        log = self.log

        try:
            info = self.inspect(options.directory)
            report.version = info.version.display or "未知"

            if info.all_patched:
                raise TargetError("这两个文件已经是主题版了；如需重做，请先「还原备份」")

            self._preflight(info, options)

            if not info.verified_version and not options.force:
                if info.version_known:
                    raise TargetError(
                        "版本号 %s 在已验证清单里，但结构指纹对不上（%s）。"
                        "这可能不是官方原版，或已被别的工具改过；确认要继续请勾选「我知道风险」。"
                        % (info.version.display, "；".join(info.fingerprint_problems))
                    )
                raise TargetError(
                    "版本 %s 尚未验证。确认要继续请勾选「我知道风险」后重试（--force）。"
                    % (info.version.display or "未知")
                )

            if info.version_known and info.fingerprint_problems:
                for problem in info.fingerprint_problems:
                    log.warn("结构指纹差异：%s" % problem)

            log.info("读取主题素材：%s" % self.theme.describe())

            outputs: Dict[str, bytes] = {}
            all_changes: List[patcher.Change] = []
            for name in REQUIRED_FILES:
                path = os.path.join(options.directory, name)
                log.info("处理 %s …" % name)
                with open(path, "rb") as fh:
                    data = fh.read()
                result = patcher.patch_file(name, data, self.theme)
                for change in result.changes:
                    log.log("warn" if change.status == "warn" else ("info" if change.status == "skip" else "ok"), change.line())
                all_changes.extend(result.changes)

                original = parse_resources(PEImage(data))
                log.info("  自检 %s …" % name)
                verify.verify_output(result.data, original, result.expected, result.changed)
                log.ok(
                    "  %s 自检通过：%s；%s"
                    % (name, verify.summarize(result.data, data), result.edit.summary() if result.edit else "-")
                )
                outputs[name] = result.data

            report.changes = all_changes
            report.warnings = info.warnings

            if options.dry_run:
                log.warn("演练模式：只生成结果，不写回磁盘")
                report.outputs = outputs
                report.ok = True
                report.elapsed = time.time() - started
                return report

            if options.make_backup:
                log.info("备份原始文件 …")
                report.backup = create_backup(
                    options.directory, list(REQUIRED_FILES), report.version, __version__
                )
                log.ok("备份完成：%s" % report.backup.directory)

            self._write_all(options.directory, outputs)

            for name in REQUIRED_FILES:
                with open(os.path.join(options.directory, name), "rb") as fh:
                    problems = verify.check_structure(fh.read())
                if problems:
                    raise VerifyError("%s 写回后的落地校验失败：%s" % (name, "；".join(problems)))
            log.ok("写回完成并通过落地校验")

            report.ok = True
            report.elapsed = time.time() - started
            log.ok(report.summary())
            return report

        except ResTunerError as exc:
            report.ok = False
            report.error = str(exc)
            report.elapsed = time.time() - started
            log.error(str(exc))
            return report
        except Exception as exc:  # noqa: BLE001 - 界面不应崩
            report.ok = False
            report.error = "%s: %s" % (type(exc).__name__, exc)
            report.elapsed = time.time() - started
            log.error(report.error)
            return report

    # --------------------------------------------------------------- 内部

    def _preflight(self, info: TargetInfo, options: ApplyOptions) -> None:
        locked = [name for name, status in info.files.items() if status.locked]
        if locked:
            raise TargetError("以下文件正被占用，请先关闭 7-Zip 与资源管理器窗口：%s" % "、".join(locked))
        unwritable = [name for name, status in info.files.items() if not status.writable]
        if unwritable:
            raise TargetError(
                "没有写入权限（%s）。请以管理员身份运行本工具，或换一个可写的目录。"
                % "、".join(unwritable)
            )
        for name, status in info.files.items():
            if not status.is_plus:
                raise TargetError("%s 不是 64 位 PE，本工具目前只支持 x64 版本" % name)
            if status.signed:
                self.log.warn("%s 带数字签名，修改后签名会失效（工具会剥离签名表）" % name)

    def _write_all(self, directory: str, outputs: Dict[str, bytes]) -> None:
        temporaries: List[tuple] = []
        try:
            for name, data in outputs.items():
                final = os.path.join(directory, name)
                temp = final + ".restuner-new"
                with open(temp, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                temporaries.append((temp, final))
            for temp, final in temporaries:
                os.replace(temp, final)
        except Exception:
            for temp, _final in temporaries:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except OSError:
                        pass
            raise

    # ------------------------------------------------------------------ 还原

    def backups(self, directory: str) -> List[Backup]:
        return list_backups(directory)

    def restore(self, backup: Backup, directory: str) -> List[str]:
        problems = verify_backup(backup)
        if problems:
            raise TargetError("备份校验失败：%s" % "；".join(problems))
        names = restore(backup, directory)
        self.log.ok("已还原 %s（来自 %s）" % ("、".join(names), backup.directory))
        return names
