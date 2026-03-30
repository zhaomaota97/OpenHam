import os
from pathlib import Path

_SKIP_DIRS = frozenset({
    'node_modules', '.git', '__pycache__', 'venv', '.venv', 'env',
    'dist', 'build', '.idea', '.vscode', '$Recycle.Bin',
    'Windows', 'System32', 'SysWOW64',
    'Program Files', 'Program Files (x86)', 'ProgramData', 'AppData',
})

def _default_search_roots() -> list:
    home = Path.home()
    return [str(p) for p in [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home,
    ] if p.exists()]

def search_files(query: str, roots: list | None = None,
                 max_depth: int = 5, max_results: int = 20) -> list:
    """搜索文件名包含 query 的文件，返回 {'name', 'path', 'dir'} 列表。"""
    q = query.strip().lower()
    if not q:
        return []
    roots = roots or _default_search_roots()
    results: list = []
    seen: set = set()

    for root in roots:
        if len(results) >= max_results:
            break
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == '.' else len(rel.split(os.sep))
            if depth >= max_depth:
                dirnames.clear()
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith('.')
            ]
            for name in filenames:
                if q in name.lower():
                    full_path = os.path.join(dirpath, name)
                    if full_path not in seen:
                        seen.add(full_path)
                        results.append({
                            'name': name,
                            'path': full_path,
                            'dir': dirpath,
                        })
                        if len(results) >= max_results:
                            return results
    return results
