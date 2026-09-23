"""报告接口：查看单场报告 / 能力成长曲线 / 学习计划 / 生成分享链接"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import load_only

from app.api.deps import CurrentUser, DbSession, get_owned_interview
from app.config import settings
from app.core.exceptions import BadRequestError, ConflictError
from app.core.knowledge_points import extract_knowledge_points, knowledge_token, priority_rank
from app.core.state_machine import InterviewStatus
from app.models import Interview, QARecord, Question, Report, ReportShare
from app.schemas.report import (
    GrowthPoint,
    KPSource,
    KnowledgePointOut,
    PracticeQuestionOut,
    ShareOut,
    SourceInterviewOut,
    StudyPlanOut,
    report_out,
)
from app.utils.response import ok

router = APIRouter()


@router.get("/growth", response_model=dict, summary="能力成长曲线（历史面试得分序列）")
async def get_growth(
    user: CurrentUser,
    db: DbSession,
    position: str | None = Query(default=None, description="按岗位筛选（不传=全部岗位）"),
    engine: str | None = Query(
        default=None,
        description="按面试链路筛选：standard=原链路 / a11=AI 对话层引擎（不传=全部）",
    ),
) -> dict:
    conditions = [
        Interview.user_id == user.id,
        Interview.status == InterviewStatus.FINISHED.value,
    ]
    if position:
        # 岗位是动态集合（positions 表），非法值不报错、返回空序列即可。
        # 各岗位评估维度与权重不同，混在一条曲线里没有可比性——按岗位筛是这条接口
        # 的主要用法，前端个人中心切 Tab 时传该参数。
        conditions.append(Interview.position == position)
    if engine:
        # 同理：两种链路的五维分不是同一把尺子（P3 按题注入校准锚点，引擎逐轮
        # LLM 打分），混画会被误读成涨跌。库里原链路存的是空串，对外叫 standard。
        conditions.append(Interview.engine == ("" if engine == "standard" else engine))

    result = await db.execute(
        select(Interview, Report)
        .join(Report, Report.interview_id == Interview.id)
        .where(*conditions)
        .order_by(Interview.finished_at.asc())
    )
    points = [
        GrowthPoint(
            interview_id=interview.id,
            position=interview.position,
            engine=interview.engine or "",
            finished_at=interview.finished_at,
            total_score=report.total_score,
            tech_score=report.tech_score,
            logic_score=report.logic_score,
            expression_score=report.expression_score,
            adaptability_score=report.adaptability_score,
            match_score=report.match_score,
        ).model_dump()
        for interview, report in result.all()
    ]
    return ok(points)


@router.get("/latest", response_model=dict, summary="最近一次面试的改进建议（个人中心用）")
async def get_latest_suggestion(user: CurrentUser, db: DbSession) -> dict:
    """返回最近一场已结束面试的建议摘要；从未完成过面试时 data 为 null"""
    result = await db.execute(
        select(Interview, Report)
        .join(Report, Report.interview_id == Interview.id)
        .where(Interview.user_id == user.id, Interview.status == InterviewStatus.FINISHED.value)
        .order_by(Interview.finished_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return ok(None)
    interview, report = row
    return ok(
        {
            "interview_id": interview.id,
            "position": interview.position,
            "finished_at": interview.finished_at,
            "total_score": report.total_score,
            "suggestions": report.suggestions,
        }
    )


# 每个知识点最多带几道配套练习题：实测知识点中位数只有 2 道关联题，5 道已覆盖
# 绝大多数；唯一的高频知识点（405 道关联题）也只展示前 5。
_PRACTICE_PER_KP = 5
# 反查锚点原题与练习题时共用的投影列：只取推荐用得到的字段，不加载得分点 /
# 追问 / 校准锚点等长文本列。**新增字段访问前必须先加进这个元组**——load_only
# 会把未列出的列变成延迟加载，在 async 上下文里访问会抛 MissingGreenlet。
_BANK_COLUMNS = (
    Question.id,
    Question.position_code,
    Question.question_no,
    Question.question,
    Question.category,
    Question.difficulty,
    Question.exam_priority,
    Question.suggested_minutes,
    Question.related_knowledge,
)


@dataclass
class _KpHit:
    """单个知识点的聚合累加器（本接口内部使用）"""

    kp_id: str
    name: str
    advice: str
    rank: int
    priority: str
    # 首次出现顺序：排序的最后一道兜底，保证结果与查询顺序无关且可复现
    seq: int
    sources: list[KPSource] = field(default_factory=list)


@router.get("/study-plan", response_model=dict, summary="智能推荐学习资源与练习计划")
async def get_study_plan(
    user: CurrentUser,
    db: DbSession,
    interview_id: int | None = Query(
        default=None, ge=1, description="指定单场面试（报告页用）；不传=聚合最近 N 场（个人中心用）"
    ),
    position: str | None = Query(default=None, description="岗位 code（仅聚合模式，不传=全部岗位）"),
    recent: int = Query(default=5, ge=1, le=20, description="聚合模式下取最近 N 场已结束面试"),
    max_knowledge: int = Query(default=10, ge=1, le=50, description="最多返回多少个知识点"),
) -> dict:
    """学习资源与练习计划：把面试考察过的题目反查回题库，给出知识点 + 题库自带的
    学习建议原文 + 同知识点的配套练习题（站内闭环，不依赖外部服务）。

    **口径是「考察过的知识点」，不是「你答得差的知识点」**——报告只有整场面试的
    5 维聚合分、没有单题得分，这里不假装知道哪道题答错。排序 = 考点优先级（高频
    必考题优先）→ 被几道题命中 → 首次出现顺序。

    只认**锚点原题**：追问是按锚点生成的文本，RAG / Mock / LLM 现场出的题也不在
    题库里，它们都反查不到，因此不参与推荐。这是口径边界，不是漏匹配。
    """
    # ---- 1. 选目标面试 ----
    if interview_id is not None:
        # 单场模式下岗位由该场面试唯一决定。忽略调用方显式传入的 position 会得到
        # 一个「看起来正常但口径不对」的结果，所以直接拒绝，不静默吞掉
        if position:
            raise BadRequestError("interview_id 与 position 不能同时传：单场模式下岗位由该场面试决定")
        interview = await get_owned_interview(interview_id, user, db)
        if interview.status != InterviewStatus.FINISHED.value:
            raise ConflictError("面试尚未结束，暂无学习计划")
        targets = [interview]
    else:
        conditions = [
            Interview.user_id == user.id,
            Interview.status == InterviewStatus.FINISHED.value,
        ]
        if position:
            # 岗位是动态集合，未开放的 code 不报错、返回空计划即可（与 /growth 同口径）
            conditions.append(Interview.position == position)
        targets = list(
            (
                await db.scalars(
                    select(Interview)
                    .where(*conditions)
                    # finished_at 是秒级精度，同秒结束的两场顺序不定——补 id 兜底，
                    # 否则「最近 N 场」会变成顺序相关的
                    .order_by(Interview.finished_at.desc(), Interview.id.desc())
                    .limit(recent)
                )
            ).all()
        )

    if not targets:
        return ok(
            StudyPlanOut(
                interview_id=None,
                source_interviews=[],
                positions=[],
                knowledge_points=[],
                total_minutes=0,
                pending_minutes=0,
                notice=(
                    "该岗位下还没有已结束的面试"
                    if position
                    else "还没有已结束的面试，完成一场面试后即可生成学习计划"
                ),
            ).model_dump()
        )

    # ---- 2. 一次拉齐题干（含最后一轮问了未作答的：被问到过就算考察过）----
    position_of = {iv.id: iv.position for iv in targets}
    qa_rows = (
        await db.execute(
            select(QARecord.interview_id, QARecord.round, QARecord.question)
            .where(QARecord.interview_id.in_(list(position_of)))
            .order_by(QARecord.interview_id.asc(), QARecord.round.asc())
        )
    ).all()

    stems_by_position: dict[str, set[str]] = {}
    asked_keys: set[tuple[str, str]] = set()
    for iid, _round, stem in qa_rows:
        stem = (stem or "").strip()
        if not stem:
            continue
        pos = position_of[iid]
        stems_by_position.setdefault(pos, set()).add(stem)
        asked_keys.add((pos, stem))

    # ---- 3. 锚点原题：按岗位分组反查题库 ----
    # 必须带 position 过滤——题干会跨岗位重复（如「什么是优先级队列？」同时在算法与
    # 系统设计岗），只按题干匹配会取到别岗的素材，结果看着正常但口径是错的
    # （同一条警告见 app/adapters/ai_evaluator.py 的 _attach_materials）。
    anchor_index: dict[tuple[str, str], Question] = {}
    for pos, stems in stems_by_position.items():
        rows = (
            await db.scalars(
                select(Question)
                .options(load_only(*_BANK_COLUMNS))
                .where(Question.position_code == pos, Question.question.in_(stems))
            )
        ).all()
        for q in rows:
            # 同岗位内实测无重复题干；万一有，取第一条即可
            anchor_index.setdefault((pos, q.question.strip()), q)

    # ---- 4. 聚合知识点 ----
    hits: dict[str, _KpHit] = {}
    for iid, round_no, stem in qa_rows:
        anchor = anchor_index.get((position_of[iid], (stem or "").strip()))
        if anchor is None:
            continue  # 追问文本 / 题库外现场题：不在题库，不参与反查
        for ref in extract_knowledge_points(anchor.related_knowledge):
            hit = hits.get(ref.kp_id)
            if hit is None:
                hit = hits[ref.kp_id] = _KpHit(
                    kp_id=ref.kp_id,
                    name=ref.name,
                    advice=ref.advice,
                    rank=priority_rank(anchor.exam_priority),
                    priority=anchor.exam_priority,
                    seq=len(hits),
                )
            elif priority_rank(anchor.exam_priority) < hit.rank:
                # 取来源题中最高的考点优先级（高频必考题 > 常规题 > 拓展题）
                hit.rank = priority_rank(anchor.exam_priority)
                hit.priority = anchor.exam_priority
            hit.sources.append(
                KPSource(
                    interview_id=iid,
                    round=round_no,
                    question_no=anchor.question_no,
                    question=anchor.question,
                )
            )

    ordered = sorted(hits.values(), key=lambda h: (h.rank, -len(h.sources), h.seq))[
        :max_knowledge
    ]

    # ---- 5. 配套练习题：一次 OR 查询覆盖全部知识点 ----
    # 不按 kp 拆成 N 次查询——那会把一次全表扫变成 N 次。实测 10 个 kp 的 OR
    # 查询约 14ms、30 个约 40ms（related_knowledge 平均仅 185 字符）。
    kp_ids = [h.kp_id for h in ordered]
    practice_by_kp: dict[str, list[Question]] = {}
    if kp_ids:
        rows = (
            await db.scalars(
                select(Question)
                .options(load_only(*_BANK_COLUMNS))
                .where(
                    or_(
                        *[
                            # autoescape 是必需项不是防御项：知识点 ID 里确实含下划线
                            # （如 java_backend-kp-soft-40155），`_` 在 LIKE 里匹配任意单字符
                            Question.related_knowledge.contains(
                                knowledge_token(kid), autoescape=True
                            )
                            for kid in kp_ids
                        ]
                    )
                )
            )
        ).all()
        kp_id_set = set(kp_ids)
        practice_by_kp = {kid: [] for kid in kp_ids}
        for q in rows:
            # 同一知识点在本题字段里出现两次时，不能把这道题挂两遍
            for kid in {r.kp_id for r in extract_knowledge_points(q.related_knowledge)}:
                if kid in kp_id_set:
                    practice_by_kp[kid].append(q)

    # ---- 6. 组装 ----
    knowledge_points: list[KnowledgePointOut] = []
    chosen: dict[int, PracticeQuestionOut] = {}  # 题目 id → 题，跨知识点去重（总时长不重复计）
    for hit in ordered:
        source_positions = {position_of[s.interview_id] for s in hit.sources}
        practice = [
            PracticeQuestionOut(
                id=q.id,
                position_code=q.position_code,
                question_no=q.question_no,
                question=q.question,
                category=q.category,
                difficulty=q.difficulty,
                exam_priority=q.exam_priority,
                suggested_minutes=q.suggested_minutes,
                asked=(q.position_code, q.question.strip()) in asked_keys,
            )
            for q in sorted(
                practice_by_kp[hit.kp_id],
                key=lambda q: (
                    0 if q.position_code in source_positions else 1,  # 同岗位优先
                    priority_rank(q.exam_priority),
                    q.suggested_minutes,  # 短题先做
                    q.id,
                ),
            )[:_PRACTICE_PER_KP]
        ]
        knowledge_points.append(
            KnowledgePointOut(
                kp_id=hit.kp_id,
                name=hit.name,
                advice=hit.advice,
                priority=hit.priority,
                hit_count=len(hit.sources),
                sources=hit.sources,
                practice_minutes=sum(p.suggested_minutes for p in practice),
                practice_questions=practice,
            )
        )
        for p in practice:
            chosen[p.id] = p

    # 去重后求和：一道题可能同时是多个知识点的配套练习，重复计会让总时长虚高
    total_minutes = sum(p.suggested_minutes for p in chosen.values())
    pending_minutes = sum(
        p.suggested_minutes
        for p in chosen.values()
        if (p.position_code, p.question.strip()) not in asked_keys
    )

    return ok(
        StudyPlanOut(
            interview_id=interview_id,
            source_interviews=[
                SourceInterviewOut(
                    interview_id=iv.id, position=iv.position, finished_at=iv.finished_at
                )
                for iv in targets
            ],
            positions=sorted({iv.position for iv in targets}),
            knowledge_points=knowledge_points,
            total_minutes=total_minutes,
            pending_minutes=pending_minutes,
            notice=(
                None
                if knowledge_points
                else "面试题目未在题库中命中（题库可能尚未导入，或题目由 RAG / AI 现场生成），"
                "暂时无法生成学习计划"
            ),
        ).model_dump()
    )


@router.get("/{interview_id}", response_model=dict, summary="获取指定面试的评估报告")
async def get_report(interview_id: int, user: CurrentUser, db: DbSession) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    if interview.status != InterviewStatus.FINISHED.value:
        raise ConflictError("面试尚未结束，暂无报告")

    report = await db.scalar(select(Report).where(Report.interview_id == interview_id))
    if report is None:
        raise ConflictError("报告生成中或生成失败，请稍后重试")
    return ok(report_out(report, interview).model_dump())


@router.post("/{interview_id}/share", response_model=dict, summary="生成报告分享链接")
async def create_share(
    interview_id: int, request: Request, user: CurrentUser, db: DbSession
) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    if interview.status != InterviewStatus.FINISHED.value:
        raise ConflictError("面试尚未结束，暂无可分享的报告")
    report = await db.scalar(select(Report).where(Report.interview_id == interview_id))
    if report is None:
        raise ConflictError("报告生成中或生成失败，请稍后重试")

    now = datetime.now()
    # 复用尚未过期的分享码：用户连点「生成链接」不该堆出一串等价的有效码。
    # 取过期时间最晚的那个，等价于优先复用有效期最长的一张。
    share = await db.scalar(
        select(ReportShare)
        .where(ReportShare.interview_id == interview_id, ReportShare.expires_at > now)
        .order_by(ReportShare.expires_at.desc())
    )
    if share is None:
        share = ReportShare(
            interview_id=interview_id,
            share_code=uuid.uuid4().hex,
            expires_at=now + timedelta(days=settings.SHARE_EXPIRE_DAYS),
        )
        db.add(share)
        await db.commit()
        await db.refresh(share)

    # base_url 取当前请求的 Host：内网穿透演示时它会是穿透域名，前端拿到即可直接分发
    base_url = str(request.base_url).rstrip("/")
    return ok(
        ShareOut(
            share_code=share.share_code,
            share_url=f"{base_url}/#/share/{share.share_code}",
            expires_at=share.expires_at,
        ).model_dump(),
        "分享链接已生成",
    )
