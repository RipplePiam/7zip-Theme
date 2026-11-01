"""目标目录的定位与体检。

"体检"要回答四个问题：
1. 这是不是一个 x64 的 7-Zip 目录？
2. 是哪个版本？
3. 现在是不是已经打过主题补丁？
4. 能不能写（权限 / 是否被占用 / 是否带数字签名）？
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .errors import TargetError
from .pe import PEImage
from .rsrc import RT_BITMAP, RT_GROUP_ICON, RT_ICON, Resource, parse_resources

REQUIRED_FILES = ("7z.dll", "7zFM.exe")


@dataclass(frozen=True)
class Fingerprint:
    """一个"已验证版本"的结构特征。

    光比对版本号不够：同一个版本号可能来自不同构建（x86/x64、第三方重打包、被改过的文件）。
    这里再核对一次"图标组数 / 图标数 / 类型索引表哈希 / 工具栏位图 ID 集合"，
    全部吻合才认为是我们验证过的那种结构。
    """

    dll_group_count: int
    dll_icon_count: int
    fm_bitmap_ids: Tuple[int, ...]
    dll_type_map_sha1: str

    def differences(self, info: "TargetInfo") -> List[str]:
        """返回与目标的差异说明；空列表表示完全吻合。"""
        dll = info.files.get("7z.dll")
        fm = info.files.get("7zFM.exe")
        if dll is None or fm is None:
            return ["缺少 7z.dll 或 7zFM.exe"]
        problems: List[str] = []
        if dll.group_count != self.dll_group_count:
            problems.append("图标组数 %d（期望 %d）" % (dll.group_count, self.dll_group_count))
        if dll.icon_count != self.dll_icon_count:
            problems.append("图标数 %d（期望 %d）" % (dll.icon_count, self.dll_icon_count))
        if dll.type_map_sha1 != self.dll_type_map_sha1:
            problems.append("类型索引表哈希不一致")
        if tuple(fm.bitmap_ids) != self.fm_bitmap_ids:
            problems.append("工具栏位图 ID 集合不一致")
        return problems

    def matches(self, info: "TargetInfo") -> bool:
        return not self.differences(info)


#: 已验证过、结构确定的官方版本。
#: 25.01 来自 7-zip.org 官方包；26.05 来自用户机器上由本工具留下的官方原版备份
#: （两者结构完全一致，逐字节复现验证见 docs/7z2501-补丁分析.md 的"26.05 复核"一节）。
VERIFIED_VERSIONS: Dict[str, Fingerprint] = {
    "25.01": Fingerprint(
        dll_group_count=27,
        dll_icon_count=56,
        fm_bitmap_ids=(100, 101, 102, 103, 104, 105, 106, 150, 151, 152, 153, 154, 155, 156, 190),
        dll_type_map_sha1="59592a87191f3bdc88aafda0847b3f5173d3dc11",
    ),
    "26.05": Fingerprint(
        dll_group_count=27,
        dll_icon_count=56,
        fm_bitmap_ids=(100, 101, 102, 103, 104, 105, 106, 150, 151, 152, 153, 154, 155, 156, 190),
        dll_type_map_sha1="59592a87191f3bdc88aafda0847b3f5173d3dc11",
    ),
}

#: 打过主题补丁的基本特征（与原版差异极大，不可能误判）
PATCHED_ICON_THRESHOLD = 100
PATCHED_GROUP_ENTRIES_THRESHOLD = 8

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_INVALID_HANDLE = ctypes.c_void_p(-1).value


@dataclass
class VersionInfo:
    file_version: Tuple[int, int, int, int] = (0, 0, 0, 0)
    product_version: Tuple[int, int, int, int] = (0, 0, 0, 0)
    strings: Dict[str, str] = field(default_factory=dict)

    @property
    def display(self) -> str:
        """优先用文件自带的 FileVersion 字符串（7-Zip 写作 "25.01"），否则按定点数格式化。"""
        declared = self.strings.get("FileVersion") or self.strings.get("ProductVersion")
        if declared:
            return declared.strip()
        major, minor, build, revision = self.file_version
        if major == 0 and minor == 0:
            return ""
        if revision:
            return "%d.%02d.%d.%d" % (major, minor, build, revision)
        return "%d.%02d" % (major, minor)

    @property
    def company(self) -> str:
        return self.strings.get("CompanyName", "")

    @property
    def product(self) -> str:
        return self.strings.get("ProductName", "")

    @property
    def description(self) -> str:
        return self.strings.get("FileDescription", "")


def _align(value: int, base: int = 4) -> int:
    return (value + base - 1) & ~(base - 1)


def _read_key(buf: bytes, off: int, limit: int) -> Tuple[str, int]:
    """读一个以 NUL 结尾的 UTF-16 键名，返回 (字符串, 续读位置)。"""
    chars: List[str] = []
    pos = off
    while pos + 1 < limit:
        ch = struct.unpack_from("<H", buf, pos)[0]
        pos += 2
        if ch == 0:
            break
        chars.append(chr(ch))
    return "".join(chars), pos


def _read_version_block(buf: bytes, off: int, end: int, path, out, fixed) -> None:
    """递归遍历 VS_VERSIONINFO。

    块结构：``wLength(2) wValueLength(2) wType(2) szKey(NUL 结尾 UTF-16) [padding] Value``

    需要区分的三种块：
    * ``VS_VERSION_INFO``：值是 VS_FIXEDFILEINFO(52B)，其后才是子块；
    * 容器（``StringFileInfo`` / ``StringTable``）：wValueLength == 0，值区就是子块；
    * 叶子字符串（``CompanyName`` 等）：wType == 1 且 wValueLength > 0。
    """
    while off + 6 <= end:
        wlen, vlen, wtype = struct.unpack_from("<HHH", buf, off)
        if wlen == 0 or off + wlen > len(buf):
            break
        block_end = off + wlen
        key, after_key = _read_key(buf, off + 6, block_end)
        val_off = _align(after_key)

        if key == "VS_VERSION_INFO":
            if vlen >= 52 and val_off + 52 <= len(buf):
                signature = struct.unpack_from("<I", buf, val_off)[0]
                if signature == 0xFEEF04BD:
                    ms, ls, pms, pls = struct.unpack_from("<IIII", buf, val_off + 8)
                    fixed["file"] = (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
                    fixed["product"] = (pms >> 16, pms & 0xFFFF, pls >> 16, pls & 0xFFFF)
            _read_version_block(buf, _align(val_off + vlen), block_end, path + [key], out, fixed)
        elif vlen == 0:
            _read_version_block(buf, val_off, block_end, path + [key], out, fixed)
        elif wtype == 1:
            text = buf[val_off : val_off + vlen * 2].decode("utf-16-le", "ignore").rstrip("\0")
            out.append((path + [key], text))
        off = _align(block_end)


def read_version_info(version_data: bytes) -> VersionInfo:
    """解析 ``RT_VERSION`` 资源。"""
    info = VersionInfo()
    fixed: Dict[str, Tuple[int, int, int, int]] = {}
    pairs: List[Tuple[List[str], str]] = []
    try:
        _read_version_block(version_data, 0, len(version_data), [], pairs, fixed)
    except Exception:  # noqa: BLE001 - 版本资源不值得让整个流程失败
        return info
    info.file_version = fixed.get("file", (0, 0, 0, 0))
    info.product_version = fixed.get("product", (0, 0, 0, 0))
    for path, text in pairs:
        if len(path) >= 4 and path[-2].upper() not in ("STRINGFILEINFO",):
            if path[-2].upper().startswith("0"):
                info.strings[path[-1]] = text
    return info


@dataclass
class FileStatus:
    """单个目标文件的体检结果。"""

    name: str
    path: str
    size: int
    is_plus: bool
    patched: bool
    signed: bool
    writable: bool
    locked: bool
    resource_count: int
    icon_count: int = 0
    group_count: int = 0
    max_group_entries: int = 0
    bitmap_ids: List[int] = field(default_factory=list)
    type_map_sha1: Optional[str] = None

    def describe(self) -> str:
        bits = ["%s" % _size(self.size)]
        bits.append("已打补丁" if self.patched else "官方原版")
        if self.signed:
            bits.append("有数字签名")
        if self.locked:
            bits.append("被占用")
        if not self.writable:
            bits.append("不可写")
        return " · ".join(bits)


@dataclass
class TargetInfo:
    directory: str
    version: VersionInfo
    files: Dict[str, FileStatus]
    warnings: List[str] = field(default_factory=list)

    @property
    def is_plus(self) -> bool:
        return all(f.is_plus for f in self.files.values())

    @property
    def any_patched(self) -> bool:
        return any(f.patched for f in self.files.values())

    @property
    def all_patched(self) -> bool:
        return bool(self.files) and all(f.patched for f in self.files.values())

    @property
    def version_known(self) -> bool:
        """版本号是否在已验证清单里（不代表结构也对得上）。"""
        return self.version.display in VERIFIED_VERSIONS

    @property
    def fingerprint_problems(self) -> List[str]:
        """与清单里记录的结构指纹的差异；版本未知时返回空列表。"""
        rule = VERIFIED_VERSIONS.get(self.version.display)
        return rule.differences(self) if rule else []

    @property
    def verified_version(self) -> bool:
        """版本号 + 结构指纹都吻合，才叫"已验证"。"""
        return self.version_known and not self.fingerprint_problems

    def summary(self) -> str:
        ver = self.version.display or "未知版本"
        arch = "x64" if self.is_plus else "非 x64"
        state = "已打主题补丁" if self.all_patched else ("部分已打补丁" if self.any_patched else "官方原版")
        if self.all_patched:
            # 已经改过的文件当然和"官方结构指纹"不同，此时再提"指纹不符"只会误导
            mark = ""
        elif not self.version_known:
            mark = "（未验证版本）"
        elif self.fingerprint_problems:
            mark = "（结构指纹不符）"
        else:
            mark = ""
        return "7-Zip %s %s · %s%s" % (ver, arch, state, mark)


def _size(value: int) -> str:
    return "%.2f MB" % (value / 1024 / 1024) if value >= 1024 * 1024 else "%.1f KB" % (value / 1024)


# ------------------------------------------------------------------ 定位目录


def find_install_dir() -> Optional[str]:
    """按注册表 -> App Paths -> 默认路径依次探测。"""
    candidates: List[str] = []
    try:
        import winreg

        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for value_name in ("Path64", "Path"):
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip", 0, winreg.KEY_READ | view
                    ) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                        if value:
                            candidates.append(value)
                except OSError:
                    continue
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\7zFM.exe",
                    0,
                    winreg.KEY_READ | view,
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if value:
                        candidates.append(os.path.dirname(value))
            except OSError:
                pass
    except ImportError:  # pragma: no cover - 非 Windows
        pass

    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "7-Zip"))

    for path in candidates:
        if path and all(os.path.isfile(os.path.join(path, f)) for f in REQUIRED_FILES):
            return os.path.abspath(path)
    return None


# -------------------------------------------------------------------- 体检


def is_admin() -> bool:
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def is_locked(path: str) -> bool:
    """尝试以"独占"方式打开；失败即说明被别的进程占用。"""
    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    handle = _k32.CreateFileW(path, GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    if handle in (_INVALID_HANDLE, None, 0, -1):
        return True
    _k32.CloseHandle(handle)
    return False


def is_writable(directory: str) -> bool:
    probe = os.path.join(directory, ".restuner-write-test.tmp")
    try:
        with open(probe, "wb") as fh:
            fh.write(b"x")
        os.remove(probe)
        return True
    except OSError:
        return False


def _theme_bitmap_digest(theme, resource_id: int) -> Optional[str]:
    if theme is None:
        return None
    path = theme.bitmap_path(resource_id)
    if not path:
        return None
    import hashlib

    from .bmp import load_bmp

    try:
        return hashlib.sha1(load_bmp(path).data).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def inspect_file(name: str, path: str, theme=None) -> FileStatus:
    with open(path, "rb") as fh:
        data = fh.read()
    image = PEImage(data)
    resources = parse_resources(image)
    signed = image.get_dir(4)[1] != 0

    icons = [r for r in resources if r.type == RT_ICON]
    groups = [r for r in resources if r.type == RT_GROUP_ICON]
    bitmaps = [r for r in resources if r.type == RT_BITMAP]

    max_entries = 0
    from .icon import parse_group

    for g in groups:
        try:
            max_entries = max(max_entries, len(parse_group(g.data)))
        except Exception:  # noqa: BLE001
            continue

    patched = False
    type_map = None
    if name.lower() == "7z.dll":
        from .patcher import type_map_digest

        type_map = type_map_digest(resources)
        if len(icons) >= PATCHED_ICON_THRESHOLD:
            patched = True
    if name.lower() == "7zfm.exe":
        expected = _theme_bitmap_digest(theme, 100)
        target = next((b for b in bitmaps if b.name == 100), None)
        if expected and target is not None:
            import hashlib

            patched = hashlib.sha1(target.data).hexdigest() == expected
    if max_entries >= PATCHED_GROUP_ENTRIES_THRESHOLD and name.lower() == "7z.dll":
        patched = True

    return FileStatus(
        name=name,
        path=path,
        size=len(data),
        is_plus=image.is_plus,
        patched=patched,
        signed=signed,
        writable=os.access(path, os.W_OK),
        locked=is_locked(path),
        resource_count=len(resources),
        icon_count=len(icons),
        group_count=len(groups),
        max_group_entries=max_entries,
        bitmap_ids=sorted(int(b.name) for b in bitmaps if isinstance(b.name, int)),
        type_map_sha1=type_map,
    )


def inspect(directory: str, theme=None) -> TargetInfo:
    """对目标目录做整体体检；缺文件时抛 :class:`TargetError`。"""
    if not os.path.isdir(directory):
        raise TargetError("目录不存在：%s" % directory)
    missing = [f for f in REQUIRED_FILES if not os.path.isfile(os.path.join(directory, f))]
    if missing:
        raise TargetError("目录里缺少 %s，这不像是 7-Zip 的安装目录" % "、".join(missing))

    files: Dict[str, FileStatus] = {}
    for name in REQUIRED_FILES:
        files[name] = inspect_file(name, os.path.join(directory, name), theme=theme)

    version = VersionInfo()
    dll_path = os.path.join(directory, "7z.dll")
    try:
        image = PEImage.from_path(dll_path)
        for res in parse_resources(image):
            if isinstance(res.type, int) and res.type == 16:
                version = read_version_info(res.data)
                break
    except Exception:  # noqa: BLE001
        pass

    warnings: List[str] = []
    if not all(f.is_plus for f in files.values()):
        warnings.append("目标不是 64 位 PE，本工具目前只支持 x64")
    if any(f.signed for f in files.values()):
        warnings.append("目标带数字签名；修改资源后签名必然失效，本工具会剥离签名表")
    if not is_writable(directory):
        warnings.append("目标目录不可写，需要以管理员身份运行")

    return TargetInfo(directory=directory, version=version, files=files, warnings=warnings)
