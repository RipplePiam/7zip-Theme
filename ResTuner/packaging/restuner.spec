# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出单个自包含的 ResTuner.exe。

要点：
* ``console=False`` —— GUI 程序，不留黑框；
* ``datas`` 只带运行时真正需要的素材（``assets/filetype`` 与 ``assets/toolbar``），
  测试用的 ``assets/7z2501-*`` 样例不会被打进去；
* ``excludes`` 砍掉明显用不到的重量级模块，减小体积。
"""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "assets")

a = Analysis(
    [os.path.join(ROOT, "run_gui.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[
        (os.path.join(ASSETS, "filetype"), os.path.join("assets", "filetype")),
        (os.path.join(ASSETS, "toolbar"), os.path.join("assets", "toolbar")),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "pefile",
        "setuptools",
        "pip",
        "pkg_resources",
        "numpy",
        "pandas",
        "matplotlib",
        "PIL",
        "unittest",
        "pydoc",
        "doctest",
        "sqlite3",
        "email",
        "http",
        "xml",
        "test",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ResTuner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ASSETS, "filetype", "7z.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
)
