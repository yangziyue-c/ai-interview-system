"""AI 对话层引擎适配器（A11，P5 交付的独立服务，端口 8005）

与 P2/P3 两个适配器有三处刻意的不同：

1. **会话式**：引擎自己维护会话状态，每次调用都要带它的 session_id，
   不像题库/P3 那样一次请求就完事；
2. **/chat 是 SSE**：基类 HTTPAdapterBase.call 做的是 resp.json()，解析不了流，
   所以这里不继承它，另写 JSON 与 SSE 两条调用路径；
3. **不做 Mock 兜底**：引擎模式开着就是开着，失败明确报错。半场之后悄悄换
   一套口径出分，是最难查的一类问题——本项目一贯避免静默降级。
"""
import asyncio
import json
import logging

import httpx

from app.adapters.ai_interviewer import _RAG_JOB_LABELS
from app.config import settings

logger = logging.getLogger(__name__)


class EngineError(RuntimeError):
    """引擎返回不合契约的内容，或业务上拒绝（会话不存在、岗位未登记等）"""


class EngineUnavailableError(EngineError):
    """连不上、超时——换一次重试可能有用"""


# 引擎的岗位取值 = 题库全名（A11 的 config.JOBS），与 RAG 过滤用的是同一套。
# 复用 _RAG_JOB_LABELS 而不另抄一份：两处各写一份、改一处忘一处，就会静默出空题集
# （RAG 那条链上踩过这个坑，原始警告在 ai_interviewer.py）。
ENGINE_JOB_LABELS = _RAG_JOB_LABELS


def parse_sse_text(text: str) -> dict:
    """解析 /chat 的 SSE 报文 → {"reply": str, "done": dict}

    抽成纯函数，单测可以直接喂真实帧样例。
    error 帧抛 EngineError；流读完了却没见到 done 帧同样算契约破裂
    ——引擎侧中途异常时就是这个形状，静默当成「面试官没说话」会很难查。
    """
    tokens: list[str] = []
    done: dict | None = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw:
            continue
        try:
            evt = json.loads(raw)
        except ValueError as exc:
            raise EngineError(f"SSE 帧不是合法 JSON：{raw[:120]}") from exc
        kind = evt.get("type")
        if kind == "token":
            tokens.append(evt.get("text") or "")
        elif kind == "done":
            done = evt
        elif kind == "error":
            raise EngineError(f"引擎报错 {evt.get('code')}：{evt.get('err')}")
        # 其余类型（未出题先说话时的 question 兜底帧）本流程不会出现，忽略
    if done is None:
        raise EngineError("SSE 流没有 done 帧，引擎可能中途异常")
    return {"reply": "".join(tokens), "done": done}


