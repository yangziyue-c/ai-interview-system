# -*- coding: utf-8 -*-
"""Embedding provider: OpenAI-compatible online API, with explicit local fallback."""
from __future__ import annotations

from typing import Iterable

import numpy as np

from app import config
from app.logging_conf import get_logger

logger = get_logger(__name__)


class OnlineEmbedding:
    """Minimal OpenAI-compatible embeddings client used by RAG and KB."""

    def __init__(self):
        self.max_seq_length = config.KB_MAX_TOKENS

    @property
    def model(self) -> str:
        return config.EMBEDDING_MODEL

    def encode(self, texts: Iterable[str], normalize_embeddings: bool = False
               ) -> np.ndarray:
        import httpx

        values = [str(x or "") for x in texts]
        if not values:
            return np.zeros((0, 0), dtype="float32")
        if not config.EMBEDDING_BASE_URL:
            raise RuntimeError("A11_EMBEDDING_BASE_URL 未配置")
        if not config.EMBEDDING_API_KEY:
            raise RuntimeError("A11_EMBEDDING_API_KEY 未配置")

        url = config.EMBEDDING_BASE_URL.rstrip("/")
        if not url.endswith("/embeddings"):
            url += "/embeddings"
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {config.EMBEDDING_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.EMBEDDING_MODEL,
                "input": values,
                "encoding_format": "float",
            },
            timeout=config.EMBEDDING_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        rows = body.get("data") or []
        if len(rows) != len(values):
            raise RuntimeError(
                f"embedding 返回条数不一致：{len(rows)} != {len(values)}")
        rows = sorted(rows, key=lambda x: int(x.get("index", 0)))
        arr = np.asarray([r.get("embedding") for r in rows], dtype="float32")
        if arr.ndim != 2 or arr.shape[0] != len(values):
            raise RuntimeError(f"embedding 返回形状非法：{arr.shape}")
        if normalize_embeddings:
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            arr = arr / np.clip(norms, 1e-12, None)
        return arr


def get_encoder(local_model: str, local_dtype: str = ""):
    provider = config.EMBEDDING_PROVIDER
    if provider in ("online", "openai", "openai_compatible"):
        logger.info("Embedding 使用在线接口 model=%s", config.EMBEDDING_MODEL)
        return OnlineEmbedding()
    if provider != "local":
        raise RuntimeError(f"未知 A11_EMBEDDING_PROVIDER={provider!r}")

    from sentence_transformers import SentenceTransformer
    kw = {}
    if local_dtype == "fp16":
        import torch
        kw["model_kwargs"] = {"torch_dtype": torch.float16}
    model = SentenceTransformer(local_model, **kw)
    model.max_seq_length = config.KB_MAX_TOKENS
    return model


def embedding_status() -> dict:
    online = config.EMBEDDING_PROVIDER in ("online", "openai", "openai_compatible")
    ready = bool(
        online and config.EMBEDDING_BASE_URL and config.EMBEDDING_API_KEY
    ) or config.EMBEDDING_PROVIDER == "local"
    error = ""
    if online and not ready:
        error = "在线 Embedding 未配置 base_url 或 api_key"
    return {
        "embedding_enabled": True,
        "embedding_provider": config.EMBEDDING_PROVIDER,
        "embedding_model": config.EMBEDDING_MODEL,
        "embedding_ready": ready,
        "embedding_error": error,
    }
