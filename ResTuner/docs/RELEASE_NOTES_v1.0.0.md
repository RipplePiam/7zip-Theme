# ResTuner 1.0 · 7-Zip 主题一键补丁工具

> 首个版本。**这个 Release 之后基本不需要再更新** —— 工具会从目标文件自身读取图标索引表，
> 以后 7-Zip 发新版直接复用，不用等补丁作者跟进。

给 7-Zip 换上 **Windows 10 Default 文件图标 + Glyfz 2016 工具栏图标**：
装好官方 7-Zip，点一下就好。

## 下载

| | |
|---|---|
| 文件 | `ResTuner.exe` |
| 大小 | 11.51 MB（12,068,842 字节） |
| SHA-256 | `F7C4B065FB37AD8B0A18E0913CA0ED66348EDA7CEEECA58BA6B0CD314EF97437` |
| 系统要求 | Windows 10 / 11 x64，**无需安装 Python** |

> 单文件 exe，启动时自解压到 `%TEMP%`。若被安全软件拦截（提示 `Failed to extract VCRUNTIME140.dll`），
> 请加白名单；也可以下载源码包用 `ResTuner/run_gui.bat` 直接跑。

## 用法

1. 照常安装官方 7-Zip（x64）
2. 运行 `ResTuner.exe`；要写 `C:\Program Files` 时，用管理员身份运行（界面右下角「以管理员身份重启」）
3. 点 **应用主题** → 按提示 **刷新图标缓存**（必要时重启资源管理器）

## 它改了什么

7-Zip 那套"复古"界面本质上是 PE 文件里的资源，所以换肤 = 换资源，**没有一行代码补丁**：

| 文件 | 资源 | 效果 |
|---|---|---|
| `7z.dll` | `RT_ICON` + `RT_GROUP_ICON`（27 种格式） | 资源管理器里的文件图标（`.7z`、`.zip`、`.rar`…） |
| `7zFM.exe` | `RT_BITMAP` #100–106 / #150–156 | 文件管理器的 7 个工具栏按钮（大、小两套） |

原版每种格式只有 32×32 / 16×16 两个 8 位色小图标；这里换成 **8 个尺寸**
（256/64/48/40/32/24/20/16，32 位色，256 用 PNG 压缩）。

## 为什么以后不用等更新

- 扩展名与图标索引的对应关系，**直接从目标文件自己的 `RT_STRING` 里读**，7-Zip 新增格式会自动跟上
- 已验证：`25.01`、`26.05`（各带结构指纹校验）；没见过的版本走自适应模式，改之前会要你确认
- 只用 Python 标准库实现，零第三方依赖

## 安全

- **写回前硬校验**：重新解析产出、比对资源集合、确认未参与替换的资源逐字节未变——不通过就不落盘
- **自动备份**：`<安装目录>\.restuner-backup\<版本>_<时间戳>\`，可一键还原并校验 SHA-256
- **改动最小**：`7zFM.exe` 等尺寸原地覆盖（节表都不动）；只有 `7z.dll` 会重建 `.rsrc`
- **不会重复叠加**：识别到已打补丁会拒绝再次执行

## 已知限制

- 仅支持 **x64**（`PE32+`）；检测到 32 位会直接拒绝，不会产出坏文件
- 目标带数字签名时，改完签名必然失效，工具会剥离签名表并在日志说明
- 目前只处理 `7z.dll` + `7zFM.exe`，`7zG.exe` / SFX 等未覆盖
- 图标缓存很顽固，改完"看着没变"就刷新缓存或注销一次

## 许可与致谢

- 代码：MIT
- 图标素材：本仓库（`Windows 10 Default by_d93yxyk`、`Glyfz 2016`）
- 7-Zip 版权归 Igor Pavlov；本工具只操作本地已安装文件的资源

<br/>

<details>
<summary>English</summary>

### ResTuner 1.0 · one-click theme patcher for 7-Zip

> First release — and **likely the only one you need**. The tool reads the icon index table from the
> target file itself, so future 7-Zip versions work without waiting for an updated patch.

Replaces 7-Zip's stock icons with the **Windows 10 Default file type icons + Glyfz 2016 toolbar icons**.

| | |
|---|---|
| File | `ResTuner.exe` |
| Size | 11.51 MB (12,068,842 bytes) |
| SHA-256 | `F7C4B065FB37AD8B0A18E0913CA0ED66348EDA7CEEECA58BA6B0CD314EF97437` |
| Requirements | Windows 10 / 11 x64 — **no Python needed** |

**Usage**: install official 7-Zip (x64) → run `ResTuner.exe` (as administrator if it must write into
`C:\Program Files`) → click **Apply theme** → refresh the icon cache when prompted.

**What it changes**: the "retro" look is pure PE resources — 27 icon groups (`RT_ICON` + `RT_GROUP_ICON`)
in `7z.dll` and 14 toolbar bitmaps (`RT_BITMAP` #100–106 / #150–156) in `7zFM.exe`.
Stock icons are 32×32 / 16×16 at 8 bpp; this tool swaps in 8 sizes (256/64/48/40/32/24/20/16, 32 bpp, 256 as PNG).

**Why no future updates are needed**: the extension → icon-index map is read from the target file's own
`RT_STRING`, so new formats are picked up automatically. Verified against `25.01` and `26.05` with a
structure fingerprint; unknown versions run in adaptive mode and ask for confirmation.

**Safety**: refuses to write unless the output re-parses and every untouched resource stays byte-identical;
automatic backup to `.restuner-backup\` with one-click restore; same-size in-place patch for `7zFM.exe`
(section table untouched); only `7z.dll` gets its `.rsrc` rebuilt; already-patched installs are rejected.

**Limitations**: x64 only; patching invalidates any Authenticode signature (the tool strips it and says so);
`7z.dll` + `7zFM.exe` only.

**License**: code MIT; icons from this repository; 7-Zip © Igor Pavlov.

</details>
