"""学习资源 / 练习计划接口测试（GET /reports/study-plan）

**为什么锚点场景要用「改写第 1 轮题干」来构造**：测试环境下 conftest 清空了所有
外部依赖，出题链路只剩「题库策略 → 内置 Mock」，而这两条都无法预先确定文本——
题库策略从候选池 random 选取，Mock 的开场题按 `interview_id % 6` 取模。若靠
「往题库插题再指望它被选中」来构造场景，用例会随题库残留数据随机失败。
故统一改为：跑完面试后把第 1 轮题干改写为指定的题库题，确定性地建立
「题干能在题库里精确命中」这一前提，与出题算法解耦。
"""
from httpx import AsyncClient
from sqlalchemy import delete, update

from app.database import async_session
from app.core.knowledge_points import extract_knowledge_points, knowledge_token, priority_rank
from app.models import QARecord, Question
from tests.helpers import make_question
from tests.test_api import (  # noqa: F401  _cleanup_made_questions 是夹具
    _cleanup_made_questions,
    _finished_interview,
    _register,
)

BASE = "/api/v1"

# 学习建议文本刻意带句号与括号，用于逐字比对（验证没有经过任何改写或总结）
ADVICE_JVM = "理解JVM运行时数据区（堆/栈/方法区/程序计数器）的划分与各区域作用。"
ADVICE_JDK = "建议从「Jre Or Jdk」的核心定义与基本用法入手。"


async def _set_round1_stem(interview_id: int, stem: str) -> None:
    """把第 1 轮题干改写为指定文本（构造确定性的「锚点命中题库」场景）"""
    async with async_session() as db:
        await db.execute(
            update(QARecord)
            .where(QARecord.interview_id == interview_id, QARecord.round == 1)
            .values(question=stem)
        )
        await db.commit()


async def _add_questions(*questions: Question) -> None:
    """造题入库

    commit 后逐条 refresh：AsyncSession 在 commit 时会让对象过期，而过期属性在
    async 上下文里直接访问会抛 MissingGreenlet（用例随后要读 `anchor.id` 等）。
    """
    async with async_session() as db:
        for q in questions:
            db.add(q)
        await db.commit()
        for q in questions:
            await db.refresh(q)


def _kp_by_id(data: dict) -> dict[str, dict]:
    return {k["kp_id"]: k for k in data["knowledge_points"]}


