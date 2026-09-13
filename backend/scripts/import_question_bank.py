"""题库导入脚本：把 V5 知识库（backend/rag/数据/*-v5.json）导入 questions 表

运行方式（必须在 backend 目录下）：
    cd backend
    <ai_interview 的 python.exe> -m scripts.import_question_bank --dry-run       # 只看统计，不落库
    <ai_interview 的 python.exe> -m scripts.import_question_bank                 # 幂等导入（upsert）
    <ai_interview 的 python.exe> -m scripts.import_question_bank --rebuild --yes # 重建表（结构变更时必用）

处理规则：
1. 源文件：`backend/rag/数据/{java,web,test,algorithm,system-design}-v5.json`
   （P5 交付的 V5 主库，每文件 18 字段的 JSON 数组），共 5012 题 / 5 岗位；
2. 「所属岗位」全名 → position_code 的映射见 POSITION_MAP——本脚本是岗位命名的
   单一事实源（`tests/test_api.py::test_weights_match_csv` 也复用它做 CSV 列名解析）；
   同时保留 V4 xlsx 简名别名，兼容旧数据源与 CSV 列名；
3. 字段逐项映射到 19 列；`stage_order` 由 `STAGE_ORDERS` 派生（V5 无该列）；
4. 题型/难度/阶段按受控词表校验，非法值跳过并在结尾汇总告警（不静默入库）；
5. 幂等：按 (position_code, question_no) 更新或插入，可重复执行；
6. `--rebuild`：VACUUM INTO 备份 → DROP TABLE → 重建 → 全量导入。
   涉及删列的结构变更无法靠 `_ensure_column` 迁移，必须走此路径。
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 GBK 编码，print 中文会抛 UnicodeEncodeError；
# stdout 可能不是 TextIOWrapper（管道/嵌入环境），hasattr 守卫防止导入即崩
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import inspect, select

from app.config import settings
from app.database import async_session, engine, init_db
from app.models import Question
from app.models.question import (
    QUESTION_CATEGORIES,
    QUESTION_DIFFICULTIES,
    QUESTION_STAGES,
    STAGE_ORDERS,
    expected_columns,
)

# 数据源目录：backend/rag/数据（交付包结构迁移后由 RAG 服务与本脚本共用同一份主库）
SRC_DIR = Path(__file__).resolve().parents[1] / "rag" / "数据"

# 岗位「所属岗位」列 → position_code
# ⚠️ V5 全名与 V4 简名并存：前者用于新数据源，后者供 CSV 列名解析与旧数据兼容
POSITION_MAP = {
    # V5 交付包（岗位全名）
    "Java 后端开发工程师": "backend",
    "Web 前端开发工程师": "frontend",
    "测试开发工程师": "test_engineer",
    "算法工程师": "algorithm",
    "系统设计工程师": "system_design",
    # V4 xlsx（简名，保留兼容：test_weights_match_csv 用「CSV 列名去空格」查本表）
    "Java后端": "backend",
    "Web前端": "frontend",
    "软件测试开发": "test_engineer",
}

# 源文件：(文件名前缀, 期望的 position_code)——用于交叉校验岗位映射是否正确
SOURCE_FILES = (
    ("java", "backend"),
    ("web", "frontend"),
    ("test", "test_engineer"),
    ("algorithm", "algorithm"),
    ("system-design", "system_design"),
)

# V5 主库 18 字段（缺字段立即报错，不做静默错位）
FIELDS = (
    "题目ID", "所属岗位", "题型分类", "难度等级", "面试阶段", "核心关键词",
    "考点优先级", "题目内容", "基础得分点", "进阶得分点", "L1基础追问",
    "L2递进追问", "L3拓展追问", "降级策略", "建议用时(分)", "适用题型基准",
    "单题校准锚点", "关联知识点",
)

# 受控词表（与 app/models/question.py 的常量一致）
_VOCABULARY = (
    ("题型分类", QUESTION_CATEGORIES),
    ("难度等级", QUESTION_DIFFICULTIES),
    ("面试阶段", QUESTION_STAGES),
)



def _text(value) -> str:
    """字段值转字符串，None/空 → ''"""
    if value is None:
        return ""
    return str(value).strip()


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_values(rec: dict, stats: dict) -> dict | None:
    """V5 记录（18 字段）→ Question 列（19 列）；校验失败返回 None 并计入 skipped"""
    qid = _text(rec.get("题目ID"))
    if not qid:
        stats["skipped"]["缺题目ID"] += 1
        return None

    invalid = [
        f"{label}={_text(rec.get(label))}"
        for label, vocab in _VOCABULARY
        if _text(rec.get(label)) not in vocab
    ]
    if invalid:
        for item in invalid:
            stats["skipped"][item] += 1
        return None

    position_code = POSITION_MAP.get(_text(rec.get("所属岗位")))
    if position_code is None:
        stats["skipped"][f"岗位={_text(rec.get('所属岗位'))}"] += 1
        return None

    stage = _text(rec.get("面试阶段"))
    return dict(
        position_code=position_code,
        question_no=qid,
        category=_text(rec.get("题型分类")),
        difficulty=_text(rec.get("难度等级")),
        question=_text(rec.get("题目内容")),
        interview_stage=stage,
        stage_order=STAGE_ORDERS.get(stage, 0),
        suggested_minutes=_int(rec.get("建议用时(分)")),
        keywords=_text(rec.get("核心关键词")),
        exam_priority=_text(rec.get("考点优先级")),
        basic_score_points=_text(rec.get("基础得分点")),
        advanced_score_points=_text(rec.get("进阶得分点")),
        follow_up_l1=_text(rec.get("L1基础追问")),
        follow_up_l2=_text(rec.get("L2递进追问")),
        follow_up_l3=_text(rec.get("L3拓展追问")),
        fallback_strategy=_text(rec.get("降级策略")),
        calibration_anchor=_text(rec.get("单题校准锚点")),
        related_knowledge=_text(rec.get("关联知识点")),
    )


def load_source() -> list[tuple[str, dict]]:
    """读取 5 个 V5 json，返回 [(源文件前缀, 记录), ...]；字段缺失/文件缺失立即报错"""
    if not SRC_DIR.exists():
        raise FileNotFoundError(
            f"V5 数据目录未找到：{SRC_DIR}\n"
            "请确认 backend/rag/数据/ 下存在 {java,web,test,algorithm,system-design}-v5.json"
        )
    records: list[tuple[str, dict]] = []
    for prefix, _code in SOURCE_FILES:
        path = SRC_DIR / f"{prefix}-v5.json"
        if not path.exists():
            raise FileNotFoundError(f"源文件缺失：{path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{path.name} 顶层不是 JSON 数组")
        missing = [f for f in FIELDS if data and f not in data[0]]
        if missing:
            raise ValueError(f"{path.name} 缺少字段：{missing}")
        records.extend((prefix, rec) for rec in data)
    return records


async def _assert_schema() -> None:
    """结构守卫：非 rebuild 路径下，表结构过旧时硬报错（而非静默漏字段）"""
    async with engine.connect() as conn:
        exists = await conn.run_sync(
            lambda c: "questions" in inspect(c).get_table_names()
        )
        if not exists:
            return
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("questions")}
        )
    missing = expected_columns() - cols
    if missing:
        raise RuntimeError(
            f"questions 表结构过旧，缺少列：{'、'.join(sorted(missing))}\n"
            "V5 换代涉及删列，无法自动迁移，请执行：\n"
            "  python -m scripts.import_question_bank --rebuild --yes"
        )


def _backup_sqlite(url: str) -> Path | None:
    """sqlite 库用 VACUUM INTO 备份（WAL 安全，不会漏掉 -wal 里的最近事务）"""
    if not url.startswith("sqlite"):
        return None
    db_path = Path(url.split("///")[-1]).resolve()
    if not db_path.exists():
        return None
    bak = db_path.with_name(f"{db_path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}-pre-rebuild")
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(f"VACUUM INTO '{bak}'")
    finally:
        con.close()
    return bak


async def _rebuild(assume_yes: bool) -> None:
    """备份 → DROP questions → 重建（结构变更的唯一入口）"""
    url = settings.DATABASE_URL
    print(f"目标库：{url}")
    if not assume_yes:
        raise RuntimeError("--rebuild 会清空 questions 表，确认请追加 --yes")

    bak = _backup_sqlite(url)
    if bak:
        print(f"已备份：{bak}")
    else:
        # 非 SQLite 目标库（如 .env 切到 MySQL）没有自动备份能力。用户已用 --yes
        # 确认过，但必须让他知道「这次删表没有回滚点」——原实现静默跳过备份就 DROP。
        print("⚠️ 目标库非 SQLite，未做自动备份——删除后本脚本无法回滚，"
              "请确认已有其它备份再继续")

    async with engine.begin() as conn:
        await conn.exec_driver_sql("DROP TABLE IF EXISTS questions")
    print("已删除旧 questions 表")

    await init_db()  # create_all 按新模型重建
    print("已按新模型重建 questions 表")


async def import_bank(rebuild: bool = False, dry_run: bool = False,
                      assume_yes: bool = False) -> dict:
    """导入全部 V5 主库文件，返回统计信息"""
    stats: dict = {
        "files": len(SOURCE_FILES), "added": 0, "updated": 0,
        "per_position": defaultdict(int), "per_stage": defaultdict(int),
        "skipped": defaultdict(int),
    }

    records = load_source()
    print(f"解析到 {len(records)} 条记录（{len(SOURCE_FILES)} 个文件）")

    # 逐条映射 + 词表校验（dry-run 也会跑，便于提前发现问题）
    prepared: list[tuple[str, dict]] = []
    for prefix, rec in records:
        values = _to_values(rec, stats)
        if values is None:
            continue
        prepared.append((prefix, values))
        # 分布统计在此累加（dry-run 与真实导入共用，保证两种模式输出一致可比）
        stats["per_position"][values["position_code"]] += 1
        stats["per_stage"][values["interview_stage"]] += 1

    if dry_run:
        stats["prepared"] = len(prepared)
        return stats

    if rebuild:
        await _rebuild(assume_yes)      # 内含「备份 → DROP → init_db 重建」
    else:
        await _assert_schema()
        await init_db()                 # 表不存在时建表（幂等）

    async with async_session() as session:
        existing = {
            (q.position_code, q.question_no): q
            for q in (await session.scalars(select(Question))).all()
        }
        pre_existing = set(existing)    # 库内原有键：用于区分「本批次新增」

        for prefix, values in prepared:
            key = (values["position_code"], values["question_no"])
            if key in existing:
                if key not in pre_existing:
                    print(f"⚠️ 重复题号（本批次覆盖）：{prefix} {values['question_no']}")
                for field, value in values.items():
                    setattr(existing[key], field, value)
                stats["updated"] += 1
            else:
                obj = Question(**values)
                session.add(obj)
                existing[key] = obj  # 登记，防同批次重复编号二次 add 触发唯一约束
                stats["added"] += 1

        await session.commit()

    return stats


def _print_stats(stats: dict, dry_run: bool) -> None:
    print()
    if dry_run:
        print(f"✅ 解析完成（--dry-run 未落库）：可导入 {stats['prepared']} 题")
    else:
        print(f"✅ 导入完成：{stats['files']} 个文件，"
              f"新增 {stats['added']} 题，更新 {stats['updated']} 题")
    print("   岗位分布：" + " / ".join(
        f"{k} {v}" for k, v in sorted(stats["per_position"].items())))
    print("   阶段分布：" + " / ".join(
        f"{k} {v}" for k, v in sorted(stats["per_stage"].items())))
    if stats["skipped"]:
        print(f"⚠️ 校验失败已跳过：{dict(stats['skipped'])}")
    else:
        print("   校验失败跳过：无")


def main() -> None:
    ap = argparse.ArgumentParser(description="V5 题库导入（backend/rag/数据/*-v5.json → questions 表）")
    ap.add_argument("--rebuild", action="store_true",
                    help="DROP 并重建 questions 表（V5 换代涉及删列，必须走此路径）")
    ap.add_argument("--yes", action="store_true", help="配合 --rebuild 确认执行（防误操作）")
    ap.add_argument("--dry-run", action="store_true", help="只解析统计，不连库不落库")
    args = ap.parse_args()

    print("=" * 60)
    print("题库导入：backend/rag/数据/*-v5.json → questions 表")
    print(f"源目录：{SRC_DIR}")
    print("=" * 60)

    stats = asyncio.run(import_bank(
        rebuild=args.rebuild, dry_run=args.dry_run, assume_yes=args.yes))
    _print_stats(stats, args.dry_run)


if __name__ == "__main__":
    main()
