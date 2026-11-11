"""面试流程仿真：用真实题库跑 N 场完整面试，统计关键指标

用途：V5 换代后的**效果度量**（替代「凭感觉验证」），也是回归基线——
数据或算法改动后重跑，指标不应劣化。重点盯三个信号：

1. **收尾题出现率必须 100%**：V5 只有 3 个阶段（无「收尾交流」），若收尾题池
   为空会返回 None → 面试降级到 Mock 通用模板（旧算法在此处的已知 bug）。
2. **Mock 兜底必须 0 次**：题库策略是最高优先级数据源，有题就不该落 Mock。
3. **L1 追问触达率必须 100%**（答得好时）：V5 的触发条件是描述式，
   旧的关键词匹配机制命中率仅约 66%，这是本次重做算法的直接动因。

用法（必须在 backend 目录下）：
    <ai_interview 的 python.exe> -m scripts.simulate_interview            # 5 岗位 × 200 场
    <ai_interview 的 python.exe> -m scripts.simulate_interview --rounds 50
    <ai_interview 的 python.exe> -m scripts.simulate_interview --position backend
"""
import argparse
import asyncio
import sys
from collections import Counter

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Question
from app.models.question import QUESTION_STAGES
from interviewer_new import question_bank as qb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POSITIONS = ("backend", "frontend", "test_engineer", "algorithm", "system_design")

# 脚本化回答：模拟两类真实考生
GOOD_ANSWER = (
    "这块我的理解是：核心机制围绕数据组织与访问效率展开，实现上通常分三层——"
    "存储层负责持久化，缓存层扛热点，接口层做限流与降级；我在项目里按这个思路"
    "优化过读写路径，把 P99 从 800ms 压到 120ms，主要收益来自减少重复计算和批量合并。"
)
VAGUE_ANSWER = "不知道，没接触过这个，说不上来。"


async def _load_questions(session, position: str) -> list[Question]:
    """按岗位加载题目——复用出题侧的投影查询（只取决策用的 8 列）

    不在这里另写一份全列查询：全列会把得分点/校准锚点等 1~3KB 的长文本
    也读进内存，且加载列集与真实出题路径不一致会让「仿真通过」的证据变弱。
    """
    return await qb.questions_of_position(session, position)


def simulate_one(position: str, questions: list[Question],
                 answer_style: str, total_rounds: int) -> dict:
    """跑一场完整面试，返回逐轮分类统计

    用纯函数 `pick_next_from_questions` 而非 `pick_next`：仿真测的是**算法决策**
    （收尾题是否出现、追问链是否触达），不是 DB 往返；逐轮重载 2146 题会让
    N 场仿真慢到不可用。真实运行时每轮的加载开销另见 docs/reports。

    `by_stem` 在岗位循环外建一次并被 400 场复用——原实现在每轮里线性扫
    2146 题反查归属，占了整个跑批约三分之二的时间。
    """
    by_stem = {q.question.strip(): q for q in questions}
    history: list[dict] = []
    stats = {"rounds": 0, "none": 0, "kinds": Counter()}

    for rnd in range(1, total_rounds + 1):
        # 调用前先推断本轮归属（锚点 + 已追问次数），便于给返回结果分类
        _anchor, trailing = qb.find_anchor_question(questions, history)
        follow_count = len(trailing)

        text = qb.pick_next_from_questions(questions, rnd, history, rnd > 1)
        if text is None:
            stats["none"] += 1
            break
        stats["rounds"] += 1

        # 分类：命中题库题干 = 出题；否则 = 追问（含降级引导）
        q_obj = by_stem.get(text.strip())
        if q_obj is not None:
            if qb._in_closing_window(rnd) and q_obj.category == qb.CLOSING_CATEGORY:
                stats["kinds"]["收尾题"] += 1
            else:
                stats["kinds"][f"新题({q_obj.interview_stage})"] += 1
        else:
            level = {0: "L1", 1: "L2", 2: "L3"}.get(follow_count, "追问(超额)")
            stats["kinds"][f"追问{level}"] += 1

        history.append({"role": "interviewer", "content": text})
        ans = GOOD_ANSWER if answer_style == "good" else VAGUE_ANSWER
        history.append({"role": "candidate", "content": ans})

    return stats


async def run(rounds: int, only_position: str | None) -> None:
    positions = (only_position,) if only_position else POSITIONS
    print("=" * 78)
    print(f"面试流程仿真：{len(positions)} 岗位 × {rounds} 场 × 2 种考生（答得好 / 答不出）")
    print("=" * 78)

    failures: list[str] = []
    for position in positions:
        async with async_session() as session:
            questions = await _load_questions(session, position)
        if not questions:
            print(f"\n[{position}] 题库为空，跳过（真实库不应出现）")
            failures.append(f"{position}: 题库为空")
            continue

        agg = Counter()
        none_total = 0
        for style in ("good", "vague"):
            for _ in range(rounds):
                # 纯内存决策，不需要会话（原实现每场开一次却不用）
                r = simulate_one(position, questions, style, settings.total_rounds)
                agg.update(r["kinds"])
                none_total += r["none"]

        total_games = rounds * 2
        closing = agg["收尾题"]
        # 收尾窗口：第 6/7 轮各 1 次 → 每场期望 1 次收尾题（先答完追问链才进窗口）
        print(f"\n[{position}]  题库 {len(questions)} 题 / {total_games} 场")
        print(f"   收尾题出现 {closing} 次 | Mock 兜底 {none_total} 次")
        print("   逐轮分类：" + " | ".join(f"{k} {v}" for k, v in sorted(agg.items())))

        if none_total:
            failures.append(f"{position}: Mock 兜底 {none_total} 次（应为 0）")
        # 答得好的那 half 必须能走到收尾窗口，故收尾题至少出现 rounds 次
        if closing < rounds:
            failures.append(
                f"{position}: 收尾题仅 {closing} 次 < {rounds}（答得好的场次应每场至少 1 次）")

    print("\n" + "=" * 78)
    if failures:
        print("❌ 未达标：")
        for f in failures:
            print(f"   - {f}")
    else:
        print("✅ 全部达标：无 Mock 兜底，收尾题按预期出现")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(description="V5 面试流程仿真")
    ap.add_argument("--rounds", type=int, default=200, help="每岗位每类考生的场次数")
    ap.add_argument("--position", default=None, help="只测某个岗位（默认全部 5 个）")
    args = ap.parse_args()

    print(f"阶段词表：{QUESTION_STAGES}  收尾窗口：round >= {qb.settings.MAX_FOLLOW_UP_ROUNDS}")
    asyncio.run(run(args.rounds, args.position))


if __name__ == "__main__":
    main()
