"""体态分析接口：浏览器本地提取的姿态关键点进，沟通姿态信号出

数据边界（与引擎侧一致）：**只收数字关键点**，不收图片、视频或音频。
摄像头画面在浏览器里由 MediaPipe 转成归一化坐标后即丢弃，上传的只有数字。
这条边界不在这层放宽——放宽一次，就等于给这条路开了个能传画面的口子。
"""
import logging

from fastapi import APIRouter

from app.adapters import get_dialogue_adapter
from app.adapters.ai_dialogue import EngineError
from app.api.deps import CurrentUser
from app.core.exceptions import ServiceUnavailableError
from app.schemas.engine import BodyLanguageRequest
from app.utils.response import ok

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze", response_model=dict, summary="体态分析（本地关键点进，沟通姿态信号出）")
async def analyze_body_language(user: CurrentUser, req: BodyLanguageRequest) -> dict:
    """分析一段姿态关键点，返回沟通姿态信号

    引擎侧的取分是刻意的：证据不足（镜头坏了、手出画、帧数太少）时**不给分**，
    而不是给个低分。所以结果是「可能没有 score」的形状，这里如实透传，
    不在这边补默认值——补一个 0 分出来，就成了「摄像头坏了 = 考生体态差」。
    """
    frames = [frame.model_dump(exclude_none=True) for frame in req.frames]
    try:
        data = await get_dialogue_adapter().analyze_body_language(frames)
    except EngineError as exc:
        raise ServiceUnavailableError(f"体态分析不可用：{exc}") from exc
    return ok(data, "分析完成")
