"""集中式日志配置。

替代散落在各处的 print：统一写入 openham.log（被 .gitignore 忽略），
开发模式下同时输出到控制台。打包成 exe 后仍能留下日志便于排错。
"""
import os
import sys
import logging

from utils.paths import _base_dir

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    root = logging.getLogger("openham")
    if _configured:
        return root

    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        fh = logging.FileHandler(os.path.join(_base_dir(), "openham.log"), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass  # 文件不可写时不阻断启动

    # 非打包（开发）模式下额外输出到控制台
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    """获取 openham 命名空间下的子 logger。"""
    return logging.getLogger(f"openham.{name}")
