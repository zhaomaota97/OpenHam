# OpenHam 联机游戏开发规范（给 AI 的提示词）

你要产出一个**可联机、电脑和手机都能玩**的网页小游戏。平台已经帮你准备好了
游戏引擎、联机通道、跨平台输入——你只管用，不用自己造轮子。

---

## 1. 产物：单个 `index.html`

- 一个文件，CSS/JS 全内联。**用 Phaser 3 画游戏**（引擎已全局注入，见下）。
- 不要自己写 `<script src="phaser...">`——平台已经注入了 `window.Phaser`，直接用。
- 配套一个 `manifest.json`：`{ "name": "游戏名", "entry": "index.html", "players": { "min": 2, "max": 4 } }`
  - `players.max` = 最多几人玩；多出来的人由你的代码安排为**观战**。

## 2. 平台已注入的全局（无需引入任何库）

游戏脚本运行前，下面三样已经就绪：

- **`Phaser`** —— Phaser 3 游戏引擎（精灵、物理 Arcade/Matter、场景、补间、音效、粒子、输入）。
- **`OpenHam`** —— 联机桥（见 §3）。注意 `OpenHam.send` 在 `OpenHamReady()` 后才可用。
- **`OpenHam.input`** —— 跨平台输入（见 §4）。电脑键盘 / 手机虚拟摇杆，自动适配。

## 3. 联机：房主当裁判（host-authoritative）

```js
OpenHam.me        // 自己的 id（字符串）
OpenHam.name      // 自己的昵称
OpenHam.isHost    // 是否房主（房主当裁判，跑唯一权威逻辑）
OpenHam.send(obj) // 把任意 JSON 发给房间里其他所有人
OpenHam.on(fn)    // fn(obj) 收到别人发来的 JSON
window.OpenHamReady = function(){ /* 这里才能 send；做握手、开始游戏 */ }
```

**标准模式（强烈建议照搬）：**
- **只有房主跑游戏逻辑/物理**，每隔一帧（或每 N 毫秒）把**权威状态**广播给所有人：
  `if (OpenHam.isHost) OpenHam.send({t:'state', players:{...}, ball:{...}, ...})`
- **非房主只渲染收到的状态、并把自己的输入发给房主**：
  `OpenHam.send({t:'input', x:OpenHam.input.x, y:OpenHam.input.y, jump:OpenHam.input.pressed('跳')})`
- **房主**在 `OpenHam.on` 里收集每个玩家的 input，喂给自己的物理。
- **玩家发现（hello 握手）**：每人上线时 `OpenHam.send({t:'hello', id:OpenHam.me, name:OpenHam.name})`；
  房主收齐后分配座位/角色，超过 `players.max` 的人设为观战（禁用输入、只渲染）。
- **新人补状态**：房主收到 hello 后，立刻广播一次完整状态，让迟到者跟上。

## 4. 跨平台输入（重点：手机也能玩）

不要自己写键盘或触摸事件。用平台的统一输入层，**一份代码电脑手机通用**：

```js
// 启用：joystick=显示虚拟摇杆(仅手机)，buttons=屏幕按钮(仅手机)，电脑自动映射键盘
OpenHam.input.enable({ joystick: true, buttons: ["跳", "射"] });

// 每帧读取：
OpenHam.input.x          // 方向 X，-1..1（手机摇杆 / 电脑 ←→ 或 A D）
OpenHam.input.y          // 方向 Y，-1..1（↑ 为 -1）（手机摇杆 / 电脑 ↑↓ 或 W S）
OpenHam.input.down("跳")   // 按钮是否按住（手机第1个按钮 / 电脑空格；第2个=J；第3个=K…）
OpenHam.input.pressed("跳") // 这一帧是否刚按下（适合跳跃/射击，每次按只触发一次）
```

