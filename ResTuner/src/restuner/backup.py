"""备份与还原。

备份放在目标目录内的 ``.restuner-backup/<版本>_<时间戳>/``，
里面是原始文件 + ``manifest.json``（记录 SHA-256、大小、版本、工具版本）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .errors import BackupError

BACKUP_DIRNAME = ".restuner-backup"
MANIFEST_NAME = "manifest.json"


@dataclass
class BackupFile:
    name: str
    size: int
    sha256: str


@dataclass
class Backup:
    directory: str
    version: str
    created: str
    files: Dict[str, BackupFile] = field(default_factory=dict)
    tool_version: str = ""

    def describe(self) -> str:
        return "%s · %s · %d 个文件" % (self.version or "未知版本", self.created, len(self.files))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_root(install_dir: str) -> str:
    return os.path.join(install_dir, BACKUP_DIRNAME)


def create_backup(
    install_dir: str,
    filenames: List[str],
    version: str,
    tool_version: str = "",
) -> Backup:
    """把目标文件复制到新的备份目录，并写 manifest。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_version = (version or "unknown").replace(" ", "")
    target = os.path.join(backup_root(install_dir), "%s_%s" % (safe_version, stamp))
    index = 1
    while os.path.exists(target):
        index += 1
        target = os.path.join(backup_root(install_dir), "%s_%s_%d" % (safe_version, stamp, index))

    try:
        os.makedirs(target, exist_ok=False)
    except OSError as exc:
        raise BackupError("无法创建备份目录 %s：%s" % (target, exc)) from exc

    backup = Backup(directory=target, version=version, created=stamp, tool_version=tool_version)
    try:
        for name in filenames:
            src = os.path.join(install_dir, name)
            if not os.path.isfile(src):
                raise BackupError("备份源文件不存在：%s" % src)
            dst = os.path.join(target, name)
            shutil.copy2(src, dst)
            backup.files[name] = BackupFile(
                name=name, size=os.path.getsize(dst), sha256=_sha256(dst)
            )
        manifest = {
            "tool": "ResTuner",
            "tool_version": tool_version,
            "version": version,
            "created": datetime.now().isoformat(timespec="seconds"),
            "files": {
                name: {"size": item.size, "sha256": item.sha256}
                for name, item in backup.files.items()
            },
        }
        with open(os.path.join(target, MANIFEST_NAME), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return backup


def list_backups(install_dir: str) -> List[Backup]:
    """按时间倒序列出所有备份。"""
    root = backup_root(install_dir)
    if not os.path.isdir(root):
        return []
    out: List[Backup] = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        manifest_path = os.path.join(path, MANIFEST_NAME)
        backup = Backup(directory=path, version=name.split("_")[0], created=name)
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                backup.version = data.get("version", backup.version)
                backup.created = data.get("created", backup.created)
                backup.tool_version = data.get("tool_version", "")
                for fname, item in data.get("files", {}).items():
                    backup.files[fname] = BackupFile(
                        name=fname, size=item.get("size", 0), sha256=item.get("sha256", "")
                    )
            except (OSError, ValueError):
                pass
        out.append(backup)
    out.sort(key=lambda b: os.path.getmtime(b.directory), reverse=True)
    return out


def restore(backup: Backup, install_dir: str) -> List[str]:
    """把备份里的文件写回目标目录（先写临时文件再原子替换）。"""
    if not backup.files:
        raise BackupError("这份备份没有可还原的文件记录")
    restored: List[str] = []
    for name in backup.files:
        src = os.path.join(backup.directory, name)
        if not os.path.isfile(src):
            raise BackupError("备份文件缺失：%s" % src)
        dst = os.path.join(install_dir, name)
        tmp = dst + ".restuner-tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        restored.append(name)
    return restored


def verify_backup(backup: Backup) -> List[str]:
    """校验备份文件哈希，返回问题列表。"""
    problems: List[str] = []
    for name, item in backup.files.items():
        path = os.path.join(backup.directory, name)
        if not os.path.isfile(path):
            problems.append("缺少文件：%s" % name)
            continue
        if item.sha256 and _sha256(path) != item.sha256:
            problems.append("哈希不匹配：%s" % name)
    return problems


def latest_backup(install_dir: str) -> Optional[Backup]:
    items = list_backups(install_dir)
    return items[0] if items else None
