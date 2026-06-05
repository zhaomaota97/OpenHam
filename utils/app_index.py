"""Windows 应用索引：扫描开始菜单快捷方式，提供模糊搜索。

启动方式直接用 os.startfile(快捷方式路径)，由 Windows 解析目标，
因此无需 pywin32 等额外依赖，也不必解析 .lnk 的真实 exe 路径。
"""
import os

# 名称里命中这些词的快捷方式直接跳过（卸载/帮助类噪声）
_SKIP_KEYWORDS = ("uninstall", "卸载", "readme", "read me")

# 索引缓存：list[{'name', 'path', '_lname'}]
_APP_CACHE: list | None = None


def _start_menu_dirs() -> list:
    dirs = []
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    appdata = os.environ.get("APPDATA", "")
    dirs.append(os.path.join(program_data, r"Microsoft\Windows\Start Menu\Programs"))
    if appdata:
        dirs.append(os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs"))
    return [d for d in dirs if os.path.isdir(d)]


def _collect_shortcuts() -> list:
    """扫描开始菜单目录下所有 .lnk/.url，按小写名去重。"""
    apps: list = []
    seen: set = set()
    for root in _start_menu_dirs():
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in (".lnk", ".url"):
                    continue
                name = os.path.splitext(fn)[0]
                lname = name.lower()
                if any(kw in lname for kw in _SKIP_KEYWORDS):
                    continue
                if lname in seen:
                    continue
                seen.add(lname)
                apps.append({
                    "name": name,
                    "path": os.path.join(dirpath, fn),
                    "_lname": lname,
                })
    return apps


def get_apps(refresh: bool = False) -> list:
    """获取（并缓存）应用索引。首次调用会扫描文件系统。"""
    global _APP_CACHE
    if _APP_CACHE is None or refresh:
        try:
            _APP_CACHE = _collect_shortcuts()
        except Exception:
            _APP_CACHE = []
    return _APP_CACHE


def _is_subseq(q: str, s: str) -> bool:
    """q 是否为 s 的子序列（模糊匹配，如 'cr' 命中 'chrome'）。"""
    it = iter(s)
    return all(ch in it for ch in q)


def _score(lname: str, q: str) -> float:
    """打分：完全相等 > 前缀 > 单词边界前缀 > 子串 > 子序列。"""
    if lname == q:
        return 100.0
    if lname.startswith(q):
        return 80.0
    parts = lname.replace("-", " ").replace("_", " ").replace(".", " ").split()
    if any(p.startswith(q) for p in parts):
        return 60.0
    idx = lname.find(q)
    if idx >= 0:
        return 40.0 - idx * 0.1
    if _is_subseq(q, lname):
        return 20.0
    return -1.0


def search_apps(query: str, limit: int = 12) -> list:
    """按模糊度排序返回匹配应用：[{'name', 'path'}]。"""
    q = query.strip().lower()
    if not q:
        return []
    scored = []
    for app in get_apps():
        sc = _score(app["_lname"], q)
        if sc > 0:
            scored.append((sc, app))
    # 若存在子串及以上的高质量匹配，则丢弃纯子序列的弱匹配（score==20）以降噪
    if any(sc >= 40 for sc, _ in scored):
        scored = [(sc, a) for sc, a in scored if sc >= 40]
    scored.sort(key=lambda x: (-x[0], x[1]["_lname"]))
    return [{"name": a["name"], "path": a["path"]} for _, a in scored[:limit]]
