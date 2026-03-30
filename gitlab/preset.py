"""
gitlab_preset.py - GitLab 触发词定义

维护关键词 -> 预览文本的映射，供 executor.py 识别 GitLab 查询指令。
仓库管理和 API 调用已迁移至 watched_repos.py。

维护说明：
  - GITLAB_BASE_URL : GitLab 实例地址
  - REPOS / BRANCHES: 首次运行时自动写入 watched.json 的默认仓库
  - _TRIGGERS       : 触发词 -> 查询类型
  - GITLAB_PREVIEWS : 输入框预览文本（与 _TRIGGERS 保持同步）
"""

# GitLab 实例地址
GITLAB_BASE_URL = "http://gitlab.i.noahgroup.com"

# 首次运行默认仓库（若 watched.json 不存在时自动写入）
# 格式：仓库别名 -> (项目路径, 显示名称)
REPOS: dict[str, tuple[str, str]] = {
    "sg": ("NI-FE/sg-static-resource", "sg-static-resource"),
    "hk": ("NI-FE/hk-ai-fe",           "hk-ai-fe"),
}
BRANCHES: list[str] = ["master", "test"]

# 触发词配置
_TRIGGERS: dict[str, str] = {
    "仓库": "all",
}

GITLAB_PREVIEWS: dict[str, str] = {
    "仓库": "↩ 查看关注仓库的最新提交",
}


def is_gitlab_query(text: str) -> bool:
    return text.strip() in _TRIGGERS