"""``.bmp`` 素材处理：剥掉 ``BITMAPFILEHEADER`` 并进行兼容性校验。

PE 里 ``RT_BITMAP`` 存的是**去掉 14 字节文件头**的 DIB。
直接把整个 ``.bmp`` 写进资源会导致 7zFM 工具栏错乱或崩溃。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .errors import ThemeError

BITMAPFILEHEADER_SIZE = 14
BI_RGB = 0


@dataclass
class Bitmap:
    """一份可直接写入 ``RT_BITMAP`` 的 DIB。"""

    width: int
    height: int
    bit_count: int
    compression: int
    palette: bytes
    data: bytes

    @property
    def size_image(self) -> int:
        if len(self.data) >= 40:
            return struct.unpack_from("<I", self.data, 20)[0]
        return 0

    @property
    def effective_height(self) -> int:
        """逻辑高度。DIB 若把 AND 掩码也算进高度（高度 = 2 × 宽度），这里折半。"""
        raw = abs(self.height)
        if self.width and raw == 2 * self.width:
            return raw // 2
        return raw


def parse_dib(data: bytes) -> Bitmap:
    """解析资源里的 DIB（无文件头）。"""
    if len(data) < 40:
        raise ThemeError("DIB 数据过短（%d 字节）" % len(data))
    bi_size, width, height, _planes, bit_count, compression = struct.unpack_from("<IiiHHI", data, 0)
    if bi_size < 40:
        raise ThemeError("不支持 BITMAPCOREHEADER 之前的 DIB 头：biSize=%d" % bi_size)
    palette_len = 0
    if bit_count <= 8 and compression == BI_RGB:
        palette_len = (1 << bit_count) * 4
    palette = data[bi_size : bi_size + palette_len]
    return Bitmap(
        width=width,
        height=height,
        bit_count=bit_count,
        compression=compression,
        palette=palette,
        data=data,
    )


def load_bmp(path: str) -> Bitmap:
    """读取 ``.bmp`` 并返回值 DIB 部分。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < BITMAPFILEHEADER_SIZE + 40:
        raise ThemeError("BMP 文件过短：%s" % path)
    if raw[0:2] != b"BM":
        raise ThemeError("不是 BMP 文件：%s" % path)
    (file_size, _r1, _r2, pixel_offset) = struct.unpack_from("<IHHI", raw, 2)
    if file_size and file_size != len(raw):
        # 只警告不阻断：某些编辑器写出的 bfSize 不准确
        pass
    if pixel_offset < BITMAPFILEHEADER_SIZE + 40 or pixel_offset > len(raw):
        raise ThemeError("BMP 像素偏移异常（%d）：%s" % (pixel_offset, path))
    dib = raw[BITMAPFILEHEADER_SIZE:]

    bi_size, width, height, _planes, bit_count, compression = struct.unpack_from("<IiiHHI", dib, 0)
    if bi_size < 40:
        raise ThemeError("不支持 BITMAPCOREHEADER 之前的 BMP 头：%s" % path)
    if compression != BI_RGB:
        raise ThemeError("仅支持未压缩的 BI_RGB 位图：%s" % path)

    palette_len = (1 << bit_count) * 4 if bit_count <= 8 else 0
    palette = dib[bi_size : bi_size + palette_len]
    return Bitmap(
        width=width,
        height=height,
        bit_count=bit_count,
        compression=compression,
        palette=palette,
        data=dib,
    )


def evaluate(target_dib: bytes, candidate: Bitmap) -> Tuple[Optional[str], List[str]]:
    """评估素材能否替换目标位图。

    返回 ``(阻断原因, 警告列表)``；阻断原因为 ``None`` 表示可以替换。

    规则：
    * **宽高必须一致**——尺寸变了会破坏 7zFM 的工具栏布局，属于硬错误；
    * 位深、调色板允许不同——整幅 DIB（含调色板）会被整体写入，素材自带配色，
      这正是主题"换肤"想要的效果；仅在差异较大时给出提示。
    """
    warnings: List[str] = []
    try:
        target = parse_dib(target_dib)
    except ThemeError as exc:
        return "目标位图无法解析：%s" % exc, warnings

    if target.width != candidate.width:
        return "宽度不一致：目标 %d / 素材 %d" % (target.width, candidate.width), warnings
    if target.effective_height != candidate.effective_height:
        return (
            "高度不一致：目标 %d / 素材 %d" % (target.effective_height, candidate.effective_height),
            warnings,
        )

    if target.bit_count != candidate.bit_count:
        warnings.append("位深 %d → %d" % (target.bit_count, candidate.bit_count))
    if target.palette != candidate.palette:
        warnings.append("调色板被替换（%d → %d 项）" % (len(target.palette) // 4, len(candidate.palette) // 4))
    if target.size_image and candidate.size_image and target.size_image != candidate.size_image:
        warnings.append("biSizeImage %d → %d" % (target.size_image, candidate.size_image))
    return None, warnings
