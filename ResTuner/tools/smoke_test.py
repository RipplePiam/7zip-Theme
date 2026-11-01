#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟测试：证明产出文件不只是"结构合法"，而是真的能被 Windows 加载与使用。

1. 数据目录一致性（每个目录的 RVA 都落在某个节区内，且不越界）
2. ``LoadLibrary`` 加载 7z.dll（走完加载器：节区映射 + 重定位 + DllMain）
3. 把 7z.exe 与目标 7z.dll 放进临时目录，跑 ``7z.exe i``（真实功能验证）
4. 按 Explorer 的方式解析每个图标组（LookupIconIdFromDirectoryEx + CreateIconFromResourceEx）

用法::

    python tools/smoke_test.py                       # 先应用主题到临时目录，再验证
    python tools/smoke_test.py --dll path\\to\\7z.dll  # 只验证指定的 DLL

仅 Windows 下可用。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from restuner import patcher  # noqa: E402
from restuner.pe import PEImage  # noqa: E402
from restuner.theme import Theme  # noqa: E402

DIR_NAMES = {
    0: "EXPORT", 1: "IMPORT", 2: "RESOURCE", 3: "EXCEPTION", 4: "SECURITY", 5: "BASERELOC",
    6: "DEBUG", 7: "ARCH", 8: "GLOBALPTR", 9: "TLS", 10: "LOADCFG", 11: "BOUNDIMP", 12: "IAT",
    13: "DELAYIMP", 14: "CLR", 15: "RESERVED",
}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.LoadLibraryW.restype = wintypes.HMODULE
kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
kernel32.LoadLibraryExW.restype = wintypes.HMODULE
kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
kernel32.FindResourceW.restype = ctypes.c_void_p
kernel32.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
kernel32.LoadResource.restype = ctypes.c_void_p
kernel32.LoadResource.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
kernel32.LockResource.restype = ctypes.c_void_p
kernel32.LockResource.argtypes = [ctypes.c_void_p]
kernel32.SizeofResource.restype = wintypes.DWORD
kernel32.SizeofResource.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
user32.LookupIconIdFromDirectoryEx.restype = ctypes.c_uint
user32.LookupIconIdFromDirectoryEx.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.CreateIconFromResourceEx.restype = wintypes.HICON
user32.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                            wintypes.DWORD, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.DestroyIcon.argtypes = [wintypes.HICON]


def _name_ptr(value):
    if isinstance(value, int):
        return ctypes.c_void_p(value)
    return ctypes.cast(ctypes.c_wchar_p(value), ctypes.c_void_p)


def dir_consistency(path: str):
    image = PEImage.from_path(path)
    problems = []
    for index, (rva, size) in enumerate(image.dirs):
        if not rva:
            continue
        section = image.section_of_rva(rva)
        if section is None:
            problems.append("目录 %s 的 RVA 0x%X 不在任何节区内" % (DIR_NAMES.get(index, index), rva))
            continue
        if rva + size > section.virtual_address + max(section.virtual_size, section.raw_size):
            problems.append("目录 %s 跨越节区边界" % DIR_NAMES.get(index, index))
    return problems


def load_dll(path: str) -> None:
    handle = kernel32.LoadLibraryW(path)
    if not handle:
        raise OSError("LoadLibraryW 失败，GetLastError=%d" % ctypes.get_last_error())
    kernel32.FreeLibrary(handle)


