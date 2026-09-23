# -*- coding: utf-8 -*-
"""
llm.py · DeepSeek 客户端（OpenAI 兼容接口）
============================================================
三种调用方式：
- chat()        一次性返回完整文本
- chat_stream() 流式 yield 文本片段（前端打字机效果）
- chat_json()   强制解析成 dict（评分用），失败返回 {} 并记录错误

LLM_MOCK=1 时启用本地桩：不联网、不烧额度，用于冒烟测试。
"""
import json
import time
from typing import Generator, Optional

from app import config
from app.logging_conf import get_logger

logger = get_logger(__name__)

Message = dict[str, str]


class LLMError(RuntimeError):
    """LLM 调用失败。"""


# ============================================================
# 真实客户端
# ============================================================
class DeepSeekClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        key = api_key or config.DEEPSEEK_API_KEY
        if not key:
            raise LLMError(
                "未设置 DEEPSEEK_API_KEY 环境变量。\n"
                "PowerShell: $env:DEEPSEEK_API_KEY='sk-xxxx'\n"
                "或直接运行 run.ps1（它会自动加载本机的 key 文件）。"
            )
        from openai import OpenAI  # 延迟 import：没有 key 时不必加载 openai
        self._client = OpenAI(
            api_key=key,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=config.LLM_TIMEOUT,
            max_retries=config.LLM_MAX_RETRIES,
        )
        self.model = model or config.DEEPSEEK_MODEL

    # ---------- 普通调用 ----------
    def chat(self, system: str, messages: list[Message],
             temperature: float | None = None) -> str:
        t0 = time.time()
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}] + messages,
            temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
            stream=False,
        )
        text = (resp.choices[0].message.content or "").strip()
        logger.debug("llm.chat model=%s in=%d out=%d ms=%d",
                     self.model, sum(len(m["content"]) for m in messages),
                     len(text), int((time.time() - t0) * 1000))
        return text

    # ---------- 流式调用 ----------
    def chat_stream(self, system: str, messages: list[Message],
                    temperature: float | None = None) -> Generator[str, None, None]:
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}] + messages,
            temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            piece = getattr(chunk.choices[0].delta, "content", None)
            if piece:
                yield piece

    # ---------- JSON 调用（评分） ----------
    def chat_json(self, system: str, messages: list[Message],
                  temperature: float | None = None) -> dict:
        """
        返回解析后的 dict。解析失败返回 {}（调用方**必须**判空，
        不要拿 {} 当 0 分用 —— 那是"评分失败"和"考得很差"的混淆）。
        """
        t = config.LLM_TEMPERATURE_SCORE if temperature is None else temperature
        text = ""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}] + messages,
                temperature=t,
                response_format={"type": "json_object"},  # DeepSeek JSON 模式
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            # JSON 模式不被支持时退回普通模式，而不是直接失败
            logger.warning("JSON 模式不可用（%s），退回普通模式重试", e)
            text = self.chat(system, messages, temperature=t)

        data = _extract_json(text)
        if not data:
            logger.error("评分 JSON 解析失败，原文前 300 字：%s", text[:300])
        return data


def _extract_json(text: str) -> dict:
    """从模型输出里尽力抠出一个 JSON 对象。"""
    if not text:
        return {}
    s = text.strip()
    if s.startswith("```"):
        # 去掉 ```json ... ``` 包裹
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(s[i:j + 1])
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


# ============================================================
# 测试桩（LLM_MOCK=1）
# ============================================================
# 追问轮的话（带问句 —— 面试官在追问时本来就该问）
_MOCK_REPLY = "嗯，你提到的这几点抓住了主干。那我顺着往下问一层：这个机制在高并发场景下会有什么代价？"
# 收尾轮的话（**不带问句**）。桩要模拟"听话"的行为，否则冒烟测试
# 根本没法验证收尾轮真的收尾了 —— 一个永远带问号的桩会把 bug 掩盖掉。
_MOCK_CLOSE = "嗯，这个点你把握住了主干。这道题先聊到这，我们换个话题。"
_MOCK_SCORES = {"技术水平": 3.5, "逻辑思维": 3.5, "沟通表达": 4.0,
                "应变能力": 3.0, "岗位匹配度": 3.5}


class MockLLM:
    """
    固定输出的桩，只为把流程/契约测通，不代表任何真实评分。

    会把最近一次的 system / messages 记下来（last_system / last_messages），
    好让 smoke_test.py 能断言"收尾轮到底有没有把收尾旁白传下去"——
    这条**接线**是最容易在重构里悄悄断掉的东西。
    """

    model = "mock"

    def __init__(self):
        self.last_system = ""
        self.last_messages: list[Message] = []
        self.calls = 0

    def _record(self, system, messages):
        self.last_system = system
        self.last_messages = list(messages)
        self.calls += 1

    @staticmethod
    def _is_close(messages) -> bool:
        """这次请求是不是收尾轮？看末尾有没有那条临时旁白。"""
        from app.core.prompts import CLOSE_DIRECTIVE
        return any(m.get("content") == CLOSE_DIRECTIVE for m in (messages or []))

    def chat(self, system, messages, temperature=None) -> str:
        self._record(system, messages)
        return "[MOCK] " + (_MOCK_CLOSE if self._is_close(messages) else _MOCK_REPLY)

    def chat_stream(self, system, messages, temperature=None):
        self._record(system, messages)
        text = _MOCK_CLOSE if self._is_close(messages) else _MOCK_REPLY
        for piece in text:
            yield piece

    def chat_json(self, system, messages, temperature=None) -> dict:
        self._record(system, messages)
        # 桩要模仿**真模型的行为**：第一维是按题型标签回键的（行为素质题的
        # prompt 里第一维叫「岗位胜任力关联度」）。若这里永远回「技术水平」，
        # scoring.py 里那条别名归一的代码路径在冒烟里一次都走不到 ——
        # 桩会把 bug 掩盖掉，而不只是不报错。
        text = "".join(m.get("content", "") for m in (messages or []))
        scores = dict(_MOCK_SCORES)
        if config.DIM1_LABEL_BEHAVIORAL in text:
            scores[config.DIM1_LABEL_BEHAVIORAL] = scores.pop(config.DIMENSIONS[0])
        return dict(scores, comment="[MOCK] 桩评分", errors=[])


# ============================================================
# 单例
# ============================================================
_client = None


def get_llm():
    """拿 LLM 客户端（单例）。LLM_MOCK=1 时返回桩。"""
    global _client
    if _client is None:
        if config.LLM_MOCK:
            logger.warning("LLM_MOCK=1 —— 使用本地桩，不会调用真实模型")
            _client = MockLLM()
        else:
            _client = DeepSeekClient()
    return _client


def llm_configured() -> bool:
    """有没有可用的 LLM（给 /health 用）。"""
    if config.LLM_MOCK:
        return True
    return bool(config.DEEPSEEK_API_KEY)
