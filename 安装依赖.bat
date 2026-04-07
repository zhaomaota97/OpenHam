@echo off
chcp 65001 >nul
echo ==============================
echo  OpenHam 依赖安装
echo ==============================
echo.

set PYTHON=runtime\python.exe
set PIP_BOOTSTRAP=runtime\get-pip.py

:: 检查 Python 是否存在
if not exist "%PYTHON%" (
    echo [错误] 未找到 runtime\python.exe
    echo 请确认已解压便携 Python 运行时到 runtime\ 目录
    pause
    exit /b 1
)

:: 检查 pip 是否已安装
%PYTHON% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [1/2] 正在引导安装 pip...
    %PYTHON% "%PIP_BOOTSTRAP%"
    if errorlevel 1 (
        echo [错误] pip 安装失败，请检查网络连接
        pause
        exit /b 1
    )
    echo [1/2] pip 安装成功
) else (
    echo [1/2] pip 已存在，跳过
)

echo.
echo [2/2] 正在安装项目依赖...
%PYTHON% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [错误] 部分依赖安装失败，请检查网络或手动重试
    pause
    exit /b 1
)

echo.
echo ==============================
echo  安装完成！现在可以运行：
echo  一键启动OpenHam.vbs
echo ==============================
echo.
pause
