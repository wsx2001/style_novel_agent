@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PORT=8000"

rem ---- 参数解析：rebuild=强制重建前端；skip-build=跳过构建 ----
set "REBUILD="
set "NOBUILD="
if /i "%~1"=="rebuild" set "REBUILD=1"
if /i "%~1"=="force"   set "REBUILD=1"
if /i "%~1"=="skip-build" set "NOBUILD=1"
if /i "%~1"=="nobuild" set "NOBUILD=1"

echo ============================================================
echo   FictionForge 快速启动
echo ============================================================

rem ---- 1. 检查端口是否已被占用（注意：findstr 含空格会被拆成多个检索词，需两次过滤）----
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [FictionForge] 端口 %PORT% 已被占用，服务可能已在运行。
    echo                 如需重启，请先执行 stop.cmd 再运行本脚本。
    echo.
    pause
    exit /b 1
)

rem ---- 2. 检查后端虚拟环境 ----
if not exist "backend\venv\Scripts\python.exe" (
    echo [FictionForge] 未找到后端虚拟环境 backend\venv\Scripts\python.exe
    echo                 请先按 README.md 的「首次安装」完成环境准备。
    echo.
    pause
    exit /b 1
)

rem ---- 3. 前端构建产物检查（缺失时自动构建；rebuild 强制重建）----
set "NEED_BUILD="
if not defined NOBUILD (
    if defined REBUILD set "NEED_BUILD=1"
    if not exist "frontend\dist\index.html" set "NEED_BUILD=1"
)
if defined NEED_BUILD (
    echo [FictionForge] 开始构建前端（npm run build）...
    pushd frontend
    call npm run build
    if errorlevel 1 (
        popd
        echo [FictionForge] 前端构建失败。请确认已执行 npm install。
        echo.
        pause
        exit /b 1
    )
    popd
) else (
    echo [FictionForge] 使用已有构建产物 frontend\dist（如需重建请运行 start.cmd rebuild）
)

rem ---- 4. 启动后端（前台运行，Ctrl+C 停止）----
echo [FictionForge] 正在启动服务：http://127.0.0.1:%PORT%
echo [FictionForge] 请保持此窗口运行。停止：本窗口 Ctrl+C，或在另一终端执行 stop.cmd
echo ------------------------------------------------------------
cd backend
venv\Scripts\python.exe start.py
echo.
echo [FictionForge] 服务已退出。
endlocal