class TestStudyPlan:
    async def test_single_interview_plan(self, client: AsyncClient, _cleanup_made_questions):
        """单场模式：返回该场考察过的知识点，advice 与题库原文逐字一致"""
        _, headers = await _register(client, "plan")
        anchor = make_question(
            question="JVM、JDK、JRE 三者有什么区别和联系？",
            exam_priority="高频必考题",
            related_knowledge=(
                f"java-backend-kp-3180|JVM入门与体系结构|{ADVICE_JVM}\n"
                f"java-backend-kp-4911|Jre Or Jdk|{ADVICE_JDK}"
            ),
        )
        await _add_questions(anchor)

        interview_id = await _finished_interview(client, headers)
        await _set_round1_stem(interview_id, anchor.question)

        resp = await client.get(f"{BASE}/reports/study-plan?interview_id={interview_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        assert data["interview_id"] == interview_id
        assert data["positions"] == ["backend"]
        assert data["source_interviews"][0]["interview_id"] == interview_id
        assert data["notice"] is None

        kps = _kp_by_id(data)
        assert set(kps) == {"java-backend-kp-3180", "java-backend-kp-4911"}
        # 学习建议是题库原文，不重写不总结
        assert kps["java-backend-kp-3180"]["advice"] == ADVICE_JVM
        assert kps["java-backend-kp-4911"]["advice"] == ADVICE_JDK
        assert kps["java-backend-kp-3180"]["priority"] == "高频必考题"

        # 只有锚点原题（第 1 轮）参与反查——追问轮次与 Mock 题的文本不在题库里
        for kp in kps.values():
            assert kp["hit_count"] == 1
            assert [s["round"] for s in kp["sources"]] == [1]
        assert kps["java-backend-kp-3180"]["sources"][0]["question_no"] == anchor.question_no

    async def test_practice_falls_back_to_whole_bank(self, client: AsyncClient, _cleanup_made_questions):
        """配套练习来自全库（含别岗位的题），并标出哪些已经练过"""
        _, headers = await _register(client, "practice")
        anchor = make_question(
            question="JVM、JDK、JRE 三者有什么区别和联系？",
            related_knowledge=f"java-backend-kp-3180|JVM入门与体系结构|{ADVICE_JVM}",
            suggested_minutes=3,
        )
        await _add_questions(anchor)
        interview_id = await _finished_interview(client, headers)
        await _set_round1_stem(interview_id, anchor.question)

        # 面试结束后再插练习题：确保它们绝不会被出题算法抽到，锚点集合保持干净
        same_pos = make_question(
            question="JVM 内存模型是什么？",
            related_knowledge=f"java-backend-kp-3180|JVM入门与体系结构|{ADVICE_JVM}",
            suggested_minutes=5,
        )
        other_pos = make_question(
            position_code="frontend",  # 刻意放一道别岗位的题：知识点 ID 会跨岗位被引用
            question="前端工程里怎么排查内存泄漏？",
            related_knowledge=f"java-backend-kp-3180|JVM入门与体系结构|{ADVICE_JVM}",
            suggested_minutes=2,
        )
        await _add_questions(same_pos, other_pos)

        resp = await client.get(f"{BASE}/reports/study-plan?interview_id={interview_id}", headers=headers)
        data = resp.json()["data"]
        kp = data["knowledge_points"][0]
        practice = kp["practice_questions"]

        # 同岗位优先 → 同岗位内建议用时短的在前 → 别岗位的排最后
        assert [p["id"] for p in practice][:2] == [anchor.id, same_pos.id]
        assert practice[-1]["position_code"] == "frontend"
        # asked 只对「本计划的来源面试里问到过」的题为真
        assert [p["asked"] for p in practice] == [True, False, False]
        # 学习建议与建议用时都透传
        assert practice[0]["suggested_minutes"] == 3 and practice[0]["question_no"] == anchor.question_no

        assert kp["practice_minutes"] == 10
        assert data["total_minutes"] == 10
        assert data["pending_minutes"] == 7  # 未练过的 5 + 2

    async def test_anchor_match_is_position_scoped(self, client: AsyncClient, _cleanup_made_questions):
        """题干跨岗位重复时，只取本场面试岗位的那一道（否则会串到别岗的知识点）"""
        _, headers = await _register(client, "scoped")
        backend_q = make_question(
            question="什么是优先级队列？",
            related_knowledge="java-backend-kp-100|后端优先队列|后端视角的学习建议。",
        )
        frontend_q = make_question(
            position_code="frontend",
            question="什么是优先级队列？",  # 与上面题干完全相同
            related_knowledge="web-frontend-kp-200|前端优先队列|前端视角的学习建议。",
        )
        await _add_questions(backend_q, frontend_q)

        interview_id = await _finished_interview(client, headers)  # backend 场
        await _set_round1_stem(interview_id, backend_q.question)

        data = (
            await client.get(f"{BASE}/reports/study-plan?interview_id={interview_id}", headers=headers)
        ).json()["data"]
        assert set(_kp_by_id(data)) == {"java-backend-kp-100"}

    async def test_kp_token_match_rejects_prefix_id(self, client: AsyncClient, _cleanup_made_questions):
        """知识点 ID 用完整 token（ID+竖线）匹配，不会被更长的前缀 ID 误命中

        构造 `kp-318` 与 `kp-3180` 这对合成数据（真实库实测无此关系），把不变量钉死：
        谁把 knowledge_token 改回裸 ID，这条立刻红。
        """
        _, headers = await _register(client, "prefix")
        short_kp, long_kp = "java-backend-kp-318", "java-backend-kp-3180"
        anchor = make_question(
            question="短 ID 锚点题？",
            related_knowledge=f"{short_kp}|短ID知识点|短 ID 的建议。",
        )
        longer = make_question(
            question="长 ID 练习题？",
            related_knowledge=f"{long_kp}|长ID知识点|长 ID 的建议。",
        )
        await _add_questions(anchor, longer)
        interview_id = await _finished_interview(client, headers)
        await _set_round1_stem(interview_id, anchor.question)

        data = (
            await client.get(f"{BASE}/reports/study-plan?interview_id={interview_id}", headers=headers)
        ).json()["data"]
        kps = _kp_by_id(data)
        assert set(kps) == {short_kp}
        # 裸 ID LIKE 会命中 kp-3180 那道题；完整 token 不会
        assert [p["id"] for p in kps[short_kp]["practice_questions"]] == [anchor.id]

    async def test_aggregate_across_positions(self, client: AsyncClient, _cleanup_made_questions):
        """聚合模式：不传参覆盖最近 N 场的多个岗位，?position / ?recent 可收敛"""
        _, headers = await _register(client, "agg")
        backend_q = make_question(
            question="后端锚点题？",
            related_knowledge="java-backend-kp-11|后端知识点|后端建议。",
        )
        frontend_q = make_question(
            position_code="frontend",
            question="前端锚点题？",
            related_knowledge="web-frontend-kp-22|前端知识点|前端建议。",
        )
        await _add_questions(backend_q, frontend_q)

        backend_id = await _finished_interview(client, headers, "backend")
        await _set_round1_stem(backend_id, backend_q.question)
        frontend_id = await _finished_interview(client, headers, "frontend")
        await _set_round1_stem(frontend_id, frontend_q.question)

        # 不传参：两场都进来，岗位去重后按字母序
        data = (await client.get(f"{BASE}/reports/study-plan", headers=headers)).json()["data"]
        assert data["interview_id"] is None
        assert data["positions"] == ["backend", "frontend"]
        assert set(_kp_by_id(data)) == {"java-backend-kp-11", "web-frontend-kp-22"}
        assert {s["interview_id"] for s in data["source_interviews"]} == {backend_id, frontend_id}

        # 按岗位收敛
        data = (
            await client.get(f"{BASE}/reports/study-plan?position=frontend", headers=headers)
        ).json()["data"]
        assert data["positions"] == ["frontend"]
        assert set(_kp_by_id(data)) == {"web-frontend-kp-22"}

        # 只取最近一场：frontend 后跑，故为它（finished_at 是秒级精度，靠 id 兜底排序）
        data = (
            await client.get(f"{BASE}/reports/study-plan?recent=1", headers=headers)
        ).json()["data"]
        assert set(_kp_by_id(data)) == {"web-frontend-kp-22"}
        assert [s["interview_id"] for s in data["source_interviews"]] == [frontend_id]

    async def test_max_knowledge_truncates(self, client: AsyncClient, _cleanup_made_questions):
        """max_knowledge 截断（不截断的话 5 场 × 7 轮最多可堆到上百个知识点）"""
        _, headers = await _register(client, "cap")
        anchor = make_question(
            question="多知识点锚点题？",
            related_knowledge="\n".join(
                f"java-backend-kp-90{i}|知识点{i}|建议{i}。" for i in range(1, 4)
            ),
        )
        await _add_questions(anchor)
        interview_id = await _finished_interview(client, headers)
        await _set_round1_stem(interview_id, anchor.question)

        resp = await client.get(
            f"{BASE}/reports/study-plan?interview_id={interview_id}&max_knowledge=2", headers=headers
        )
        assert len(resp.json()["data"]["knowledge_points"]) == 2

    async def test_notice_when_no_finished_interview(self, client: AsyncClient):
        """没有已结束的面试：200 + 空计划 + notice，不报错（与 /growth 同口径）"""
        _, headers = await _register(client, "empty")

        resp = await client.get(f"{BASE}/reports/study-plan", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["knowledge_points"] == []
        assert data["total_minutes"] == 0
        assert data["notice"]

        # 未开放的岗位 code：不报错，返回空计划（岗位是动态集合）
        resp = await client.get(f"{BASE}/reports/study-plan?position=rust", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["knowledge_points"] == []

    async def test_notice_when_stem_not_in_bank(self, client: AsyncClient, _cleanup_made_questions):
        """题干在题库里匹配不到：200 + 空计划 + notice

        用「删掉那道锚点题」构造匹配落空，而不是「题库为空」——同文件的其它用例与
        test_api 的题库用例都会留下题目，空库断言会变成执行顺序相关的。
        """
        _, headers = await _register(client, "nobank")
        anchor = make_question(
            question="即将从题库消失的题？",
            related_knowledge="java-backend-kp-77|知识点|建议。",
        )
        await _add_questions(anchor)
        interview_id = await _finished_interview(client, headers)
        await _set_round1_stem(interview_id, anchor.question)

        async with async_session() as db:
            await db.execute(delete(Question).where(Question.id == anchor.id))
            await db.commit()

        data = (
            await client.get(f"{BASE}/reports/study-plan?interview_id={interview_id}", headers=headers)
        ).json()["data"]
        assert data["knowledge_points"] == []
        assert data["total_minutes"] == 0
        assert data["notice"]

    async def test_interview_not_finished_409(self, client: AsyncClient):
        """面试尚未结束：409（还没有报告，也就没有可推荐的依据）"""
        _, headers = await _register(client, "ongoing")
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]

        resp = await client.get(
            f"{BASE}/reports/study-plan?interview_id={interview_id}", headers=headers
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == 40900

    async def test_unknown_or_foreign_interview_404(self, client: AsyncClient):
        """不存在的面试与别人的面试一律 404（不区分，避免泄露存在性）"""
        _, headers_a = await _register(client, "ownera")
        _, headers_b = await _register(client, "ownerb")
        interview_id = await _finished_interview(client, headers_a)

        resp = await client.get(f"{BASE}/reports/study-plan?interview_id=999999", headers=headers_a)
        assert resp.status_code == 404

        resp = await client.get(
            f"{BASE}/reports/study-plan?interview_id={interview_id}", headers=headers_b
        )
        assert resp.status_code == 404

    async def test_interview_id_and_position_conflict(self, client: AsyncClient):
        """interview_id 与 position 互斥：同传 400（不静默忽略调用方显式传的参数）"""
        _, headers = await _register(client, "conflict")
        resp = await client.get(
            f"{BASE}/reports/study-plan?interview_id=1&position=backend", headers=headers
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

    async def test_study_plan_requires_auth(self, client: AsyncClient):
        """未登录：401"""
        resp = await client.get(f"{BASE}/reports/study-plan")
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100

    async def test_param_bounds(self, client: AsyncClient):
        """越界参数：422 且归一到 code 40000"""
        _, headers = await _register(client, "bounds")
        for qs in ("recent=0", "recent=21", "max_knowledge=0", "max_knowledge=51", "interview_id=0"):
            resp = await client.get(f"{BASE}/reports/study-plan?{qs}", headers=headers)
            assert resp.status_code == 422, qs
            assert resp.json()["code"] == 40000, qs


class TestKnowledgePoints:
    """知识点解析纯函数（口径与 P5 交付包的 01_generate_rag_data.py 对齐）"""

    def test_extract_three_and_two_segments(self):
        """标准三段行正常解析；缺第三段时学习建议为空串"""
        points = extract_knowledge_points(
            "kp-1|知识点甲|建议甲。\nkp-2|知识点乙"
        )
        assert [(p.kp_id, p.name, p.advice) for p in points] == [
            ("kp-1", "知识点甲", "建议甲。"),
            ("kp-2", "知识点乙", ""),
        ]

    def test_extract_skips_blank_and_malformed(self):
        """空行、纯空白行、不足两段的行整行丢弃；None / 空串返回空列表"""
        assert extract_knowledge_points("kp-1|甲|建议。\n\n   \n没有竖线的行\n") == [
            extract_knowledge_points("kp-1|甲|建议。")[0]
        ]
        assert extract_knowledge_points(None) == []
        assert extract_knowledge_points("") == []

    def test_knowledge_token_and_priority_rank(self):
        """token 带竖线后缀（防前缀 ID 误命中）；未知优先级排最后"""
        assert knowledge_token("java-backend-kp-318") == "java-backend-kp-318|"
        assert priority_rank("高频必考题") < priority_rank("常规题") < priority_rank("拓展题")
        assert priority_rank("") == priority_rank("没见过的取值")
