import subprocess
import os
import sys

# ================= 配置部分 =================
# 目标文件夹路径
TARGET_DIR = r"C:\Users\40902\Desktop\playground"

# Antigravity 可执行文件路径
ANTIGRAVITY_EXE = r"C:\Users\40902\AppData\Local\Programs\Antigravity\Antigravity.exe"
# ===========================================

def launch_ide():
    # 1. 检查文件夹是否存在
    if not os.path.exists(TARGET_DIR):
        print(f"❌ 错误：找不到目标文件夹 -> {TARGET_DIR}", flush=True)
        return

    # 2. 检查 IDE 是否存在
    if not os.path.exists(ANTIGRAVITY_EXE):
        print(f"❌ 错误：在路径下找不到 Antigravity.exe", flush=True)
        print(f"当前配置路径: {ANTIGRAVITY_EXE}", flush=True)
        return

    print(f"🚀 正在调用 Antigravity 开启项目...", flush=True)
    print(f"📂 项目路径: {TARGET_DIR}", flush=True)

    try:
        # 使用 Popen 异步启动，脚本执行完后 IDE 不会随之关闭
        # 将文件夹路径作为第一个参数传递给 exe
        subprocess.Popen([ANTIGRAVITY_EXE, TARGET_DIR])
        print("✅ 启动指令已发送，请检查任务栏。", flush=True)
    except Exception as e:
        print(f"❌ 启动过程中发生意外错误: {e}", flush=True)

if __name__ == "__main__":
    launch_ide()