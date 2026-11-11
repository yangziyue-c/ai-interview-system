# -*- coding: utf-8 -*-
"""
A11 AI 面试官框架（2 号 AI 对话层）
============================================================
包级副作用：在**任何东西 import torch / sentence_transformers 之前**，
先把 HuggingFace 的离线环境变量设好。这一步必须发生在包的最前面，
因为 sentence_transformers 在被 import 时就会读这些变量。

放在这里而不是 config.py，是为了保证「只要 import app.* 就一定先生效」。
"""
import os

# 模型已完整缓存在本地，禁止联网下载（离线跑更快，也不会因网络问题卡住启动）
os.environ.setdefault("HF_HOME", r"D:\A11-Data\hf_cache")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

__version__ = "1.0.0"
