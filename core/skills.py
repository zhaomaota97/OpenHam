"""Skill 注册表 —— agent（Layer 2）的能力脊柱。

精确匹配漏下来的输入，由路由 LLM 读各 skill 的 `when_to_use` 自行决定调哪个；
没有合适的再走简短回答兜底。每个 skill 是一个自描述单元：

    register_skill(Skill(
        name="add_task",
        when_to_use="用户想新增一条待办任务时…",
        arg_hint="任务标题",
        mutating=True,                       # 写操作 → 路由后需确认/可撤销
        handler=lambda arg: ...,             # 执行并返回结果文本
    ))

注意：开应用、计算器、查 IP 这类「确定性 + 零等待」的能力属于 Layer 1（插件精确
匹配），不要注册成 skill —— skill 是给「可容忍等待的意图识别」用的。
"""
from dataclasses import dataclass
from typing import Callable, Dict, List


@dataclass
class Skill:
    name: str                       # 唯一标识（路由 LLM 返回它）
    when_to_use: str                # 给路由 LLM 看：什么情况下该选这个
    handler: Callable[[str], str]   # handler(arg) -> 结果文本
    arg_hint: str = ""              # 参数说明（让模型从输入里提取 arg）
    mutating: bool = False          # 写操作（增删改）→ 需确认 / 可撤销


SKILL_REGISTRY: Dict[str, Skill] = {}


def register_skill(skill: Skill) -> None:
    SKILL_REGISTRY[skill.name] = skill


def all_skills() -> List[Skill]:
    return list(SKILL_REGISTRY.values())


def get_skill(name: str) -> Skill | None:
    return SKILL_REGISTRY.get(name)


def catalog_text() -> str:
    """渲染成给路由 LLM 的 skill 清单（名字 + 何时用 + 参数）。"""
    lines = []
    for s in all_skills():
        line = f"- {s.name}: {s.when_to_use}"
        if s.arg_hint:
            line += f"（参数：{s.arg_hint}）"
        lines.append(line)
    return "\n".join(lines)


# ── Layer 2 路由：一次 LLM 调用，要么命中技能、要么直接给出答案 ──
# 合并「先路由再回答」为单次调用：普通提问不再多付一次路由的延迟。
_ROUTER_SYS = (
    "你是 OpenHam 的助手。下面是一份「可用技能」清单（名字 + 何时使用 + 参数）。\n"
    "判断用户输入：\n"
    '- 若某个技能正好能处理它 → 只输出一个 JSON 对象：{"skill": "技能名", "arg": "按参数说明从输入里提取的参数"}，'
    "不要输出任何其它字符；\n"
    "- 否则（普通提问 / 闲聊 / 没有合适技能）→ 直接、简洁地用纯文本回答用户，不要输出 JSON。\n"
    "拿不准是否有技能匹配时，就当作普通提问直接回答。"
)


def route_sys_prompt() -> str:
    """流式路由用的 system prompt。"""
    return _ROUTER_SYS if all_skills() else "你是简洁的助手，直接用纯文本回答用户。"


def route_user_prompt(text: str) -> str:
    """流式路由用的 user prompt（带技能清单）。"""
    t = (text or "").strip()
    return f"【可用技能】\n{catalog_text()}\n\n【用户输入】\n{t}" if all_skills() else t


def parse_skill(raw: str) -> dict | None:
    """从（累计的）模型输出里解析技能调用；不是有效技能则返回 None。"""
    import json
    i, j = (raw or "").find("{"), (raw or "").rfind("}")
    if 0 <= i < j:
        try:
            obj = json.loads(raw[i:j + 1])
            name = obj.get("skill")
            if name and name in SKILL_REGISTRY:
                return {"skill": name, "arg": (obj.get("arg") or "").strip()}
        except Exception:
            pass
    return None


def route(text: str, api_key: str = None) -> dict:
    """单轮调用：返回 {"skill": name, "arg": str}（命中技能）或 {"answer": str}（直接回答）。
    异常时返回 {"answer": None}，让上层做兜底提示。"""
    import json
    from core.ai_client import call_deepseek_sync
    has_skills = bool(all_skills())
    sys_prompt = _ROUTER_SYS if has_skills else "你是简洁的助手，直接用纯文本回答用户。"
    prompt = (f"【可用技能】\n{catalog_text()}\n\n【用户输入】\n{(text or '').strip()}"
              if has_skills else (text or "").strip())
    try:
        raw = (call_deepseek_sync(prompt, api_key, sys_prompt, max_tokens=800) or "").strip()
    except Exception:
        return {"answer": None}
    # 优先尝试解析成技能调用；解析失败 / 技能名无效 → 当作直接回答
    if has_skills:
        i, j = raw.find("{"), raw.rfind("}")
        if 0 <= i < j:
            try:
                obj = json.loads(raw[i:j + 1])
                name = obj.get("skill")
                if name and name in SKILL_REGISTRY:
                    return {"skill": name, "arg": (obj.get("arg") or "").strip()}
            except Exception:
                pass
    return {"answer": raw}
