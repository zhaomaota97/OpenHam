# 🐹 OpenHam

**The AI assistant that lives in your hotkey. Fast, private, always ready.**

[English](#english) | [中文](#中文)

---

## English

**The AI assistant that lives in your hotkey. Fast, private, always ready.**

OpenHam is a lightweight desktop AI companion that appears instantly when you need it — no window switching, no browser tabs, just press `Alt+Space` and start typing. Built for creators, developers, and anyone who wants AI assistance without the friction.

### Why OpenHam?

Most AI assistants make you come to them. OpenHam comes to you.

| Traditional AI | OpenHam |
|----------------|---------|
| Open browser → Find tab → Click input | Press `Alt+Space` |
| Context switching breaks flow | Overlay appears, you stay focused |
| API keys in cloud configs | Encrypted local environment variables |
| Heavy Electron apps | Native Qt, minimal footprint |
| Generic responses | Streaming conversations with personality |

### Meet Ham 🐹

Your assistant has a name. A presence. A soul.

Ham is fast, direct, and always ready. Ham doesn't waste your time with pleasantries when you need an answer *now*. Ham streams responses in real-time so you can start reading before the thought is finished. Ham also does math — just type `2+2*3` and get instant results, no "calculator mode" needed.

Ham is also a hamster. This is intentional and brings joy to an otherwise utilitarian tool.

```
You: "What's the capital of Iceland?"
Ham: "Reykjavik. Population ~130k. Northernmost capital in the world.
      Fun fact: geothermal heating keeps it warm despite being 2° 
      south of the Arctic Circle."

You: "127.5 * 0.85"
Ham: "108.375"
      (calculated instantly, no API call)
```

### Prerequisites

- **Python 3.9+** — [Download](https://www.python.org/downloads/)
- **Windows** — Uses Windows-specific APIs for global hotkeys and single-instance protection
- **DeepSeek API Key** — [Get one here](https://platform.deepseek.com/) (or use any OpenAI-compatible API)

### Quick Start

```bash
# Clone OpenHam
git clone https://github.com/zhaomaota97/OpenHam.git
cd OpenHam

# Install dependencies
pip install -r requirements.txt

# Set up your API key
cp .env
# Edit .env and add: DEEPSEEK_API_KEY=sk-your-key-here

# Run
python main.py
```

**Or use the pre-built executable:**

1. Download the latest release from [Releases](https://github.com/zhaomaota97/OpenHam/releases)
2. Extract to any folder
3. Run `OpenHam.exe`
4. Press `Alt+Space` to activate

### Core Features

✅ **Global Hotkey Activation** — Press `Alt+Space` anywhere, anytime (fully customizable)  
✅ **Streaming AI Responses** — Real-time token-by-token output, no waiting  
✅ **Instant Math Calculation** — Type expressions like `2+2*3`, get immediate results  
✅ **Local File Search** — Type `找 keyword` to instantly search files across your machine  
✅ **Built-in Commands** — `cmd`, `powershell`, `截图`, `任务管理器` and more  
✅ **System Tray Integration** — Runs in background, zero taskbar clutter  
✅ **Single Instance Protection** — Prevents multiple instances from conflicting  
✅ **Secure by Default** — API keys stored in environment variables, never in config files  
✅ **Lightweight & Fast** — Native Qt UI, minimal memory footprint  

### Configuration

Edit `config.json` to customize behavior:

```json
{
  "hotkey": "<alt>+<space>",
  "search_roots": []
}
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `hotkey` | Global hotkey (keyboard lib format) | `<alt>+<space>` |
| `search_roots` | Directories to search (empty = Desktop/Documents/Downloads/Home) | `[]` |

**API Key Management**: API keys are managed via the `DEEPSEEK_API_KEY` environment variable, not stored in `config.json`, preventing accidental leaks.

**Hotkey Format Examples**:
- `<alt>+<space>` — Alt + Space (default)
- `<ctrl>+<F11>` — Ctrl + F11
- `<alt>+<F1>` — Alt + F1

### Usage

1. **Start the app**: Run `main.py` or the `.exe` executable
2. **Trigger window**: Press the configured hotkey (default `Alt+Space`)
3. **Enter query**:
   - Plain text: Send to AI for streaming response
   - Math expression (e.g., `2+2*3`): Real-time calculation display
   - `找 keyword`: Search local files by name
   - Built-in command (e.g., `cmd`, `截图`): Instant action
4. **File search results**: `↵` open file · `Ctrl+↵` open folder · `↑↓` navigate
5. **Press Esc**: Close the window and return to your work

### Technical Stack

- **UI Framework**: PyQt6 — Native, lightweight, cross-platform
- **Hotkey Monitoring**: keyboard — Low-level hook (WH_KEYBOARD_LL), suppresses system shortcuts
- **AI Backend**: OpenAI-compatible API (default: DeepSeek)
- **Expression Calculation**: Python AST — Safe evaluation, no `eval()`
- **File Search**: `os.walk` — Recursive, threaded, skip-list filtered
- **Process Singleton**: Windows named mutex — Prevents duplicate instances

### Architecture

```
main.py        — Application entry, hotkey management, signal orchestration
window.py      — Qt input window UI and interaction logic
executor.py    — Core logic for AI chat and expression evaluation
config.json    — Application config (hotkey, model settings)
build.py       — PyInstaller packaging script
```

### Development

**Clone and Install**

```bash
git clone https://github.com/zhaomaota97/OpenHam.git
cd OpenHam
pip install -r requirements.txt
```

**Run Development Version**

```bash
python main.py
```

**Build Executable**

```bash
python build.py
# Output files in dist/ directory
```

### Security First

OpenHam is built with security as a default, not an afterthought.

✅ **Environment-based secrets** — API keys never touch config files  
✅ **Local-first architecture** — No data leaves your machine except API calls  
✅ **Safe expression evaluation** — AST-based math parser, no arbitrary code execution  
✅ **Single instance protection** — Prevents race conditions and conflicts  

### Contributing

OpenHam is MIT licensed and welcomes contributions.

- **Features**: Open a PR on GitHub
- **Bugs**: Open an issue with reproduction steps
- **Ideas**: Start a discussion in Issues

### Community

⭐ **Star us on GitHub** — [github.com/zhaomaota97/OpenHam](https://github.com/zhaomaota97/OpenHam)  
🐛 **Report bugs** — [Open an issue](https://github.com/zhaomaota97/OpenHam/issues)  
💡 **Request features** — [Start a discussion](https://github.com/zhaomaota97/OpenHam/discussions)  

### License

MIT License — Free to use, modify, and distribute. See [LICENSE](LICENSE) for details.

### Roadmap

- [ ] macOS and Linux support
- [ ] Plugin system for custom commands
- [ ] Local LLM support (Ollama, LM Studio)
- [ ] Multi-language UI
- [ ] Voice input support
- [ ] Custom themes

---

Ham is waiting. Press `Ctrl+F11`. 🐹

---

## 中文

**活在快捷键里的 AI 助手。快速、私密、随时待命。**

OpenHam 是一个轻量级桌面 AI 伴侣，需要时即刻出现——无需切换窗口、无需打开浏览器标签，只需按下 `Alt+Space` 就能开始输入。专为创作者、开发者以及所有希望无摩擦使用 AI 的人打造。

### 为什么选择 OpenHam？

大多数 AI 助手需要你主动去找它们。OpenHam 主动来找你。

| 传统 AI | OpenHam |
|---------|---------|
| 打开浏览器 → 找标签页 → 点击输入框 | 按 `Alt+Space` |
| 上下文切换打断工作流 | 悬浮窗出现，你保持专注 |
| API 密钥存在云端配置 | 加密的本地环境变量 |
| 臃肿的 Electron 应用 | 原生 Qt，极小体积 |
| 通用化回复 | 实时流式对话，有个性 |

### 认识 Ham 🐹

你的助手有名字、有存在感、有灵魂。

Ham 快速、直接、随时待命。当你需要答案时，Ham 不会浪费时间寒暄客套。Ham 实时流式输出响应，让你在思考完成前就能开始阅读。Ham 还会做数学题——只需输入 `2+2*3` 就能立即得到结果，无需切换"计算器模式"。

Ham 也是一只仓鼠。这是有意为之，为这个实用工具增添了一份乐趣。

```
你: "冰岛的首都是哪里？"
Ham: "雷克雅未克。人口约 13 万。世界最北端的首都。
      冷知识：尽管位于北极圈以南 2°，地热供暖让它保持温暖。"

你: "127.5 * 0.85"
Ham: "108.375"
      (即时计算，无需 API 调用)
```

### 前置要求

- **Python 3.9+** — [下载](https://www.python.org/downloads/)
- **Windows 系统** — 使用 Windows 专用 API 实现全局热键和单实例保护
- **DeepSeek API 密钥** — [在这里获取](https://platform.deepseek.com/)（或使用任何 OpenAI 兼容 API）

### 快速开始

```bash
# 克隆 OpenHam
git clone https://github.com/zhaomaota97/OpenHam.git
cd OpenHam

# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥
cp .env
# 编辑 .env 并添加: DEEPSEEK_API_KEY=sk-your-key-here

# 运行
python main.py
```

**或使用预构建的可执行文件：**

1. 从 [Releases](https://github.com/zhaomaota97/OpenHam/releases) 下载最新版本
2. 解压到任意文件夹
3. 运行 `OpenHam.exe`
4. 按 `Alt+Space` 激活

### 核心特性

✅ **全局热键激活** — 随时随地按 `Alt+Space`（完全可自定义）  
✅ **流式 AI 响应** — 实时逐字输出，无需等待  
✅ **即时数学计算** — 输入表达式如 `2+2*3`，立即获得结果  
✅ **本地文件搜索** — 输入 `找 关键词` 即可快速搜索本机文件  
✅ **内置快捷指令** — `cmd`、`powershell`、`截图`、`任务管理器` 等  
✅ **系统托盘集成** — 后台运行，零任务栏占用  
✅ **单实例保护** — 防止多个实例冲突  
✅ **默认安全** — API 密钥存储在环境变量中，永不进入配置文件  
✅ **轻量快速** — 原生 Qt 界面，极小内存占用  

### 配置说明

编辑 `config.json` 自定义行为：

```json
{
  "hotkey": "<alt>+<space>",
  "search_roots": []
}
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `hotkey` | 全局热键（keyboard 库格式） | `<alt>+<space>` |
| `search_roots` | 文件搜索目录（空 = 桌面/文档/下载/主目录） | `[]` |

**API 密钥管理**：API 密钥通过 `DEEPSEEK_API_KEY` 环境变量管理，不存储在 `config.json` 中，防止意外泄露。

**热键格式示例**：
- `<alt>+<space>` — Alt + Space（默认）
- `<ctrl>+<F11>` — Ctrl + F11
- `<alt>+<F1>` — Alt + F1

### 使用方式

1. **启动应用**：运行 `main.py` 或 `.exe` 可执行文件
2. **触发窗口**：按配置的热键（默认 `Alt+Space`）
3. **输入查询**：
   - 纯文本：发送给 AI 进行流式响应
   - 数学表达式（如 `2+2*3`）：实时计算显示
   - `找 关键词`：按文件名搜索本机文件
   - 内置指令（如 `cmd`、`截图`）：即时执行
4. **文件搜索结果**：`↵` 打开文件 · `Ctrl+↵` 打开所在文件夹 · `↑↓` 导航
5. **按 Esc**：关闭窗口，返回工作

### 技术栈

- **UI 框架**：PyQt6 — 原生、轻量、跨平台
- **热键监听**：keyboard — 低级钩子（WH_KEYBOARD_LL），可抑制系统快捷键
- **AI 后端**：OpenAI 兼容 API（默认：DeepSeek）
- **表达式计算**：Python AST — 安全求值，无 `eval()`
- **文件搜索**：`os.walk` — 递归、多线程、跳过系统目录
- **进程单例**：Windows 命名互斥体 — 防止重复实例

### 架构

```
main.py        — 应用入口、热键管理、信号编排
window.py      — Qt 输入窗口 UI 和交互逻辑
executor.py    — AI 对话和表达式求值的核心逻辑
config.json    — 应用配置（热键、模型设置）
build.py       — PyInstaller 打包脚本
```

### 开发

**克隆并安装**

```bash
git clone https://github.com/zhaomaota97/OpenHam.git
cd OpenHam
pip install -r requirements.txt
```

**运行开发版本**

```bash
python main.py
```

**构建可执行文件**

```bash
python build.py
# 输出文件在 dist/ 目录
```

### 安全优先

OpenHam 将安全作为默认设置，而非事后补救。

✅ **基于环境变量的密钥** — API 密钥永不接触配置文件  
✅ **本地优先架构** — 除 API 调用外，数据不离开你的机器  
✅ **安全表达式求值** — 基于 AST 的数学解析器，无任意代码执行  
✅ **单实例保护** — 防止竞态条件和冲突  

### 贡献

OpenHam 采用 MIT 许可证，欢迎贡献。

- **功能**：在 GitHub 上提交 PR
- **Bug**：提交 issue 并附上复现步骤
- **想法**：在 Issues 中发起讨论

### 社区

⭐ **在 GitHub 上给我们加星** — [github.com/zhaomaota97/OpenHam](https://github.com/zhaomaota97/OpenHam)  
🐛 **报告 Bug** — [提交 issue](https://github.com/zhaomaota97/OpenHam/issues)  
💡 **功能请求** — [发起讨论](https://github.com/zhaomaota97/OpenHam/discussions)  

### 许可证

MIT 许可证 — 自由使用、修改和分发。详见 [LICENSE](LICENSE)。

### 路线图

- [ ] macOS 和 Linux 支持
- [ ] 自定义命令插件系统
- [ ] 本地 LLM 支持（Ollama、LM Studio）
- [ ] 多语言界面
- [ ] 语音输入支持
- [ ] 自定义主题

---

Ham 在等你。按下 `Alt+Space`。🐹