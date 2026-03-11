"""
打包脚本：pyinstaller + 裁剪 PyQt6 + UPX 压缩
运行方式：python build.py
"""
import subprocess
import sys
import os

# 优先使用项目 venv 内的 Python，确保 PyQt6 等依赖能被找到
_venv_python = os.path.join(os.path.dirname(__file__), "venv", "Scripts", "python.exe")
_python = _venv_python if os.path.exists(_venv_python) else sys.executable

# 只排除标准库中体积大但用不到的模块
# 注意：以下模块被 OpenAI/requests/httpx 依赖，不能排除：
#   - email, html, http, urllib, xml, xmlrpc
EXCLUDE = [
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "difflib",
    "ftplib",
    "imaplib",
    "smtplib",
    "poplib",
    "telnetlib",
    "nntplib",
    "turtle",
    "curses",
]

exclude_args = []
for mod in EXCLUDE:
    exclude_args += ["--exclude-module", mod]

cmd = [
    _python, "-m", "PyInstaller",
    "--onedir",           # 文件夹模式：启动不需要解压，秒开；替代 --onefile
    "--windowed",
    "--icon", "logo.png",
    "--name", "OpenHam",
    "--hidden-import", "PyQt6",
    "--hidden-import", "PyQt6.QtWidgets",
    "--hidden-import", "PyQt6.QtCore",
    "--hidden-import", "PyQt6.QtGui",
    "--hidden-import", "PyQt6.sip",
    "--collect-all", "PyQt6",
    "--hidden-import", "requests",
    "--hidden-import", "certifi",
    "--hidden-import", "openai",
    "--collect-all", "openai",
    "--hidden-import", "httpx",
    "--collect-all", "httpx",
    "--hidden-import", "anyio",
    "--hidden-import", "pynput",
    "--hidden-import", "pynput.keyboard._win32",
    "--hidden-import", "pynput.mouse._win32",
    "--collect-all", "pynput",
    *exclude_args,
    "main.py",
]

print("▶ 开始构建...")
print(" ".join(cmd))
result = subprocess.run(cmd)
if result.returncode == 0:
    # --onedir 输出目录是 dist/OpenHam/
    import shutil
    src = os.path.join(os.path.dirname(__file__), "config.json")
    dst = os.path.join(os.path.dirname(__file__), "dist", "OpenHam", "config.json")
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"   已复制 config.json → dist/OpenHam/")
    logo_src = os.path.join(os.path.dirname(__file__), "logo.png")
    logo_dst = os.path.join(os.path.dirname(__file__), "dist", "OpenHam", "logo.png")
    if os.path.exists(logo_src):
        shutil.copy2(logo_src, logo_dst)
        print(f"   已复制 logo.png → dist/OpenHam/")
    
    # 复制 .env（优先本地 .env，其次 .env.example）
    env_src = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_src):
        env_src = os.path.join(os.path.dirname(__file__), ".env.example")
    env_dst = os.path.join(os.path.dirname(__file__), "dist", "OpenHam", ".env")
    if os.path.exists(env_src):
        shutil.copy2(env_src, env_dst)
        print(f"   已复制 .env → dist/OpenHam/")
    
    print("\n✅ 构建完成，输出在 dist/OpenHam/OpenHam.exe")
    print("   用户只需编辑 .env 中的 DEEPSEEK_API_KEY 即可")
else:
    print("\n❌ 构建失败，请检查上方错误信息")
