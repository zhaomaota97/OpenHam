import subprocess
import ctypes
import sys
import time

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    print("⚠ 需要管理员权限，正在请求提升...")
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, __file__, None, 1)
    sys.exit()

print("正在查找 LetsPRO.exe 进程...")

check = subprocess.run('tasklist /FI "IMAGENAME eq LetsPRO.exe"', 
                      capture_output=True, text=True, 
                      shell=True, encoding='gbk')

if 'LetsPRO.exe' in check.stdout:
    print("✓ 找到 LetsPRO.exe 进程")
    
    result = subprocess.run('taskkill /F /IM LetsPRO.exe', 
                           capture_output=True, text=True,
                           shell=True, encoding='gbk')
    
    if result.returncode == 0:
        print("✅ LetsPRO.exe 已成功结束")
    else:
        print(f"❌ 结束失败: {result.stderr}")
else:
    print("⚠ 未找到 LetsPRO.exe 进程")

print("3秒后自动关闭...")
time.sleep(3)