- 手机上会**自动**在屏幕左下角画虚拟摇杆、右下角画你命名的按钮——你**不用管**。
- 电脑上摇杆方向映射到方向键/WASD，按钮按顺序映射到 空格 / J / K / L。
- 纯点击/落子类游戏（井字棋、卡牌）不需要 `enable`，直接用 Phaser 的指针事件
  （`this.input.on('pointerdown', ...)`，手机点击和鼠标点击通用）。

## 5. 手机适配（很重要）

- `<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">`
- Phaser 配置用自适应缩放，铺满屏幕、横竖屏都不变形：
  ```js
  const config = {
    type: Phaser.AUTO, parent: document.body,
    scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH,
             width: 800, height: 450 },   // 固定内部坐标，CSS 自动缩放
    physics: { default: 'arcade', arcade: { gravity: { y: 0 } } },
    backgroundColor: '#1d1d1f',
    scene: { create, update }
  };
  new Phaser.Game(config);
  ```
- 美术：优先用 Phaser 的图形 API（`this.add.rectangle/circle/star`、`graphics`）、几何精灵、
  或内联 base64 贴图；也可用 emoji 当贴图（`this.add.text(x,y,'🚀',{fontSize:'40px'})`）。
  **不要引用任何外部图片/音频网址**（除平台已注入的 Phaser 外，不依赖任何外链）。

## 6. 防卡死（硬性要求，不满足很容易卡死）

- **必须有「重新开始」按钮**（始终可点）。任何玩家点击都要
  `OpenHam.send({t:'reset'})` 广播，所有人收到 `reset` 一起重置本局——大家一起重开。
- 分出胜负/平局后能立刻重来；人数不够时显示「等待其他玩家…」而不是卡住。
- 有人中途退出不死锁；新人进来能看到当前局面（靠房主补发状态）。

## 7. 最小可联机模板（Phaser，照着改）

```html
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<style>html,body{margin:0;height:100%;background:#1d1d1f;overflow:hidden}</style></head>
<body><script>
let scene, players = {};
function create(){
  scene = this;
  OpenHam.input.enable({ joystick:true, buttons:["跳"] });
  this.restartBtn = this.add.text(10,10,'重新开始',{backgroundColor:'#333',color:'#fff',padding:8})
    .setInteractive().setScrollFactor(0).setDepth(999)
    .on('pointerdown',()=>OpenHam.send({t:'reset'}));
  OpenHam.on(onNet);
  window.OpenHamReady = ()=>{ OpenHam.send({t:'hello', id:OpenHam.me, name:OpenHam.name}); };
}
function update(){
  // 把自己的输入发给房主（或自己就是房主）
  OpenHam.send({t:'input', id:OpenHam.me, x:OpenHam.input.x, y:OpenHam.input.y, jump:OpenHam.input.pressed('跳')});
  if (OpenHam.isHost){ /* 房主：用收到的 input 跑物理，再广播 state */ }
}
function onNet(o){ /* 处理 hello / input / state / reset */ }
new Phaser.Game({ type:Phaser.AUTO, parent:document.body,
  scale:{mode:Phaser.Scale.FIT,autoCenter:Phaser.Scale.CENTER_BOTH,width:800,height:450},
  physics:{default:'arcade'}, backgroundColor:'#1d1d1f', scene:{create,update} });
</script></body></html>
```

## 8. 产出前自检

- [ ] 有 `manifest.json`，填了 `name` 和 `players.max`。
- [ ] 单文件 `index.html`，用 `window.Phaser`，没有任何外部 `<script src>`/图片/音频外链。
- [ ] 移动控制用 `OpenHam.input`（动作游戏 enable 摇杆+按钮）；点击类用 Phaser 指针事件。
- [ ] 联机用房主裁判：房主广播 state、非房主发 input + 渲染；有 hello 握手 + 超员观战。
- [ ] 有「重新开始」按钮，广播 `reset` 全员重置；分胜负后能重来，不卡死。
- [ ] Phaser `Scale.FIT` 自适应，手机横竖屏都能玩。

只输出完整 HTML（从 `<!DOCTYPE html>` 到 `</html>`），不要解释、不要 markdown 代码围栏。
