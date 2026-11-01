"""``.ico`` 解析与 ``RT_ICON`` / ``RT_GROUP_ICON`` 的构造。

要点（也是现有补丁的一处缺陷来源）：``GRPICONDIR`` 里的宽高**必须**与图像数据本身一致，
所以这里一律从数据推导，不信任 ``.ico`` 目录项里记录的宽高。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Sequence

from .errors import ThemeError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: PNG IHDR 里的 color type -> 位深（用于填 GRPICONDIR 的 wBitCount）
_PNG_COLOR_DEPTH = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


@dataclass
class IconImage:
    """图标中的一幅图像；``data`` 为裸 DIB（无 BITMAPFILEHEADER）或整段 PNG。"""

    width: int
    height: int
    bit_count: int
    data: bytes

    @property
    def is_png(self) -> bool:
        return self.data[:8] == PNG_SIGNATURE


def _png_dimensions(data: bytes) -> tuple:
    if len(data) < 26:
        raise ThemeError("PNG 图标数据过短")
    width, height = struct.unpack_from(">II", data, 16)
    depth = data[24]
    color_type = data[25]
    channels = _PNG_COLOR_DEPTH.get(color_type, 4)
    return width, height, depth * channels


def _dib_dimensions(data: bytes) -> tuple:
    if len(data) < 16:
        raise ThemeError("DIB 图标数据过短")
    bi_size, bi_width, bi_height, bi_planes, bi_bit_count = struct.unpack_from("<IiiHH", data, 0)
    if bi_size < 12:
        raise ThemeError("DIB 头长度异常：%d" % bi_size)
    height = abs(bi_height) // 2  # DIB 的高度包含 AND 掩码
    return abs(bi_width), height, bi_bit_count


def image_dimensions(data: bytes) -> tuple:
    """从图像数据本身推导 (宽, 高, 位深)。"""
    if data[:8] == PNG_SIGNATURE:
        return _png_dimensions(data)
    return _dib_dimensions(data)


def parse_ico(path: str) -> List[IconImage]:
    """读取 ``.ico``，返回其中全部图像（保持文件内顺序）。"""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ThemeError("无法读取图标素材 %s：%s" % (path, exc)) from exc
    if len(raw) < 6:
        raise ThemeError("不是有效的 ICO 文件：%s" % path)
    reserved, kind, count = struct.unpack_from("<HHH", raw, 0)
    if reserved != 0 or kind != 1:
        raise ThemeError("不是有效的 ICO 文件（头标记异常）：%s" % path)
    if count == 0:
        raise ThemeError("ICO 内没有任何图像：%s" % path)
    if 6 + count * 16 > len(raw):
        raise ThemeError("ICO 目录越界：%s" % path)

    images: List[IconImage] = []
    for i in range(count):
        width, height, _colors, _r, _planes, _bpp, size, offset = struct.unpack_from(
            "<BBBBHHII", raw, 6 + i * 16
        )
        if size == 0 or offset + size > len(raw):
            raise ThemeError("ICO 第 %d 幅图像越界：%s" % (i, path))
        payload = raw[offset : offset + size]
        real_w, real_h, real_bpp = image_dimensions(payload)
        if (width or 256) != real_w or (height or 256) != real_h:
            # 目录项与数据不一致时以数据为准（现有补丁正是踩了这个坑）
            pass
        images.append(IconImage(width=real_w, height=real_h, bit_count=real_bpp, data=payload))
    return images


def _entry_byte(value: int) -> int:
    """GRPICONDIR 的宽/高字段：256 记作 0。"""
    if value >= 256:
        return 0
    if value <= 0:
        raise ThemeError("图标尺寸非法：%d" % value)
    return value


def _color_count(bit_count: int) -> int:
    if bit_count >= 8:
        return 0
    return 1 << max(bit_count, 1)


def make_group(images: Sequence[IconImage], ids: Sequence[int]) -> bytes:
    """由图像与对应资源 ID 生成 ``GRPICONDIR`` 资源数据。"""
    if len(images) != len(ids):
        raise ThemeError("图标数量与 ID 数量不一致")
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for img, icon_id in zip(images, ids):
        out += struct.pack(
            "<BBBBHHIH",
            _entry_byte(img.width),
            _entry_byte(img.height),
            _color_count(img.bit_count),
            0,
            1,
            img.bit_count,
            len(img.data),
            icon_id,
        )
    return bytes(out)


def parse_group(data: bytes) -> List[dict]:
    """解析 ``GRPICONDIR`` 资源数据（自检与对比用）。"""
    if len(data) < 6:
        raise ThemeError("GRPICONDIR 数据过短")
    _reserved, _kind, count = struct.unpack_from("<HHH", data, 0)
    if 6 + count * 14 > len(data):
        raise ThemeError("GRPICONDIR 目录越界")
    out = []
    for i in range(count):
        w, h, colors, _r, planes, bpp, size, icon_id = struct.unpack_from("<BBBBHHIH", data, 6 + i * 14)
        out.append(
            {
                "width": w or 256,
                "height": h or 256,
                "colors": colors,
                "planes": planes,
                "bit_count": bpp,
                "bytes": size,
                "icon_id": icon_id,
            }
        )
    return out
