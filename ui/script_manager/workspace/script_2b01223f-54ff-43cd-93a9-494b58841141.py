import os
import subprocess
import sys

# ================= 配置部分 =================
CONFIG = {
    "PROJECT_PATH": r"C:\Users\40902\Desktop\code\hk-ai-fe",
    "TARGET_BRANCH": "release/20260331",
    "SOURCE_BRANCH": "test"
}

def update_status(step_msg):
    """打印当前进度"""
    print(f"\n>>>>>>> 【当前进度】 {step_msg} <<<<<<<", flush=True)

def run_command(cmd, cwd, step_name):
    """执行 Git 命令并实时打印原始日志"""
    print(f"  [执行指令]: {cmd}", flush=True)
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0
    )

    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            try:
                decoded = line.decode('utf-8').strip()
            except UnicodeDecodeError:
                decoded = line.decode('gbk', errors='replace').strip()
            if decoded:
                print(f"    | {decoded}", flush=True)

    if process.returncode != 0:
        print(f"\n!!!!!!!! ERROR: {step_name} 失败 !!!!!!!!", flush=True)
        # 针对异常情况给出具体的提示
        if "代码合并" in step_name:
            print("💡 提示: 检测到合并冲突，请手动进入项目处理冲突后再提交。", flush=True)
        elif "切换目标分支" in step_name:
            print(f"💡 提示: 目标分支 {CONFIG['TARGET_BRANCH']} 可能不存在，请检查分支名称或确保已在远程创建。", flush=True)
        sys.exit(1)

def main():
    path = CONFIG["PROJECT_PATH"]

    # 1. 切换到源分支(test)并更新
    update_status(f"切换至源分支 {CONFIG['SOURCE_BRANCH']} 并拉取最新代码")
    run_command(f"git checkout {CONFIG['SOURCE_BRANCH']}", path, "切换源分支")
    run_command("git pull", path, "同步源分支远程代码")

    # 2. 切换到目标分支(release)并更新
    update_status(f"切换至目标分支 {CONFIG['TARGET_BRANCH']} 并拉取最新代码")
    run_command(f"git checkout {CONFIG['TARGET_BRANCH']}", path, "切换目标分支")
    run_command("git pull", path, "同步目标分支远程代码")

    # 3. 合并源分支到目标分支
    update_status(f"合并源分支: {CONFIG['SOURCE_BRANCH']} 到 {CONFIG['TARGET_BRANCH']}")
    # 增加 git fetch 确保本地知道远程分支的最新状态
    run_command("git fetch origin", path, "获取远程分支状态")
    run_command(f"git merge {CONFIG['SOURCE_BRANCH']}", path, "代码合并操作")

    # 4. 推送至远程
    update_status(f"推送合并后的代码到远程 {CONFIG['TARGET_BRANCH']}")
    run_command("git push", path, "推送至远程仓库")

    update_status(f"🎉 【任务成功完成】 {CONFIG['SOURCE_BRANCH']} 的代码已成功合并并推送至 {CONFIG['TARGET_BRANCH']}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 用户手动停止了脚本", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"\n系统异常: {e}", flush=True)
        sys.exit(1)