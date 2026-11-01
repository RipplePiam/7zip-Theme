"""PE 资源目录的解析与重建。

资源在 PE 里是一棵三层树::

    RT_<TYPE>  ->  NAME/ID  ->  LANGID  ->  IMAGE_RESOURCE_DATA_ENTRY  ->  数据

本模块提供：
* :func:`parse_resources` —— 把树摊平成 :class:`Resource` 列表（保留语言、代码页、原始顺序）
* :func:`build_rsrc`      —— 由资源列表生成一整段 ``.rsrc`` 节内容
* :func:`apply_edits`     —— 把最终资源集合写回 :class:`PEImage`（等尺寸原地改 / 变尺寸整节重建）
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .checksum import update_checksum
from .errors import ResourceError
from .pe import PEImage, align_up

ResourceId = Union[int, str]
ResourceKey = Tuple[ResourceId, ResourceId, int]

#: 常见资源类型名
RT_NAMES: Dict[int, str] = {
    1: "RT_CURSOR",
    2: "RT_BITMAP",
    3: "RT_ICON",
    4: "RT_MENU",
    5: "RT_DIALOG",
    6: "RT_STRING",
    7: "RT_FONTDIR",
    8: "RT_FONT",
    9: "RT_ACCELERATOR",
    10: "RT_RCDATA",
    11: "RT_MESSAGETABLE",
    12: "RT_GROUP_CURSOR",
    14: "RT_GROUP_ICON",
    16: "RT_VERSION",
    17: "RT_DLGINCLUDE",
    19: "RT_PLUGPLAY",
    20: "RT_VXD",
    21: "RT_ANICURSOR",
    22: "RT_ANIICON",
    23: "RT_HTML",
    24: "RT_MANIFEST",
}

RT_BITMAP = 2
RT_ICON = 3
RT_STRING = 6
RT_GROUP_ICON = 14
RT_VERSION = 16

_CERTIFICATE_TABLE = 4
_RESOURCE_TABLE = 2


@dataclass
class Resource:
    """一条资源记录。``data`` 是不含任何文件头的裸数据。"""

    type: ResourceId
    name: ResourceId
    lang: int
    data: bytes
    codepage: int = 0

    @property
    def key(self) -> ResourceKey:
        return (self.type, self.name, self.lang)

    def type_label(self) -> str:
        if isinstance(self.type, str):
            return self.type
        return RT_NAMES.get(self.type, "RT_%d" % self.type)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<Resource %s %r lang=%d %dB>" % (
            self.type_label(),
            self.name,
            self.lang,
            len(self.data),
        )


# --------------------------------------------------------------------- 解析


def _string_cursor(image: PEImage, section_rva: int) -> Callable[[int], str]:
    def read(relative_offset: int) -> str:
        rva = section_rva + relative_offset
        off = image.rva_to_offset(rva)
        if off is None:
            raise ResourceError("资源名字符串 RVA 0x%X 不可达" % rva)
        length = image.u16(off)
        raw = bytes(image.data[off + 2 : off + 2 + length * 2])
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError as exc:  # pragma: no cover
            raise ResourceError("资源名字符串解码失败: %s" % exc) from exc

    return read


def parse_resources(image: PEImage) -> List[Resource]:
    """解析全部资源，保持资源目录中的原始顺序。"""
    section_rva, section_size = image.get_dir(_RESOURCE_TABLE)
    if not section_rva or not section_size:
        return []
    root = image.rva_to_offset(section_rva)
    if root is None:
        raise ResourceError("资源目录 RVA 0x%X 无法映射到文件偏移" % section_rva)

    read_string = _string_cursor(image, section_rva)
    out: List[Resource] = []

    def walk(offset: int, path: List[ResourceId]) -> None:
        if offset + 16 > len(image.data):
            raise ResourceError("资源目录表越界")
        named = image.u16(offset + 12)
        ids = image.u16(offset + 14)
        for i in range(named + ids):
            entry = offset + 16 + i * 8
            name_field = image.u32(entry)
            ident: ResourceId = (
                read_string(name_field & 0x7FFFFFFF) if name_field & 0x80000000 else name_field
            )
            child = image.u32(entry + 4)
            if child & 0x80000000:
                sub = image.rva_to_offset(section_rva + (child & 0x7FFFFFFF))
                if sub is None:
                    raise ResourceError("子目录 RVA 不可达")
                walk(sub, path + [ident])
            else:
                data_entry = image.rva_to_offset(section_rva + child)
                if data_entry is None:
                    raise ResourceError("数据项 RVA 不可达")
                data_rva = image.u32(data_entry)
                data_size = image.u32(data_entry + 4)
                codepage = image.u32(data_entry + 8)
                payload = b""
                if data_size:
                    payload_off = image.rva_to_offset(data_rva)
                    if payload_off is None:
                        raise ResourceError("资源数据 RVA 0x%X 不可达" % data_rva)
                    payload = bytes(image.data[payload_off : payload_off + data_size])
                if len(path) != 2:
                    raise ResourceError("资源树层级异常：%r" % (path + [ident],))
                out.append(
                    Resource(
                        type=path[0],
                        name=path[1],
                        lang=int(ident),
                        data=payload,
                        codepage=codepage,
                    )
                )

    walk(root, [])
    return out


def resource_map(resources: Iterable[Resource]) -> Dict[ResourceKey, Resource]:
    return {r.key: r for r in resources}


# --------------------------------------------------------------------- 重建


def _order_key(value: ResourceId):
    """命名项排在数字 ID 之前（与 MSVC 资源编译器的产出顺序一致）。"""
    if isinstance(value, str):
        return (0, value)
    return (1, int(value))


def _resource_key(res: Resource):
    return (_order_key(res.type), _order_key(res.name), int(res.lang))


def build_rsrc(resources: Sequence[Resource], section_rva: int) -> bytes:
    """由资源列表生成完整的 ``.rsrc`` 节内容（长度未做文件对齐）。

    ``section_rva`` 用于填写数据项里的 ``OffsetToData``。
    """
    items = sorted(resources, key=_resource_key)
    if not items:
        return b""

    types: List[ResourceId] = []
    names_by_type: Dict[ResourceId, List[ResourceId]] = {}
    langs_by: Dict[Tuple[ResourceId, ResourceId], List[int]] = {}
    for res in items:
        if res.type not in names_by_type:
            names_by_type[res.type] = []
            types.append(res.type)
        bucket_names = names_by_type[res.type]
        if res.name not in bucket_names:
            bucket_names.append(res.name)
        bucket_langs = langs_by.setdefault((res.type, res.name), [])
        if res.lang not in bucket_langs:
            bucket_langs.append(res.lang)

    # ---- 第一遍：分配各段偏移
    root_off = 0
    pos = 16 + 8 * len(types)

    type_dir: Dict[ResourceId, int] = {}
    for t in types:
        type_dir[t] = pos
        pos += 16 + 8 * len(names_by_type[t])

    name_dir: Dict[Tuple[ResourceId, ResourceId], int] = {}
    for t in types:
        for n in names_by_type[t]:
            name_dir[(t, n)] = pos
            pos += 16 + 8 * len(langs_by[(t, n)])

    str_off: Dict[Tuple[str, object], int] = {}
    for t in types:
        if isinstance(t, str):
            str_off[("type", t)] = pos
            pos += 2 + len(t.encode("utf-16-le"))
    for t in types:
        for n in names_by_type[t]:
            if isinstance(n, str):
                str_off[("name", (t, n))] = pos
                pos += 2 + len(n.encode("utf-16-le"))

    pos = align_up(pos, 4)
    de_off: Dict[ResourceKey, int] = {}
    for res in items:
        de_off[res.key] = pos
        pos += 16

    pos = align_up(pos, 4)
    data_off: Dict[ResourceKey, int] = {}
    for res in items:
        data_off[res.key] = pos
        pos += align_up(len(res.data), 4)

    buf = bytearray(pos)

    def write_entries(
        offset: int,
        values: Sequence[object],
        id_of: Callable[[object], int],
        child_of: Callable[[object], int],
    ) -> None:
        named = sum(1 for v in values if isinstance(v, str))
        struct.pack_into("<IIHHHH", buf, offset, 0, 0, 0, 0, named, len(values) - named)
        for i, value in enumerate(values):
            struct.pack_into("<II", buf, offset + 16 + i * 8, id_of(value), child_of(value))

    write_entries(
        root_off,
        types,
        lambda t: (0x80000000 | str_off[("type", t)]) if isinstance(t, str) else int(t),  # type: ignore[arg-type]
        lambda t: 0x80000000 | type_dir[t],  # type: ignore[operator]
    )

    for t in types:
        def id_of_name(n, t=t):
            if isinstance(n, str):
                return 0x80000000 | str_off[("name", (t, n))]
            return int(n)

        write_entries(
            type_dir[t],
            names_by_type[t],
            id_of_name,
            lambda n, t=t: 0x80000000 | name_dir[(t, n)],
        )

    for t in types:
        for n in names_by_type[t]:
            write_entries(
                name_dir[(t, n)],
                langs_by[(t, n)],
                lambda lang: int(lang),
                lambda lang, t=t, n=n: de_off[(t, n, int(lang))],
            )

    # ---- 字符串
    for t in types:
        if isinstance(t, str):
            off = str_off[("type", t)]
            encoded = t.encode("utf-16-le")
            struct.pack_into("<H", buf, off, len(t))
            buf[off + 2 : off + 2 + len(encoded)] = encoded
    for t in types:
        for n in names_by_type[t]:
            if isinstance(n, str):
                off = str_off[("name", (t, n))]
                encoded = n.encode("utf-16-le")
                struct.pack_into("<H", buf, off, len(n))
                buf[off + 2 : off + 2 + len(encoded)] = encoded

    # ---- 数据项 + 数据
    for res in items:
        de = de_off[res.key]
        struct.pack_into(
            "<IIII",
            buf,
            de,
            section_rva + data_off[res.key],
            len(res.data),
            res.codepage,
            0,
        )
        doff = data_off[res.key]
        buf[doff : doff + len(res.data)] = res.data

    return bytes(buf)


# ------------------------------------------------------------------ 落盘


@dataclass
class EditResult:
    """一次资源落盘的结果摘要，便于日志与自检。"""

    mode: str = "noop"
    added: List[ResourceKey] = field(default_factory=list)
    removed: List[ResourceKey] = field(default_factory=list)
    replaced: List[ResourceKey] = field(default_factory=list)
    rsrc_growth: int = 0
    sections_moved: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return "mode=%s +%d -%d ~%d rsrc_growth=%+d moved=%s" % (
            self.mode,
            len(self.added),
            len(self.removed),
            len(self.replaced),
            self.rsrc_growth,
            ",".join(self.sections_moved) or "-",
        )


def apply_edits(
    image: PEImage,
    resources: Sequence[Resource],
    original: Sequence[Resource],
    *,
    strip_signature: bool = True,
) -> Tuple[bytes, EditResult]:
    """把 ``resources`` 作为最终资源集合写回 ``image``，返回 (新文件字节, 摘要)。"""
    orig_map = resource_map(original)
    new_map = resource_map(resources)

    added = [k for k in new_map if k not in orig_map]
    removed = [k for k in orig_map if k not in new_map]
    replaced = [k for k in new_map if k in orig_map and new_map[k].data != orig_map[k].data]

    result = EditResult(added=added, removed=removed, replaced=replaced)

    if not added and not removed:
        if not replaced:
            result.mode = "noop"
            update_checksum(image)
            return bytes(image.data), result
        if all(len(new_map[k].data) == len(orig_map[k].data) for k in new_map):
            _patch_in_place(image, new_map, replaced)
            result.mode = "inplace"
            update_checksum(image)
            return bytes(image.data), result

    return _rebuild_section(image, new_map, result, strip_signature=strip_signature)


def _patch_in_place(
    image: PEImage, new_map: Dict[ResourceKey, Resource], keys: Sequence[ResourceKey]
) -> None:
    """等尺寸覆盖：只改数据字节，资源目录与节表完全不动。"""
    section_rva, _ = image.get_dir(_RESOURCE_TABLE)
    for key in keys:
        res = new_map[key]
        entry_off = _data_entry_offset(image, section_rva, key)
        data_rva = image.u32(entry_off)
        size = image.u32(entry_off + 4)
        if size != len(res.data):
            raise ResourceError("原地覆盖尺寸不一致：%r" % (key,))
        off = image.rva_to_offset(data_rva)
        if off is None:
            raise ResourceError("资源数据 RVA 0x%X 不可达" % data_rva)
        image.data[off : off + size] = res.data


def _data_entry_offset(image: PEImage, section_rva: int, key: ResourceKey) -> int:
    """定位某条资源的 IMAGE_RESOURCE_DATA_ENTRY 文件偏移。"""
    root = image.rva_to_offset(section_rva)
    if root is None:
        raise ResourceError("资源目录不可达")
    read_string = _string_cursor(image, section_rva)

    def entries(offset: int) -> List[Tuple[ResourceId, int]]:
        named = image.u16(offset + 12)
        ids = image.u16(offset + 14)
        out: List[Tuple[ResourceId, int]] = []
        for i in range(named + ids):
            entry = offset + 16 + i * 8
            name_field = image.u32(entry)
            ident: ResourceId = (
                read_string(name_field & 0x7FFFFFFF) if name_field & 0x80000000 else name_field
            )
            out.append((ident, image.u32(entry + 4)))
        return out

    def descend(offset: int, want: ResourceId) -> int:
        for ident, child in entries(offset):
            if ident == want:
                return child & 0x7FFFFFFF
        raise ResourceError("资源项 %r 不存在" % (want,))

    type_rel = descend(root, key[0])
    type_off = image.rva_to_offset(section_rva + type_rel)
    if type_off is None:
        raise ResourceError("资源类型子目录不可达")
    name_rel = descend(type_off, key[1])
    name_off = image.rva_to_offset(section_rva + name_rel)
    if name_off is None:
        raise ResourceError("资源名字子目录不可达")
    de_rel = descend(name_off, key[2])
    de_off = image.rva_to_offset(section_rva + de_rel)
    if de_off is None:
        raise ResourceError("数据项不可达")
    return de_off


def _rebuild_section(
    image: PEImage,
    new_map: Dict[ResourceKey, Resource],
    result: EditResult,
    *,
    strip_signature: bool,
) -> Tuple[bytes, EditResult]:
    rsrc = image.section_by_name(".rsrc")
    if rsrc is None:
        raise ResourceError("目标文件没有 .rsrc 节，无法重建资源")

    file_align = image.file_alignment or 0x200
    section_align = image.section_alignment or 0x1000
    orig_raw_size = rsrc.raw_size
    orig_res_dir = image.get_dir(_RESOURCE_TABLE)

    new_blob = build_rsrc(list(new_map.values()), rsrc.virtual_address)
    new_vsize = len(new_blob)
    new_raw_size = align_up(new_vsize, file_align)

    # 证书表按"文件偏移"记录，节区搬动后必然失效 -> 先摘掉
    cert_off, cert_size = image.get_dir(_CERTIFICATE_TABLE)
    if strip_signature and cert_size:
        if 0 < cert_off <= len(image.data):
            del image.data[cert_off:]
        image.set_dir(_CERTIFICATE_TABLE, 0, 0)

    # 尾部 overlay（若有）先摘下来，最后原样接回
    last_end = max((s.raw_end for s in image.sections), default=0)
    overlay = bytes(image.data[last_end:]) if last_end < len(image.data) else b""

    keep_raw = new_raw_size <= orig_raw_size
    body = bytearray(image.data[: rsrc.raw_ptr])

    moves: List[Tuple[object, int, int]] = []  # (section, new_va, new_raw_ptr)

    if keep_raw:
        body.extend(new_blob)
        body.extend(b"\0" * (orig_raw_size - new_vsize))
        body.extend(image.data[rsrc.raw_end : last_end])
    else:
        body.extend(new_blob)
        body.extend(b"\0" * (new_raw_size - new_vsize))
        followers = sorted(
            (s for s in image.sections if s.raw_ptr >= rsrc.raw_end and s.raw_size),
            key=lambda s: s.raw_ptr,
        )
        va_cursor = rsrc.virtual_address + new_vsize
        for sec in followers:
            sec_bytes = bytes(image.data[sec.raw_ptr : sec.raw_end])
            if len(sec_bytes) < sec.raw_size:
                sec_bytes += b"\0" * (sec.raw_size - len(sec_bytes))
            new_va = align_up(va_cursor, section_align)
            new_raw_ptr = align_up(len(body), file_align)
            body.extend(b"\0" * (new_raw_ptr - len(body)))
            body.extend(sec_bytes)
            moves.append((sec, new_va, new_raw_ptr))
            result.sections_moved.append(sec.name)
            va_cursor = new_va + sec.span

    body.extend(b"\0" * (align_up(len(body), file_align) - len(body)))
    body.extend(overlay)

    image.data = body

    # ---- 应用节区搬迁（先移目录 RVA，再改节表本身）
    for sec, new_va, new_raw_ptr in moves:
        delta = new_va - sec.virtual_address
        if delta:
            _shift_directory_rvas(image, sec, delta)
        image.set_u32(sec.header_offset + 12, new_va)
        image.set_u32(sec.header_offset + 20, new_raw_ptr)
        sec.virtual_address = new_va
        sec.raw_ptr = new_raw_ptr

    # ---- .rsrc 节表
    image.set_u32(rsrc.header_offset + 8, new_vsize)
    image.set_u32(rsrc.header_offset + 16, orig_raw_size if keep_raw else new_raw_size)
    rsrc.virtual_size = new_vsize
    if not keep_raw:
        rsrc.raw_size = new_raw_size

    # ---- 数据目录
    image.set_dir(_RESOURCE_TABLE, rsrc.virtual_address, new_vsize)

    # ---- SizeOfInitializedData：按 .rsrc 的 RawSize 变化量平移
    raw_delta = (orig_raw_size if keep_raw else new_raw_size) - orig_raw_size
    image.size_of_initialized_data = max(0, image.size_of_initialized_data + raw_delta)
    image.set_u32(image.optional_header_offset + 8, image.size_of_initialized_data)

    # ---- SizeOfImage
    last = max(image.sections, key=lambda s: s.virtual_end)
    image.size_of_image = align_up(last.virtual_end, section_align)
    image.set_u32(image.optional_header_offset + 56, image.size_of_image)

    update_checksum(image)

    result.mode = "rebuild"
    result.rsrc_growth = new_vsize - (orig_res_dir[1] or 0)
    return bytes(image.data), result


def _shift_directory_rvas(image: PEImage, sec, delta: int) -> None:
    """把落在 ``sec`` 旧 RVA 区间内的数据目录 RVA 平移 ``delta``。"""
    lo, hi = sec.virtual_address, sec.virtual_end
    for i in range(len(image.dirs)):
        rva, size = image.dirs[i]
        if rva and lo <= rva < hi:
            image.set_dir(i, rva + delta, size)
