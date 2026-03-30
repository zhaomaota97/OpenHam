from openai import OpenAI

def call_deepseek_stream(text: str, api_key: str):
    """流式调用 DeepSeek，逐个 yield 文本片段；失败时 yield 错误提示。"""
    print(f"[DeepSeek] 开始流式请求，文本: {text!r}，key 前8位: {api_key[:8]}...")
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个极度精简的助手，必须用中文回答，"
                        "回答内容严格不超过120个汉字，直接给出答案，不要任何废话。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=160,
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
