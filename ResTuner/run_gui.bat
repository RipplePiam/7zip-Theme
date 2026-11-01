:: coding utf-8-bom
@echo off
chcp 65001 >nul
REM ResTuner 启动脚本：优先用 py 启动器，其次用 python
setlocal
set "HERE=%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%HERE%run_gui.py" %*
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%HERE%run_gui.py" %*
    goto :end
)

echo [错误] 没有找到 Python 3.9+。请先安装 Python，或改用打包好的 exe。
pause

:end
if errorlevel 1 pause
endlocal
