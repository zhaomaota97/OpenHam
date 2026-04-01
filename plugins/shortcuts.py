import subprocess
from core.plugin_manager import openham_plugin

@openham_plugin(trigger="计算器", desc="打开计算器")
def plugin_calc(text: str):
    subprocess.Popen("calc.exe")
    return {"type": "result", "content": "✅ 已打开计算器"}

@openham_plugin(trigger="记事本", desc="打开记事本")
def plugin_notepad(text: str):
    subprocess.Popen("notepad.exe")
    return {"type": "result", "content": "✅ 已打开记事本"}

@openham_plugin(trigger="cmd", desc="打开 CMD")
def plugin_cmd(text: str):
    subprocess.Popen("cmd.exe")
    return {"type": "result", "content": "✅ 已打开 CMD"}

@openham_plugin(trigger=["powershell", "ps"], desc="打开 PowerShell")
def plugin_powershell(text: str):
    subprocess.Popen("powershell.exe")
    return {"type": "result", "content": "✅ 已打开 PowerShell"}

@openham_plugin(trigger=["资源管理器", "文件管理器"], desc="打开资源管理器")
def plugin_explorer(text: str):
    subprocess.Popen("explorer.exe")
    return {"type": "result", "content": "✅ 已打开资源管理器"}

@openham_plugin(trigger="任务管理器", desc="打开任务管理器")
def plugin_taskmgr(text: str):
    subprocess.Popen("taskmgr.exe")
    return {"type": "result", "content": "✅ 已打开任务管理器"}

@openham_plugin(trigger=["控制面板", "control"], desc="打开控制面板")
def plugin_control(text: str):
    subprocess.Popen("control.exe")
    return {"type": "result", "content": "✅ 已打开控制面板"}

@openham_plugin(trigger=["设置", "settings"], desc="打开设置")
def plugin_settings(text: str):
    subprocess.Popen(["explorer.exe", "ms-settings:"])
    return {"type": "result", "content": "✅ 已打开设置"}

@openham_plugin(trigger=["截图", "截图工具"], desc="框选截图 (系统原生)")
def plugin_screenclip(text: str):
    subprocess.Popen(["explorer.exe", "ms-screenclip:"])
    return {"type": "result", "content": "✅ 请框选截图区域"}

@openham_plugin(trigger=["画图", "mspaint"], desc="打开画图")
def plugin_mspaint(text: str):
    subprocess.Popen("mspaint.exe")
    return {"type": "result", "content": "✅ 已打开画图"}
