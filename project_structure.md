# OpenHam 项目架构概览

经过深度的代码分离与重构，当前系统已经演进为高内聚、低耦合的多模块架构。整个项目的核心功能被拆解为以下几个职责分明的领域：

```text
OpenHam/
├── main.py                  # ✅ 程序的唯一主入口：合并组装各个独立的模块、调度执行层
├── build.py                 # 📦 Pyinstaller 打包编译脚本
├── OpenHam.spec             # ⚙️ Pyinstaller 打包配置文件
├── requirements.txt         # 📄 Python 外部环境依赖
├── config.json              # 🔧 热键及搜索根目录等本地设置
├── logo.png                 # 🖼️ 系统托盘和程序图标
├── window.py.bak            # 🔙 (原) 近2700行的旧窗口大文件备份（可随时删除）
├── patch_main.py            # 🗑️ 重构时用到的临时脚本（可删除）
│
├── core/                    # 🧠 核心业务逻辑调度引擎
│   ├── ai_client.py         # ➔ 专门处理 DeepSeek API 通信请求及流式输出解析
│   ├── script_engine.py     # ➔ 脚本调度引擎：解析执行命令、检测自定义脚本触发并提供 AutoComplete
│   └── signals.py           # ➔ 统筹及定义 PyQt 的全局线程信号 (HotKey, File, AI 等)
│
├── ui/                      # 🎨 所有界面视图和 Overlay 表现层 (互相解耦)
│   ├── __init__.py          # ➔ 模块出口：统一导出组件以供 main 调用
│   ├── input_window.py      # ➔ 程序呼出时的主搜索/指令输入界面及剪贴板逻辑
│   ├── pomodoro.py          # ➔ 桌面右下角负责点击穿透的番茄钟浮层
│   ├── gitlab.py            # ➔ 右上角的 GitLab 变动监测浮层
│   ├── script_manager.py    # ➔ 自定义脚本功能配置窗口与代码编辑器组件
│   └── tray.py              # ➔ 电脑右下角的系统托盘 (Tray Icon) 与浮窗气泡 (Toast)
│
├── gitlab/                  # 🦊 GitLab 专业功能特化包
│   ├── __init__.py
│   ├── preset.py            # ➔ 预设的 GitLab 常用库指令字典、API 路由
│   └── watched_repos.py     # ➔ 后台监听工具：轮询解析分支变动、Etag 缓存及 Webhook 服务器
│
├── utils/                   # 🛠️ 纯原生的底层工具大礼包 (随时可以拔插到其它项目)
│   ├── paths.py             # ➔ 用于处理获取 base_dir 资源根路径的方法
│   ├── search.py            # ➔ 并发本地硬盘深层文件检索的工具
│   └── system_tools.py      # ➔ 负责：解析番茄语法文本、获取本机电脑软硬件状态、解析二维码
│
└── script_manager/          # 📜 用户自定义数据的动态仓
    ├── scripts.json         # ➔ 保存用户配置的特定快捷键与执行脚本
    └── workspace/           # ➔ 脚本运行的虚拟执行工作区
```

## 架构优势
1. **彻底解耦**: PyQt 界面（位于 `ui/`）和具体的系统功能或执行逻辑（位于 `core/`、`utils/`、`gitlab/`）彻底分离，互相之间没有冗余的交叉引用。
2. **便于维护**: 单个 Python 文件的代码行数从近 3000 行缩减至几百行以内，查找并修改一个独立的 Bug 或 UI 样式变得异常简单。
3. **即插即用**: `utils` 文件夹内的方法做到了真正的与业务无关，可以直接移植到将来的其他脚本或新项目中。
