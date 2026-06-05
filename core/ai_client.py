from openai import OpenAI

from core import app_config
from core.logging_setup import get_logger

log = get_logger("ai")

# 内置默认系统提示（约束输出极简）
_DEFAULT_SYS = (
    "你是一个极度精简的助手，必须用中文回答，"
    "回答内容严格不超过120个汉字，直接给出答案，不要任何废话。"
)


def _client(api_key: str | None):
    """按当前用户配置构造 OpenAI 兼容客户端。"""
    key = (api_key or app_config.get_api_key() or "").strip()
    base_url = app_config.get("ai_base_url")
    return OpenAI(api_key=key, base_url=base_url), key


def _thinking_extra() -> dict:
    """根据配置生成思考模式开关参数（False=非思考模式）。"""
    enabled = bool(app_config.get("ai_thinking"))
    return {"thinking": {"type": "enabled" if enabled else "disabled"}}


def call_deepseek_stream(text: str, api_key: str | None = None, sys_prompt: str = None):
    """流式调用 DeepSeek，逐个 yield 文本片段；失败时 yield 错误提示。"""
    log.info("流式请求开始，文本: %r...", text[:20])
    try:
        client, key = _client(api_key)
        if not key:
            yield "❌ 未配置 API Key：请在「设置 → AI 模型」中填入你的 DeepSeek Key"
            return

        system_content = sys_prompt if sys_prompt else app_config.get("ai_system_prompt") or _DEFAULT_SYS

        stream = client.chat.completions.create(
            model=app_config.get("ai_model"),
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": text},
            ],
            max_tokens=4096 if sys_prompt else 160,
            stream=True,
            extra_body=_thinking_extra(),
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


def call_deepseek_sync(prompt: str, api_key: str | None, sys_prompt: str,
                       max_tokens: int = 4096) -> str:
    """非流式调用 DeepSeek，并使用特定的 sys_prompt，常用于约束输出格式。"""
    log.info("同步请求开始")
    try:
        client, key = _client(api_key)
        if not key:
            raise Exception("未配置 API Key，请在「设置 → AI 模型」中填入你的 DeepSeek Key")
        resp = client.chat.completions.create(
            model=app_config.get("ai_model"),
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            stream=False,
            extra_body=_thinking_extra(),
        )
        result = resp.choices[0].message.content
        if resp.choices[0].finish_reason == "length":
            raise Exception("生成内容遭到阶段截断，当前需求过于复杂（超出了模型单次最大输出限制），建议拆分需求。")
        log.info("同步请求完成")
        return result
    except Exception as e:
        log.exception("同步请求异常: %s", e)
        raise e
