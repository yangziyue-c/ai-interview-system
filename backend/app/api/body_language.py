"""体态分析接口：浏览器本地提取的姿态关键点进，沟通姿态信号出

数据边界（与引擎侧一致）：**只收数字关键点**，不收图片、视频或音频。
摄像头画面在浏览器里由 MediaPipe 转成归一化坐标后即丢弃，上传的只有数字。
这条边界不在这层放宽——放宽一次，就等于给这条路开了个能传画面的口子。

落库（2026-10-31）：请求同时带 `interview_id` + `round` 时，把引擎返回的
结果写进对应问答记录。报告页的「体态稳定性」评语据此聚合——原先只转发、
不保存，报告里就没有任何体态数据可写。不传这两个字段时行为不变。
"""
import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.adapters import get_dialogue_adapter
from app.adapters.ai_dialogue import EngineError
from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, NotFoundError, ServiceUnavailableError
from app.models import Interview, QARecord
from app.schemas.engine import BodyLanguageRequest
from app.utils.response import ok

logger = logging.getLogger(__name__)
router = APIRouter()


async def _store_result(db: DbSession, user_id: int, interview_id: int, round_no: int, data: dict) -> None:
    """把体态分析结果写进对应轮次的问答记录

    显式传了 interview_id/round 却对不上（会话不是本人的、轮次不存在）时
    明确报错，不静默跳过：静默会让「报告里没有体态数据」变得无从排查——
    到底是没采集、没传对参数，还是落库失败，从外部完全看不出来。
    """
    interview = await db.scalar(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == user_id)
    )
    if interview is None:
        raise NotFoundError("面试会话不存在")
    qa = await db.scalar(
        select(QARecord).where(
            QARecord.interview_id == interview_id, QARecord.round == round_no
        )
    )
    if qa is None:
        raise BadRequestError(f"面试第 {round_no} 轮问答记录不存在，体态结果未保存")
    # 同一轮多次分析时后者覆盖前者：一轮只保留最近一次（前端正常每轮只调一次）
    qa.body_language = data
    await db.commit()


@router.post("/analyze", response_model=dict, summary="体态分析（本地关键点进，沟通姿态信号出）")
async def analyze_body_language(user: CurrentUser, req: BodyLanguageRequest, db: DbSession) -> dict:
    """分析一段姿态关键点，返回沟通姿态信号

    引擎侧的取分是刻意的：证据不足（镜头坏了、手出画、帧数太少）时**不给分**，
    而不是给个低分。所以结果是「可能没有 score」的形状，这里如实透传，
    不在这边补默认值——补一个 0 分出来，就成了「摄像头坏了 = 考生体态差」。
    """
    if (req.interview_id is None) != (req.round is None):
        raise BadRequestError("interview_id 与 round 需要同时提供（或都不提供）")

    frames = [frame.model_dump(exclude_none=True) for frame in req.frames]
    try:
        data = await get_dialogue_adapter().analyze_body_language(frames)
    except EngineError as exc:
        raise ServiceUnavailableError(f"体态分析不可用：{exc}") from exc

    stored = False
    if req.interview_id is not None and req.round is not None:
        await _store_result(db, user.id, req.interview_id, req.round, data)
        stored = True

    payload = dict(data) if isinstance(data, dict) else {"result": data}
    payload["stored"] = stored
    return ok(payload, "分析完成")
