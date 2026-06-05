# OpenHam Relay（中转服务器）

跑在公网服务器（如阿里云 ECS）上的 WebSocket 房间转发服务。OpenHam 客户端
连上它后即可建房 / 进房 / 互相收发（聊天、游戏状态、文件分块都走同一条转发通道）。

## 依赖

- Python 3.8+
- `websockets`

## 快速运行（手动）

```bash
python3 -m pip install websockets
python3 server.py                 # 默认监听 0.0.0.0:9000
```

环境变量可覆盖默认值：

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENHAM_RELAY_HOST` | `0.0.0.0` | 监听地址 |
| `OPENHAM_RELAY_PORT` | `9000`   | 监听端口 |

## ⚠️ 云控制台需手动配置

在 ECS 安全组「入方向」放行：

- **relay 端口**（默认 `9000/TCP`）—— 客户端连接用
- **`22/TCP`** —— 若需远程 SSH 部署/维护

客户端连接地址即：`ws://<ECS公网IP>:9000`

## 开机自启（systemd，推荐生产用）

1. 把本目录上传到服务器，例如 `/opt/openham-relay/`：
   ```bash
   scp -r relay/ <user>@<ECS_IP>:/opt/openham-relay/
   ```
2. 在服务器上安装依赖并创建服务：
   ```bash
   python3 -m pip install websockets
   sudo cp /opt/openham-relay/openham-relay.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now openham-relay
   sudo systemctl status openham-relay      # 查看状态
   journalctl -u openham-relay -f           # 看实时日志
   ```

修改 `openham-relay.service` 里的 `User=` 和 `ExecStart` 路径以匹配你的环境。
