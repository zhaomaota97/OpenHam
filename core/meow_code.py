"""喵咪密码：把 6 位房间号可逆地编码成一串"猫言猫语"。

设计要点（保证 100% 可逆、无歧义）：
- 每个数字固定编码为 2 个喵字（等长），解码时每 2 字一切，绝不切错。
- 仅使用 喵/咪/呜/嗷 四个字排列组合。
- 头尾包 `喵～ … ～喵` 作为识别标记（～ 为全角，token 内不含，安全）。

这是"障眼法"式编码，不提供真正的安全性（规则公开即可逆），
仅用于趣味展示与隐藏裸数字。真正的防护由服务端（房间过期等）负责。
"""
import re
import secrets

# 数字 → 2 字 token（10 个 token 互不相同，等长）
_DIGIT_TO_TOKEN = {
    "0": "喵喵", "1": "喵咪", "2": "喵呜", "3": "喵嗷", "4": "咪喵",
    "5": "咪咪", "6": "咪呜", "7": "咪嗷", "8": "呜喵", "9": "呜咪",
}
_TOKEN_TO_DIGIT = {v: k for k, v in _DIGIT_TO_TOKEN.items()}

_PREFIX = "喵～"
_SUFFIX = "～喵"

_CODE_LEN = 6  # 房间号位数


class MeowCodeError(ValueError):
    """喵咪密码解码失败（格式非法）。"""


def generate_room_code() -> str:
    """生成一个随机的 6 位房间号字符串（含前导零）。"""
    return f"{secrets.randbelow(10 ** _CODE_LEN):0{_CODE_LEN}d}"


def encode(code) -> str:
    """6 位房间号（int 或 str）→ 喵咪密码串。"""
    s = str(code).strip()
    if not s.isdigit():
        raise MeowCodeError(f"房间号必须是数字：{code!r}")
    s = s.zfill(_CODE_LEN)
    if len(s) != _CODE_LEN:
        raise MeowCodeError(f"房间号必须是 {_CODE_LEN} 位：{code!r}")
    body = "".join(_DIGIT_TO_TOKEN[ch] for ch in s)
    return f"{_PREFIX}{body}{_SUFFIX}"


def decode(meow: str) -> str:
    """喵咪密码串 → 6 位房间号字符串。非法输入抛 MeowCodeError。

    宽容处理：自动去除空白；头尾标记可有可无（粘贴时可能被裁掉）。
    """
    if not meow:
        raise MeowCodeError("空字符串")
    s = re.sub(r"\s+", "", meow.strip())
    if s.startswith(_PREFIX):
        s = s[len(_PREFIX):]
    if s.endswith(_SUFFIX):
        s = s[: -len(_SUFFIX)]
    if len(s) != _CODE_LEN * 2:
        raise MeowCodeError(f"长度不对（应为 {_CODE_LEN * 2} 个喵字）：{meow!r}")
    digits = []
    for i in range(0, len(s), 2):
        token = s[i:i + 2]
        if token not in _TOKEN_TO_DIGIT:
            raise MeowCodeError(f"无法识别的喵字：{token!r}")
        digits.append(_TOKEN_TO_DIGIT[token])
    return "".join(digits)


def looks_like_meow(text: str) -> bool:
    """快速判断一段文本是否像喵咪密码（用于 UI 区分房间码与普通输入）。"""
    try:
        decode(text)
        return True
    except MeowCodeError:
        return False


if __name__ == "__main__":
    # 自测：往返一致性 + 边界 + 非法输入
    samples = ["000000", "999999", "483920", "100000", "007007"]
    for s in samples:
        enc = encode(s)
        dec = decode(enc)
        assert dec == s, f"往返失败 {s} -> {enc} -> {dec}"
        print(f"{s}  ->  {enc}  ->  {dec}")

    # 随机批量往返
    bad = 0
    for _ in range(20000):
        code = generate_room_code()
        if decode(encode(code)) != code:
            bad += 1
    print(f"\n随机往返 20000 次，失败 {bad} 次")

    # 容错：无头尾、带空格
    assert decode("咪喵呜喵喵嗷呜咪喵呜喵喵") == "483920"
    assert decode("喵～ 咪喵 呜喵 喵嗷 呜咪 喵呜 喵喵 ～喵") == "483920"
    print("无头尾/带空格 容错 OK")

    # 非法输入应报错
    for bad_in in ["", "abc", "喵", "喵～喵喵～喵", "12345x"]:
        try:
            decode(bad_in)
            print(f"❌ 应报错却没报：{bad_in!r}")
        except MeowCodeError:
            pass
    print("非法输入拦截 OK")
    print("\nMEOW SELFTEST PASS")
