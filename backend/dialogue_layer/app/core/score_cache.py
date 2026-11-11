# -*- coding: utf-8 -*-
"""Small SQLite-backed cache for deterministic model scoring calls."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from typing import Optional

from app import config


def enabled() -> bool:
    return bool(
        config.A11_SCORE_CACHE
        and not config.LLM_MOCK
        and not config.RERANKER_MOCK
    )


def make_key(namespace: str, ctx: dict, model: str) -> str:
    payload = {
        "namespace": namespace,
        "model": model,
        "scoring_version": config.SCORING_VERSION,
        "score_step": config.SCORE_STEP,
        "ctx": ctx,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.SCORE_CACHE_DB), exist_ok=True)
    conn = sqlite3.connect(config.SCORE_CACHE_DB, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS score_cache (
            cache_key TEXT PRIMARY KEY,
            namespace TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at REAL NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    return conn


def get(namespace: str, key: str) -> Optional[dict]:
    if not enabled():
        return None
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT payload FROM score_cache WHERE cache_key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def put(namespace: str, key: str, model: str, payload: dict) -> None:
    if not enabled() or not payload:
        return
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO score_cache "
                "(cache_key, namespace, model, created_at, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    key,
                    namespace,
                    model,
                    time.time(),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
    except Exception:
        return
