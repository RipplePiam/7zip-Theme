"""PE 校验和（CheckSum）计算。

算法与 ``CheckSumMappedFile`` 一致：把整个文件按 16 位字累加（Checksum 字段本身按 0 计），
进位折叠，最后加上文件长度。
"""
from __future__ import annotations

from .pe import PEImage


def compute_checksum(data: bytes, checksum_offset: int) -> int:
    """计算 PE 校验和。``data`` 中 ``checksum_offset`` 处的 4 字节会被视为 0。"""
    buf = bytearray(data)
    if 0 <= checksum_offset <= len(buf) - 4:
        buf[checksum_offset : checksum_offset + 4] = b"\0\0\0\0"

    total = 0
    length = len(buf)
    # 逐 16 位字累加（小端），每步折叠进位，避免溢出
    end = length - (length % 2)
    for i in range(0, end, 2):
        total += buf[i] | (buf[i + 1] << 8)
        total = (total & 0xFFFF) + (total >> 16)
    if length % 2:
        total += buf[-1]
        total = (total & 0xFFFF) + (total >> 16)

    total = (total & 0xFFFF) + (total >> 16)
    total += length
    return total & 0xFFFFFFFF


def update_checksum(image: PEImage) -> int:
    """就地写入校验和并返回新值。"""
    value = compute_checksum(bytes(image.data), image.checksum_offset)
    image.set_u32(image.checksum_offset, value)
    image.checksum = value
    return value
