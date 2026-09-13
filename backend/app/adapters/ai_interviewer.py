"""P2 适配器：AI 面试官（生成开场题与动态追问）

数据源优先级（2026-09-14 起，V5 知识库换代：5012 题 / 5 岗位）：
  1. 题库策略（questions 表，见 interviewer_new/question_bank.py）
  2. RAG 语义检索（backend/rag/，8003，题库未命中时的语义兜底，P1 新增）
  3. AI_INTERVIEWER_URL（外部服务的扩展位）
  4. LLM_API_KEY（直接调 OpenAI 兼容大模型）
  5. 内置 Mock 题库
任一路径失败均逐级降级，流程不中断；网络级（HTTP/LLM）各有 15 秒超时预算，
逐级串行时最坏叠加（题库未命中 + 外部服务宕机 + LLM 已配置 ≈ 30 秒到 Mock）。

【外部服务接入约定】（仅当 .env 配置 AI_INTERVIEWER_URL 且题库策略未命中时生效）
POST {AI_INTERVIEWER_URL}/generate
Content-Type: application/json
{
    "position": "backend",        # 岗位 code（由 GET /positions 动态下发）
    "round": 2,                   # 当前是第几题（1 开场题，2~7 追问）
    "is_follow_up": true,          # 是否为追问
    "history": [                   # 完整对话历史（含本轮之前的问答）
        {"role": "interviewer", "content": "..."},
        {"role": "candidate", "content": "..."}
    ]
}
# 期望返回：
{ "question": "你下一题的题目文本" }

约定：15 秒内未返回 / 非 2xx / 未配置 URL 时，后端自动降级，保证面试流程不中断。
"""
import logging
import time

import httpx

from app.adapters.base import AdapterTimeoutError, HTTPAdapterBase
from app.config import settings
from app.database import async_session
from interviewer_new import question_bank

logger = logging.getLogger(__name__)

# ---------------- Mock 题库 ----------------
# 岗位专用开场池已删除（2026-09-06）：其题干与 questions 表逐字双写，题库换代后
# 会漂移。题库策略覆盖所有已入库岗位，Mock 只服务无题库岗位，统一走通用池。
GENERAL_OPENING_QUESTIONS: list[str] = [
    "请先做个简单的自我介绍，重点说说你最有代表性的项目经历。",
    "谈谈你对我们这个岗位的理解，以及你认为自己最匹配这个岗位的优势是什么？",
    "最近一次你在项目中遇到技术难题是什么？最后是怎么解决的？",
    "描述一次你与团队成员意见冲突的经历，你是如何处理的？",
    "你平时如何学习新技术？请举一个最近学习并应用了新技术的例子。",
    "你的职业规划是什么？未来三年希望达到什么样的技术水平？",
]

FOLLOW_UP_QUESTIONS: list[str] = [
    "能结合你做过的一个具体项目，把这个知识点展开说说吗？",
    "这个方案有什么缺点？如果流量再扩大十倍，你会怎么演进？",
    "为什么选择这种方案，而不是其他的？当时是怎么权衡的？",
    "如果让你重新设计一次，你会改进哪些地方？",
    "说说这个知识点背后的底层原理。",
    "在实际生产环境中遇到过类似问题吗？当时是怎么定位和解决的？",
]

SHORT_ANSWER_FOLLOW_UP = "你的回答比较简略，能结合具体的项目经历展开说说吗？"
# 「回答简略/笼统」的判定统一复用 question_bank.is_vague_answer（<20 字或否定词），
# 与题库策略层同一口径，避免两条数据源路径行为分叉。


_LLM_SYSTEM_PROMPT = (
    "你是一名资深互联网公司的技术面试官，正在面试一名应聘「{position}」岗位的计算机专业学生。"
    "你的提问要专业、有深度，并针对对方的回答进行针对性追问，逐步考察其真实水平。"
    "只输出下一个面试问题的文本本身，不要输出任何解释、前缀或多余字符。"
)

_POSITION_LABELS = {
    "backend": "后端开发工程师",
    "frontend": "前端开发工程师",
    "test_engineer": "测试开发工程师",
    "algorithm": "算法工程师",
    "system_design": "系统设计工程师",
}

# RAG 向量库的岗位过滤值 = V5 交付包的岗位全名（与上面的展示名**不同**，勿混用：
# backend 是「Java 后端开发工程师」而非「后端开发工程师」，传错会过滤出空集）
_RAG_JOB_LABELS = {
    "backend": "Java 后端开发工程师",
    "frontend": "Web 前端开发工程师",
    "test_engineer": "测试开发工程师",
    "algorithm": "算法工程师",
    "system_design": "系统设计工程师",
}