class DialogueEngineAdapter:
    """A11 客户端；未配置 URL 时所有业务方法抛 EngineUnavailableError"""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self._health_body: dict | None = None
        self._health_checked_at: float = float("-inf")

    # ---------------- 健康探测 ----------------
    async def health(self, *, force: bool = False) -> dict | None:
        """读引擎 /health 的 body；未配置或探测失败返回 None

        ⚠️ 引擎的 /health **恒返回 200**（依赖没就绪时用字段表达，不用状态码），
        所以判据只能是 body 里的字段，不能看 HTTP 状态码。
        探测本身失败不算异常路径——返回 None，由调用方决定怎么报。
        """
        if not self.base_url:
            return None
        now = asyncio.get_running_loop().time()
        if not force and now - self._health_checked_at < settings.DIALOGUE_HEALTH_CACHE_SECONDS:
            return self._health_body
        body: dict | None = None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    body = resp.json()
        except Exception as exc:  # noqa: BLE001 — 探活失败不该把面试路径炸掉
            logger.info("对话层探活失败：%s", exc)
        self._health_body = body
        self._health_checked_at = now
        return body

    async def is_ready(self, *, force: bool = False) -> bool:
        """能否承接一场面试：题库已载 + 评分器就绪 + LLM 可用

        LLM_MOCK=1 时 llm_configured 也为真（引擎侧的桩），所以桩模式同样可用。
        """
        body = await self.health(force=force)
        return bool(
            body
            and body.get("bank_loaded")
            and body.get("scorer_ready")
            and body.get("llm_configured")
        )

    async def unavailable_reason(self) -> str:
        """未就绪时给一句能直接展示给用户的话（就绪时返回空串）"""
        if not self.base_url:
            return "对话层引擎未配置（DIALOGUE_ENGINE_URL 为空）"
        body = await self.health(force=True)
        if body is None:
            return f"连不上对话层服务 {self.base_url}，请确认它已启动"
        missing = [name for name, key in (
            ("题库未加载完成", "bank_loaded"),
            ("评分模型未就绪", "scorer_ready"),
            ("未配置大模型密钥", "llm_configured"),
        ) if not body.get(key)]
        return "、".join(missing)

    # ---------------- 会话流程 ----------------
    async def start(self, position: str) -> dict:
        """建会话；返回 {session_id, ...}"""
        return await self._call_json(
            "/start", {"job": self._job_of(position)}, settings.DIALOGUE_START_TIMEOUT_SECONDS
        )

    async def next_question(self, session_id: str) -> dict:
        """出下一题；finished=true 时该场已问完"""
        return await self._call_json(
            "/next", {"session_id": session_id}, settings.DIALOGUE_START_TIMEOUT_SECONDS
        )

    async def answer(self, session_id: str, text: str) -> dict:
        """提交一次作答，返回面试官回应与下一步指令

        follow_up=true 表示面试官在追问同一题（继续答）；
        false 表示本题结束，调用方接着调 next_question。
        """
        data = await self._consume_sse(
            "/chat", {"session_id": session_id, "message": text}, settings.DIALOGUE_CHAT_TIMEOUT_SECONDS
        )
        done = data["done"]
        return {
            "reply": data["reply"],
            "follow_up": bool(done.get("follow_up")),
            "action": done.get("action"),
            "q_index": done.get("q_index"),
            "swapped": bool(done.get("swapped")),
            "done": done,
        }

    async def finish(self, session_id: str) -> dict:
        """结束并出分：five_dim_avg / total_score_100 / summary / digest / raw …"""
        return await self._call_json(
            "/finish", {"session_id": session_id}, settings.DIALOGUE_FINISH_TIMEOUT_SECONDS
        )

    async def growth(self, position: str, records: list[dict]) -> dict:
        """把若干场的 digest 原样喂回引擎，取错题本 / 考点地图 / 历史成绩

        records 是各场 `/finish` 顶层 digest 的原样列表（引擎侧上限 100 份、
        单份 64KB）。这一路是纯计算、不调 LLM，30 秒预算足够。
        """
        return await self._call_json(
            "/growth",
            {"job": self._job_of(position), "records": records},
            settings.DIALOGUE_START_TIMEOUT_SECONDS,
        )

    async def transcribe(self, filename: str, content: bytes, content_type: str) -> dict:
        """把一段音频交给引擎做本地转写（multipart 进、文字与表达指标出）

        ⚠️ 首次调用会触发引擎侧懒加载 ASR 模型，可能返回「还在加载」——
        那是正常形态（`ok=false` + `detail` 写明），不是故障，前端可稍后重试。
        """
        if not self.base_url:
            raise EngineUnavailableError("对话层引擎未配置（DIALOGUE_ENGINE_URL 为空）")
        path = "/asr"
        files = {"file": (filename or "answer.webm", content, content_type or "application/octet-stream")}
        timeout = settings.DIALOGUE_ASR_TIMEOUT_SECONDS
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await asyncio.wait_for(
                    client.post(f"{self.base_url}{path}", files=files), timeout=timeout
                )
        except asyncio.TimeoutError:
            raise EngineUnavailableError(f"对话层 {path} 超时（>{timeout:.0f}s）") from None
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(f"对话层 {path} 网络错误：{exc}") from exc
        body = self._decode(resp, path)
        # 引擎的 /asr 用 ok 字段表达成功与否（缺模型、还在加载都走 ok=false）
        if not body.get("ok"):
            raise EngineError(body.get("error") or body.get("detail") or "语音转写失败")
        return body

    # ---------------- 内部 ----------------
    def _job_of(self, position: str) -> str:
        job = ENGINE_JOB_LABELS.get(position)
        if not job:
            # fail-closed：不带岗位过滤地送请求，引擎会在全库乱抽题（且题干不在
            # 本岗位题库 → 学习计划反查不到）。未知岗位宁可明确报错。
            raise EngineError(f"岗位 {position} 未登记引擎全名，无法使用对话层引擎")
        return job

    async def _call_json(self, path: str, payload: dict, timeout: float) -> dict:
        if not self.base_url:
            raise EngineUnavailableError("对话层引擎未配置（DIALOGUE_ENGINE_URL 为空）")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await asyncio.wait_for(
                    client.post(f"{self.base_url}{path}", json=payload), timeout=timeout
                )
        except asyncio.TimeoutError:
            raise EngineUnavailableError(f"对话层 {path} 超时（>{timeout:.0f}s）") from None
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(f"对话层 {path} 网络错误：{exc}") from exc
        return self._decode(resp, path)

    async def _consume_sse(self, path: str, payload: dict, timeout: float) -> dict:
        if not self.base_url:
            raise EngineUnavailableError("对话层引擎未配置（DIALOGUE_ENGINE_URL 为空）")

        async def _drain() -> list[str]:
            out: list[str] = []
            # read 超时管「单块停滞」，总时长再由外层 wait_for 兜住——
            # 一个不吐字也不关闭的流，只有总闸拦得住。
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
                async with client.stream("POST", f"{self.base_url}{path}", json=payload) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        self._decode(resp, path)  # 一定抛，不会返回
                    async for line in resp.aiter_lines():
                        out.append(line)
            return out

        try:
            lines = await asyncio.wait_for(_drain(), timeout=timeout)
        except asyncio.TimeoutError:
            raise EngineUnavailableError(f"对话层 {path} 超时（>{timeout:.0f}s）") from None
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(f"对话层 {path} 网络错误：{exc}") from exc
        return parse_sse_text("\n".join(lines))

    @staticmethod
    def _decode(resp: httpx.Response, path: str) -> dict:
        """统一解码与报错：引擎错误体是 {code, err, session_id}，code 是字符串"""
        try:
            body = resp.json()
        except ValueError as exc:
            raise EngineError(f"对话层 {path} 返回非 JSON（HTTP {resp.status_code}）") from exc
        if resp.status_code >= 400:
            code = body.get("code") if isinstance(body, dict) else None
            err = body.get("err") if isinstance(body, dict) else str(body)[:120]
            if code == "session_not_found" or resp.status_code == 404:
                raise EngineError(f"引擎会话不存在或已过期：{err}")
            raise EngineError(f"对话层 {path} 失败（HTTP {resp.status_code}）：{err}")
        if not isinstance(body, dict):
            raise EngineError(f"对话层 {path} 返回的不是对象")
        return body


_adapter: DialogueEngineAdapter | None = None


def get_dialogue_adapter() -> DialogueEngineAdapter:
    """模块级惰性单例（照 ai_evaluator 的写法）"""
    global _adapter
    if _adapter is None:
        _adapter = DialogueEngineAdapter(settings.DIALOGUE_ENGINE_URL)
    return _adapter
