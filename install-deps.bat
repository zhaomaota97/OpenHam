@echo off
chcp 65001 >nul
echo ==============================
echo  OpenHam 依赖安装（阿里镜像）
echo ==============================
echo.

set PYTHON=runtime\python.exe
set PIP_BOOTSTRAP=runtime\get-pip.py
set MIRROR=https://mirrors.aliyun.com/pypi/simple/

if not exist "%PYTHON%" (
    echo [错误] 未找到 runtime\python.exe
    pause
    exit /b 1
)

%PYTHON% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [1/2] 正在引导安装 pip...
    %PYTHON% "%PIP_BOOTSTRAP%" -i %MIRROR%
    if errorlevel 1 (
        echo [错误] pip 安装失败，请检查网络
        pause
        exit /b 1
    )
) else (
    echo [1/2] pip 已存在，跳过
)

echo.
echo [2/2] 正在从阿里镜像安装项目依赖...
%PYTHON% -m pip install -i %MIRROR% -r requirements.txt

if errorlevel 1 (
    echo.
    echo [错误] 部分依赖安装失败，请检查网络或重试
    pause
    exit /b 1
)

echo.
echo ==============================
echo  安装完成！运行 OpenHam.exe 即可启动
echo ==============================
echo.
pause
