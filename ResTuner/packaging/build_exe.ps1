# 一键打包成单文件 exe
#
# 用法：右键「使用 PowerShell 运行」，或
#     powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
#
# 前置：pip install pyinstaller
#       若提示缺少 tkinter，请重装 Python 并勾选 tcl/tk 组件。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Write-Host "检查 PyInstaller …" -ForegroundColor Cyan
    $probe = & py -3 -c "import PyInstaller, sys; print(PyInstaller.__version__)" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $probe) {
        Write-Host "没有找到 PyInstaller，请先执行：" -ForegroundColor Yellow
        Write-Host "    py -3 -m pip install pyinstaller" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "PyInstaller $probe" -ForegroundColor Green

    Write-Host "开始打包（约 30-60 秒）…" -ForegroundColor Cyan
    Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
    & py -3 -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\restuner.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

    $exe = Join-Path $root "dist\ResTuner.exe"
    if (-not (Test-Path $exe)) { throw "没有生成 dist\ResTuner.exe" }

    $file = Get-Item $exe
    $hash = (Get-FileHash $exe -Algorithm SHA256).Hash
    Write-Host ""
    Write-Host "打包完成" -ForegroundColor Green
    Write-Host ("  产物  : {0}" -f $file.FullName)
    Write-Host ("  大小  : {0:N2} MB" -f ($file.Length / 1MB))
    Write-Host ("  SHA256: {0}" -f $hash)
}
finally {
    Pop-Location
}
