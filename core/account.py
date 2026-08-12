"""统一账号：桌面端浏览器 SSO 登录（Logto）→ 换网关 session token 存本机。
AI 统一走网关，用户不再自带 key；积分余额从网关查询。"""
import requests

from core import app_config
from core import oidc_login

GATEWAY = "https://gateway.focus.beer"


def password_login(username: str, password: str) -> str:
    """用户名密码登录（走网关 /auth/login，不需要本地端口/浏览器）→ 保存 token，返回用户名。"""
    r = requests.post(GATEWAY + "/auth/login", json={"username": (username or "").strip(), "password": password}, timeout=20)
    d = {}
    try:
        d = r.json()
    except Exception:
        pass
    if not r.ok:
        raise RuntimeError(d.get("error") or f"登录失败（{r.status_code}）")
    app_config.set_account(d["token"], d.get("username") or (username or "").strip())
    return app_config.get_account_username()


def register(username: str, password: str) -> str:
    """注册（走网关 /auth/register）→ 保存 token，返回用户名。"""
    r = requests.post(GATEWAY + "/auth/register", json={"username": (username or "").strip(), "password": password}, timeout=20)
    d = {}
    try:
        d = r.json()
    except Exception:
        pass
    if not r.ok:
        raise RuntimeError(d.get("error") or f"注册失败（{r.status_code}）")
    app_config.set_account(d["token"], d.get("username") or (username or "").strip())
    return app_config.get_account_username()


def sso_login(cancel_event=None) -> str:
    """浏览器登录（阻塞，用户在浏览器完成）→ 保存 token/username，返回用户名。"""
    id_token = oidc_login.browser_login(cancel_event=cancel_event)
    r = requests.post(GATEWAY + "/auth/sso", json={"idToken": id_token}, timeout=20)
    d = {}
    try:
        d = r.json()
    except Exception:
        pass
    if not r.ok:
        raise RuntimeError(d.get("error") or f"登录失败（{r.status_code}）")
    app_config.set_account(d["token"], d.get("username") or "")
    return app_config.get_account_username()


def logout() -> None:
    app_config.clear_account()


def get_credits() -> dict:
    """返回 {'unlimited': bool, 'balance': int|None}；未登录/失败返回 None。"""
    token = app_config.get_token()
    if not token:
        return None
    try:
        r = requests.get(GATEWAY + "/credits", headers={"Authorization": f"Bearer {token}"}, timeout=6)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None
