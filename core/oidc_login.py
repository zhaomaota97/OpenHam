"""桌面端浏览器登录：Logto 授权码 + PKCE 回环流程。
本地回环 HTTP 服务**只绑定一次并常驻**（避免每次登录重绑端口导致 10048），
用 state 匹配回调。每次登录：打开系统浏览器到 Logto 登录页 → 服务接住回调 → 换 id_token。"""
import base64
import hashlib
import http.server
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser

import requests

LOGTO = "https://auth.focus.beer"
APP_ID = "z24kr4le2a1kcn0qt0rx0"   # Logto 原生应用 OpenHam Desktop
PORTS = list(range(46739, 46749))  # 备选端口段（都已在 Logto 注册回调）；自动挑一个没被占用的

_server = None
_redirect = None                   # 实际选中的回调地址（绑定成功后确定）
_server_lock = threading.Lock()
_pending = {}   # state -> {"event": Event, "code": str|None, "error": str|None}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(u.query)
        state = (q.get("state") or [None])[0]
        p = _pending.get(state)
        if p is not None:
            p["code"] = (q.get("code") or [None])[0]
            p["error"] = (q.get("error_description") or q.get("error") or [None])[0]
            p["event"].set()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "<html><body style='font-family:sans-serif;text-align:center;padding:64px'>"
            "<h2>登录成功 ✓</h2><p>可以关闭此页面，返回 OpenHam。</p></body></html>".encode("utf-8"))

    def log_message(self, *a):
        pass


class _ReuseServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _ensure_server():
    """常驻回环服务：从备选端口段挑第一个能绑定的，绑成功后固定使用。"""
    global _server, _redirect
    with _server_lock:
        if _server is not None:
            return
        for port in PORTS:
            try:
                _server = _ReuseServer(("127.0.0.1", port), _Handler)
            except OSError:
                continue
            _redirect = f"http://localhost:{port}/callback"
            threading.Thread(target=_server.serve_forever, daemon=True).start()
            return
        raise RuntimeError("无法启动登录服务，请关闭其它正在运行的 OpenHam 后重试。")


def browser_login(timeout: int = 180, cancel_event=None) -> str:
    """阻塞：浏览器完成登录后返回 id_token；失败/超时/取消抛异常。"""
    _ensure_server()
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(16)
    ev = threading.Event()
    _pending[state] = {"event": ev, "code": None, "error": None}
    try:
        auth_url = f"{LOGTO}/oidc/auth?" + urllib.parse.urlencode({
            "client_id": APP_ID,
            "redirect_uri": _redirect,
            "response_type": "code",
            "scope": "openid profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "login",
        })
        webbrowser.open(auth_url)

        deadline = time.time() + timeout
        while not ev.is_set():
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("已取消")
            if time.time() > deadline:
                raise RuntimeError("登录超时，请重试")
            ev.wait(0.5)

        p = _pending[state]
        if p.get("error"):
            raise RuntimeError("登录被拒绝：" + str(p["error"]))
        code = p.get("code")
        if not code:
            raise RuntimeError("未收到登录回调，请重试")
    finally:
        _pending.pop(state, None)

    tok = requests.post(f"{LOGTO}/oidc/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect,
        "client_id": APP_ID,
        "code_verifier": verifier,
    }, timeout=20)
    data = {}
    try:
        data = tok.json()
    except Exception:
        pass
    id_token = data.get("id_token")
    if not id_token:
        raise RuntimeError("换取令牌失败：" + str(data.get("error_description") or data.get("error") or "未知错误"))
    return id_token
