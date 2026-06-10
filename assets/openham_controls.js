/* OpenHam 统一输入层：桌面用键盘，触屏自动显示虚拟摇杆 + 按钮。
 * 游戏只需：OpenHam.input.enable({joystick:true, buttons:["跳","射"]})
 * 然后每帧读：OpenHam.input.x / .y（-1..1）、.down("跳")、.pressed("跳")。
 * 同一份游戏代码在电脑和手机上都能玩，无需自己写触摸控制。
 */
(function () {
  var OH = (window.OpenHam = window.OpenHam || {});
  if (OH.input) return; // 防重复注入

  var cur = {};   // 按钮当前是否按下
  var edge = {};  // 刚按下（被 pressed() 消费一次）
  var keys = {};  // 键盘按键状态
  var joy = { active: false, x: 0, y: 0 };
  var btnDefs = []; // [{name, key}]

  var isTouch = ('ontouchstart' in window) ||
                (navigator.maxTouchPoints > 0) ||
                (window.matchMedia && window.matchMedia('(pointer:coarse)').matches);

  function setBtn(name, v) {
    if (v && !cur[name]) edge[name] = true; // 上升沿
    cur[name] = v;
  }

  // ── 键盘 ──────────────────────────────────────────────
  window.addEventListener('keydown', function (e) {
    var k = (e.key || '').toLowerCase();
    keys[k] = true;
    for (var i = 0; i < btnDefs.length; i++) {
      if (btnDefs[i].key === k) { setBtn(btnDefs[i].name, true); e.preventDefault(); }
    }
  });
  window.addEventListener('keyup', function (e) {
    var k = (e.key || '').toLowerCase();
    keys[k] = false;
    for (var i = 0; i < btnDefs.length; i++) {
      if (btnDefs[i].key === k) setBtn(btnDefs[i].name, false);
    }
  });
  function keyDir() {
    var x = 0, y = 0;
    if (keys['arrowleft'] || keys['a']) x -= 1;
    if (keys['arrowright'] || keys['d']) x += 1;
    if (keys['arrowup'] || keys['w']) y -= 1;
    if (keys['arrowdown'] || keys['s']) y += 1;
    return { x: x, y: y };
  }

  // ── 触屏：虚拟摇杆 + 按钮 DOM ────────────────────────────
  var DEFAULT_KEYS = [' ', 'j', 'k', 'l', 'u', 'i'];

  function makeJoystick() {
    var base = document.createElement('div');
    base.style.cssText = 'position:fixed;left:22px;bottom:22px;width:120px;height:120px;' +
      'border-radius:50%;background:rgba(0,0,0,0.18);border:2px solid rgba(255,255,255,0.35);' +
      'touch-action:none;z-index:99999;';
    var thumb = document.createElement('div');
    thumb.style.cssText = 'position:absolute;left:35px;top:35px;width:50px;height:50px;' +
      'border-radius:50%;background:rgba(255,255,255,0.55);box-shadow:0 2px 8px rgba(0,0,0,0.3);';
    base.appendChild(thumb);
    document.body.appendChild(base);
    var R = 45, pid = null;
    function update(cx, cy) {
      var r = base.getBoundingClientRect();
      var dx = cx - (r.left + 60), dy = cy - (r.top + 60);
      var d = Math.hypot(dx, dy);
      if (d > R) { dx = dx / d * R; dy = dy / d * R; }
      thumb.style.left = (35 + dx) + 'px';
      thumb.style.top = (35 + dy) + 'px';
      joy.x = dx / R; joy.y = dy / R; joy.active = true;
    }
    function reset() { thumb.style.left = '35px'; thumb.style.top = '35px'; joy.x = 0; joy.y = 0; joy.active = false; pid = null; }
    base.addEventListener('pointerdown', function (e) { pid = e.pointerId; base.setPointerCapture(pid); update(e.clientX, e.clientY); e.preventDefault(); });
    base.addEventListener('pointermove', function (e) { if (e.pointerId === pid) { update(e.clientX, e.clientY); e.preventDefault(); } });
    base.addEventListener('pointerup', function (e) { if (e.pointerId === pid) reset(); });
    base.addEventListener('pointercancel', reset);
  }

  function makeButton(name, idx) {
    var b = document.createElement('div');
    var right = 26 + (idx % 2) * 96;
    var bottom = 30 + Math.floor(idx / 2) * 96;
    b.textContent = name;
    b.style.cssText = 'position:fixed;right:' + right + 'px;bottom:' + bottom + 'px;width:78px;height:78px;' +
      'border-radius:50%;background:rgba(0,0,0,0.20);border:2px solid rgba(255,255,255,0.35);' +
      'color:#fff;font:600 16px/78px sans-serif;text-align:center;user-select:none;touch-action:none;z-index:99999;';
    document.body.appendChild(b);
    b.addEventListener('pointerdown', function (e) { setBtn(name, true); b.style.background = 'rgba(255,255,255,0.35)'; e.preventDefault(); });
    var up = function () { setBtn(name, false); b.style.background = 'rgba(0,0,0,0.20)'; };
    b.addEventListener('pointerup', up);
    b.addEventListener('pointercancel', up);
    b.addEventListener('pointerleave', up);
  }

  // ── 公开 API ──────────────────────────────────────────
  OH.input = {
    x: 0, y: 0,
    enable: function (opts) {
      opts = opts || {};
      var names = opts.buttons || [];
      btnDefs = names.map(function (n, i) { return { name: n, key: (DEFAULT_KEYS[i] || '').toLowerCase() }; });
      function build() {
        if (isTouch) {
          if (opts.joystick) makeJoystick();
          names.forEach(function (n, i) { makeButton(n, i); });
        }
      }
      if (document.body) build();
      else window.addEventListener('DOMContentLoaded', build);
      return OH.input;
    },
    down: function (name) { return !!cur[name]; },
    pressed: function (name) { if (edge[name]) { edge[name] = false; return true; } return false; },
  };

  // ── 联机助手（房主裁判模式的高层封装，省得每个游戏手写）────────────
  OH.players = [];   // [{id,name}]，含自己；平台自动维护
  OH._joinCb = null; OH._stateCb = null; OH._inputCb = null;

  function addPlayer(id, name) {
    if (!id) return false;
    for (var i = 0; i < OH.players.length; i++) {
      if (OH.players[i].id === id) { OH.players[i].name = name; return false; }
    }
    OH.players.push({ id: id, name: name });
    return true;
  }

  OH.onJoin = function (cb) { OH._joinCb = cb; return OH; };   // 房主：新人加入(可在此广播状态给他)
  OH.onState = function (cb) { OH._stateCb = cb; return OH; }; // 非房主：收到房主的权威状态
  OH.onInput = function (cb) { OH._inputCb = cb; return OH; }; // 房主：收到某玩家输入 cb(id, input)
  OH.syncState = function (s) { if (OH.isHost && OH.send) OH.send({ __oh: 'state', s: s }); }; // 房主广播状态
  OH.sendInput = function (i) { if (OH.send) OH.send({ __oh: 'input', id: OH.me, i: i }); };    // 玩家把输入发给房主

  // 平台内部消息路由（桥收到 __oh 前缀的消息会调这里，不会传给游戏的 OpenHam.on）
  OH._onmsg = function (o) {
    if (o.__oh === 'hello') {
      var isNew = addPlayer(o.id, o.name);
      if (OH.isHost) {
        OH.send({ __oh: 'roster', players: OH.players });        // 把最新名单广播给所有人
        if (isNew && OH._joinCb) OH._joinCb({ id: o.id, name: o.name });
      }
    } else if (o.__oh === 'roster') {
      OH.players = o.players || OH.players;
    } else if (o.__oh === 'state') {
      if (OH._stateCb) OH._stateCb(o.s);
    } else if (o.__oh === 'input') {
      if (OH.isHost && OH._inputCb) OH._inputCb(o.id, o.i);
    }
  };
  // 桥就绪后由桥调用：把自己加进名单并向全员握手
  OH._onready = function () {
    addPlayer(OH.me, OH.name);
    if (OH.send) OH.send({ __oh: 'hello', id: OH.me, name: OH.name });
  };

  // 每帧把方向汇总到 input.x / input.y（摇杆优先，否则键盘）
  function loop() {
    var k = keyDir();
    var x = joy.active ? joy.x : k.x;
    var y = joy.active ? joy.y : k.y;
    OH.input.x = Math.max(-1, Math.min(1, x));
    OH.input.y = Math.max(-1, Math.min(1, y));
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();
