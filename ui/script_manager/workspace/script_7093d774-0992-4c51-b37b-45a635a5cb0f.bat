@echo off
chcp 65001 >nul
echo ========================================
echo Windows 11 系统信息查询脚本
echo ========================================
echo.

REM 检查系统版本
ver | findstr /i "Windows 11" >nul
if %errorlevel% neq 0 (
    echo [错误] 当前系统不是Windows 11，脚本将退出。
    exit /b 1
)

echo [步骤1/4] 正在获取系统基本信息...
systeminfo | findstr /c:"OS 名称" /c:"OS 版本" /c:"系统制造商" /c:"系统型号" /c:"系统类型" /c:"系统启动时间" /c:"处理器" /c:"物理内存总量"
if %errorlevel% neq 0 (
    echo [警告] 获取系统基本信息时遇到问题。
)

echo.
echo [步骤2/4] 正在获取磁盘信息...
wmic logicaldisk get caption,size,freespace
if %errorlevel% neq 0 (
    echo [警告] 获取磁盘信息时遇到问题。
)

echo.
echo [步骤3/4] 正在获取网络适配器信息...
ipconfig | findstr /c:"IPv4" /c:"适配器"
if %errorlevel% neq 0 (
    echo [警告] 获取网络适配器信息时遇到问题。
)

echo.
echo [步骤4/4] 正在获取用户信息...
echo 用户名: %USERNAME%
echo 计算机名: %COMPUTERNAME%
echo 用户域: %USERDOMAIN%

echo.
echo ========================================
echo 系统信息查询完成。
echo ========================================