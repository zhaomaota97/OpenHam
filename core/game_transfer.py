"""游戏包传输：把 zip 字节切成 base64 分片，经 relay 通道发送并在对端重组。

消息（包在 relay 的 data 字段里）：
    {"t":"game_meta",  "name":..., "size":N, "chunks":K}   # 先发，宣告即将传输
    {"t":"game_chunk", "seq":i, "b64":"..."}               # K 个分片
对端按 seq 收齐后还原出完整 zip 字节。
"""
import math
import base64

CHUNK_RAW = 48 * 1024   # 每片原始字节数（base64 后约 64KB，单条 WebSocket 消息可承载）


def chunk_package(data: bytes, name: str) -> list:
    """把包字节切分成 [meta, chunk0, chunk1, ...] 一串待发消息。"""
    n = max(1, math.ceil(len(data) / CHUNK_RAW))
    msgs = [{"t": "game_meta", "name": name, "size": len(data), "chunks": n}]
    for i in range(n):
        piece = data[i * CHUNK_RAW:(i + 1) * CHUNK_RAW]
        msgs.append({"t": "game_chunk", "seq": i, "b64": base64.b64encode(piece).decode("ascii")})
    return msgs


class Reassembler:
    """收集分片并在收齐后还原完整字节。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.name = None
        self.size = 0
        self.total = 0
        self._parts: dict[int, bytes] = {}

    def on_meta(self, m: dict):
        self.reset()
        self.name = m.get("name", "游戏")
        self.size = int(m.get("size", 0))
        self.total = int(m.get("chunks", 0))

    def on_chunk(self, m: dict):
        """收到一个分片；若已收齐则返回完整字节，否则返回 None。"""
        if self.total <= 0:
            return None
        try:
            self._parts[int(m["seq"])] = base64.b64decode(m["b64"])
        except Exception:
            return None
        if len(self._parts) >= self.total:
            try:
                data = b"".join(self._parts[i] for i in range(self.total))
            except KeyError:
                return None  # 还有缺片
            if self.size and len(data) != self.size:
                return None  # 大小不符，等待/丢弃
            return data
        return None

    @property
    def progress(self) -> float:
        return len(self._parts) / self.total if self.total else 0.0


if __name__ == "__main__":
    import os
    # 自测：随机字节往返 + 乱序到达
    for size in (10, CHUNK_RAW, CHUNK_RAW + 1, CHUNK_RAW * 3 + 123, 500_000):
        data = os.urandom(size)
        msgs = chunk_package(data, "测试游戏")
        meta, chunks = msgs[0], msgs[1:]
        r = Reassembler()
        r.on_meta(meta)
        # 故意乱序
        result = None
        for m in reversed(chunks):
            out = r.on_chunk(m)
            if out is not None:
                result = out
        assert result == data, f"往返失败 size={size}"
        print(f"size={size:>8}  chunks={meta['chunks']:>3}  ✓")
    print("\nGAME TRANSFER SELFTEST PASS")
