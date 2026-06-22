from openai import OpenAI

from core import app_config
from core.logging_setup import get_logger

log = get_logger("ai")

# 内置默认系统提示（约束输出极简）
_DEFAULT_SYS = (
    "你是一个极度精简的助手，必须用中文回答，"
    "回答内容严格不超过120个汉字，直接给出答案，不要任何废话。"
)

# 多轮对话（AI 对话插件）默认系统提示：常规聊天助手，鼓励 Markdown 排版
_CHAT_SYS = (
    "你是 OpenHam 内置的 AI 助手，友好、专业、有耐心。"
    "请用简洁清晰的中文回答；可使用 Markdown 排版"
    "（标题、列表、表格、`行内代码` 以及```代码块```）让回答更易读。"
)


def _client(api_key: str | None):
    """按当前用户配置构造 OpenAI 兼容客户端。"""
    key = (api_key or app_config.get_api_key() or "").strip()
    base_url = app_config.get("ai_base_url")
    return OpenAI(api_key=key, base_url=base_url), key


def _resolve_params(cfg: dict | None) -> dict:
    """把 bot 的可选配置解析成 create() 的关键字参数。
    未设置的项（空串 / None / 0 / 空列表）一律走全局或模型默认。"""
    cfg = cfg or {}
    out = {}
    out["model"] = (cfg.get("model") or "").strip() or app_config.get("ai_model")
    # 思考模式：bot 配置优先（True/False），未设置(None)则跟随全局开关
    th = cfg.get("thinking", None)
    enabled = bool(app_config.get("ai_thinking")) if th is None else bool(th)
    out["extra_body"] = {"thinking": {"type": "enabled" if enabled else "disabled"}}
    for k in ("temperature", "top_p", "frequency_penalty", "presence_penalty"):
        v = cfg.get(k)
        if v is not None:
            out[k] = v
    if cfg.get("stop"):
        out["stop"] = cfg["stop"]
    if cfg.get("response_format") == "json":
        out["response_format"] = {"type": "json_object"}
    return out


def _resolve_max_tokens(cfg: dict | None, fallback: int) -> int:
    mt = (cfg or {}).get("max_tokens")
    try:
        mt = int(mt)
    except (TypeError, ValueError):
        mt = 0
    return mt if mt > 0 else fallback


def call_deepseek_stream(text: str, api_key: str | None = None, sys_prompt: str = None,
                         max_tokens: int | None = None, cfg: dict | None = None):
    """流式调用 DeepSeek，逐个 yield 文本片段；失败时 yield 错误提示。"""
    log.info("流式请求开始，文本: %r...", text[:20])
    try:
        client, key = _client(api_key)
        if not key:
            yield "❌ 未配置 API Key：请在「设置 → AI 模型」中填入你的 DeepSeek Key"
            return

        system_content = sys_prompt if sys_prompt else app_config.get("ai_system_prompt") or _DEFAULT_SYS
        fallback = max_tokens if max_tokens else (4096 if sys_prompt else 160)
        stream = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": text},
            ],
            max_tokens=_resolve_max_tokens(cfg, fallback),
            stream=True,
            **_resolve_params(cfg),
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
            if chunk.choices[0].finish_reason == "length":
                yield "❌ AI 请求失败：生成内容遭到阶段截断，当前需求过于复杂（超出了模型单次最大输出限制），建议将其拆分为更小的任务步骤。"
        log.info("流式请求完成")
    except Exception as e:
        log.exception("流式请求异常: %s", e)
        yield f"❌ AI 请求失败：{e}"


def call_chat_stream(messages, api_key: str | None = None, max_tokens: int = 4096,
                     cfg: dict | None = None):
    """多轮对话流式调用（携带上下文）。

    逐个 yield 二元组 (kind, text)：kind 为 "reasoning"(思考过程) 或 "answer"(正式回答)。
    思考过程仅在思考模式开启、且模型返回 reasoning_content 时出现。
    messages 为 [{"role","content"}, ...]，通常不含 system；本函数会自动补一条 system。
    失败时 yield ("answer", 错误提示)，调用方无需 try。"""
    log.info("聊天流式请求，历史轮数=%d", len(messages))
    try:
        client, key = _client(api_key)
        if not key:
            yield ("answer", "❌ 未配置 API Key：请在「设置 → AI 模型」中填入你的 DeepSeek Key")
            return

        msgs = list(messages)
        if not msgs or msgs[0].get("role") != "system":
            sys_content = app_config.get("ai_system_prompt") or _CHAT_SYS
            msgs = [{"role": "system", "content": sys_content}] + msgs

        stream = client.chat.completions.create(
            messages=msgs,
            max_tokens=_resolve_max_tokens(cfg, max_tokens),
            stream=True,
            **_resolve_params(cfg),
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                yield ("reasoning", rc)
            content = getattr(delta, "content", None)
            if content:
                yield ("answer", content)
            if chunk.choices[0].finish_reason == "length":
                yield ("answer", "\n\n> ⚠️ 输出已达到单次最大长度被截断，可继续追问让我接着写。")
        log.info("聊天流式请求完成")
    except Exception as e:
        log.exception("聊天流式请求异常: %s", e)
        yield ("answer", f"❌ AI 请求失败：{e}")


def call_deepseek_sync(prompt: str, api_key: str | None, sys_prompt: str,
                       max_tokens: int = 4096, cfg: dict | None = None) -> str:
    """非流式调用 DeepSeek，并使用特定的 sys_prompt，常用于约束输出格式。返回正式回答文本。"""
    log.info("同步请求开始")
    try:
        client, key = _client(api_key)
        if not key:
            raise Exception("未配置 API Key，请在「设置 → AI 模型」中填入你的 DeepSeek Key")
        resp = client.chat.completions.create(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=_resolve_max_tokens(cfg, max_tokens),
            stream=False,
            **_resolve_params(cfg),
        )
        result = resp.choices[0].message.content
        if resp.choices[0].finish_reason == "length":
            raise Exception("生成内容遭到阶段截断，当前需求过于复杂（超出了模型单次最大输出限制），建议拆分需求。")
        log.info("同步请求完成")
        return result
    except Exception as e:
        log.exception("同步请求异常: %s", e)
        raise e
