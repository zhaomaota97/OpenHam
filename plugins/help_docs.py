from core.plugin_manager import openham_plugin, get_plugin_previews, PLUGIN_MATCHERS
from core.script_engine import _sm_load_scripts
from gitlab.preset import GITLAB_PREVIEWS

@openham_plugin(trigger=["help", "?", "帮助", "指令"], desc="查看所有可用指令 (预设/插件/自定义)")
def plugin_help(text: str):
    lines = []
    
    # 1. 内置命令
    lines.append("=== 🛠️ 原生内置命令 ===")
    lines.append("脚本 / 脚本配置 : 打开脚本管理器")
    lines.append("ip : 查看本机局域网 IP")
    
    # 2. GitLab 预设
    lines.append("\n=== 🦊 GitLab 快捷键 ===")
    for k, v in GITLAB_PREVIEWS.items():
        lines.append(f"{k} : {v.lstrip('↩ ')}")
        
    # 3. 插件系统
    lines.append("\n=== 🧩 插件生态 ===")
    for k, v in get_plugin_previews().items():
        lines.append(f"{k} : {v.lstrip('🧩 ')}")
    # 动态触发器（如番茄钟）
    for matcher in PLUGIN_MATCHERS:
        if matcher.get("desc"):
            lines.append(f"【动态规则】: {matcher['desc'].lstrip('🧩 ')}")
            
    # 4. 自定义脚本
    scripts = _sm_load_scripts()
    if scripts:
        lines.append("\n=== ⚙️ 用户自定义脚本 ===")
        for s in scripts:
            trigger = s.get("trigger", "").strip()
            desc = s.get("description", "无描述").strip()
            if trigger:
                lines.append(f"{trigger} : {desc}")
                
    content = "\n".join(lines)
    return {"type": "info", "content": content}