class AIInterviewerAdapter(HTTPAdapterBase):
    """P2：生成开场题与追问

    数据源优先级与降级约定见模块 docstring（题库策略 → 外部 P2 → LLM → Mock）。
    """

    def __init__(self) -> None:
        super().__init__(settings.AI_INTERVIEWER_URL, "P2-AI面试官")
        # RAG 健康探测缓存（探测本身有 1 秒超时，缓存避免每轮白等）
        self._rag_available = False
        self._rag_checked_at = float("-inf")  # 首次调用立即探测

    # ---------------- 数据源实现（统一签名 async -> str | None，None = 落下一级） ----------------

    async def _generate_via_bank(
        self, position: str, round_no: int, history: list[dict], is_follow_up: bool
    ) -> str | None:
        """题库策略（最高优先级）：策略决策在 interviewer_new/question_bank.py 的 pick_next

        自开短会话（只读）：刻意不复用请求级会话——请求会话里可能有未提交的
        脏写（答案/轮次），会话内 SELECT 会触发 autoflush 把写锁提前到出题全程
        （含网络级降级源的等待时间）；独立短会话 + WAL 下读不阻塞写。
        """
        try:
            async with async_session() as session:
                result = await question_bank.pick_next(session, position, round_no, history, is_follow_up)
            if result is None:
                # 区分「正常未命中」（岗位无题/池抽空）与异常——前者也应留痕
                logger.info("题库策略未命中（position=%s, round=%s），降级下一级", position, round_no)
            return result
        except Exception as exc:  # noqa: BLE001 - 题库异常不阻断面试，落下一级数据源
            logger.warning("题库策略出题失败(%s)，降级", exc, exc_info=True)
            return None

    async def _rag_ready(self) -> bool:
        """RAG 服务健康探测（结果按 RAG_HEALTH_CACHE_SECONDS 缓存）

        未启用时每轮都去连会白等超时；缓存后最坏一个窗口才重试一次。
        探测超时取 0.5 秒：Windows 上「端口无监听」不会快速 RST，会耗满整个超时
        （实测 1s 超时单次耗时 1.0~1.2s），RAG 没起时这个代价要乘以面试轮数。
        """
        if not settings.RAG_API_URL:
            return False
        now = time.monotonic()
        if now - self._rag_checked_at < settings.RAG_HEALTH_CACHE_SECONDS:
            return self._rag_available
        self._rag_checked_at = now
        try:
            async with httpx.AsyncClient(timeout=0.5) as client:
                resp = await client.get(f"{settings.RAG_API_URL}/health")
                self._rag_available = resp.status_code == 200
        except Exception:  # noqa: BLE001 - 探测失败即视为不可用
            self._rag_available = False
        return self._rag_available

    async def _generate_via_rag(self, position: str, history: list[dict]) -> str | None:
        """RAG 语义选题（P1 新增，插在题库策略之下）：仅在题库策略未命中时生效

        用最后一条候选人回答（冷启动用岗位名）做语义召回，取 Top-N 道不同题，
        返回首个本场未问过的题干。未配置 / 服务未就绪 / 超时 / 结果全重复 → None。

        签名刻意不含 round_no / is_follow_up：语义召回只关心「考生说了什么」
        与「岗位是什么」，轮次由调用方（题库策略）负责；收了不用的参数会让读者
        误以为 RAG 分支有轮次语义。

        注：V5 题库覆盖 5 个岗位共 5012 题，题库策略极少返回 None，因此这一级
        多数场次不会被调用——它的价值是「题库缺失时的语义兜底」；主动使用的
        入口见 `POST /api/v1/rag/search`（透传 RAG 服务）。
        """
        if not await self._rag_ready():
            return None
        job = _RAG_JOB_LABELS.get(position)
        if not job:
            # 未知岗位 fail-closed：宁可跳过 RAG，也不能不带岗位过滤地全库检索
            # （那会把别的岗位的题读给候选人，且题干不在本题库 → 追问链断）
            logger.info("岗位 %s 未登记 RAG 全名，跳过 RAG 源", position)
            return None
        query = (question_bank.last_candidate_answer(history)
                 or _POSITION_LABELS.get(position, position))
        asked = {(m.get("content") or "").strip()
                 for m in history if m.get("role") == "interviewer"}
        try:
            async with httpx.AsyncClient(timeout=settings.RAG_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{settings.RAG_API_URL}/rag/search",
                    json={"query": query, "job": job,
                          # level="原题"：向量库里「原题」只占约 7%，其余是语义变体/
                          # 追问/得分点等改写片段——拿那些当题干会出现「你提到了X…」
                          # 这类无上下文的句子，且文本与题库不一致会导致锚点丢失
                          "mode": "select", "top": 3, "level": "原题"},
                )
                resp.raise_for_status()
                for item in (resp.json().get("results") or []):
                    text = str(item.get("题目") or "").strip()
                    if text and text not in asked:
                        return text
        except Exception as exc:  # noqa: BLE001 - 任何失败都落下一级
            logger.info("RAG 语义选题不可用(%s)，降级下一级", exc)
        return None

    async def _generate_via_http(self, payload: dict) -> str | None:
        """外部 P2 服务（扩展位）：失败/契约不符返回 None（落下一级）"""
        if not self.base_url:
            return None
        try:
            result = await self.call("/generate", payload)
        except (AdapterTimeoutError, RuntimeError) as exc:
            logger.warning("外部 P2 服务调用失败(%s)，降级下一级", exc)
            return None
        if not isinstance(result, dict):
            logger.warning("外部 P2 服务返回格式异常（非 JSON 对象），降级下一级")
            return None
        question = str(result.get("question") or "").strip()
        if not question:
            logger.warning("外部 P2 服务返回缺少 question 字段，降级下一级")
            return None
        return question

    async def _generate_via_llm(self, payload: dict) -> str | None:
        """直接调用 OpenAI 兼容大模型生成问题；未配置/失败返回 None（落下一级）"""
        if not settings.LLM_API_KEY or not settings.LLM_BASE_URL:
            return None
        position_label = _POSITION_LABELS.get(payload["position"], "后端开发工程师")
        messages: list[dict] = [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT.format(position=position_label)}
        ]
        if payload["history"]:
            for item in payload["history"]:
                messages.append({
                    "role": "assistant" if item["role"] == "interviewer" else "user",
                    "content": item["content"],
                })
        else:
            messages.append({"role": "user", "content": "面试开始，请提问。"})

        try:
            # httpx client timeout 已约束 15 秒预算，无需再叠 wait_for（双定时器语义混淆）
            async with httpx.AsyncClient(timeout=settings.ADAPTER_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{settings.LLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                    json={
                        "model": settings.LLM_MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                    },
                )
                resp.raise_for_status()
                content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
                content = (content or "").strip()
                if not content:
                    raise RuntimeError("LLM 返回空内容")
                return content
        except Exception as exc:  # noqa: BLE001 - 任何失败都降级
            logger.warning("LLM 直连失败(%s)，降级下一级", exc, exc_info=True)
            return None

    async def generate_question(
        self,
        position: str,
        round_no: int,
        history: list[dict],
        interview_id: int,
        is_follow_up: bool = False,
    ) -> str:
        """生成第 round_no 题；is_follow_up=False 表示开场题"""
        payload = {
            "position": position,
            "round": round_no,
            "is_follow_up": is_follow_up,
            "history": history,
        }

        async def _mock() -> str:
            if not is_follow_up:
                # 开场题走通用池：题库策略覆盖所有已入库岗位，Mock 只服务无题库岗位
                return GENERAL_OPENING_QUESTIONS[interview_id % len(GENERAL_OPENING_QUESTIONS)]
            # 追问：候选回答简略/笼统且展开句本场未问过 → 请求展开；否则轮换追问模板
            last_answer = question_bank.last_candidate_answer(history)
            asked = {item.get("content") for item in history if item.get("role") == "interviewer"}
            if question_bank.is_vague_answer(last_answer) and SHORT_ANSWER_FOLLOW_UP not in asked:
                return SHORT_ANSWER_FOLLOW_UP
            return FOLLOW_UP_QUESTIONS[(round_no - 2) % len(FOLLOW_UP_QUESTIONS)]

        # 数据源链：题库策略 → RAG 语义检索 → 外部服务 → LLM 直连 → 内置 Mock
        # 每级实现内自行捕获异常并返回 None（None = 落下一级），首个非空即返回
        for source in (
            lambda: self._generate_via_bank(position, round_no, history, is_follow_up),
            lambda: self._generate_via_rag(position, history),
            lambda: self._generate_via_http(payload),
            lambda: self._generate_via_llm(payload),
            _mock,
        ):
            question = await source()
            if question:
                return question
        return await _mock()  # 防御兜底：各源全空时保证 str 契约


adapter: AIInterviewerAdapter | None = None


def get_interviewer_adapter() -> AIInterviewerAdapter:
    global adapter
    if adapter is None:
        adapter = AIInterviewerAdapter()
    return adapter
