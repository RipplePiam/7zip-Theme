"""主题包：文件类型图标（``.ico``）与工具栏位图（``.bmp``）的素材目录。

v1 只有一套固定主题，但接口按"主题包"抽象，v2 增加主题时无需改调用方。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

from .errors import ThemeError

#: 7zFM.exe 工具栏位图资源 ID -> (子目录, 素材文件名)
#: 100..106 为大图标(48x36)，150..156 为小图标(24x24)；顺序取自 7-Zip 源码的 IDB_* 定义。
TOOLBAR_SLOTS: Dict[int, Tuple[str, str]] = {
    100: ("48x36", "Add.bmp"),
    101: ("48x36", "Extract.bmp"),
    102: ("48x36", "Test.bmp"),
    103: ("48x36", "Copy.bmp"),
    104: ("48x36", "Move.bmp"),
    105: ("48x36", "Delete.bmp"),
    106: ("48x36", "Info.bmp"),
    150: ("24x24", "Add.bmp"),
    151: ("24x24", "Extract.bmp"),
    152: ("24x24", "Test.bmp"),
    153: ("24x24", "Copy.bmp"),
    154: ("24x24", "Move.bmp"),
    155: ("24x24", "Delete.bmp"),
    156: ("24x24", "Info.bmp"),
}

#: 扩展名别名：没有专属素材时回退到"同图标"的基础格式。
#: 依据是 7-Zip 自己的类型表（RT_STRING 里 `txz:23` 与 `xz:23` 共用索引）。
ALIASES: Dict[str, str] = {
    "txz": "xz",
    "tbz": "bz2",
    "tbz2": "bz2",
    "bzip2": "bz2",
    "taz": "z",
    "tgz": "gz",
    "tpz": "gz",
    "gzip": "gz",
    "lha": "lzh",
    "esd": "wim",
    "swm": "wim",
    "vhdx": "vhd",
    "tzst": "zst",
    "zstd": "zst",
    "lz5": "lz4",
}

DEFAULT_THEME_NAME = "Windows 10 Default 文件图标 + Glyfz 2016 工具条"


class Theme:
    """一套主题素材。"""

    def __init__(self, root: str, name: str = DEFAULT_THEME_NAME) -> None:
        self.root = os.path.abspath(root)
        self.name = name
        self.filetype_dir = os.path.join(self.root, "filetype")
        self.toolbar_dir = os.path.join(self.root, "toolbar")
        if not os.path.isdir(self.filetype_dir):
            raise ThemeError("主题缺少 filetype 素材目录：%s" % self.filetype_dir)
        if not os.path.isdir(self.toolbar_dir):
            raise ThemeError("主题缺少 toolbar 素材目录：%s" % self.toolbar_dir)
        self._ico_cache: Dict[str, Optional[str]] = {}

    # ---------------------------------------------------------- 文件类型图标

    def ico_path(self, ext: str) -> Optional[str]:
        """按扩展名找 ``.ico``，命中别名则回退。"""
        key = ext.lower().lstrip(".")
        if key in self._ico_cache:
            return self._ico_cache[key]
        seen = set()
        current: Optional[str] = key
        found: Optional[str] = None
        while current and current not in seen:
            seen.add(current)
            candidate = os.path.join(self.filetype_dir, current + ".ico")
            if os.path.isfile(candidate):
                found = candidate
                break
            current = ALIASES.get(current)
        self._ico_cache[key] = found
        return found

    def pick_ico(self, exts: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
        """在一组共享同一索引的扩展名里挑第一个有素材的。

        返回 ``(规范扩展名, 路径)``；规范扩展名取自素材文件名，
        所以 ``txz`` 会回显成它实际使用的 ``xz``，日志更准确。
        """
        for ext in exts:
            path = self.ico_path(ext)
            if path:
                base = os.path.splitext(os.path.basename(path))[0]
                return base, path
        return None, None

    def available_filetypes(self) -> List[str]:
        out = []
        for name in sorted(os.listdir(self.filetype_dir)):
            if name.lower().endswith(".ico"):
                out.append(name[:-4])
        return out

    # ------------------------------------------------------------ 工具栏位图

    def bitmap_path(self, resource_id: int) -> Optional[str]:
        slot = TOOLBAR_SLOTS.get(resource_id)
        if slot is None:
            return None
        path = os.path.join(self.toolbar_dir, slot[0], slot[1])
        return path if os.path.isfile(path) else None

    def describe(self) -> str:
        icos = len(self.available_filetypes())
        bmps = sum(1 for rid in TOOLBAR_SLOTS if self.bitmap_path(rid))
        return "%s（%d 个格式图标，%d 个工具栏位图）" % (self.name, icos, bmps)
