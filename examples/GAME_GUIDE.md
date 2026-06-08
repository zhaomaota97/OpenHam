# OpenHam 游戏包开发规范（给 AI 的提示词）

> 把本文件整段发给任意 AI，并在结尾补一句"请按此规范帮我做一个 XXX 游戏"，
> 即可得到一个能在 OpenHam 房间里联机的游戏包。

你要产出的是一个 **OpenHam 游戏包**：玩家在电脑或手机上进入同一个房间后，
能一起玩你写的这个游戏。游戏跑在一个**沙箱网页视图（iframe）**里，靠 OpenHam
注入的全局对象 `OpenHam` 和其他玩家通信。

---

## 1. 产物结构

一个文件夹，**强烈建议做成单个 `index.html`**（把 CSS/JS 全内联），这样手机端开箱即玩：

```
我的游戏/
  index.html        # 入口，必须
  manifest.json     # 元信息
  （可选）其它 .js/.css/图片/音频
```

`manifest.json`：

```json
{
  "name": "游戏名",
  "entry": "index.html",
  "version": "1.0",
  "players": { "min": 2, "max": 2 }
}
```

- `players.max` 是这个游戏**最多几个人玩**。多出来的人应被你的代码安排为**观战**。
- OpenHam 房间本身有人数硬上限（默认 16），但"这个游戏几个人玩"由你在游戏里强制。

---

## 2. 联机 API（OpenHam 自动注入，无需引入任何库）

游戏加载时，OpenHam 会在 `window` 上注入：

```js
// 桥就绪后回调——在这里初始化你的游戏，别在全局直接用 OpenHam（可能还没就绪）
window.OpenHamReady = function () {
  OpenHam.me;        // 字符串：自己的玩家 id（唯一）
  OpenHam.name;      // 字符串：自己的昵称（可用于记分榜显示）
  OpenHam.isHost;    // 布尔：自己是不是房主（建房的人 = 第一个进来的）

  // 接收其他玩家发来的消息
  OpenHam.on(function (msg) {
    // msg 是对方 OpenHam.send 发出的对象
    // 额外带：msg._from = 对方昵称, msg._id = 对方玩家 id
  });
};

// 把本方操作/状态广播给房间里其他所有人
OpenHam.send({ k: "move", x: 1, y: 2 });
```

就这些。没有别的方法，**不要假设存在其它 API**。

---

## 3. 必须遵守的多人模式：房主当裁判（host-authoritative）

为避免各客户端状态打架，约定 **房主（`OpenHam.isHost===true`）是唯一权威**：

- **房主**：维护全部游戏状态、做规则判定、按节奏把"权威状态"广播给所有人。
- **其他玩家**：只把自己的"输入"发给房主，渲染则以房主广播的状态为准。
- **观战者**：只接收并渲染状态，不参与输入。

### 玩家发现 / 角色分配（hello 握手）

新玩家进来时游戏才加载，房主需要知道"来了个人、给他什么角色"。约定：

1. 非房主就绪时发 `OpenHam.send({k:"hello"})`。
2. 房主收到 `hello`，用 `msg._id` 认人：还有空位就把他设为玩家2/3…，满了就让他观战。
3. 房主在广播的状态里带上各角色对应的 `id`；每个客户端用 `OpenHam.me` 和这些 id 比对，得知自己是"玩家几"还是"观战"。

### 强制人数上限

`players.max` 个之外的人，房主一律分配为观战。客户端据此把输入禁用、只渲染。

---

## 4. 手机兼容（很重要）

游戏会在手机浏览器里跑，请务必：

- **做成单文件 `index.html`**（内联一切）。多文件虽支持，但单文件最稳。
- 加 `<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">`。
- 用 **Pointer 事件**（`pointerdown/pointermove`）统一处理鼠标和触摸；canvas 设 `touch-action:none`。
- 自适应屏幕：canvas 用固定内部坐标 + CSS `max-width/max-height` 缩放，坐标换算用 `getBoundingClientRect()`。
- 只用标准 Web API，别用需要联网的 CDN/外链资源。

### 美术素材

优先**内联 SVG**（矢量，高清屏锐利、随屏幕缩放、零外部文件，最适合手机）。
也可用 emoji 当贴图，或把图片转成 `data:` URI 内联。
尽量别用单独的图片文件——沙箱 iframe 里外链资源不一定能加载，单文件最稳。

---

## 5. 最小模板（可直接改）

```html
<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<style>html,body{margin:0;height:100%;background:#1c1a14;color:#ede5d0;
  font-family:system-ui,"Microsoft YaHei",sans-serif;touch-action:none;}</style></head>
<body>
<div id="status">连接中…</div>
<script>
window.OpenHamReady = function () {
  const mine = OpenHam.isHost ? "X" : "O";
  document.getElementById("status").textContent = "你是 " + mine;
  OpenHam.on(function (msg) {
    if (msg.k === "ping") console.log(msg._from, "说 ping");
  });
  // 示例：点一下广播一下
  document.body.onclick = () => OpenHam.send({ k: "ping" });
};
</script></body></html>
```

---

## 6. 防卡死：硬性要求（不满足游戏很容易卡死、无法继续）

以下**必须做到**：

1. **必须有「重新开始」按钮**，始终可见、可点。点击后：重置本局状态，并 `OpenHam.send({k:"reset"})` 广播；**所有人（含房主）收到 `reset` 都重置本局**——大家一起重开。
2. **任何玩家都能点「重新开始」**（别只让房主能点）。否则房主中途退出后就再没人能重开了。
3. **结束后能重来**：分出胜负/平局后别停在结束画面回不去——靠重新开始即可再来一局。
4. **等人不卡死**：人数不够时显示「等待其他玩家…」，不要卡住或报错；够了再开始。
5. **有人中途退出不死锁**：回合制别永远停在某人的回合（提供"重新开始"让大家重来）。
6. **新加入者能看到当前局面**：房主收到新人的 `hello` 后，广播一次完整状态，避免新人看到空白/错乱画面。
7. **始终有清晰状态提示**：轮到谁、在等待、已结束——让玩家随时明白现在该干嘛。
8. **输入要校验**：非法操作（不该你动、点了不该点的、观战者乱点）一律忽略，绝不让游戏卡住或报错。

---

## 7. 检查清单（产出前自检）

- [ ] 有 `manifest.json`，填了 `name` 和 `players.max`。
- [ ] 入口是 `index.html`，最好单文件内联。
- [ ] 在 `window.OpenHamReady` 里初始化，没有在全局裸用 `OpenHam`。
- [ ] 房主当裁判；其他人发输入、渲染用房主状态。
- [ ] 有 hello 握手；超过 `players.max` 的人进入观战。
- [ ] **有始终可见的「重新开始」按钮，任何人可点，点击广播 `reset` 让所有人一起重开。**
- [ ] **结束后能重来、等人不卡、有人退出不死锁、新加入者能看到当前局面。**
- [ ] 手机：viewport + pointer 事件 + 自适应缩放。
- [ ] 不引用任何外部网络资源。

---

## 8. 参考实现

- `games/tictactoe/` —— 回合制（井字棋），最简单的双人同步。
- `games/pong/` —— 实时动作（弹球对战），演示房主当裁判 + hello 握手 + 超员观战。
- `games/whack/` —— 移动端优先（打仓鼠），演示内联 SVG 美术 + 多人抢分 + 记分榜。

照着这两个例子改，是最快的方式。
