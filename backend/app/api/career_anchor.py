"""岗位倾向速测接口：20 条陈述 → 推荐岗位 → 引导进入该岗位面试

题目与计分都在后端，前端只负责答题与展示。与前端 v3 的结果页字段逐项对齐：
`scores`（五个岗位的兴趣/能力/指数）、`consistency_percent`、`confidence`、
`title`、`narrative`、`signal_label`、`signal_narrative`。

推荐只依据考生自己的偏好与能力自评，不做能力判定，也不输出性格标签。
"""
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.career_anchor import (
    POSITION_REASONS,
    public_questions,
    score_answers,
    validate_answers,
)
from app.core.exceptions import BadRequestError, ServiceUnavailableError
from app.models import Position, UserSetting
from app.schemas.career_anchor import AnchorSubmitRequest
from app.utils.response import ok

router = APIRouter()


@router.get("/questions", response_model=dict, summary="获取岗位倾向速测题目")
async def get_anchor_questions(_: CurrentUser) -> dict:
    return ok(public_questions())


@router.post("/submit", response_model=dict, summary="提交 20 条评分，返回推荐岗位")
async def submit_anchor(req: AnchorSubmitRequest, user: CurrentUser, db: DbSession) -> dict:
    try:
        validate_answers(req.answers)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc

    result = score_answers(req.answers)

    # 只推荐已开放岗位：系统默认五岗全开，这里保留过滤是为了岗位下线时
    # 不会把考生引到一个无法开始面试的方向
    rows = (await db.scalars(select(Position).where(Position.enabled.is_(True)))).all()
    enabled = {row.code for row in rows}
    names = {row.code: row.name for row in rows}
    scores = [item for item in result["scores"] if item["position"] in enabled]
    if not scores:
        raise ServiceUnavailableError("当前没有开放的面试岗位，暂时无法推荐")

    for item in scores:
        item["name"] = names.get(item["position"], item["name"])

    top = scores[0]
    if top["position"] != result["recommended"]["position"]:
        # 首选岗位已下线：改用当前开放岗位里的第一名，文案同步重算
        result["recommended"] = {
            "position": top["position"],
            "name": top["name"],
            "index": top["index"],
            "reason": POSITION_REASONS.get(top["position"], ""),
        }
        result["title"] = top["name"]
        result["guide"] = f"可以先用「{top['name']}」开始一场模拟面试，系统会按该岗位的题目出题。"

    result["recommended"]["name"] = names.get(
        result["recommended"]["position"], result["recommended"]["name"]
    )
    result["alternatives"] = [
        {"position": item["position"], "name": item["name"], "index": item["index"]}
        for item in scores[1:3]
    ]
    result["scores"] = scores

    # 落一份结果摘要：前端从 GET /settings 读它判断「是否测过」，
    # 换设备也能看到上次推荐，不依赖浏览器本地存储。
    setting = await db.get(UserSetting, user.id)
    if setting is None:
        setting = UserSetting(user_id=user.id)
        db.add(setting)
    setting.career_anchor_result = {
        "position": result["recommended"]["position"],
        "name": result["recommended"]["name"],
        "index": result["recommended"]["index"],
        "consistency_percent": result["consistency_percent"],
        "confidence": result["confidence"],
        "tested_at": datetime.now().isoformat(timespec="seconds"),
    }
    await db.commit()

    return ok(result, "推荐岗位已生成")
