import os
import subprocess
import sys
import shutil

# ================= 配置部分 =================
CONFIG = {
    # 项目 A (前端工程) 配置
    "PROJECT_A_PATH": r"C:\Users\40902\Desktop\code\hk-ai-fe",
    "PROJECT_A_BRANCH": "release/20260331",
    "BUILD_COMMAND": "npm run build",
    "BUILD_DIST_DIR": r"C:\Users\40902\Desktop\code\hk-ai-fe\dist",
    
    # 项目 B (静态资源) 配置
    "PROJECT_B_PATH": r"C:\Users\40902\Desktop\code\sg-static-resource",
    "PROJECT_B_BRANCH": "release/20260331_02",
    "TARGET_DEPLOY_DIR": r"C:\Users\40902\Desktop\code\sg-static-resource\h5\ai-vip",
    
    # Git 提交信息
    "COMMIT_MESSAGE": "ai对话项目3月底版本"
}
# ============================================

def update_status(step_msg):
    """打印当前进度"""
    print(f"\n{'='*10} 【当前进度】 {step_msg} {'='*10}", flush=True)

def run_command(cmd, cwd, step_name):
    """执行命令行指令并实时打印原始日志"""
    print(f"  [执行指令]: {cmd} (目录: {cwd})", flush=True)
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
        print(f"\n!!!!!!!! ERROR: {step_name} 失败 (退出码: {process.returncode}) !!!!!!!!", flush=True)
        if "checkout" in cmd:
            print("💡 提示: 请检查分支名是否正确，或本地是否有未提交的更改导致无法切换分支。", flush=True)
        elif "npm run build" in cmd:
            print("💡 提示: 前端项目打包失败，请检查项目代码或依赖是否正常。", flush=True)
        sys.exit(1)

def check_git_changes(cwd):
    """检查 Git 工作区是否有变更"""
    result = subprocess.run(
        "git status --porcelain", 
        cwd=cwd, 
        shell=True, 
        capture_output=True, 
        text=True
    )
    return bool(result.stdout.strip())

def replace_directory(src, dst):
    """清空目标目录并复制新文件"""
    print(f"  [文件操作]: 准备将 {src} 的内容替换到 {dst}", flush=True)
    
    if not os.path.exists(src):
        print(f"\n!!!!!!!! ERROR: 找不到打包产物目录: {src} !!!!!!!!", flush=True)
        sys.exit(1)
        
    try:
        # 如果目标目录存在，先清空它
        if os.path.exists(dst):
            print(f"    | 正在清理旧的目标目录: {dst}", flush=True)
            shutil.rmtree(dst)
        
        # 复制新的打包产物到目标目录
        print(f"    | 正在复制新文件...", flush=True)
        shutil.copytree(src, dst)
        print("    | 文件替换完成！", flush=True)
    except Exception as e:
        print(f"\n!!!!!!!! ERROR: 文件替换失败: {e} !!!!!!!!", flush=True)
        sys.exit(1)

def main():
    # ---------------- 阶段 1：处理项目 A ----------------
    update_status("阶段 1/4: 更新项目 A 并打包")
    path_a = CONFIG["PROJECT_A_PATH"]
    
    run_command(f"git checkout {CONFIG['PROJECT_A_BRANCH']}", path_a, "项目A: 切换分支")
    run_command("git pull", path_a, "项目A: 拉取最新代码")
    run_command(CONFIG["BUILD_COMMAND"], path_a, "项目A: 执行打包")

    # ---------------- 阶段 2：处理项目 B ----------------
    update_status("阶段 2/4: 更新项目 B")
    path_b = CONFIG["PROJECT_B_PATH"]
    
    run_command(f"git checkout {CONFIG['PROJECT_B_BRANCH']}", path_b, "项目B: 切换分支")
    run_command("git pull", path_b, "项目B: 拉取最新代码")

    # ---------------- 阶段 3：替换文件 ----------------
    update_status("阶段 3/4: 替换静态资源文件")
    replace_directory(CONFIG["BUILD_DIST_DIR"], CONFIG["TARGET_DEPLOY_DIR"])

    # ---------------- 阶段 4：提交并推送项目 B ----------------
    update_status("阶段 4/4: 提交并推送项目 B")
    
    # 检查是否有文件变更（防止因为文件完全一样导致 git commit 报错）
    run_command("git add .", path_b, "项目B: 暂存更改")
    
    if check_git_changes(path_b):
        commit_cmd = f'git commit -m "{CONFIG["COMMIT_MESSAGE"]}"'
        run_command(commit_cmd, path_b, "项目B: 提交更改")
        run_command("git push", path_b, "项目B: 推送至远程")
        update_status("🎉 【任务成功完成】 打包产物已成功更新并推送到远程仓库！")
    else:
        update_status("⚠️ 【任务完成】 打包产物与之前完全一致，没有产生新的文件变更，无需提交和推送。")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 用户手动停止了脚本", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"\n系统异常: {e}", flush=True)
        sys.exit(1)