"""题库接口：题目列表（过滤/分页）与详情

数据来源：questions 表（scripts/import_question_bank.py 从 题库/*.xlsx 导入）。
主要使用者：后端开发 B（AI专项1）的面试官对话逻辑（选题/追问），
B 的服务账号登录后携带 Bearer token 调用即可（与全站鉴权一致）。

选题约定（详见 docs/REPORT_TO_P2.md）：
- 开场题（第 1 轮）：interview_stage=开场热身 且 difficulty=easy
- 追问（第 2~7 轮）：结合 follow_up_triggers（L1 关键词触发 / L2 深入 / L3 极限 / 降级策略）
"""
from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError, NotFoundError
from app.models import Question
from app.models.question import QUESTION_CATEGORIES, QUESTION_DIFFICULTIES, QUESTION_STAGES
from app.schemas.question import QuestionOut
from app.utils.response import ok

router = APIRouter()


@router.get("", response_model=dict, summary="题库列表（按岗位/大类/难度/阶段过滤，分页）")
async def list_questions(
    _: CurrentUser,
    db: DbSession,
    position: str | None = Query(default=None, description="岗位 code，如 backend"),
    category: str | None = Query(default=None, description="大类，如 技术知识/场景与设计/编码与算法/项目深挖/行为面试"),
    difficulty: str | None = Query(default=None, description="难度：easy / medium / hard"),
    stage: str | None = Query(default=None, description="面试阶段：开场热身 / 核心考察 / 深度考察 / 收尾交流"),
    q: str | None = Query(default=None, description="题干模糊搜索关键词"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> dict:
    # 受控词表校验：非法值立刻 400，避免题库改名后静默返回空集
    # （position 是岗位开放集合，不在此校验）
    for value, vocabulary in (
        (category, QUESTION_CATEGORIES),
        (difficulty, QUESTION_DIFFICULTIES),
        (stage, QUESTION_STAGES),
    ):
        if value is not None and value not in vocabulary:
            raise BadRequestError(f"无效值「{value}」，可选值：{' / '.join(vocabulary)}")

    conditions = []
    if position:
        conditions.append(Question.position_code == position)
    if category:
        conditions.append(Question.category == category)
    if difficulty:
        conditions.append(Question.difficulty == difficulty)
    if stage:
        conditions.append(Question.interview_stage == stage)
    if q:
        # autoescape 转义 %/_，避免用户输入被当作 LIKE 通配符
        conditions.append(Question.question.contains(q, autoescape=True))

    total = await db.scalar(select(func.count()).select_from(Question).where(*conditions))
    result = await db.scalars(
        select(Question).where(*conditions).order_by(Question.id.asc()).limit(limit).offset(offset)
    )
    return ok(
        {
            "total": total or 0,
            "items": [QuestionOut.model_validate(item).model_dump() for item in result.all()],
        }
    )


@router.get("/{question_id}", response_model=dict, summary="题库详情（单题全量字段）")
async def get_question(question_id: int, _: CurrentUser, db: DbSession) -> dict:
    question = await db.get(Question, question_id)
    if question is None:
        raise NotFoundError("题目不存在")
    return ok(QuestionOut.model_validate(question).model_dump())