def check_icons(path: str):
    handle = kernel32.LoadLibraryExW(path, None, 0x00000002)
    if not handle:
        raise OSError("LoadLibraryEx 失败，GetLastError=%d" % ctypes.get_last_error())
    ok = fail = 0
    failures = []
    for group in range(0, 40):
        resource = None
        for name in (str(group), group):
            resource = kernel32.FindResourceW(handle, _name_ptr(name), _name_ptr(14))
            if resource:
                break
        if not resource:
            continue
        data = kernel32.LockResource(kernel32.LoadResource(handle, resource))
        for cx in (16, 24, 32, 48, 256):
            icon_id = user32.LookupIconIdFromDirectoryEx(ctypes.c_void_p(data), True, cx, cx, 0)
            if not icon_id:
                failures.append((group, cx, "LookupIconId 返回 0"))
                fail += 1
                continue
            icon_res = kernel32.FindResourceW(handle, _name_ptr(icon_id), _name_ptr(3))
            if not icon_res:
                failures.append((group, cx, "找不到 RT_ICON %s" % icon_id))
                fail += 1
                continue
            size = kernel32.SizeofResource(handle, icon_res)
            payload = kernel32.LockResource(kernel32.LoadResource(handle, icon_res))
            hicon = user32.CreateIconFromResourceEx(
                ctypes.c_void_p(payload), size, True, 0x00030000, cx, cx, 0)
            if not hicon:
                failures.append((group, cx, "CreateIconFromResourceEx 失败"))
                fail += 1
            else:
                ok += 1
                user32.DestroyIcon(hicon)
    kernel32.FreeLibrary(handle)
    return ok, fail, failures


def run_7z(dll_path: str, workdir: str):
    seven = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "7-Zip", "7z.exe")
    if not os.path.isfile(seven):
        return None
    os.makedirs(workdir, exist_ok=True)
    shutil.copy2(seven, os.path.join(workdir, "7z.exe"))
    shutil.copy2(dll_path, os.path.join(workdir, "7z.dll"))
    return subprocess.run(
        [os.path.join(workdir, "7z.exe"), "i"],
        capture_output=True, text=True, encoding="mbcs", errors="replace", cwd=workdir,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="ResTuner 冒烟测试")
    parser.add_argument("--dll", default=None, help="直接指定要验证的 7z.dll（默认先用主题现做一个）")
    parser.add_argument("--keep", default=os.path.join(ROOT, "out", "smoke"), help="中间文件目录")
    args = parser.parse_args()

    if sys.platform != "win32":
        sys.stderr.write("仅支持 Windows\n")
        return 2

    dll_path = args.dll
    if not dll_path:
        sample = os.path.join(ROOT, "assets", "7z2501-x64", "7z.dll")
        if not os.path.isfile(sample):
            sys.stderr.write("缺少样例 %s，请用 --dll 指定\n" % sample)
            return 2
        theme = Theme(os.path.join(ROOT, "assets"))
        with open(sample, "rb") as fh:
            data = fh.read()
        result = patcher.patch_dll(data, theme)
        os.makedirs(args.keep, exist_ok=True)
        dll_path = os.path.join(args.keep, "7z.dll")
        with open(dll_path, "wb") as fh:
            fh.write(result.data)
        print("已生成：%s（%d 字节）" % (dll_path, len(result.data)))

    print("\n1. 数据目录一致性")
    problems = dir_consistency(dll_path)
    print("   %s" % ("OK" if not problems else "；".join(problems)))

    print("\n2. LoadLibrary")
    try:
        load_dll(dll_path)
        print("   OK")
    except OSError as exc:
        print("   FAILED：%s" % exc)
        return 1

    print("\n3. 7z.exe i")
    proc = run_7z(dll_path, os.path.join(args.keep, "run"))
    if proc is None:
        print("   跳过（没找到已安装的 7z.exe）")
    else:
        first = [line for line in (proc.stdout or "").replace("\r", "").split("\n") if line.strip()][:1]
        print("   rc=%d %s" % (proc.returncode, first[0] if first else ""))
        if proc.returncode != 0:
            print("   stderr: %s" % (proc.stderr or "")[:300])
            return 1

    print("\n4. 图标解码")
    ok, fail, failures = check_icons(dll_path)
    print("   成功 %d / 失败 %d" % (ok, fail))
    for item in failures[:8]:
        print("     %s" % (item,))

    return 0 if (fail == 0 and not problems) else 1


if __name__ == "__main__":
    raise SystemExit(main())
