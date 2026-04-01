# OpenHam 插件开发指南

OpenHam 的插件系统不仅轻量且高度解耦（Micro-kernel Architecture）。只需在 `plugins/` 目录中存入带有 `@openham_plugin` 装饰器的 `.py` 文件，系统就会在启动时动态识别、构建配置档案字典并在运行时自动挂载它们，完全不需要修改核心调度引擎的代码。

## 一分钟上手示例：普通预设命令
如果只需要让用户敲入某个词触发执行简单的函数：

```python
from core.plugin_manager import openham_plugin
import time

@openham_plugin(trigger=["时间", "time"], desc="查看当前时间戳")
def plugin_timestamp(text: str):
    t = time.strftime('%Y-%m-%d %H:%M:%S')
    return {"type": "info", "content": f"当前系统级时间:\n{t}"}
```
重启 OpenHam 并在输入框敲入 `time`，即可在右侧查看！

---

## 进阶玩法：动态正则拦截与环境预设 (Lifecycle Hooks)

如果你的插件不只是响应简单的“口令”，比如像 GitLab 提交信息检索引擎一样，需要 **后台网络轮询** 或通过 **模糊正则表达式匹配** 长句子，可以利用 `match` 和 `setup` 来挂载独立生命周期：

```python
import threading
from core.plugin_manager import openham_plugin, OpenHamPluginAPI

def _my_dynamic_matcher(text: str) -> bool:
    """定义复杂的截获规则，甚至对接 NLP 匹配意图"""
    return text.startswith("智能查询:")

def setup_my_engine(api: OpenHamPluginAPI):
    """
    当 OpenHam 首次加载你的插件时被调用一次。
    非常适合在这里挂载 PyQt5/6 弹出窗、挂载守护线程轮询网络请求或注册全局热键。
    """
    api.show_toast("后台引擎", "分析系统初始化完毕！")
    # 可以通过 api.get_config("key") 获取 config.json 中写入的任意持久配置

@openham_plugin(
    match=_my_dynamic_matcher,   # 传参接收自定义的截获规则
    setup=setup_my_engine,       # 绑定你自定义的插件初始化执行流
    desc="超级复杂的匹配引擎"
)
def plugin_ai_query(text: str):
    real_query = text.split("智能查询:")[1].strip()
    
    # 因为可能需要耗时操作，请记得另起线程，不要阻塞用户 UI
    def _run():
        import time; time.sleep(2)
        print(f"后台线程处理长任务: {real_query}")
    threading.Thread(target=_run, daemon=True).start()
    
    # 让主输入框提示“已接管”并自动合上主体遮罩
    return {"type": "text", "content": "✅ 查询已受理，正转入后台"}
```

---

## 返回值契约体系
你的主函数（`@openham_plugin` 装饰包裹的方法）被调用执行后，可以选择返回一个标准的字典（`dict`）。底层的执行渲染引擎 (`core/script_engine.py`) 会根据 `type` 的类型，自动调度 `ui/InputWindow` 实施绚丽的渲染：

1. **大面板信息展示 (`type: "info"`)**
   显示右侧纯文本或富文本打散的信息大框（适合日志、参数呈现）。
   ```python
   return {"type": "info", "content": "一段巨大的日志列表..."}
   ```
2. **底部状态反馈板 (`type: "text"` 或 `"error"`)**
   只在输入框底部横条位进行简单的高亮反馈提示，适合“已经转移到别的窗口了，关闭当前提示”这种非侵入式提示。
   ```python
   return {"type": "text", "content": "✅ 已开启专用面板"} 
   ```
3. **二维码展示 (`type: "qr"`)**
   将所提供的二进制字节序列数据，作为二维码图像投屏在右侧。
   ```python
   return {"type": "qr", "content": b"\x89PNG\r\n\x1a\n..."} 
   ```

如果是执行第三方独立窗口进程，并希望 OpenHam 完全静默，你可以直接拉起你的 GUI（确保它具备独立 PyQt 层）或者挂入守护线程栈，然后返回 `None` 即可。
