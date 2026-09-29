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
import re
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

        def _json_call(msgs: list[Message], temp: float) -> str:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}] + msgs,
                temperature=temp,
                response_format={"type": "json_object"},  # DeepSeek JSON 模式
            )
            return (resp.choices[0].message.content or "").strip()

        text = ""
        try:
            text = _json_call(messages, t)
        except Exception as e:
            # JSON 模式不被支持时退回普通模式，而不是直接失败
            logger.warning("JSON 模式不可用（%s），退回普通模式重试", e)
            text = self.chat(system, messages, temperature=t)

        data = _extract_json(text)
        if not data:
            # JSON 偶发截断/尾逗号/转义错误时，再给模型一次只修格式的机会。
            # 这次失败才真正返回 {}；不要拿一个临时格式错误当“考生没答好”。
            repair = messages + [{
                "role": "user",
                "content": ("上一次输出不是合法 JSON。请保持原有评分内容，"
                            "只重新输出一个完整、合法的 JSON 对象；"
                            "不要 markdown，不要解释，不要省略括号或引号。"),
            }]
            try:
                text2 = _json_call(repair, 0.0)
                data = _extract_json(text2)
                if not data:
                    text = text2
            except Exception:
                logger.exception("评分 JSON 修复重试失败")
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
    def _load(candidate: str) -> dict:
        # JSON 模式偶发带尾逗号/控制字符；先做最小的确定性修复。
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        obj = json.loads(candidate, strict=False)
        return obj if isinstance(obj, dict) else {}

    try:
        return _load(s)
    except Exception:
        pass
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            return _load(s[i:j + 1])
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
        # 测试用的**单次开关**：置 True 之后，追问轮也返回收尾式的话（不带问句）。
        # 存在的唯一理由是 `session` 的收尾污染守卫（`needs_question`）——
        # 那条代码要跑，得先有一个"面试官该提问却没提问"的回复，而默认桩
        # 在追问轮**永远**返回带问句的 `_MOCK_REPLY`（那是刻意的，见上）。
        # 于是冒烟里那条路径永不触发、等于没覆盖。这个开关让冒烟能真的走到它。
        # ⚠️ 它**只影响桩**，且默认 False ⇒ 不开启时行为与加这个字段之前逐字节相同。
        self.force_wrapup = False
        # 同上，另一个测试用单次开关：置成一个**场外考点名**之后，总评里会带上它
        # （且**不加** `[[ ]]` 标注）⇒ 走 `summary_guard` 的外来标题扫描那条路。
        # 用来在冒烟里真的跑到"重生一次 → 仍不过 → 确定性兜底"这条链路，
        # 而不用去连真模型。空串 = 关。
        self.force_alien = ""

    def _record(self, system, messages):
        self.last_system = system
        self.last_messages = list(messages)
        self.calls += 1

    @staticmethod
    def _is_close(messages) -> bool:
        """这次请求是不是收尾轮？看末尾有没有那条临时旁白。"""
        from app.core.prompts import CLOSE_DIRECTIVE
        return any(m.get("content") == CLOSE_DIRECTIVE for m in (messages or []))

    def _reply_text(self, messages) -> str:
        if self._is_close(messages) or self.force_wrapup:
            return _MOCK_CLOSE
        return _MOCK_REPLY

    def _is_summary(self, system) -> bool:
        """这次请求是不是**整场总评**？`MockLLM` 里只有总评走 `chat()`。"""
        return "负责写面试评价" in (system or "")

    def _summary_text(self, messages) -> str:
        """
        桩版总评。**必须照真模型的契约来写**（提到考点就用 `[[考点名]]` 标出、
        且只用清单里的名字）—— 否则一开 `A11_SUMMARY_GUARD` 就会成片走到
        "没有标注 ⇒ 重生 ⇒ 兜底"，冒烟的 summary 全变成兜底文案，
        既没覆盖到正常路径，又会打掉一批既有断言。
        与 `chat_json` 里那段"第一维按题型标签回键"是同一条纪律：
        **桩要模仿真模型的形状，不然桩会把 bug 掩盖掉。**
        """
        body = "".join(m.get("content", "") for m in (messages or []))
        names: list[str] = []
        for line in body.splitlines():
            if "考点：" not in line:
                continue
            for n in line.split("考点：", 1)[1].split("、"):
                n = n.strip()
                if n and "未绑" not in n and n not in names:
                    names.append(n)
        tagged = (("第 1 题的 " + "、".join(f"[[{n}]]" for n in names[:2]))
                  if names else "本场没有测出明确的知识点")
        tail = f"另外值得注意的是 {self.force_alien}。" if self.force_alien else ""
        return (f"[MOCK] 本场整体表现平稳。强项集中在 {tagged} 这一块，"
                f"薄弱点是原理层面的展开还不够深。建议把关键机制讲到实现层再练一轮。{tail}")

    def chat(self, system, messages, temperature=None) -> str:
        self._record(system, messages)
        if self._is_summary(system):
            return self._summary_text(messages)
        return "[MOCK] " + self._reply_text(messages)

    def chat_stream(self, system, messages, temperature=None):
        self._record(system, messages)
        text = self._reply_text(messages)
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
        detail = {
            dim: {
                "reason": "[MOCK] 桩评分依据",
                "evidence": ["[MOCK] 桩证据"],
                "confidence": "medium",
            }
            for dim in scores
        }
        return dict(
            scores,
            comment="[MOCK] 桩评分",
            errors=[],
            score_detail={
                "dimensions": detail,
                "missing_points": [],
                "misconceptions": [],
                "followup_eval": [],
                "confidence": "medium",
            },
        )


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
