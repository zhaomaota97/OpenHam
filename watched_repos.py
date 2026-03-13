"""
watched_repos.py — 关注仓库管理 & 后台轮询

职责：
  - watched.json 持久化关注列表
  - ETag 条件轮询（默认30秒），检测到新提交触发回调
  - 可选本地 Webhook HTTP 服务器（GitLab push 事件）
"""

import json
import os
import threading
from urllib.parse import quote, urlparse

import requests

_DEFAULT_POLL_INTERVAL = 30  # 秒


def _base_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


class WatchedReposManager:
    """
    管理关注仓库列表。支持持久化、ETag 轮询、动态增删、Webhook 接收。
    所有公开方法均线程安全。
    """

    def __init__(self, gitlab_base_url: str, token: str | None = None):
        self._base_url = gitlab_base_url.rstrip("/")
        self._token = token
        self._path = os.path.join(_base_dir(), "watched.json")
        self._lock = threading.Lock()
        self._data = self._load()
        self._cache: dict[str, dict] = {}   # ETag/SHA 缓存，key = "path::branch"
        self._stop_flag = threading.Event()
        self._on_change: callable | None = None
        self._webhook_started = False

    # ── 持久化 ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        defaults = {
            "repos": [],
            "poll_interval": _DEFAULT_POLL_INTERVAL,
            "webhook_enabled": False,
            "webhook_port": 19876,
        }
        if not os.path.exists(self._path):
            return dict(defaults)
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in defaults.items():
                data.setdefault(k, v)
            return data
        except Exception:
            return dict(defaults)

    def _save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WatchedRepos] 保存失败: {e}")

    # ── URL 工具 ─────────────────────────────────────────────────────────

    @staticmethod
    def url_to_project_path(url: str) -> str:
        path = urlparse(url).path.strip("/")
        return path[:-4] if path.endswith(".git") else path

    @staticmethod
    def url_to_name(url: str) -> str:
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        return tail[:-4] if tail.endswith(".git") else tail

    # ── CRUD ─────────────────────────────────────────────────────────────

    def get_repos(self) -> list:
        with self._lock:
            return list(self._data.get("repos", []))

    def has_repos(self) -> bool:
        return bool(self.get_repos())

    def add_or_update(self, url: str, name: str, branches: list[str]):
        """添加或更新仓库（按 URL 去重）。"""
        url = url.rstrip("/")
        with self._lock:
            for r in self._data["repos"]:
                if r["url"].rstrip("/") == url:
                    r["name"] = name
                    r["branches"] = branches
                    self._save()
                    return
            self._data["repos"].append({"url": url, "name": name, "branches": branches})
            self._save()

    def remove(self, url: str):
        url = url.rstrip("/")
        with self._lock:
            self._data["repos"] = [
                r for r in self._data["repos"] if r["url"].rstrip("/") != url
            ]
            self._save()

    # ── 配置 ─────────────────────────────────────────────────────────────

    def get_poll_interval(self) -> int:
        return int(self._data.get("poll_interval", _DEFAULT_POLL_INTERVAL))

    def is_webhook_enabled(self) -> bool:
        return bool(self._data.get("webhook_enabled", False))

    def set_webhook_enabled(self, enabled: bool):
        with self._lock:
            self._data["webhook_enabled"] = enabled
            self._save()

    def get_webhook_url(self) -> str:
        import socket
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
        return f"http://{ip}:{self._data.get('webhook_port', 19876)}/webhook"

    # ── HTTP 基础 ────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self._token} if self._token else {}

    def _api_url(self, project_path: str, endpoint: str = "") -> str:
        return f"{self._base_url}/api/v4/projects/{quote(project_path, safe='')}{endpoint}"

    # ── 获取分支列表（编辑模式用）────────────────────────────────────────

    def fetch_branches(self, url: str) -> list[str] | str:
        """返回仓库全部分支名列表（自动分页），失败返回错误字符串。"""
        pp = self.url_to_project_path(url)
        h = self._headers()
        all_branches: list[str] = []
        page = 1
        while True:
            try:
                resp = requests.get(
                    self._api_url(pp, "/repository/branches"),
                    headers=h,
                    params={"per_page": 100, "order_by": "updated", "sort": "desc", "page": page},
                    timeout=8,
                )
            except requests.exceptions.Timeout:
                return "⚠ 请求超时" if not all_branches else all_branches
            except requests.exceptions.ConnectionError:
                return f"⚠ 无法连接 {self._base_url}" if not all_branches else all_branches
            except Exception as e:
                return f"⚠ {e}" if not all_branches else all_branches
            # 仅首页检查鉴权 / 404 错误
            if page == 1:
                if resp.status_code in (401, 403):
                    return "🔒 需要认证，请设置 GITLAB_TOKEN"
                if resp.status_code == 404:
                    return "🔒 仓库不存在或需要认证" if not self._token else "仓库不存在"
                if resp.status_code != 200:
                    return f"HTTP {resp.status_code}"
            elif resp.status_code != 200:
                break  # 后续分页出错就停止，返回已获取的内容
            try:
                data = resp.json()
            except Exception as e:
                return f"❌ 解析失败: {e}" if not all_branches else all_branches
            if not data:
                break
            all_branches.extend(b["name"] for b in data)
            next_page = resp.headers.get("X-Next-Page", "").strip()
            if not next_page:
                break
            page = int(next_page)
        return all_branches or "暂无分支"

    # ── 获取结构化提交数据 ────────────────────────────────────────────────

    def fetch_structured(self) -> list:
        """获取所有关注仓库的最新提交信息（结构化列表）。"""
        repos = self.get_repos()
        if not repos:
            return [{"repo": "", "info": "尚未配置关注仓库，点击右上角  ✏  开始添加", "branches": []}]
        h = self._headers()
        return [self._fetch_one(r, h) for r in repos]

    def _fetch_one(self, repo: dict, headers: dict) -> dict:
        pp = self.url_to_project_path(repo["url"])
        name = repo.get("name") or self.url_to_name(repo["url"])
        err = self._check_project(pp, headers)
        if err:
            return {"repo": name, "error": err, "branches": []}
        return {
            "repo": name, "error": None,
            "branches": [self._fetch_branch(pp, b, headers) for b in repo.get("branches", [])],
        }

    def _check_project(self, pp: str, headers: dict) -> str | None:
        try:
            r = requests.get(self._api_url(pp), headers=headers, timeout=8)
        except requests.exceptions.Timeout:
            return "⚠ 连接超时"
        except requests.exceptions.ConnectionError:
            return f"⚠ 无法连接 {self._base_url}"
        except Exception as e:
            return f"⚠ {e}"
        if r.status_code in (401, 403):
            return "🔒 需要认证"
        if r.status_code == 404:
            return "🔒 私有仓库，请设置 GITLAB_TOKEN" if not self._token else "❌ 仓库不存在"
        if r.status_code != 200:
            return f"⚠ HTTP {r.status_code}"
        return None

    def _fetch_branch(self, pp: str, branch: str, headers: dict) -> dict:
        base = {"branch": branch, "sha": "", "date": "", "author": "", "message": "", "error": None}
        try:
            r = requests.get(
                self._api_url(pp, f"/repository/branches/{quote(branch, safe='')}"),
                headers=headers, timeout=8,
            )
        except Exception as e:
            return {**base, "error": str(e)}
        if r.status_code in (401, 403):
            return {**base, "error": "🔒 需要认证"}
        if r.status_code == 404:
            return {**base, "error": "分支不存在"}
        if r.status_code != 200:
            return {**base, "error": f"HTTP {r.status_code}"}
        try:
            commit = r.json().get("commit", {})
            msg = commit.get("title", "").strip()
            return {
                **base,
                "sha": (commit.get("id") or "")[:8],
                "date": (commit.get("committed_date") or "")[:10],
                "author": commit.get("author_name", "").strip(),
                "message": msg[:59] + "…" if len(msg) > 60 else msg,
            }
        except Exception as e:
            return {**base, "error": f"解析失败: {e}"}

    # ── ETag 轮询 ────────────────────────────────────────────────────────

    def start_polling(self, on_change: callable):
        """
        启动后台轮询线程。检测到新提交时在后台线程调用
        on_change(structured: list)，调用方必须保证线程安全（用 Qt 信号传回主线程）。
        """
        self._on_change = on_change
        self._stop_flag.clear()
        threading.Thread(target=self._poll_loop, daemon=True, name="GitLabPoller").start()

    def stop_polling(self):
        self._stop_flag.set()

    def _poll_loop(self):
        self._poll_once(first_run=True)  # 建立初始 ETag 缓存
        while not self._stop_flag.wait(self.get_poll_interval()):
            self._poll_once()

    def _poll_once(self, first_run: bool = False):
        repos = self.get_repos()
        if not repos:
            return
        changed = False
        h = self._headers()
        for repo in repos:
            pp = self.url_to_project_path(repo["url"])
            for branch in repo.get("branches", []):
                if self._check_changed(pp, branch, h, first_run):
                    changed = True
        if changed and not first_run and self._on_change:
            self._on_change(self.fetch_structured())

    def _check_changed(self, pp: str, branch: str, headers: dict, first_run: bool) -> bool:
        """ETag 条件请求：304 = 无变化，200 = 可能有新提交。"""
        key = f"{pp}::{branch}"
        req_h = dict(headers)
        cached = self._cache.get(key, {})
        if cached.get("etag"):
            req_h["If-None-Match"] = cached["etag"]
        try:
            r = requests.get(
                self._api_url(pp, f"/repository/branches/{quote(branch, safe='')}"),
                headers=req_h, timeout=8,
            )
        except Exception:
            return False
        if r.status_code == 304:
            return False
        if r.status_code != 200:
            return False
        try:
            new_sha = r.json().get("commit", {}).get("id", "")
        except Exception:
            return False
        new_etag = r.headers.get("ETag", "")
        changed = not first_run and bool(cached.get("sha")) and cached["sha"] != new_sha
        self._cache[key] = {"etag": new_etag, "sha": new_sha}
        return changed

    # ── Webhook HTTP 服务 ─────────────────────────────────────────────────

    def start_webhook_server(self, on_push: callable):
        """
        启动本地 HTTP 服务器接收 GitLab Webhook push 事件。
        on_push() 在接收到 push 时被调用（后台线程，线程安全由调用方保证）。
        """
        if self._webhook_started:
            return
        port = int(self._data.get("webhook_port", 19876))
        import http.server

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(handler):
                length = int(handler.headers.get("Content-Length", 0))
                body = handler.rfile.read(length)
                handler.send_response(200)
                handler.end_headers()
                try:
                    payload = json.loads(body)
                    if payload.get("object_kind") == "push":
                        on_push()
                except Exception:
                    pass

            def log_message(self, fmt, *args):
                pass  # 静默日志

        def _serve():
            try:
                srv = http.server.HTTPServer(("", port), _Handler)
                srv.serve_forever()
            except Exception as e:
                print(f"[Webhook] 启动失败: {e}")

        threading.Thread(target=_serve, daemon=True, name="GitLabWebhook").start()
        self._webhook_started = True
