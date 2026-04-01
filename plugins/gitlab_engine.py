import os
import threading
from dotenv import load_dotenv

from core.plugin_manager import openham_plugin, OpenHamPluginAPI
from plugins.gitlab.overlay import GitLabOverlay
from plugins.gitlab import preset as gitlab_preset
from plugins.gitlab.watched_repos import WatchedReposManager
from core.signals import GitLabSignal, BranchResultSignal

# 全局环境隔离
manager: WatchedReposManager = None
gitlab_overlay: GitLabOverlay = None
gitlab_signal: GitLabSignal = None
branch_result_signal: BranchResultSignal = None

def setup_gitlab(api: OpenHamPluginAPI):
    global manager, gitlab_overlay, gitlab_signal, branch_result_signal
    
    load_dotenv()
    _gl_token = os.getenv("GITLAB_TOKEN", "").strip() or None
    manager = WatchedReposManager(gitlab_preset.GITLAB_BASE_URL, _gl_token)

    # UI 和信号绑定必须在主线程（即导入及加载插件时）被初始化
    gitlab_overlay = GitLabOverlay()
    gitlab_signal = GitLabSignal()
    gitlab_signal.data.connect(gitlab_overlay.update_data)
    
    branch_result_signal = BranchResultSignal()
    branch_result_signal.result.connect(gitlab_overlay.show_branch_choices)

    def _reload_edit():
        gitlab_overlay.load_edit_repos(
            manager.get_repos(),
            manager.is_webhook_enabled(),
            manager.get_webhook_url(),
        )

    def on_gitlab_refresh():
        gitlab_overlay.show_loading()
        def _fetch():
            gitlab_signal.data.emit(manager.fetch_structured())
        threading.Thread(target=_fetch, daemon=True).start()

    def on_branch_fetch(url: str):
        def _fetch():
            branch_result_signal.result.emit(url, manager.fetch_branches(url))
        threading.Thread(target=_fetch, daemon=True).start()

    def on_repo_add(url: str, name: str, branches: list):
        manager.add_or_update(url, name, branches)
        _reload_edit()

    def on_repo_remove(url: str):
        manager.remove(url)
        _reload_edit()

    def on_webhook_toggle(enabled: bool):
        manager.set_webhook_enabled(enabled)
        if enabled:
            manager.start_webhook_server(
                lambda: gitlab_signal.data.emit(manager.fetch_structured())
            )
        _reload_edit()

    # 连接界面抛出的事件
    gitlab_overlay.refresh_requested.connect(on_gitlab_refresh)
    gitlab_overlay.edit_mode_opened.connect(_reload_edit)
    gitlab_overlay.branch_fetch_requested.connect(on_branch_fetch)
    gitlab_overlay.repo_add_requested.connect(on_repo_add)
    gitlab_overlay.repo_remove_requested.connect(on_repo_remove)
    gitlab_overlay.webhook_toggle.connect(on_webhook_toggle)

    # 启动后台守护进程进行轮询更新
    manager.start_polling(lambda data: gitlab_signal.data.emit(data))

@openham_plugin(match=gitlab_preset.is_gitlab_query, setup=setup_gitlab, desc="查看 GitLab 提交列表 (正则感知)")
def plugin_gitlab(text: str):
    """
    当匹配到类如 `ai对话合test` 时，由调度引擎触发本函数
    """
    global manager, gitlab_overlay, gitlab_signal
    
    gitlab_overlay.show_loading()
    
    def _gitlab_call():
        result = manager.fetch_structured()
        gitlab_signal.data.emit(result)
        
    threading.Thread(target=_gitlab_call, daemon=True).start()
    
    # 返回通用标识，让主调度器自动隐藏唤醒栏
    return {"type": "text", "content": "✅ 已开启 GitLab 工具盘"}
