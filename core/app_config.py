"""用户级配置存储（含密钥与 AI 参数）。

与 config.json 分离：config.json 受 git 跟踪、仅存放非敏感的应用配置
（热键、搜索目录）；本模块的 user_settings.json 被 .gitignore 忽略，
存放每个用户自己的 DeepSeek API Key 与 AI 模型参数，避免密钥被提交泄露。

为兼容旧版本（密钥写在 .env 的 DEEPSEEK_API_KEY），get_api_key() 在
user_settings.json 未配置时会回退读取环境变量。
"""
import os
import json
import logging

from utils.paths import _base_dir

log = logging.getLogger("openham.config")

_SETTINGS_FILE = "user_settings.json"

_DEFAULTS = {
    "deepseek_api_key": "",
    "ai_model": "deepseek-v4-flash",
    "ai_base_url": "https://api.deepseek.com",
    "ai_thinking": False,  # False = 非思考模式
    # 联机
    "relay_url": "wss://openham.focus.beer/relay/",  # OpenHam relay（统一到 openham 子域）
    "nickname": "",
    # 更新
    "update_url": "https://openham.focus.beer",  # 更新/下载源（含展示页）
}

_cache: dict | None = None


def _path() -> str:
    return os.path.join(_base_dir(), _SETTINGS_FILE)


def load_settings(refresh: bool = False) -> dict:
    """加载用户设置（带缓存），缺失项以默认值补全。"""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    data = dict(_DEFAULTS)
    path = _path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in _DEFAULTS})
        except Exception as e:
            log.warning("读取 %s 失败，使用默认值: %s", _SETTINGS_FILE, e)
    if data.get("relay_url") in ("ws://47.102.218.59:9000", "wss://relay.focus.beer/"):
        data["relay_url"] = _DEFAULTS["relay_url"]
    if data.get("update_url") in ("http://47.102.218.59/openham", "https://focus.beer/openham"):
        data["update_url"] = _DEFAULTS["update_url"]
    _cache = data
    return _cache


def save_settings(updates: dict) -> None:
    """更新并持久化用户设置；同步刷新内存缓存（同进程内即时生效）。"""
    data = load_settings()
    data.update({k: v for k, v in updates.items() if k in _DEFAULTS})
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("写入 %s 失败: %s", _SETTINGS_FILE, e)
        raise


def get(key: str, default=None):
    return load_settings().get(key, default if default is not None else _DEFAULTS.get(key))


def get_api_key() -> str:
    """获取 DeepSeek API Key：优先用户设置，其次回退环境变量（向后兼容）。"""
    key = (load_settings().get("deepseek_api_key") or "").strip()
    if key:
        return key
    return os.getenv("DEEPSEEK_API_KEY", "").strip()
