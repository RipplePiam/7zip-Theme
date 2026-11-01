"""PE 文件结构的最小实用封装。

只覆盖 ResTuner 需要的部分：读头、节表、数据目录、RVA<->偏移换算，
以及少量定点写入辅助。不依赖第三方库。

坐标系约定
----------
* ``offset``  —— 文件内偏移
* ``rva``     —— 相对虚拟地址（ImageBase 已加载后的相对偏移）
"""
from __future__ import annotations

import struct
from typing import Dict, List, Optional, Sequence, Tuple

from .errors import PEError

#: 数据目录下标 -> 名称
DIR_NAMES: Dict[int, str] = {
    0: "EXPORT",
    1: "IMPORT",
    2: "RESOURCE",
    3: "EXCEPTION",
    4: "SECURITY",
    5: "BASERELOC",
    6: "DEBUG",
    7: "ARCH",
    8: "GLOBALPTR",
    9: "TLS",
    10: "LOADCFG",
    11: "BOUNDIMP",
    12: "IAT",
    13: "DELAYIMP",
    14: "CLR",
    15: "RESERVED",
}

PE32_MAGIC = 0x10B
PE32_PLUS_MAGIC = 0x20B

SECTION_SCN_CNT_INITIALIZED_DATA = 0x00000040
SECTION_SCN_MEM_EXECUTE = 0x20000000


def align_up(value: int, alignment: int) -> int:
    """向上对齐；alignment 必须是 2 的幂。"""
    if alignment <= 1:
        return value
    return (value + alignment - 1) & ~(alignment - 1)


class Section:
    """节表项。``header_offset`` 是它在文件里的位置，便于定点改写。"""

    __slots__ = (
        "name",
        "virtual_size",
        "virtual_address",
        "raw_size",
        "raw_ptr",
        "characteristics",
        "header_offset",
    )

    def __init__(
        self,
        name: str,
        virtual_size: int,
        virtual_address: int,
        raw_size: int,
        raw_ptr: int,
        characteristics: int,
        header_offset: int,
    ) -> None:
        self.name = name
        self.virtual_size = virtual_size
        self.virtual_address = virtual_address
        self.raw_size = raw_size
        self.raw_ptr = raw_ptr
        self.characteristics = characteristics
        self.header_offset = header_offset

    @property
    def span(self) -> int:
        """RVA 维度的跨度（取 VirtualSize 与 RawSize 的较大者）。"""
        return max(self.virtual_size, self.raw_size)

    @property
    def virtual_end(self) -> int:
        return self.virtual_address + self.span

    @property
    def raw_end(self) -> int:
        return self.raw_ptr + self.raw_size

    def has_initialized_data(self) -> bool:
        return bool(self.characteristics & SECTION_SCN_CNT_INITIALIZED_DATA)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<Section %s va=0x%x vs=0x%x raw=0x%x/0x%x>" % (
            self.name,
            self.virtual_address,
            self.virtual_size,
            self.raw_ptr,
            self.raw_size,
        )


