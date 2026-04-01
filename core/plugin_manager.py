import os
import json
import importlib.util
from typing import Dict, Any, Callable, List, Optional
from utils.paths import _base_dir

PLUGIN_REGISTRY: Dict[str, Callable] = {}
PLUGIN_MATCHERS: List[Dict[str, Any]] = []
PLUGIN_PREVIEWS: Dict[str, str] = {}
PLUGIN_SETUPS: List[Callable] = []

# New maps for GUI functionality and overrides
ALL_PLUGINS_META: Dict[str, Dict[str, Any]] = {}
_PLUGIN_CONFIG: Dict[str, Any] = {}
_conf_path = os.path.join(_base_dir(), "config", "plugins.json")

def _load_config():
    global _PLUGIN_CONFIG
    _PLUGIN_CONFIG = {}
    if os.path.exists(_conf_path):
        try:
            with open(_conf_path, "r", encoding="utf-8") as f:
                _PLUGIN_CONFIG = json.load(f)
        except Exception as e:
            print(f"[PluginManager] Config load failed: {e}")

def save_plugin_config(config: Dict[str, Any]):
    global _PLUGIN_CONFIG
    _PLUGIN_CONFIG = config
    os.makedirs(os.path.dirname(_conf_path), exist_ok=True)
    with open(_conf_path, "w", encoding="utf-8") as f:
        json.dump(_PLUGIN_CONFIG, f, ensure_ascii=False, indent=2)

def get_plugin_config() -> Dict[str, Any]:
    return _PLUGIN_CONFIG

class OpenHamPluginAPI:
    def __init__(self):
        self._handlers = {}

    def register_handler(self, name: str, func: Callable):
        self._handlers[name] = func

    def call(self, name: str, *args, **kwargs):
        if name in self._handlers:
            return self._handlers[name](*args, **kwargs)

plugin_api = OpenHamPluginAPI()

def openham_plugin(trigger: str | List[str] | None = None, 
                   match: Callable[[str], bool] | None = None,
                   desc: str = "",
                   setup: Callable[[OpenHamPluginAPI], None] | None = None):
    """
    OpenHam 插件注册装饰器。现在拦截时会读取 user_config 热覆盖。
    """
    def decorator(func):
        plugin_id = f"{func.__module__}.{func.__name__}"
        default_triggers = [trigger] if isinstance(trigger, str) else (trigger or [])
        
        # 保存元数据用于 UI 展示
        ALL_PLUGINS_META[plugin_id] = {
            "id": plugin_id,
            "func_name": func.__name__,
            "module_name": func.__module__,
            "default_triggers": default_triggers,
            "desc": desc,
            "has_match": bool(match),
            "has_setup": bool(setup)
        }
        
        # 查找配置覆写
        conf = _PLUGIN_CONFIG.get(plugin_id, {})
        enabled = conf.get("enabled", True)
        
        if not enabled:
            return func  # 不装载到实际工作字典中
            
        triggers = conf.get("triggers", default_triggers)
        
        for t in triggers:
            PLUGIN_REGISTRY[t] = func
            if desc:
                PLUGIN_PREVIEWS[t] = f"🧩 {desc}"
                
        if match:
            PLUGIN_MATCHERS.append({"match": match, "execute": func, "desc": f"🧩 {desc}" if desc else ""})
        if setup:
            PLUGIN_SETUPS.append(setup)
        return func
    return decorator

def reload_plugins():
    """强制重载所有插件（在保存配置后调用）"""
    global PLUGIN_REGISTRY, PLUGIN_MATCHERS, PLUGIN_PREVIEWS, PLUGIN_SETUPS, ALL_PLUGINS_META
    PLUGIN_REGISTRY.clear()
    PLUGIN_MATCHERS.clear()
    PLUGIN_PREVIEWS.clear()
    PLUGIN_SETUPS.clear()
    ALL_PLUGINS_META.clear()
    
    # API Handlers don't strictly need clearing right now, but optional.
    
    load_plugins()

def load_plugins():
    """扫描并挂载 plugins/ 目录下所有的 .py 文件"""
    _load_config()
    plugins_dir = os.path.join(_base_dir(), "plugins")
    if not os.path.exists(plugins_dir):
        os.makedirs(plugins_dir, exist_ok=True)
        with open(os.path.join(plugins_dir, "__init__.py"), "w", encoding="utf-8") as f:
            pass

    import sys
    for filename in os.listdir(plugins_dir):
        if filename.endswith(".py") and not filename.startswith("_"):
            path = os.path.join(plugins_dir, filename)
            module_name = f"plugins.{filename[:-3]}"
            
            # 由于可能热重载，必须从 sys.modules 中移除，强制重新导入执行 decorator
            if module_name in sys.modules:
                del sys.modules[module_name]

            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception as e:
                    print(f"[PluginManager] 挂载插件 {filename} 失败: {e}")
                    
    # 执行所有的 setup 钩子
    for setup_func in PLUGIN_SETUPS:
        try:
            setup_func(plugin_api)
        except Exception as e:
            print(f"[PluginManager] 执行插件 setup 失败: {e}")

def get_plugin_previews() -> Dict[str, str]:
    return PLUGIN_PREVIEWS

def execute_plugin(text: str, *args, **kwargs) -> Optional[Dict[str, Any]]:
    """执行插件，返回标准的 UI 渲染原语字典"""
    # 优先匹配静态触发
    if text in PLUGIN_REGISTRY:
        try:
            return PLUGIN_REGISTRY[text](text, *args, **kwargs)
        except Exception as e:
            return {"type": "error", "content": f"❌ 插件执行出错: {e}"}
            
    # 其次尝试动态匹配
    for matcher in PLUGIN_MATCHERS:
        try:
            if matcher["match"](text):
                return matcher["execute"](text, *args, **kwargs)
        except Exception as e:
            return {"type": "error", "content": f"❌ 插件动态匹配执行出错: {e}"}
            
    return None
