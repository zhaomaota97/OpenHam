import os
import subprocess
import shutil
import sys

# ================= 配置部分 =================
CONFIG = {
    "PROJECT_A": {
        "name": "app-config-manage",
        "path": r"C:\Users\40902\Desktop\code\app-config-manage",
        "build_cmd": "npm run build-w",
        "out_dir": "fz-platform"
    },
    "PROJECT_B": {
        "name": "static-resource",
        "path": r"C:\Users\40902\Desktop\code\static-resource",
        "target_dir": os.path.join("h5", "fz-platform")
    },
    "BRANCH_TEST": "test",
    "FEATURE_BRANCH": "feature/证券定投"
}

def update_status(step_msg):
    """更新当前进度文字"""
    print(f"\n>>>>>>> 【当前进度】 {step_msg} <<<<<<<", flush=True)

def run_command(cmd, cwd, step_name):
    """执行命令并实时打印流式日志"""
    print(f"  [执行命令]: {cmd}", flush=True)
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
        # 如果在项目B Pull失败，通常是因为本地有未提交的改动
        if "项目B拉取最新" in step_name:
            print("💡 提示: 请检查项目B本地是否有未提交的修改，建议执行 git checkout . 清理后再运行。", flush=True)
        sys.exit(1)

def main():
    # --- 0. 提前获取指定分支的 Commit 信息 ---
    update_status(f"准备工作: 获取 {CONFIG['FEATURE_BRANCH']} 的最新 Commit")
    try:
        subprocess.run("git fetch", cwd=CONFIG['PROJECT_A']['path'], shell=True, capture_output=True)
        commit_msg = subprocess.check_output(
            f"git log -1 --pretty=%B {CONFIG['FEATURE_BRANCH']}", 
            cwd=CONFIG['PROJECT_A']['path'], 
            shell=True
        ).decode('utf-8', errors='replace').strip()
        print(f"    [目标Commit]: {commit_msg}", flush=True)
    except Exception as e:
        print(f"    ❌ 无法获取分支信息: {e}", flush=True)
        sys.exit(1)

    # --- 1. 项目 A 操作 ---
    update_status("项目 A: 切换分支并同步")
    run_command(f"git checkout {CONFIG['BRANCH_TEST']}", CONFIG['PROJECT_A']['path'], "项目A切换分支")
    run_command("git pull", CONFIG['PROJECT_A']['path'], "项目A拉取代码")

    update_status(f"项目 A: 合并 {CONFIG['FEATURE_BRANCH']}")
    run_command(f"git merge {CONFIG['FEATURE_BRANCH']}", CONFIG['PROJECT_A']['path'], "项目A代码合并")

    update_status("项目 A: 执行打包 (Build)")
    run_command(CONFIG["PROJECT_A"]["build_cmd"], CONFIG["PROJECT_A"]["path"], "项目A构建编译")

    # --- 2. 项目 B 准备工作 (先 Pull 再 替换) ---
    update_status("项目 B: 切换分支并拉取远程最新代码")
    run_command(f"git checkout {CONFIG['BRANCH_TEST']}", CONFIG['PROJECT_B']['path'], "项目B切换分支")
    # 先把远程最新的代码拿下来，确保本地 B 是最干净的
    run_command("git pull", CONFIG['PROJECT_B']['path'], "项目B拉取最新")

    # --- 3. 文件替换操作 ---
    update_status("文件操作: 将 A 的产物覆盖到 B")
    src = os.path.join(CONFIG["PROJECT_A"]["path"], CONFIG["PROJECT_A"]["out_dir"])
    dst = os.path.join(CONFIG["PROJECT_B"]["path"], CONFIG["PROJECT_B"]["target_dir"])
    
    try:
        if os.path.exists(dst):
            shutil.rmtree(dst) # 删除旧的
        shutil.copytree(src, dst) # 拷贝新的
        print(f"    ✅ 产物已同步至项目B目录", flush=True)
    except Exception as e:
        print(f"    ❌ 文件操作失败: {e}", flush=True)
        sys.exit(1)

    # --- 4. 项目 B 提交与推送 ---
    update_status("项目 B: 提交变更并推送")
    run_command("git add .", CONFIG['PROJECT_B']['path'], "项目B暂存文件")
    
    # 检查是否有内容变更
    status = subprocess.check_output("git status --porcelain", cwd=CONFIG['PROJECT_B']['path'], shell=True).decode('utf-8')
    if status.strip():
        run_command(f'git commit -m "{commit_msg}"', CONFIG['PROJECT_B']['path'], "项目B提交代码")
        run_command("git push", CONFIG['PROJECT_B']['path'], "项目B推送远端")
        update_status("🎉 【全流程成功完成】")
    else:
        update_status("✨ 检查发现产物无变化，无需提交推送")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 用户手动停止")
        sys.exit(0)