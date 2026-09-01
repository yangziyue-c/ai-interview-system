"""P2 适配器：AI 面试官（生成开场题与动态追问）

【给 P2 的接入约定】
在 .env 中配置 AI_INTERVIEWER_URL 后，后端会向你的服务发起：
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

约定：15 秒内未返回 / 非 2xx / 未配置 URL 时，后端自动使用内置 Mock 题库兜底，
保证面试流程不中断。
"""
import asyncio
import logging

import httpx

from app.adapters.base import HTTPAdapterBase
from app.config import settings

logger = logging.getLogger(__name__)

# ---------------- Mock 题库 ----------------
# 岗位由数据库 positions 表动态维护（替代硬编码枚举）；
# 开场题按岗位 code 匹配专用池，未配置的岗位回退通用池，保证任何岗位都可面试。
OPENING_QUESTIONS: dict[str, list[str]] = {
    "backend": [
        "请先做个简单的自我介绍，重点说说你最有代表性的后端项目经历。",
        "谈谈你对 HTTP 协议的理解：一次完整的 HTTP 请求从发出到响应经历了哪些过程？",
        "MySQL 的索引有哪些类型？为什么一般建议使用自增主键？",
        "什么是缓存穿透、缓存击穿、缓存雪崩？分别如何解决？",
        "请描述你理解的 RESTful API 设计原则，并举一个你实践过的例子。",
        "如果线上一个接口响应突然变慢，你会按什么思路排查？",
    ],
    "frontend": [
        "请先做个简单的自我介绍，重点说说你最有代表性的前端项目经历。",
        "说说浏览器从输入 URL 到页面渲染完成的整个过程。",
        "什么是闭包？它在实际开发中有哪些应用场景和坑？",
        "谈谈你对 Vue/React 响应式原理的理解。",
        "前端首屏加载速度慢，你会从哪些方面优化？",
        "HTTP 缓存有哪些策略？前端工程中如何配合？",
    ],
    "test_engineer": [
        "请先做个简单的自我介绍，重点说说你在测试相关项目或实习中的经历。",
        "说说你对软件测试整体流程的理解：从需求评审到上线回归，测试人员分别在哪些环节发挥作用？",
        "等价类划分和边界值分析分别解决什么问题？请举一个你实际用过的例子。",
        "一个 Bug 从提交到关闭会经历哪些状态流转？如果开发拒绝修复，你会怎么处理？",
        "接口测试与 UI 测试相比有什么优势？你在项目里如何设计接口自动化测试？",
        "如果线上出现了一个偶发性的严重 Bug，你会按什么思路去定位和复现？",
    ],
}

# 通用开场题池：岗位没有专用题库时的兜底（岗位无关的通用问题）
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
SHORT_ANSWER_THRESHOLD = 15  # 回答少于该字数时触发"展开"追问


_LLM_SYSTEM_PROMPT = (
    "你是一名资深互联网公司的技术面试官，正在面试一名应聘「{position}」岗位的计算机专业学生。"
    "你的提问要专业、有深度，并针对对方的回答进行针对性追问，逐步考察其真实水平。"
    "只输出下一个面试问题的文本本身，不要输出任何解释、前缀或多余字符。"
)

_POSITION_LABELS = {"backend": "后端开发工程师", "frontend": "前端开发工程师", "test_engineer": "测试开发工程师"}


class AIInterviewerAdapter(HTTPAdapterBase):
    """P2：生成开场题与追问

    数据源优先级：
      1. AI_INTERVIEWER_URL（P2 的 HTTP 服务）
      2. LLM_API_KEY（直接调 OpenAI 兼容大模型，P2 服务未就绪时的临时方案）
      3. 内置 Mock 题库
    任一路径失败/超时（15 秒）均降级到 Mock，流程不中断。
    """

    def __init__(self) -> None:
        super().__init__(settings.AI_INTERVIEWER_URL, "P2-AI面试官")

    async def _generate_via_llm(self, payload: dict, mock_func) -> str:
        """直接调用 OpenAI 兼容大模型生成问题；失败降级 Mock"""
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
            async with httpx.AsyncClient(timeout=settings.ADAPTER_TIMEOUT_SECONDS) as client:
                resp = await asyncio.wait_for(
                    client.post(
                        f"{settings.LLM_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                        json={
                            "model": settings.LLM_MODEL,
                            "messages": messages,
                            "temperature": 0.7,
                        },
                    ),
                    timeout=settings.ADAPTER_TIMEOUT_SECONDS,
                )
                resp.raise_for_status()
                content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
                content = (content or "").strip()
                if not content:
                    raise RuntimeError("LLM 返回空内容")
                return content
        except Exception as exc:  # noqa: BLE001 - 任何失败都降级
            logger.warning("LLM 直连失败(%s)，已降级为 Mock 兜底", exc)
            return await mock_func()

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
                pool = OPENING_QUESTIONS.get(position) or GENERAL_OPENING_QUESTIONS
                return pool[interview_id % len(pool)]
            # 追问：候选回答过短 → 请求展开；否则按轮次轮换追问模板
            last_answer = next(
                (item["content"] for item in reversed(history) if item["role"] == "candidate"), ""
            )
            if len(last_answer.strip()) < SHORT_ANSWER_THRESHOLD:
                return SHORT_ANSWER_FOLLOW_UP
            pool = FOLLOW_UP_QUESTIONS
            return pool[(round_no - 2) % len(pool)]

        if self.base_url:
            result = await self.call_or_fallback("/generate", payload, _mock)
        elif settings.LLM_API_KEY:
            result = await self._generate_via_llm(payload, _mock)
        else:
            return await _mock()

        # Mock/LLM 直接返回题目字符串；外部服务返回 {"question": "..."}
        if isinstance(result, dict):
            question = str(result.get("question") or "")
        else:
            question = str(result or "")
        if not question:
            logger.warning("P2 返回缺少 question 字段，使用 Mock 兜底")
            question = await _mock()
        return question


adapter: AIInterviewerAdapter | None = None


def get_interviewer_adapter() -> AIInterviewerAdapter:
    global adapter
    if adapter is None:
        adapter = AIInterviewerAdapter()
    return adapter
