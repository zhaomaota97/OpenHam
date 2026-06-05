# OpenHam 游戏包

把一个 HTML 小游戏做成"包"，在 OpenHam 联机房间里和朋友一起玩。

## 游戏包结构

一个文件夹即可：

```
我的游戏/
  index.html        # 入口（必须，或在 manifest 指定）
  manifest.json     # 可选：{"name":"游戏名","entry":"index.html"}
  *.js *.css 图片 音频 ...
```

- 没有 `manifest.json` 时，自动用文件夹名当游戏名、`index.html` 当入口。
- 上限 30MB。只渲染网页内容（html/js/css/资源），**不会执行 exe/bat 等**，因此打开别人的包是安全的。

## 怎么玩

1. 房主（甲）在 OpenHam「联机」里**建房** → 把喵咪密码发给朋友。
2. 房主点「**🎮 发布游戏**」→ 选游戏文件夹 → 游戏自动分发给房内所有人并打开。
3. 朋友粘喵咪密码**进房**后，会自动收到游戏并弹出游戏窗口。
4. 中途加入的人，房主会自动把游戏补发给他。

## 联机 API（游戏 JS 里直接用）

OpenHam 会自动注入一个全局对象 `OpenHam`，无需任何引入：

```js
// 桥就绪后回调（在这里初始化你的游戏）
window.OpenHamReady = function () {
  OpenHam.me;       // 字符串：自己的玩家 id
  OpenHam.isHost;   // 布尔：自己是不是房主

  // 接收其他人发来的操作
  OpenHam.on(function (msg) {
    // msg 是对方 OpenHam.send 发出的对象；msg._from 是对方昵称
  });
};

// 把本方操作广播给房间里其他人
OpenHam.send({ k: "move", i: 4 });
```

约定（建议）：自己定义 `k` 字段区分消息类型，房主当裁判（用 `OpenHam.isHost` 判断）。

## 示例

`tictactoe/` 是一个完整的双人井字棋，演示了 `OpenHamReady` / `send` / `on` / `isHost` 的用法，可直接发布试玩。
