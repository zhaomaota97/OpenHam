import subprocess
import ast
import operator
from openai import OpenAI

# 允许的运算符映射，不使用 eval() 避免安全风险
_OPERATORS = {
    ast.Add:      operator.add,
    ast.Sub:      operator.sub,
    ast.Mult:     operator.mul,
    ast.Div:      operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod:      operator.mod,
    ast.Pow:      operator.pow,
    ast.USub:     operator.neg,
    ast.UAdd:     operator.pos,
}

def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        # 防止除以0
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ZeroDivisionError
        # 限制指数过大
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")

def evaluate_expr(text: str):
    """尝试将 text 作为算术表达式求值。
    成功返回结果字符串，无法识别则返回 None。"""
    text = text.strip()
    if not text:
        return None
    try:
        tree = ast.parse(text, mode="eval")
        result = _eval_node(tree)
        # 整数结果去掉小数点
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"= {result}"
    except ZeroDivisionError:
        return "= 除以零错误"
    except Exception:
        return None


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


def execute(text: str) -> str:
    """执行预设指令。命中返回 '✅ ...'，未命中返回 None。"""
    text = text.strip()

    if text == "计算器":
        subprocess.Popen("calc.exe")
        return "✅ 已打开计算器"

    if text == "记事本":
        subprocess.Popen("notepad.exe")
        return "✅ 已打开记事本"

    return None


# 指令 → 预览文本的映射，与 execute 中的逻辑保持同步
_PREVIEWS = {
    "计算器": "↩ 打开计算器",
    "记事本": "↩ 打开记事本",
}

def preview(text: str):
    """返回指令的预览提示字符串，无匹配则返回 None。"""
    return _PREVIEWS.get(text.strip())
