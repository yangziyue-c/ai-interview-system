"""系统运行参数（前端渲染所需的只读配置）

为什么单独开一个接口：前端要渲染「第 N / 共几轮」就必须知道「一场面试共几轮」，
而这个值由后端 `.env` 的 `MAX_FOLLOW_UP_ROUNDS` 决定。前端硬编码会在改配置后
与后端**静默漂移**（演示前端曾写死 7），故改由后端下发。

新增前端需要的运行参数时，加在这里，不要再让前端猜。
"""
from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.config import settings
from app.utils.response import ok

router = APIRouter()


@router.get("", response_model=dict, summary="前端运行参数（面试总轮数等）")
async def get_config(_: CurrentUser) -> dict:
    # 引擎链路的题数由对话层决定（固定 10 题），原链路才是 1 + 追问轮数。
    # 这里不加判断的话，前端胶囊在引擎场会显示「第 5 / 共 7 题」而实际有 10 题。
    engine_on = settings.engine_enabled
    return ok(
        {
            "total_rounds": (
                settings.DIALOGUE_ENGINE_TOTAL_QUESTIONS if engine_on else settings.total_rounds
            ),
            "max_follow_up_rounds": settings.MAX_FOLLOW_UP_ROUNDS,
            "engine": "a11" if engine_on else "standard",
        }
    )
