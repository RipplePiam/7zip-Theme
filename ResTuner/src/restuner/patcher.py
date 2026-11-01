"""打补丁引擎：把主题素材落进 7z.dll / 7zFM.exe。

设计要点
--------
* 7zFM.exe 只有等尺寸的工具栏位图替换 -> 走"原地覆盖"，不动任何 PE 结构；
* 7z.dll 需要新增 200 多个 RT_ICON、重建 27 个图标组 -> 整段重建 ``.rsrc``；
* 某个格式没有素材时**整组不动**，只记 SKIP，绝不产出半成品。
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import bmp as bmp_mod
from . import icon as icon_mod
from .errors import ResourceError, ThemeError
from .pe import PEImage
from .rsrc import (
    RT_BITMAP,
    RT_GROUP_ICON,
    RT_ICON,
    RT_STRING,
    EditResult,
    Resource,
    ResourceKey,
    apply_edits,
    parse_resources,
    resource_map,
)
from .theme import TOOLBAR_SLOTS, Theme

#: 新建 RT_ICON 使用的代码页；1200 = Unicode，与 Windows 对"资源内 PNG 图标"的约定一致
NEW_ICON_CODEPAGE = 1200

#: 类型表至少有这么多个 ``扩展名:索引`` 条目，避免把普通 UI 字符串误当成类型表
TYPE_TABLE_MIN_ENTRIES = 5

_TYPES_TOKEN = re.compile(r"([A-Za-z0-9_+.\-]+):(\d+)")


@dataclass
class Change:
    """一条可展示给用户的变更记录。"""

    file: str
    kind: str  # bitmap | icon-group | info | skip | warn
    detail: str
    status: str = "ok"  # ok | skip | warn

    def line(self) -> str:
        icon = {"ok": "✓", "skip": "·", "warn": "!"}.get(self.status, " ")
        return "%s %s: %s" % (icon, self.file, self.detail)


@dataclass
class PatchOutput:
    """一个文件打完补丁后的结果。"""

    name: str
    data: bytes
    changes: List[Change] = field(default_factory=list)
    edit: Optional[EditResult] = None
    resources_before: int = 0
    resources_after: int = 0
    expected: List[Resource] = field(default_factory=list)
    changed: Set[ResourceKey] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return True


# --------------------------------------------------------------- 类型索引表


def parse_string_block(data: bytes) -> List[str]:
    """解析 RT_STRING 资源块：16 个"长度前缀 + UTF-16"字符串。"""
    out: List[str] = []
    pos = 0
    total = len(data)
    for _ in range(16):
        if pos + 2 > total:
            break
        length = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        chunk = data[pos : pos + length * 2]
        pos += length * 2
        out.append(chunk.decode("utf-16-le", "ignore"))
    return out


def find_type_map(resources: Sequence[Resource]) -> Optional[Resource]:
    """找到 7-Zip 的"扩展名:索引"类型表资源（RT_STRING）。"""
    for res in resources:
        if res.type != RT_STRING:
            continue
        for text in parse_string_block(res.data):
            if len(_TYPES_TOKEN.findall(text)) >= TYPE_TABLE_MIN_ENTRIES:
                return res
    return None


def type_map_digest(resources: Sequence[Resource]) -> Optional[str]:
    """类型表资源的 SHA-1，用于版本指纹比对。"""
    res = find_type_map(resources)
    if res is None:
        return None
    return hashlib.sha1(res.data).hexdigest()


def type_index_table(resources: Sequence[Resource]) -> Dict[int, List[str]]:
    """从 7z.dll 的字符串表里读出 ``索引 -> 扩展名列表``。

    字符串形如 ``7z:0 zip:1 bz2:2 bzip2:2 ...``；同一索引可以有多个扩展名。
    """
    table: Dict[int, List[str]] = {}
    res = find_type_map(resources)
    if res is None:
        return table
    for text in parse_string_block(res.data):
        tokens = _TYPES_TOKEN.findall(text)
        if len(tokens) < TYPE_TABLE_MIN_ENTRIES:
            continue
        for ext, idx in tokens:
            table.setdefault(int(idx), []).append(ext.lower())
    return table


# ------------------------------------------------------------------ 7zFM.exe


def patch_fm(data: bytes, theme: Theme, filename: str = "7zFM.exe") -> PatchOutput:
    image = PEImage(data)
    resources = parse_resources(image)
    by_key = resource_map(resources)
    out = PatchOutput(name=filename, data=data, resources_before=len(resources))

    replaced: List[Resource] = []
    for resource_id in sorted(TOOLBAR_SLOTS):
        target = _find_bitmap(by_key, resource_id)
        if target is None:
            out.changes.append(
                Change(filename, "info", "工具栏位图 #%d 不存在，跳过" % resource_id, "skip")
            )
            continue
        path = theme.bitmap_path(resource_id)
        if path is None:
            out.changes.append(
                Change(filename, "info", "工具栏位图 #%d 没有素材，跳过" % resource_id, "skip")
            )
            continue
        candidate = bmp_mod.load_bmp(path)
        blocking, warnings = bmp_mod.evaluate(target.data, candidate)
        if blocking:
            out.changes.append(
                Change(
                    filename,
                    "bitmap",
                    "#%d ← %s 不兼容（%s），跳过" % (resource_id, os.path.basename(path), blocking),
                    "warn",
                )
            )
            continue
        replaced.append(Resource(target.type, target.name, target.lang, candidate.data, target.codepage))
        note = ("；" + "，".join(warnings)) if warnings else ""
        out.changes.append(
            Change(
                filename,
                "bitmap",
                "#%d ← toolbar/%s/%s（%dx%d %dbpp）%s"
                % (
                    resource_id,
                    TOOLBAR_SLOTS[resource_id][0],
                    TOOLBAR_SLOTS[resource_id][1],
                    candidate.width,
                    candidate.effective_height,
                    candidate.bit_count,
                    note,
                ),
                "warn" if warnings else "ok",
            )
        )

    if not replaced:
        out.edit = EditResult(mode="noop")
        out.data = data
        out.expected = list(resources)
        out.resources_after = len(resources)
        out.changes.append(Change(filename, "info", "没有可替换的位图，文件未改动", "skip"))
        return out

    replaced_keys = {r.key for r in replaced}
    final = [r for r in resources if r.key not in replaced_keys] + replaced
    new_data, edit = apply_edits(image, final, resources)
    out.data = new_data
    out.edit = edit
    out.resources_after = len(final)
    out.expected = final
    out.changed = set(replaced_keys)
    return out


def _find_bitmap(by_key: Dict[ResourceKey, Resource], resource_id: int) -> Optional[Resource]:
    for (rtype, name, _lang), res in by_key.items():
        if rtype == RT_BITMAP and name == resource_id:
            return res
    return None


# ------------------------------------------------------------------- 7z.dll


def patch_dll(data: bytes, theme: Theme, filename: str = "7z.dll") -> PatchOutput:
    image = PEImage(data)
    resources = parse_resources(image)
    out = PatchOutput(name=filename, data=data, resources_before=len(resources))

    table = type_index_table(resources)
    if not table:
        raise ResourceError("在 %s 里找不到 7-Zip 的类型索引表（RT_STRING），无法确定图标与格式的对应关系" % filename)

    groups = [r for r in resources if r.type == RT_GROUP_ICON]
    if not groups:
        raise ResourceError("%s 里没有 RT_GROUP_ICON 资源" % filename)

    next_icon_id = _next_icon_id(resources)
    new_groups: Dict[ResourceKey, bytes] = {}
    new_icons: List[Resource] = []

    for group in groups:
        index = _group_index(group.name)
        if index is None:
            out.changes.append(
                Change(filename, "icon-group", "图标组 %r 名字不是数字索引，跳过" % (group.name,), "skip")
            )
            continue
        exts = table.get(index, [])
        ext, path = theme.pick_ico(exts)
        if path is None:
            out.changes.append(
                Change(
                    filename,
                    "icon-group",
                    "索引 %d（%s）没有素材，整组保留官方图标"
                    % (index, "/".join(exts) or "未知格式"),
                    "skip",
                )
            )
            continue
        try:
            images = icon_mod.parse_ico(path)
        except ThemeError as exc:
            out.changes.append(Change(filename, "icon-group", "素材 %s 无法解析（%s），跳过" % (os.path.basename(path), exc), "warn"))
            continue

        ids = list(range(next_icon_id, next_icon_id + len(images)))
        next_icon_id += len(images)
        new_groups[group.key] = icon_mod.make_group(images, ids)
        for img, icon_id in zip(images, ids):
            new_icons.append(
                Resource(type=RT_ICON, name=icon_id, lang=group.lang, data=img.data, codepage=NEW_ICON_CODEPAGE)
            )
        sizes = "/".join(str(i.width) for i in images)
        out.changes.append(
            Change(
                filename,
                "icon-group",
                "索引 %d（%s）← %s，%d 个尺寸 [%s]"
                % (index, ext, os.path.basename(path), len(images), sizes),
            )
        )

    if not new_groups:
        out.edit = EditResult(mode="noop")
        out.data = data
        out.expected = list(resources)
        out.resources_after = len(resources)
        out.changes.append(Change(filename, "info", "没有可替换的图标组，文件未改动", "skip"))
        return out

    final: List[Resource] = []
    for res in resources:
        if res.key in new_groups:
            final.append(Resource(res.type, res.name, res.lang, new_groups[res.key], res.codepage))
        else:
            final.append(res)
    final.extend(new_icons)

    # 清掉不再被任何图标组引用的 RT_ICON（旧图标残留）
    referenced = set()
    for res in final:
        if res.type == RT_GROUP_ICON:
            try:
                for entry in icon_mod.parse_group(res.data):
                    referenced.add(entry["icon_id"])
            except ThemeError:
                continue
    before_icons = sum(1 for r in resources if r.type == RT_ICON)
    final = [
        r
        for r in final
        if not (r.type == RT_ICON and isinstance(r.name, int) and r.name not in referenced)
    ]
    after_icons = sum(1 for r in final if r.type == RT_ICON)
    out.changes.append(
        Change(filename, "icon-group", "RT_ICON：%d → %d（清理未被引用的旧图标）" % (before_icons, after_icons))
    )

    new_data, edit = apply_edits(image, final, resources)
    out.data = new_data
    out.edit = edit
    out.resources_after = len(final)
    out.expected = final
    out.changed = set(new_groups) | {r.key for r in new_icons} | {
        r.key for r in resources if r.type == RT_ICON and r.key not in {x.key for x in final}
    }
    return out


def _next_icon_id(resources: Sequence[Resource]) -> int:
    ids = [r.name for r in resources if r.type == RT_ICON and isinstance(r.name, int)]
    return (max(ids) if ids else 0) + 1


def _group_index(name) -> Optional[int]:
    if isinstance(name, int):
        return name
    if isinstance(name, str) and name.strip().isdigit():
        return int(name.strip())
    return None


# -------------------------------------------------------------------- 分发


def patch_file(name: str, data: bytes, theme: Theme) -> PatchOutput:
    lowered = name.lower()
    if lowered == "7zfm.exe":
        return patch_fm(data, theme, name)
    if lowered == "7z.dll":
        return patch_dll(data, theme, name)
    raise ResourceError("不支持的目标文件：%s" % name)
