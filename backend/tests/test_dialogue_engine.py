"""AI 对话层引擎（A11）的适配与落库用例

不连真服务：SSE 用真实帧格式喂纯函数，流程用假适配器替换单例。
真模型与真链路的验证方式是后端 start.bat + A11 自带的 smoke_test.py
（见 backend/dialogue_layer/README-集成说明.md）。
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.adapters.ai_dialogue import EngineError, parse_sse_text
from app.config import settings
from app.core.engine_report import build_engine_meta, build_engine_report
from app.database import async_session
from app.models import QARecord

BASE = "/api/v1"


def _unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _register(client: AsyncClient, prefix: str = "engine") -> tuple[str, dict]:
    resp = await client.post(
        f"{BASE}/auth/register",
        json={
            "username": _unique_name(prefix),
            "password": "pass123456",
            "nickname": "引擎测试选手",
            "target_position": "backend",
        },
    )
    assert resp.status_code == 200
    access_token = resp.json()["data"]["access_token"]
    return access_token, {"Authorization": f"Bearer {access_token}"}


async def _auth_headers(client: AsyncClient, prefix: str = "engine") -> dict:
    """注册一个用户并返回带 token 的请求头"""
    _, headers = await _register(client, prefix)
    return headers


# ============================================================
# SSE 解析（纯函数）
# ============================================================
_SSE_REPLY = "\n".join([
    'data: {"type": "token", "text": "嗯"}',
    "",
    'data: {"type": "token", "text": "，你提到的那几点抓住了主干。"}',
    "",
    'data: {"type": "done", "follow_up": true, "q_index": 3, "action": "L1", "swapped": false}',
    "",
])


def test_parse_sse_joins_tokens_and_keeps_done():
    out = parse_sse_text(_SSE_REPLY)
    assert out["reply"] == "嗯，你提到的那几点抓住了主干。"
    assert out["done"]["follow_up"] is True
    assert out["done"]["q_index"] == 3


def test_parse_sse_raises_on_error_frame():
    # 流已开之后才出错时，引擎走的是 error 帧而不是 HTTP 错误码
    text = 'data: {"type": "error", "code": "llm_unavailable", "err": "没配 key"}'
    with pytest.raises(EngineError, match="llm_unavailable"):
        parse_sse_text(text)


def test_parse_sse_raises_without_done():
    text = 'data: {"type": "token", "text": "说到一半就断了"}'
    with pytest.raises(EngineError, match="done"):
        parse_sse_text(text)


# ============================================================
# 报告换算（纯函数）
# ============================================================
def _finish_payload(**overrides) -> dict:
    """合成的 /finish 返回：**结构**照真实样例，内容是编的

    （真实样例的 raw 里含得分点原文，不引进测试夹具）
    """
    payload = {
        "session_id": "0a1b2c3d",
        "job": "Java 后端开发工程师",
        "five_dim_avg": {
            "技术水平": 4.0, "逻辑思维": 3.0, "沟通表达": 4.5,
            "应变能力": 2.0, "岗位匹配度": 3.5,
        },
        "total_score": 3.5,
        "total_score_100": 70.0,
        "weights": "技术35% 逻辑25% 沟通10% 应变10% 匹配20%",
        "summary": "整体表现不错，原理讲得清楚。",
        "rounds": 10,
        "partial": False,
        "notes": [],
        "raw": {
            "questions_asked": 10,
            "scoring_failed_rounds": [],
            "swaps_used": 0,
            "rounds": [
                {"five_dim": {"技术水平": 5.0, "逻辑思维": 4.0}, "comment": "这道题答得最扎实。"}
            ],
            "blindspots": {
                "summary": {"kp_total": 20, "kp_hit": 15, "kg_available": True},
                "domains": [
                    {"domain": "分布式基础", "kps_weak": 3, "weak_kps": ["CAP 理论", "BASE 理论"]},
                    {"domain": "未归类", "kps_weak": 9, "weak_kps": ["职业素养"]},
                ],
                "knowledge_points": [
                    {"kp_id": "k1", "title": "CAP 理论", "domain": "分布式基础",
                     "hit": False, "best_score": 20.0},
                    {"kp_id": "k2", "title": "幂等设计", "domain": "分布式基础",
                     "hit": False, "best_score": 35.0},
                ],
            },
        },
    }
    payload.update(overrides)
    return payload


_DIM_FIELDS = ("total_score", "tech_score", "logic_score", "expression_score",
               "adaptability_score", "match_score")


def test_engine_report_converts_one_to_five_into_hundred():
    report = build_engine_report("backend", [], _finish_payload())
    # 引擎是 1~5 分制，本项目是 0~100 —— 换算漏了会让六个分数全部缩水 20 倍
    assert report["tech_score"] == 80.0        # 4.0 × 20
    assert report["expression_score"] == 90.0  # 4.5 × 20
    assert report["adaptability_score"] == 40.0
    assert report["total_score"] == 70.0
    for key in _DIM_FIELDS:
        assert 0.0 <= report[key] <= 100.0


def test_engine_report_derives_three_columns():
    report = build_engine_report("backend", [], _finish_payload())
    assert any("技术水平" in item for item in report["strengths"])
    assert any("这道题答得最扎实。" in item for item in report["strengths"])
    assert any("应变能力" in item for item in report["weaknesses"])
    assert any("分布式基础" in item for item in report["weaknesses"])
    # 「未归类」是 KG 不可用时的兜底桶，不能当成薄弱领域报给考生
    assert not any("未归类" in item for item in report["weaknesses"])
    assert any("CAP 理论" in item for item in report["suggestions"])
    for key in ("strengths", "weaknesses", "suggestions"):
        assert report[key] and len(report[key]) <= 4


def test_engine_report_fills_missing_dimension_with_average():
    payload = _finish_payload()
    payload["five_dim_avg"]["应变能力"] = None      # 引擎的 null 是「没有数据」，不是 0 分
    report = build_engine_report("backend", [], payload)
    assert report["adaptability_score"] == 75.0     # (80+60+90+70)/4，不是 0


def test_engine_report_ignores_out_of_range_and_bool():
    payload = _finish_payload()
    payload["five_dim_avg"]["技术水平"] = 99.0      # 越界（引擎应是 1~5）
    payload["five_dim_avg"]["逻辑思维"] = True      # bool 是 int 子类，别当 1 分
    report = build_engine_report("backend", [], payload)
    # 两者都按缺失处理 → 被其余三维（90 / 40 / 70）的均值 66.7 回填
    assert report["tech_score"] == 66.7
    assert report["logic_score"] == 66.7


def test_engine_report_falls_back_when_nothing_scored():
    payload = _finish_payload()
    payload["five_dim_avg"] = dict.fromkeys(payload["five_dim_avg"], None)
    payload["total_score_100"] = None
    qa_list = [{"round": 1, "question": "题目", "answer": "我的回答" * 20, "audio_url": None}]
    report = build_engine_report("backend", qa_list, payload)
    for key in _DIM_FIELDS:
        assert 0.0 <= report[key] <= 100.0   # 兜底报告也必须满足 NOT NULL 与取值范围
    assert report["summary"]
    assert report["suggestions"]


def test_engine_meta_keeps_notes_out_of_summary():
    payload = _finish_payload(partial=True, notes=["本场换过 1 题（原因：考生明说没接触过）"])
    report = build_engine_report("backend", [], payload)
    meta = build_engine_meta(payload)
    assert "换过" not in report["summary"]          # notes 是内部口径，不污染考生文案
    assert meta["notes"] == payload["notes"]        # 只做留痕
    assert meta["engine"] == "a11"
    assert meta["partial"] is True
    assert meta["session_id"] == payload["session_id"]


# ============================================================
# 引擎链路流程（假适配器，不打真服务）
# ============================================================
class _FakeEngine:
    """按脚本走的假引擎：第 1 题追问一次，第 2 题答完即收尾"""

    def __init__(self, total: int = 2) -> None:
        self.total = total
        self.asked = 0
        self.turns = 0

    async def is_ready(self, **_) -> bool:
        return True

    async def unavailable_reason(self) -> str:
        return ""

    async def start(self, position: str) -> dict:
        return {"session_id": "0a1b2c3d"}

    async def next_question(self, session_id: str) -> dict:
        self.asked += 1
        if self.asked > self.total:
            return {"finished": True, "q_index": self.asked}
        return {"finished": False, "q_index": self.asked,
                "question": f"第 {self.asked} 道题：请讲讲你的理解。"}

    async def answer(self, session_id: str, text: str) -> dict:
        self.turns += 1
        follow_up = self.turns == 1     # 只在第一题追问一次
        return {
            "reply": "那你再展开说说实现细节？",
            "follow_up": follow_up,
            "action": "L1" if follow_up else "close",
            "q_index": self.asked,
            "swapped": False,
            "done": {"follow_up": follow_up},
        }

    async def finish(self, session_id: str) -> dict:
        return _finish_payload()


@pytest.fixture
def engine_mode(monkeypatch):
    """开引擎开关 + 换假适配器"""
    from app.api import interviews as interviews_api

    fake = _FakeEngine()
    monkeypatch.setattr(settings, "DIALOGUE_ENGINE", "a11")
    monkeypatch.setattr(interviews_api, "get_dialogue_adapter", lambda: fake)
    return fake


async def test_engine_flow_mirrors_rounds_and_finishes(client: AsyncClient, engine_mode):
    headers = await _auth_headers(client, "flow")

    start = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
    assert start.status_code == 200
    data = start.json()["data"]
    interview_id = data["interview"]["id"]
    assert data["question"] == "第 1 道题：请讲讲你的理解。"

    # 第一次作答 → 引擎决定追问：题号不推进，追问文本就是前端要展示的下一条
    resp = await client.post(
        f"{BASE}/interviews/{interview_id}/answers",
        json={"answer": "我会从原理、实现与取舍三个层面来讲。"},
        headers=headers,
    )
    body = resp.json()["data"]
    assert body["finished"] is False
    assert body["next_question"] == "那你再展开说说实现细节？"
    assert body["interview"]["current_round"] == 1

    detail = (await client.get(f"{BASE}/interviews/{interview_id}", headers=headers)).json()["data"]
    assert len(detail["qa_records"]) == 1
    # 题面必须保持题库原题面逐字不变（学习计划靠它反查题库），追问只进 engine_turns
    assert detail["qa_records"][0]["question"] == "第 1 道题：请讲讲你的理解。"

    async with async_session() as session:
        turns = (await session.execute(
            select(QARecord.engine_turns).where(QARecord.interview_id == interview_id)
        )).scalars().all()
    assert turns[0] and turns[0][0]["reply"] == "那你再展开说说实现细节？"

    # 第二次作答 → 本题收尾 → 引擎出新题
    body = (await client.post(
        f"{BASE}/interviews/{interview_id}/answers",
        json={"answer": "实现上用读写分离加缓存。"}, headers=headers,
    )).json()["data"]
    assert body["finished"] is False
    assert body["next_question"] == "第 2 道题：请讲讲你的理解。"
    assert body["interview"]["current_round"] == 2

    # 第三次作答 → 引擎收尾 → 自动出报告
    body = (await client.post(
        f"{BASE}/interviews/{interview_id}/answers",
        json={"answer": "最后补充一下取舍。"}, headers=headers,
    )).json()["data"]
    assert body["finished"] is True
    report = body["report"]
    assert report["interview_id"] == interview_id
    for key in ("total_score", "tech_score", "logic_score",
                "expression_score", "adaptability_score", "match_score"):
        assert 0.0 <= report[key] <= 100.0
    assert report["strengths"] and report["weaknesses"] and report["suggestions"]

    detail = (await client.get(f"{BASE}/interviews/{interview_id}", headers=headers)).json()["data"]
    assert detail["status"] == "finished"
    assert [qa["round"] for qa in detail["qa_records"]] == [1, 2]


async def test_engine_not_ready_blocks_start_and_leaves_no_session(client: AsyncClient, monkeypatch):
    from app.api import interviews as interviews_api

    class _DeadEngine:
        async def is_ready(self, **_) -> bool:
            return False

        async def unavailable_reason(self) -> str:
            return "连不上对话层服务 http://localhost:8005"

    monkeypatch.setattr(settings, "DIALOGUE_ENGINE", "a11")
    monkeypatch.setattr(interviews_api, "get_dialogue_adapter", _DeadEngine)

    headers = await _auth_headers(client, "dead")
    resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
    assert resp.status_code == 503
    assert resp.json()["code"] == 50300     # 明确报「依赖不可用」，不是 500

    # 门禁在建会话之前 —— 不该留下一个 in_progress 却跑不动的空会话
    listed = (await client.get(f"{BASE}/interviews", headers=headers)).json()["data"]
    assert listed == []


async def test_config_reports_engine_totals(client: AsyncClient, engine_mode):
    headers = await _auth_headers(client, "config")
    cfg = (await client.get(f"{BASE}/config", headers=headers)).json()["data"]
    assert cfg["engine"] == "a11"
    assert cfg["total_rounds"] == settings.DIALOGUE_ENGINE_TOTAL_QUESTIONS


async def test_growth_carries_engine_and_can_filter(client: AsyncClient, monkeypatch):
    """成长曲线带链路标识且可按链路筛选：两种口径不是同一把尺子，不能混着比"""
    from app.api import interviews as interviews_api

    headers = await _auth_headers(client, "growth")

    # 第一场：原链路（引擎开关此刻是关的）
    d = (await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)).json()["data"]
    std_id = d["interview"]["id"]
    await client.post(
        f"{BASE}/interviews/{std_id}/answers",
        json={"answer": "原链路的回答。" * 10}, headers=headers,
    )
    await client.post(f"{BASE}/interviews/{std_id}/finish", headers=headers)

    # 第二场：引擎链路（同一实例，适配器在生产里也是单例）
    fake = _FakeEngine()
    monkeypatch.setattr(settings, "DIALOGUE_ENGINE", "a11")
    monkeypatch.setattr(interviews_api, "get_dialogue_adapter", lambda: fake)
    d = (await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)).json()["data"]
    eng_id = d["interview"]["id"]
    for _ in range(10):
        body = (await client.post(
            f"{BASE}/interviews/{eng_id}/answers",
            json={"answer": "引擎链路的回答。"}, headers=headers,
        )).json()["data"]
        if body["finished"]:
            break

    points = (await client.get(f"{BASE}/reports/growth", headers=headers)).json()["data"]
    by_id = {p["interview_id"]: p for p in points}
    assert by_id[std_id]["engine"] == ""
    assert by_id[eng_id]["engine"] == "a11"

    only_std = (await client.get(f"{BASE}/reports/growth?engine=standard", headers=headers)).json()["data"]
    only_eng = (await client.get(f"{BASE}/reports/growth?engine=a11", headers=headers)).json()["data"]
    assert [p["interview_id"] for p in only_std] == [std_id]
    assert [p["interview_id"] for p in only_eng] == [eng_id]
    # 非法值不报错，返回空序列（与 position 参数的既有口径一致）
    assert (await client.get(f"{BASE}/reports/growth?engine=nope", headers=headers)).json()["data"] == []
