"""通用大模型调用（OpenAI 兼容接口）

只服务「需要现生成一段面向考生的文字」的功能（当前是示范作答）。不复用
`ai_interviewer` 里的出题 LLM 路径：那条路的失败语义是**落下一级数据源**，
而示范作答失败时不能编一份内容顶上——调用方要拿到明确的不可用信号。

配置沿用 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`（与出题共用一套 key）。
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 示范作答是一次性生成 300~500 字，比出题长；15 秒的通用预算偏紧，单独放宽。
SAMPLE_TIMEOUT_SECONDS = 40.0


class LLMError(Exception):
    """大模型不可用：未配置、网络失败、返回空内容都归到这里

    API 层把它转成 50300（依赖服务不可用），不静默返回空字符串——空内容在
    前端会显示成一张空白弹窗，比一次明确的报错难查得多。
    """


async def chat(
    messages: list[dict],
    *,
    timeout: float = SAMPLE_TIMEOUT_SECONDS,
    temperature: float = 0.7,
) -> str:
    """调一次 OpenAI 兼容的 /chat/completions，返回正文

    messages 为 [{role, content}]。任何失败抛 LLMError。
    """
    if settings.OFFLINE_MODE:
        raise LLMError("离线版未启用大模型，无法生成示范作答")
    if not settings.LLM_API_KEY or not settings.LLM_BASE_URL:
        raise LLMError("未配置大模型（LLM_BASE_URL / LLM_API_KEY），无法生成示范作答")
    base_url = settings.LLM_BASE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                json={
                    "model": settings.LLM_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            content = (
                (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
                or ""
            ).strip()
    except Exception as exc:  # noqa: BLE001 - 网络/解析/HTTP 错误统一归口
        logger.warning("大模型调用失败（示范作答）：%s", exc, exc_info=True)
        raise LLMError(f"大模型调用失败：{exc}") from exc
    if not content:
        raise LLMError("大模型返回空内容")
    return content
