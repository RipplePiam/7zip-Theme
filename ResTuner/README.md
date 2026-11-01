# ResTuner

> 7-Zip 主题「一键」补丁工具 —— 官方每发布一个新版本，装好之后点一下，文件类型图标与工具栏位图就换成主题版。

**零第三方依赖**：只用 Python 标准库（`tkinter` / `struct` / `hashlib` / `winreg`），Python 3.9+ 即可运行。

本工具是 [7zip-Theme](https://github.com/RipplePiam/7zip-Theme) 仓库的一部分，目录为 `ResTuner/`；
验收基线复用父目录的 `patches/7z2501-x64-patch/`（与 `assets/7z2501-x64-patch/` 逐字节相同，故不重复存放）。

![主界面](docs/gui.png)

---

## 它在做什么

7-Zip 那套"复古"界面，本质上是两个 PE 文件里的 **资源**：

| 文件 | 资源 | 作用 |
|---|---|---|
| `7z.dll` | `RT_ICON` + `RT_GROUP_ICON`（27 个格式） | 资源管理器里 `.7z` / `.zip` / `.rar`… 的文件图标 |
| `7zFM.exe` | `RT_BITMAP`（100–106、150–156） | 文件管理器工具栏的 7 个按钮（大/小两套） |

所以"换肤"= **资源替换**，一行代码补丁都不需要。

原版每个格式只有 32×32 / 16×16 两个 8bpp 小图标；本工具把每个格式换成
8 种尺寸（256/64/48/40/32/24/20/16，32bpp，256 用 PNG 压缩），
并把工具栏位图换成 4bpp 主题素材。

> 详细逆向分析见 [docs/7z2501-补丁分析.md](docs/7z2501-补丁分析.md)

---

## 快速开始

**方式一（推荐，机器上不需要 Python）**：直接双击 `dist\ResTuner.exe`
**方式二（有 Python 3.9+）**：双击 `run_gui.bat`，或 `py -3 run_gui.py`

然后：

1. 照常安装官方 7-Zip（x64）
2. 运行上面的程序，它会自动探测安装目录 → 显示版本与"官方原版 / 已打补丁"
3. 点 **应用主题** → 自动备份 → 打补丁 → 自检 → 写回
4. 按提示 **刷新图标缓存**（资源管理器可能还需要重启一次才能在旧文件上看到新图标）

需要写入 `C:\Program Files\7-Zip` 时，点界面右下角 **以管理员身份重启**。

---

## 安全设计

| 机制 | 说明 |
|---|---|
| **写回前硬性自检** | 重新解析产出、比对资源键集合、逐个校验替换内容、并确认**未参与替换的资源逐字节未变**；任一项失败就放弃写回 |
| **临时文件 + 原子替换** | 先写 `*.restuner-new`，校验通过才 `os.replace` |
| **自动备份** | `<安装目录>\.restuner-backup\<版本>_<时间戳>\`，含 `manifest.json`（SHA-256 可在还原前校验） |
| **一键还原** | 界面「还原备份」按哈希校验后写回，还原结果与原始文件逐字节一致 |
| **幂等** | 已打过补丁的文件会识别出来并拒绝重复叠加 |
| **只做该做的事** | `7zFM.exe` 只有等尺寸位图替换 → 走原地覆盖，**节表/头部一律不动**；只有 `7z.dll` 需要重建 `.rsrc` |
| **缺素材就跳过** | 某个格式没有素材时整组保留官方图标，只记 SKIP，绝不产出半成品 |

---

## 版本自适应

* 图标索引 ↔ 扩展名的映射**从目标文件自己的 `RT_STRING` 读取**（`7z:0 zip:1 …`），
  所以 7-Zip 新增格式时会自动跟上（只要 `assets/filetype` 里有对应 `.ico`）
* 工具栏位图按 ID 表（100–106 / 150–156）定位，并校验尺寸/位深是否匹配
* 内置"已验证版本"清单（当前 `25.01`、`26.05`），每条记录都带**结构指纹**
  （图标组数 / 图标数 / 类型索引表 SHA-1 / 工具栏位图 ID 集合）。
  版本号命中但指纹对不上时，会降级提示"结构指纹不符"，仍需勾选「我知道风险」；
  完全没见过的版本则提示"未验证版本"。26.05 的复核过程见 [docs/26.05-复核.md](docs/26.05-复核.md)
* 结果逐项报告：成功 / 跳过 / 警告一目了然

---

## 目录结构

```
ResTuner/
├─ run_gui.bat / run_gui.py       启动器
├─ assets/
│  ├─ filetype/*.ico              文件类型图标素材（每个 8 个尺寸）
│  ├─ toolbar/{24x24,48x36}/*.bmp 工具栏素材（4bpp）
│  └─ 7z2501-x64/                 测试输入：官方原版 25.01
│                                 （参考补丁复用父仓库 ../patches/7z2501-x64-patch）
├─ src/restuner/
│  ├─ pe.py            PE 头 / 节表 / 数据目录 / RVA 换算
│  ├─ checksum.py      PE CheckSum（与 CheckSumMappedFile 一致）
│  ├─ rsrc.py          资源树解析 + .rsrc 重建 + 落盘策略
│  ├─ icon.py          .ico → RT_ICON / GRPICONDIR（宽高从图像推导）
│  ├─ bmp.py           .bmp 去文件头 + 兼容性评估
│  ├─ theme.py         主题包（素材目录 + 别名表 + 位图 ID 表）
│  ├─ target.py        目录定位 / 体检 / 版本信息 / 占用与权限
│  ├─ patcher.py       打补丁规则（7zFM 原地、7z.dll 重建）
│  ├─ verify.py        自检与资源级比对
│  ├─ backup.py        备份 / 还原 / 校验
│  ├─ service.py       编排层（体检 → 打补丁 → 自检 → 备份 → 写回）
│  ├─ logbus.py        线程安全日志
│  └─ gui/app.py       tkinter 界面
├─ tests/             单元 + 验收测试（unittest）
├─ tools/
│  ├─ verify_parity.py 资源级验收（对参考补丁）
│  ├─ smoke_test.py    Windows 冒烟（LoadLibrary / 7z.exe i / 图标解码）
│  └─ dump_res.py      资源树打印
├─ packaging/
│  ├─ restuner.spec    PyInstaller 打包配置
│  ├─ version_info.txt Windows 版本资源
│  └─ build_exe.ps1    一键打包脚本
├─ dist/ResTuner.exe   构建好的单文件 exe
└─ docs/               逆向分析报告
```

---

## 打包成单文件 exe

仓库里已经带了构建好的产物：

```
dist\ResTuner.exe      约 11.5 MB，自包含，目标机器不需要装 Python
```

重新打包：

```bat
py -3 -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
```

或直接：

```bat
py -3 -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\restuner.spec
```

打包配置在 [packaging/restuner.spec](packaging/restuner.spec)：

* `console=False` —— 窗口程序，不带黑框；
* 只把 `assets/filetype` 与 `assets/toolbar` 打进 exe（测试用的 7z2501 样例不会进去）；
* 版本资源来自 [packaging/version_info.txt](packaging/version_info.txt)，图标用 `assets/filetype/7z.ico`。

exe 运行时的路径规则（见 `src/restuner/paths.py`）：

| 用途 | 路径 |
|---|---|
| 内置素材 | PyInstaller 解包目录 `sys._MEIPASS\assets` |
| 日志 | `%LOCALAPPDATA%\ResTuner\logs`（不可写时依次回退到 `%TEMP%`、exe 同级 `logs\`，全都不可写就静默不落盘） |
| 备份 | 目标 7-Zip 目录下的 `.restuner-backup\` |

> **已知情况**：PyInstaller 单文件 exe 每次启动都要先把自身解包到 `%TEMP%`。
> 如果某些安全软件 / 应用控制策略（ASR）拦截了这一动作，会看到
> `Failed to extract VCRUNTIME140.dll: ... Permission denied`。
> 处理办法：给 exe 加白名单；或改用目录形式的构建（`--onedir`），它不需要运行时解包。

---

## 开发

```bat
:: 跑全部测试（63 项）
py -3 -m unittest discover -s tests -v

:: 验收：产出与参考补丁资源级等价（除三处已知缺陷）
py -3 tools/verify_parity.py

:: 冒烟：真的能被 Windows 加载并使用
py -3 tools/smoke_test.py
```

`tools/verify_parity.py` 的判定逻辑就是验收标准：
与父仓库的 `patches/7z2501-x64-patch` 相比，**只允许**下列三处差异（都是参考补丁的缺陷，我们主动不复刻）：

1. `7zFM.exe` 的 `RT_GROUP_ICON #100`：参考补丁把高度写成了宽度（110×63 → 110×110）
2. 两个文件的 `RT_VERSION`：参考补丁被"重新编译"改了 4 个字节，我们原样保留
3. `7z.dll` 的 `RT_GROUP_ICON 4`（arj）：参考补丁漏删旧 8bpp 图标（11/12），我们清理干净

---

## 常见问题

**改完图标没变？**
资源管理器的图标缓存很顽固。用界面上的「刷新图标缓存」，或结束并重启 `explorer.exe`，必要时注销一次。

**提示文件被占用？**
关掉所有 7-Zip 窗口（包括任务栏里的 7zFM），必要时也关掉正在使用压缩包的资源管理器窗口。

**提示没有写入权限？**
`C:\Program Files` 需要管理员。点界面右下角「以管理员身份重启」。

**杀毒软件报警？**
工具本身不联网、不改代码段，只替换 PE 资源并把 `CheckSum` 重算。特征上确实"改可执行文件"，
若被拦截请加白名单。若目标文件带数字签名，改完签名必然失效，工具会剥离签名表并在日志里说明。

**支持 32 位 / ARM64 吗？**
目前只支持 x64（`PE32+`）。检测到非 x64 会直接拒绝，不会产出坏文件。

---

## 许可

主题素材版权归原作者（`RipplePiam/7zip-Theme` 等）；代码部分 MIT。
7-Zip 本身为 Igor Pavlov 所有，本项目只操作本地已安装文件的资源。
