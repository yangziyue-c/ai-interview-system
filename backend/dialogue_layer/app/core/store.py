# -*- coding: utf-8 -*-
"""
store.py · 会话存储
============================================================
内存字典 + TTL 懒清扫 + 容量上限。

修 #6：原实现是一个裸的 dict，会话只增不减、永不回收；且 /finish 直接把会话
pop 掉，导致结果再也取不回来。这里改成：
- 每个会话带 expire_at；每次访问时顺带清一遍过期的（懒清扫，不需要后台线程）
- /finish 之后**不删除**会话，只是把 TTL 换成长一点的 RESULT_TTL，
  于是 /finish 与 /result/{sid} 都变成幂等的
- 条数超上限时淘汰最久未活动的会话，防止内存无上限增长

FastAPI 的同步端点跑在线程池里，所以这里必须加锁 —— 裸 dict 会被多线程同时改。
"""
import threading
import time
from typing import Optional

from app import config
from app.logging_conf import get_logger

logger = get_logger(__name__)


class SessionStore:
    def __init__(self,
                 session_ttl: int = config.SESSION_TTL,
                 result_ttl: int = config.RESULT_TTL,
                 max_sessions: int = config.MAX_SESSIONS):
        self._lock = threading.RLock()
        self._sessions: dict[str, object] = {}
        self._expire_at: dict[str, float] = {}
        self._session_ttl = session_ttl
        self._result_ttl = result_ttl
        self._max = max_sessions

    # ---------- 基本操作 ----------
    def add(self, session) -> None:
        sid = session.session_id
        with self._lock:
            self._evict_expired_locked()
            if len(self._sessions) >= self._max:
                self._evict_lru_locked()
            self._sessions[sid] = session
            self._expire_at[sid] = time.time() + self._session_ttl
        logger.info("会话已创建 sid=%s job=%s 当前活跃=%d",
                    sid, getattr(session, "job", "?"), len(self._sessions))

    def get(self, session_id: str):
        with self._lock:
            self._evict_expired_locked()
            s = self._sessions.get(session_id)
            if s is not None:
                # 未结束的会话每次访问续期；已结束的保持 result TTL
                if getattr(s, "phase", "") != "finished":
                    self._expire_at[session_id] = time.time() + self._session_ttl
            return s

    def keep_result(self, session_id: str) -> None:
        """会话结束后调用：把 TTL 换成长一点的 RESULT_TTL，使结果可复查。"""
        with self._lock:
            if session_id in self._sessions:
                self._expire_at[session_id] = time.time() + self._result_ttl

    def evict_expired(self) -> int:
        with self._lock:
            return self._evict_expired_locked()

    # ---------- 统计（/health 用）----------
    def stats(self) -> dict:
        with self._lock:
            active = sum(1 for s in self._sessions.values()
                         if getattr(s, "phase", "") != "finished")
            return {"sessions_active": active,
                    "sessions_finished": len(self._sessions) - active,
                    "sessions_total": len(self._sessions),
                    "session_capacity": self._max}

    # ---------- 内部（调用方已持锁）----------
    def _evict_expired_locked(self) -> int:
        now = time.time()
        dead = [sid for sid, ts in self._expire_at.items() if ts <= now]
        for sid in dead:
            self._sessions.pop(sid, None)
            self._expire_at.pop(sid, None)
        if dead:
            logger.info("已回收过期会话 %d 个，剩余 %d", len(dead), len(self._sessions))
        return len(dead)

    def _evict_lru_locked(self) -> None:
        if not self._sessions:
            return
        sid = min(self._expire_at, key=self._expire_at.get)
        s = self._sessions.pop(sid, None)
        self._expire_at.pop(sid, None)
        logger.warning("会话数达上限 %d，淘汰最久未活动的 sid=%s phase=%s",
                       self._max, sid, getattr(s, "phase", "?"))


STORE = SessionStore()
