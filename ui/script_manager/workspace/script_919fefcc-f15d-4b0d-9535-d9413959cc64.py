import os
import subprocess
import sys

# ================= 配置部分 =================
CONFIG = {
    "PROJECT_PATH": r"C:\Users\40902\Desktop\code\hk-ai-fe",
    "TARGET_BRANCH": "test",
    "SOURCE_BRANCH": "feature/货币兑换"
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
        # 针对合并冲突给出的提示
        if "代码合并" in step_name:
            print("💡 提示: 检测到合并冲突，请手动进入项目处理冲突后再提交。", flush=True)
        sys.exit(1)

def main():
    path = CONFIG["PROJECT_PATH"]

    # 1. 切换分支并更新
    update_status(f"切换至 {CONFIG['TARGET_BRANCH']} 并拉取最新代码")
    run_command(f"git checkout {CONFIG['TARGET_BRANCH']}", path, "切换分支")
    run_command("git pull", path, "同步远程代码")

    # 2. 合并功能分支
    update_status(f"合并功能分支: {CONFIG['SOURCE_BRANCH']}")
    # 增加 git fetch 确保本地知道远程分支的最新状态
    run_command("git fetch origin", path, "获取远程分支状态")
    run_command(f"git merge {CONFIG['SOURCE_BRANCH']}", path, "代码合并操作")

    # 3. 推送至远程
    update_status(f"推送合并后的代码到远程 {CONFIG['TARGET_BRANCH']}")
    run_command("git push", path, "推送至远程仓库")

    update_status("🎉 【任务成功完成】 货币兑换功能已同步至测试分支")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 用户手动停止了脚本", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"\n系统异常: {e}", flush=True)
        sys.exit(1)