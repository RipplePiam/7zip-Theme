"""输出自检与资源级比对。

自检是**写回前的硬门槛**：任何一项不通过都必须放弃写回，原文件保持不变。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .errors import VerifyError
from .pe import PEImage
from .rsrc import Resource, ResourceKey, parse_resources, resource_map

Digest = Dict[ResourceKey, Tuple[int, str]]


def digest(resources: Sequence[Resource]) -> Digest:
    return {r.key: (len(r.data), hashlib.sha1(r.data).hexdigest()) for r in resources}


def digest_of_bytes(data: bytes) -> Digest:
    return digest(parse_resources(PEImage(data)))


@dataclass
class Diff:
    missing: List[ResourceKey] = field(default_factory=list)
    extra: List[ResourceKey] = field(default_factory=list)
    changed: List[ResourceKey] = field(default_factory=list)

    @property
    def equal(self) -> bool:
        return not (self.missing or self.extra or self.changed)

    def describe(self, limit: int = 12) -> str:
        parts = []
        if self.missing:
            parts.append("缺失 %d 项：%s" % (len(self.missing), _brief(self.missing, limit)))
        if self.extra:
            parts.append("多出 %d 项：%s" % (len(self.extra), _brief(self.extra, limit)))
        if self.changed:
            parts.append("内容不同 %d 项：%s" % (len(self.changed), _brief(self.changed, limit)))
        return "；".join(parts) if parts else "完全一致"


def _brief(keys: Sequence[ResourceKey], limit: int) -> str:
    shown = ", ".join("%s/%s/%s" % k for k in keys[:limit])
    return shown + ("…" if len(keys) > limit else "")


def diff(a: Digest, b: Digest) -> Diff:
    out = Diff()
    out.missing = [k for k in a if k not in b]
    out.extra = [k for k in b if k not in a]
    out.changed = [k for k in a if k in b and a[k] != b[k]]
    return out


# ---------------------------------------------------------------- 硬性自检


def check_structure(data: bytes, *, expect_plus: bool = True) -> List[str]:
    """结构自检；返回问题列表。"""
    problems: List[str] = []
    try:
        image = PEImage(data)
    except Exception as exc:  # noqa: BLE001 - 任何解析异常都算失败
        return ["无法解析为 PE：%s" % exc]
    if expect_plus and not image.is_plus:
        problems.append("输出不是 PE32+")
    problems.extend(image.sanity_check())
    if image.checksum:
        from .checksum import compute_checksum

        calc = compute_checksum(bytes(image.data), image.checksum_offset)
        if calc != image.checksum:
            problems.append("校验和不匹配：头内 0x%08X / 实算 0x%08X" % (image.checksum, calc))
    return problems


def check_expected(data: bytes, expected: Sequence[Resource]) -> List[str]:
    """输出里的资源集合必须与"预期集合"完全一致。"""
    problems: List[str] = []
    try:
        actual = parse_resources(PEImage(data))
    except Exception as exc:  # noqa: BLE001
        return ["输出资源无法解析：%s" % exc]
    d = diff(digest(expected), digest(actual))
    if not d.equal:
        problems.append("资源集合与预期不一致：" + d.describe())
    return problems


def check_preserved(
    original: Sequence[Resource],
    output: Sequence[Resource],
    changed: Set[ResourceKey],
) -> List[str]:
    """未参与替换的资源必须逐字节保持不变。"""
    before = resource_map(original)
    after = resource_map(output)
    problems: List[str] = []
    for key, res in before.items():
        if key in changed:
            continue
        other = after.get(key)
        if other is None:
            problems.append("资源被意外删除：%s" % (key,))
        elif other.data != res.data:
            problems.append("资源被意外修改：%s" % (key,))
    return problems


def verify_output(
    new_data: bytes,
    original: Sequence[Resource],
    expected: Sequence[Resource],
    changed: Set[ResourceKey],
) -> None:
    """综合自检；不通过则抛 :class:`VerifyError`。"""
    problems: List[str] = []
    problems.extend(check_structure(new_data))
    problems.extend(check_expected(new_data, expected))
    problems.extend(check_preserved(original, parse_resources(PEImage(new_data)), changed))
    if problems:
        raise VerifyError("输出自检未通过：\n  - " + "\n  - ".join(problems))


def summarize(new_data: bytes, baseline: Optional[bytes] = None) -> str:
    """给日志用的一行摘要。"""
    try:
        image = PEImage(new_data)
    except Exception:  # noqa: BLE001
        return "无法解析"
    text = "%d 字节，SizeOfImage=0x%X，校验和 0x%08X" % (
        len(new_data),
        image.size_of_image,
        image.checksum,
    )
    if baseline is not None:
        text += "（原 %d 字节）" % len(baseline)
    return text
