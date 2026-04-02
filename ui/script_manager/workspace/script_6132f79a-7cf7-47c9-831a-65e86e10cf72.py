import subprocess
import ctypes
import sys

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, __file__, None, 1)
    sys.exit()

APP_PATH = r"C:\Program Files (x86)\letsvpn\LetsPRO.exe"

print("正在查找 LetsPRO.exe 进程...")

check = subprocess.run('tasklist /FI "IMAGENAME eq LetsPRO.exe"', 
                      capture_output=True, text=True, 
                      shell=True, encoding='gbk')

if 'LetsPRO.exe' in check.stdout:
    print("✓ 找到进程，正在结束...")
    
    result = subprocess.run('taskkill /F /IM LetsPRO.exe', 
                           capture_output=True, text=True,
                           shell=True, encoding='gbk')
    
    if result.returncode == 0:
        print("✅ 进程已结束，正在重启...")
        subprocess.Popen(f'"{APP_PATH}"', shell=True)
        print("✅ 已重启")
    else:
        print(f"❌ 结束失败: {result.stderr}")
else:
    print("⚠ 未找到进程")