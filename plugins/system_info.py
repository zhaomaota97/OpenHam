from core.plugin_manager import openham_plugin
from utils.system_tools import get_system_info

@openham_plugin(trigger="电脑信息", desc="查看系统信息")
def plugin_system_info(text: str):
    info = get_system_info()
    return {"type": "info", "content": info}