class PEImage:
    """一个可读、可少量改写的 PE 映像。"""

    def __init__(self, data: bytes) -> None:
        self.data = bytearray(data)
        self.sections: List[Section] = []
        self.dirs: List[Tuple[int, int]] = []
        self._parse()

    # ------------------------------------------------------------------ 读

    @classmethod
    def from_path(cls, path: str) -> "PEImage":
        with open(path, "rb") as fh:
            return cls(fh.read())

    def _parse(self) -> None:
        d = self.data
        if len(d) < 0x40:
            raise PEError("文件太小，不是有效的 PE 文件")
        if d[0:2] != b"MZ":
            raise PEError("缺少 MZ 头，不是 PE 文件")
        self.e_lfanew = self.u32(0x3C)
        if self.e_lfanew + 24 > len(d):
            raise PEError("e_lfanew 越界")
        if d[self.e_lfanew : self.e_lfanew + 4] != b"PE\0\0":
            raise PEError("缺少 PE 签名")

        coff = self.e_lfanew + 4
        self.machine = self.u16(coff)
        self.number_of_sections = self.u16(coff + 2)
        self.timestamp = self.u32(coff + 4)
        self.optional_header_size = self.u16(coff + 16)
        self.characteristics = self.u16(coff + 18)

        opt = coff + 20
        self.optional_header_offset = opt
        if opt + 2 > len(d):
            raise PEError("可选头越界")
        self.magic = self.u16(opt)
        if self.magic not in (PE32_MAGIC, PE32_PLUS_MAGIC):
            raise PEError("不支持的可选头 Magic 0x%X" % self.magic)
        self.is_plus = self.magic == PE32_PLUS_MAGIC

        # 通用字段（PE32 与 PE32+ 位置相同）
        self.size_of_code = self.u32(opt + 4)
        self.size_of_initialized_data = self.u32(opt + 8)
        self.size_of_uninitialized_data = self.u32(opt + 12)
        self.entry_point = self.u32(opt + 16)
        self.base_of_code = self.u32(opt + 20)
        if self.is_plus:
            self.image_base = struct.unpack_from("<Q", d, opt + 24)[0]
        else:
            self.image_base = self.u32(opt + 28)
        self.section_alignment = self.u32(opt + 32)
        self.file_alignment = self.u32(opt + 36)
        self.size_of_image = self.u32(opt + 56)
        self.size_of_headers = self.u32(opt + 60)
        self.checksum_offset = opt + 64
        self.checksum = self.u32(opt + 64)
        self.subsystem = self.u16(opt + 68)
        self.dll_characteristics = self.u16(opt + 70)
        if self.is_plus:
            self.number_of_rva_and_sizes = self.u32(opt + 108)
            self.dir_base = opt + 112
        else:
            self.number_of_rva_and_sizes = self.u32(opt + 92)
            self.dir_base = opt + 96

        count = min(self.number_of_rva_and_sizes, 16)
        for i in range(count):
            self.dirs.append((self.u32(self.dir_base + i * 8), self.u32(self.dir_base + i * 8 + 4)))
        while len(self.dirs) < 16:
            self.dirs.append((0, 0))

        table = opt + self.optional_header_size
        if table + 40 * self.number_of_sections > len(d):
            raise PEError("节表越界")
        for i in range(self.number_of_sections):
            o = table + i * 40
            name = bytes(d[o : o + 8]).rstrip(b"\0").decode("latin-1")
            self.sections.append(
                Section(
                    name=name,
                    virtual_size=self.u32(o + 8),
                    virtual_address=self.u32(o + 12),
                    raw_size=self.u32(o + 16),
                    raw_ptr=self.u32(o + 20),
                    characteristics=self.u32(o + 36),
                    header_offset=o,
                )
            )

    def u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def set_u16(self, offset: int, value: int) -> None:
        struct.pack_into("<H", self.data, offset, value & 0xFFFF)

    def set_u32(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.data, offset, value & 0xFFFFFFFF)

    def get_dir(self, index: int) -> Tuple[int, int]:
        return self.dirs[index]

    def set_dir(self, index: int, rva: int, size: int) -> None:
        self.dirs[index] = (rva, size)
        self.set_u32(self.dir_base + index * 8, rva)
        self.set_u32(self.dir_base + index * 8 + 4, size)

    # ------------------------------------------------------- RVA <-> 偏移

    def section_of_rva(self, rva: int) -> Optional[Section]:
        for s in self.sections:
            if s.virtual_address <= rva < s.virtual_end:
                return s
        return None

    def section_of_offset(self, offset: int) -> Optional[Section]:
        for s in self.sections:
            if s.raw_ptr <= offset < s.raw_end:
                return s
        return None

    def section_by_name(self, name: str) -> Optional[Section]:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def rva_to_offset(self, rva: int) -> Optional[int]:
        if rva < self.size_of_headers:
            return rva
        s = self.section_of_rva(rva)
        if s is None:
            return None
        delta = rva - s.virtual_address
        if delta >= s.raw_size:
            return None
        return s.raw_ptr + delta

    def offset_to_rva(self, offset: int) -> Optional[int]:
        s = self.section_of_offset(offset)
        if s is None:
            return offset if offset < self.size_of_headers else None
        return s.virtual_address + (offset - s.raw_ptr)

    def read_rva(self, rva: int, size: int) -> bytes:
        off = self.rva_to_offset(rva)
        if off is None or off + size > len(self.data):
            raise PEError("RVA 0x%X 不可读" % rva)
        return bytes(self.data[off : off + size])

    # ------------------------------------------------------------ 一致性

    def sanity_check(self) -> List[str]:
        """返回问题列表；空列表表示结构自洽。"""
        problems: List[str] = []
        aligned_va = [s.virtual_address for s in self.sections]
        if aligned_va != sorted(aligned_va):
            problems.append("节表 VirtualAddress 不是升序")
        for s in self.sections:
            if s.raw_ptr and s.raw_size and s.raw_end > len(self.data):
                problems.append("节 %s 的原始数据越界" % s.name)
            if s.virtual_address % self.section_alignment:
                problems.append("节 %s 的 VirtualAddress 未按节对齐" % s.name)
            if s.raw_ptr % self.file_alignment:
                problems.append("节 %s 的 PointerToRawData 未按文件对齐" % s.name)
        last = max(self.sections, key=lambda x: x.virtual_end)
        expect_image = align_up(last.virtual_end, self.section_alignment)
        if expect_image != self.size_of_image:
            problems.append(
                "SizeOfImage=0x%X，按节表推算应为 0x%X" % (self.size_of_image, expect_image)
            )
        res = self.get_dir(2)
        rsrc = self.section_by_name(".rsrc")
        if rsrc is not None and res[0] != rsrc.virtual_address:
            problems.append(
                "RESOURCE 目录 RVA 0x%X 与 .rsrc 节 0x%X 不一致" % (res[0], rsrc.virtual_address)
            )
        return problems

    def describe(self) -> str:  # pragma: no cover - 调试用
        lines = [
            "PE32+ " if self.is_plus else "PE32  ",
            "sections=%d image=0x%X checksum=0x%X" % (self.number_of_sections, self.size_of_image, self.checksum),
        ]
        for s in self.sections:
            lines.append(
                "  %-8s va=0x%08X vs=0x%08X raw=0x%08X/0x%08X" % (s.name, s.virtual_address, s.virtual_size, s.raw_ptr, s.raw_size)
            )
        return "\n".join(lines)
