# -*- coding: utf-8 -*-
"""
logging_conf.py · 日志配置
============================================================
控制台 + logs/app.log（按大小轮转）。所有模块用 logging.getLogger(__name__)。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from app import config

_configured = False


def setup_logging(level: str | None = None) -> None:
    """初始化根 logger。重复调用是安全的（只生效一次）。"""
    global _configured
    if _configured:
        return

    lvl = (level or config.LOG_LEVEL).upper()
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    # Windows 控制台编码兜底：不设的话中文日志可能直接抛 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    handlers: list[logging.Handler] = []
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    handlers.append(console)

    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        fileh = RotatingFileHandler(
            os.path.join(config.LOG_DIR, "app.log"),
            maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fileh.setFormatter(fmt)
        handlers.append(fileh)
    except Exception as e:  # 日志文件写不了也不该让服务起不来
        print(f"[logging] 文件日志不可用（{e}），仅输出到控制台")

    logging.basicConfig(level=lvl, handlers=handlers, force=True)

    # 这些库太吵，压到 WARNING
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers",
                  "transformers", "filelock", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
