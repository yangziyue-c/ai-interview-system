"""RAG 语义检索接口（透传 backend/rag/ 服务，V5 知识库）

RAG 服务是独立进程（8003，由 start.py 拉起），主后端只做透传与格式归一：

- 统一响应 `{code, message, data}`（RAG 服务本身返回裸 JSON）；
- RAG 不可用/超时时返回 `available=false` + 空结果，让调用方优雅降级（而非 500）。

用途：题库浏览的语义搜索、按考生表述找相关题、取某题全层级素材（mode=expand）。
面试出题链的自动兜底见 `app/adapters/ai_interviewer.py::_generate_via_rag`。
"""
from typing import Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.config import settings
from app.utils.response import ok

router = APIRouter()


class RagSearchIn(BaseModel):
    query: str = Field(description="检索文本：面试问题或考生表述")
    job: Optional[str] = Field(default=None, description="岗位全名过滤，如「Java 后端开发工程师」")
    mode: str = Field(default="select", description="select=出题（Top-N 道不同题）/ expand=深挖（一题全层级）")
    top: int = Field(default=3, ge=1, le=20, description="select 模式返回几道题")
    level: Optional[str] = Field(default=None, description="层级过滤：原题/L1/L2/L3/语义变体…")


@router.post("/search", response_model=dict, summary="RAG 语义检索（透传知识库服务）")
async def rag_search(body: RagSearchIn, _: CurrentUser) -> dict:
    if not settings.RAG_API_URL:
        return ok({"available": False, "results": [], "reason": "未配置 RAG_API_URL"})
    try:
        async with httpx.AsyncClient(timeout=settings.RAG_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.RAG_API_URL}/rag/search", json=body.model_dump()
            )
            resp.raise_for_status()
            data = resp.json()
            data["available"] = True
            return ok(data)
    except Exception as exc:  # noqa: BLE001 - 检索服务不可用不应让前端拿到 500
        return ok({
            "available": False, "results": [],
            "reason": f"{type(exc).__name__}: {exc}",
        })
