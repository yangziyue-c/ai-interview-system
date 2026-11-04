"""职业锚定测试接口：5 道选择题 → 推荐岗位 → 引导进入该岗位面试

只做「引导入口」：推荐依据是考生自己勾选的工作偏好，不涉及能力评测。
推荐的岗位一定从 positions 表里已开放的岗位中选，前端拿到 code 后直接调
`POST /interviews` 即可开始一场该岗位的模拟面试。
"""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.career_anchor import (
    ANCHOR_QUESTIONS,
    build_reason,
    public_questions,
    rank_positions,
    score_answers,
    validate_answers,
)
from app.core.exceptions import BadRequestError, ServiceUnavailableError
from app.models import Position
from app.schemas.career_anchor import AnchorSubmitRequest
from app.utils.response import ok

router = APIRouter()


@router.get("/questions", response_model=dict, summary="获取职业锚定测试题目")
async def get_anchor_questions(_: CurrentUser) -> dict:
    return ok({"questions": public_questions(), "total": len(ANCHOR_QUESTIONS)})


@router.post("/submit", response_model=dict, summary="提交答案，返回推荐岗位")
async def submit_anchor(req: AnchorSubmitRequest, _: CurrentUser, db: DbSession) -> dict:
    try:
        validate_answers(req.answers)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc

    scores = score_answers(req.answers)
    rows = (
        await db.scalars(select(Position).where(Position.enabled.is_(True)))
    ).all()
    enabled = {row.code for row in rows}
    names = {row.code: row.name for row in rows}

    ranked = rank_positions(scores, enabled)
    if not ranked:
        # 全部岗位下线时没有可推荐项：明确报错，不返回一个不存在的岗位
        raise ServiceUnavailableError("当前没有开放的面试岗位，暂时无法推荐")

    top_code, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    top_name = names.get(top_code, top_code)

    ordered = [
        {"position": code, "name": names.get(code, code), "score": score}
        for code, score in ranked
    ]
    return ok(
        {
            "recommended": {
                "position": top_code,
                "name": top_name,
                "score": top_score,
                "reason": build_reason(top_name, top_score, second_score),
            },
            "alternatives": ordered[1:3],
            "scores": ordered,
            "guide": f"可以先用「{top_name}」开始一场模拟面试，系统会按该岗位的题目出题。",
        },
        "推荐岗位已生成",
    )
