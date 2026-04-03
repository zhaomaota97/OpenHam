from openai import OpenAI

def call_deepseek_stream(text: str, api_key: str, sys_prompt: str = None):
    """流式调用 DeepSeek，逐个 yield 文本片段；失败时 yield 错误提示。"""
    print(f"[DeepSeek] 开始流式请求，文本: {text[:20]!r}...，key 前8位: {api_key[:8]}...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        
        default_sys = (
            "你是一个极度精简的助手，必须用中文回答，"
            "回答内容严格不超过120个汉字，直接给出答案，不要任何废话。"
        )
        system_content = sys_prompt if sys_prompt else default_sys
        
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": system_content,
                },
                {"role": "user", "content": text},
            ],
            max_tokens=800 if sys_prompt else 160,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                print(f"[DeepSeek] chunk: {delta!r}")
                yield delta
        print("[DeepSeek] 流式完成")
    except Exception as e:
        import traceback
        print(f"[DeepSeek] 异常: {e}")
        traceback.print_exc()
        yield f"❌ AI 请求失败：{e}"

def call_deepseek_sync(prompt: str, api_key: str, sys_prompt: str) -> str:
    """非流式调用 DeepSeek，并使用特定的 sys_prompt，常用于约束输出格式。"""
    print(f"[DeepSeek] 开始同步请求，key 前8位: {api_key[:8]}...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            stream=False,
        )
        result = resp.choices[0].message.content
        print("[DeepSeek] 同步请求完成")
        return result
    except Exception as e:
        import traceback
        print(f"[DeepSeek Sync] 异常: {e}")
        traceback.print_exc()
        raise e
