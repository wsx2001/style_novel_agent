@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

rem ---- 端口（与 backend/.env 的 PORT 保持一致，默认 8000）----
set "PORT=8000"

echo ============================================================
echo   FictionForge 快速关闭
echo ============================================================
echo [FictionForge] 正在查找端口 %PORT% 上的服务进程...

rem ---- 通过两次 findstr 精确匹配「端口 8000 且处于 LISTENING 状态」的行 ----
set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    if not "%%p"=="" if not defined FOUND (
        set "FOUND=1"
        echo [FictionForge] 找到进程 PID=%%p，正在结束...
        taskkill /PID %%p /F >nul 2>&1
        if errorlevel 1 (
            echo [FictionForge] 结束进程 PID=%%p 失败，请手动检查。
        ) else (
            echo [FictionForge] 已结束进程 PID=%%p。
        )
    )
)

if not defined FOUND (
    echo [FictionForge] 端口 %PORT% 上没有正在运行的服务，无需关闭。
)

echo ------------------------------------------------------------
echo [FictionForge] 完成。如仍有残留的 python/uvicorn 进程，可执行：
echo                 taskkill /F /IM python.exe
echo                 （注意：该命令会结束本机所有 Python 进程）
echo ------------------------------------------------------------
pause
endlocal
