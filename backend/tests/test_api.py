"""全流程回归测试（P5 验收参考）

覆盖：注册登录、开始面试、多轮问答、自动结束出报告、手动结束、
成长曲线、越权访问、非法状态、音频上传、异常兜底格式。
"""
import uuid

import pytest
from httpx import AsyncClient

from app.models import Question

BASE = "/api/v1"


def _unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _register(client: AsyncClient, prefix: str = "user", position: str = "backend") -> tuple[str, dict]:
    resp = await client.post(
        f"{BASE}/auth/register",
        json={
            "username": _unique_name(prefix),
            "password": "pass123456",
            "nickname": "测试选手",
            "target_position": position,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    token = body["data"]["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


class TestAuth:
    async def test_register_login_me(self, client: AsyncClient):
        token, headers = await _register(client)
        assert token

        # me
        resp = await client.get(f"{BASE}/auth/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["nickname"] == "测试选手"

        # 重复注册 → 400
        username = _unique_name("dup")
        resp = await client.post(
            f"{BASE}/auth/register",
            json={"username": username, "password": "pass123456"},
        )
        assert resp.status_code == 200
        resp = await client.post(
            f"{BASE}/auth/register",
            json={"username": username, "password": "pass123456"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

    async def test_register_with_student_id(self, client: AsyncClient):
        """注册携带学号 → me 返回学号"""
        username = _unique_name("stu")
        resp = await client.post(
            f"{BASE}/auth/register",
            json={
                "username": username,
                "password": "pass123456",
                "nickname": "学号选手",
                "student_id": "20260001",
            },
        )
        assert resp.status_code == 200
        token = resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get(f"{BASE}/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["student_id"] == "20260001"

        # 登录响应同样携带学号
        resp = await client.post(
            f"{BASE}/auth/login", json={"username": username, "password": "pass123456"}
        )
        assert resp.json()["data"]["user"]["student_id"] == "20260001"

    async def test_login_wrong_password(self, client: AsyncClient):
        username = _unique_name("wrong")
        await client.post(
            f"{BASE}/auth/register",
            json={"username": username, "password": "pass123456"},
        )
        resp = await client.post(
            f"{BASE}/auth/login", json={"username": username, "password": "bad-pass"}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100

    async def test_unauthorized(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/auth/me")
        assert resp.status_code == 401
        resp = await client.get(f"{BASE}/interviews")
        assert resp.status_code == 401


class TestPositions:
    async def test_positions_list(self, client: AsyncClient):
        """岗位列表：返回已开放岗位，占位岗位不展示"""
        _, headers = await _register(client, "pos")
        resp = await client.get(f"{BASE}/positions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 3
        codes = [p["code"] for p in data]
        assert "backend" in codes and "frontend" in codes and "test_engineer" in codes
        assert all("pending" not in c for c in codes), "占位岗位不应出现在列表中"
        # 岗位项字段完整（前端岗位大厅用）
        for key in ("code", "name", "description", "tech_stack", "focus"):
            assert key in data[0]

    async def test_invalid_position(self, client: AsyncClient):
        """无效岗位：注册与开始面试均返回 40000"""
        resp = await client.post(
            f"{BASE}/auth/register",
            json={
                "username": _unique_name("badpos"),
                "password": "pass123456",
                "target_position": "rust",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

        _, headers = await _register(client, "badpos2")
        resp = await client.post(f"{BASE}/interviews", json={"position": "rust"}, headers=headers)
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

    async def test_test_engineer_interview(self, client: AsyncClient):
        """测试岗面试：seed 岗位可用，Mock 题库能出开场题"""
        _, headers = await _register(client, "qa_pos", position="test_engineer")
        resp = await client.post(f"{BASE}/interviews", json={"position": "test_engineer"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["interview"]["position"] == "test_engineer"
        assert data["question"]


class TestInterviewFlow:
    async def test_full_interview_auto_finish(self, client: AsyncClient):
        """完整面试：开场题 + 追问至上限 → 自动结束并出报告"""
        _, headers = await _register(client, "full")

        # 开始面试
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        interview_id = data["interview"]["id"]
        assert data["interview"]["status"] == "in_progress"
        assert data["question"]

        # 持续作答直到自动结束（上限 = 1 + MAX_FOLLOW_UP_ROUNDS = 7 轮）
        finished = False
        for _ in range(10):  # 防御性上限
            resp = await client.post(
                f"{BASE}/interviews/{interview_id}/answers",
                json={"answer": "我认为这个问题可以从数据一致性和系统可扩展性两个角度来分析。" * 2},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            if body["finished"]:
                finished = True
                assert body["report"] is not None
                assert 0 <= body["report"]["total_score"] <= 100
                assert body["report"]["strengths"]  # 报告含评语字段
                break
            assert body["next_question"], "未结束时应返回下一题"
        assert finished, "达到轮次上限后应自动结束"

        # 结束后再提交答案 → 409
        resp = await client.post(
            f"{BASE}/interviews/{interview_id}/answers",
            json={"answer": "已经结束了"},
            headers=headers,
        )
        assert resp.status_code == 409

        # 获取报告
        resp = await client.get(f"{BASE}/reports/{interview_id}", headers=headers)
        assert resp.status_code == 200
        report = resp.json()["data"]
        # 5 维评分：技术/逻辑/表达/应变/匹配
        for key in ("tech_score", "logic_score", "expression_score", "adaptability_score", "match_score"):
            assert 0 <= report[key] <= 100

    async def test_manual_finish_and_growth(self, client: AsyncClient):
        """手动结束 → 报告生成 → 成长曲线含该次面试"""
        _, headers = await _register(client, "manual")

        resp = await client.post(f"{BASE}/interviews", json={"position": "frontend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]

        await client.post(
            f"{BASE}/interviews/{interview_id}/answers",
            json={"answer": "我会先从资源加载、渲染管线、缓存策略三个层面来优化首屏性能。" * 2},
            headers=headers,
        )
        # 手动结束
        resp = await client.post(f"{BASE}/interviews/{interview_id}/finish", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["interview"]["status"] == "finished"
        assert resp.json()["data"]["report"]["interview_id"] == interview_id

        # 成长曲线
        resp = await client.get(f"{BASE}/reports/growth", headers=headers)
        assert resp.status_code == 200
        points = resp.json()["data"]
        assert any(p["interview_id"] == interview_id for p in points)

    async def test_list_with_score_and_latest_suggestion(self, client: AsyncClient):
        """历史列表附带综合得分；最近建议接口返回最新一场的建议"""
        _, headers = await _register(client, "score")

        # 未完成任何面试时：列表为空、最近建议为 null
        resp = await client.get(f"{BASE}/interviews", headers=headers)
        assert resp.json()["data"] == []
        resp = await client.get(f"{BASE}/reports/latest", headers=headers)
        assert resp.json()["data"] is None

        # 完成一场面试
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]
        await client.post(
            f"{BASE}/interviews/{interview_id}/answers",
            json={"answer": "我会从索引设计、SQL 优化和缓存策略三个层面来分析慢查询问题。" * 2},
            headers=headers,
        )
        await client.post(f"{BASE}/interviews/{interview_id}/finish", headers=headers)

        # 列表第一项带 total_score 且 > 0
        resp = await client.get(f"{BASE}/interviews", headers=headers)
        first = resp.json()["data"][0]
        assert first["id"] == interview_id
        assert first["status"] == "finished"
        assert first["total_score"] is not None and first["total_score"] > 0

        # 最近建议接口返回该场面试的建议
        resp = await client.get(f"{BASE}/reports/latest", headers=headers)
        data = resp.json()["data"]
        assert data["interview_id"] == interview_id
        assert data["suggestions"] and len(data["suggestions"]) > 0

    async def test_two_ongoing_conflict(self, client: AsyncClient):
        """同一用户不能同时进行两场面试"""
        _, headers = await _register(client, "ongoing")
        assert (
            await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        ).status_code == 200
        resp = await client.post(
            f"{BASE}/interviews", json={"position": "backend"}, headers=headers
        )
        assert resp.status_code == 409

    async def test_other_user_cannot_access(self, client: AsyncClient):
        """越权：他人面试一律 404"""
        _, headers_a = await _register(client, "owner")
        _, headers_b = await _register(client, "hacker")

        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers_a)
        interview_id = resp.json()["data"]["interview"]["id"]

        resp = await client.get(f"{BASE}/interviews/{interview_id}", headers=headers_b)
        assert resp.status_code == 404

    async def test_report_before_finish(self, client: AsyncClient):
        """未结束的面试取报告 → 409"""
        _, headers = await _register(client, "early")
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]
        resp = await client.get(f"{BASE}/reports/{interview_id}", headers=headers)
        assert resp.status_code == 409


class TestUpload:
    async def test_upload_audio(self, client: AsyncClient):
        _, headers = await _register(client, "audio")
        resp = await client.post(
            f"{BASE}/uploads/audio",
            files={"file": ("answer.mp3", b"fake-audio-bytes", "audio/mpeg")},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["url"].startswith("/uploads/")

    async def test_upload_bad_extension(self, client: AsyncClient):
        _, headers = await _register(client, "badext")
        resp = await client.post(
            f"{BASE}/uploads/audio",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000


class TestQuestionBank:
    """题库：导入剥离逻辑 + 查询接口契约"""

    @staticmethod
    def _question(**overrides) -> Question:
        """测试造数：默认值铺底，只覆盖差异字段"""
        base = dict(
            position_code="backend", question_no="tech_001",
            category="技术知识", sub_category="Java基础", difficulty="easy",
            question="Java中==和equals()的区别是什么？",
            score_points="【basic 0.3】……【core 0.5】……【advanced 0.2】……",
            follow_up_triggers="【L1-触发追问】……",
            reference_answer="参考答案……", note="高频考点",
            interview_stage="开场热身", stage_order=1, suggested_minutes=3,
            alternative_directions="方向1：……", excellent_example="范例……",
        )
        return Question(**(base | overrides))

    async def test_strip_soft_skill_tag(self):
        """题干内嵌的「【岗位软技能考察：X】」应剥离到独立列"""
        from scripts.import_question_bank import strip_soft_skill_tag

        question = "请做一个简短的自我介绍\n\n【岗位软技能考察：故障应急响应意识】"
        cleaned, tag = strip_soft_skill_tag(question)
        assert cleaned == "请做一个简短的自我介绍"
        assert tag == "故障应急响应意识"
        # 无标签的题干原样返回
        cleaned2, tag2 = strip_soft_skill_tag("HashMap 的底层结构是什么？")
        assert cleaned2 == "HashMap 的底层结构是什么？"
        assert tag2 == ""

    async def test_question_bank_api(self, client: AsyncClient):
        """题库接口：鉴权、过滤、分页、详情、非法词表 400（数据由导入脚本写入，此处手工造数验证契约）"""
        from app.database import async_session
        from app.models import Question

        _, headers = await _register(client, "qb")

        # 未登录 → 401
        assert (await client.get(f"{BASE}/questions")).status_code == 401

        # 空库：total=0
        resp = await client.get(f"{BASE}/questions", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0

        # 插入 2 条不同岗位的题（测试库，模拟导入结果）
        async with async_session() as db:
            db.add_all([
                self._question(),
                self._question(
                    position_code="frontend", sub_category="HTML与CSS", difficulty="medium",
                    question="CSS中BFC的概念是什么？", interview_stage="核心考察",
                    stage_order=2, suggested_minutes=5, alternative_directions="", excellent_example="",
                ),
            ])
            await db.commit()

        # 全量列表
        resp = await client.get(f"{BASE}/questions", headers=headers)
        assert resp.json()["data"]["total"] == 2

        # 按岗位过滤
        resp = await client.get(f"{BASE}/questions?position=backend", headers=headers)
        data = resp.json()["data"]
        assert data["total"] == 1
        item = data["items"][0]
        assert item["position_code"] == "backend"
        assert item["question_no"] == "tech_001"
        assert item["category"] == "技术知识"

        # 过滤 + 难度组合
        resp = await client.get(
            f"{BASE}/questions?position=frontend&difficulty=medium", headers=headers
        )
        assert resp.json()["data"]["total"] == 1

        # 题干模糊搜索
        resp = await client.get(f"{BASE}/questions?q=equals", headers=headers)
        assert resp.json()["data"]["total"] == 1

        # 非法词表 → 400（题库改名后应立刻报错，而非静默空集）
        for bad in (f"{BASE}/questions?category=不存在", f"{BASE}/questions?difficulty=hardcore",
                    f"{BASE}/questions?stage=破冰环节"):
            resp = await client.get(bad, headers=headers)
            assert resp.status_code == 400, bad
            assert resp.json()["code"] == 40000

        # 详情
        resp = await client.get(f"{BASE}/questions/{item['id']}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["question_no"] == "tech_001"

        # 不存在 → 404
        resp = await client.get(f"{BASE}/questions/99999", headers=headers)
        assert resp.status_code == 404

    async def test_weights_match_csv(self):
        """《评估维度.csv》与代码权重一致：CSV 是团队定稿，代码是执行版，机器校验防漂移"""
        import csv
        from pathlib import Path

        from app.core.evaluation_weights import GENERIC_POSITION, POSITION_CONFIG, weights_for
        from scripts.import_question_bank import POSITION_MAP

        csv_path = Path(__file__).resolve().parents[2] / "评估维度.csv"
        assert csv_path.exists(), "评估维度.csv 应在仓库根目录"
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        # CSV 岗位列 → code 的映射从导入脚本的 POSITION_MAP 派生（事实源），
        # 只做去空格归一（CSV 列名「Java 后端」带空格，题库别名「Java后端」无空格）
        csv_columns = [c for c in rows[0].keys() if c != "评估维度"]
        dim_keys = {
            "技术水平": "weight_tech", "逻辑思维": "weight_logic",
            "沟通表达": "weight_expression", "应变能力": "weight_adaptability",
            "岗位匹配度": "weight_match",
        }
        for column in csv_columns:
            code = POSITION_MAP.get(column.replace(" ", ""))
            assert code is not None, f"CSV 列「{column}」在题库别名 POSITION_MAP 中找不到对应岗位"
            assert code in POSITION_CONFIG, f"岗位 {code} 无评估权重配置"
            for row in rows:
                key = dim_keys.get(row["评估维度"])
                if key is None:  # 跳过「合计」行
                    assert row[column] == "100%", f"{column} 的合计行应为 100%"
                    continue
                assert POSITION_CONFIG[code][key] == int(row[column].rstrip("%")), (
                    f"{column} 的「{row['评估维度']}」与代码权重不一致"
                )

        # Mock 兜底权重派生自同一数据源，抽查换算正确
        assert weights_for("backend")["tech"] == 0.35
        assert weights_for("unknown_generic") == {
            k.removeprefix("weight_"): v / 100
            for k, v in GENERIC_POSITION.items() if k.startswith("weight_")
        }


class TestHealth:
    async def test_health(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "healthy"
