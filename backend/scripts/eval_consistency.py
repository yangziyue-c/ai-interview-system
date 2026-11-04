"""评分一致性实验：稳定性 + 校准锚点档位校验（答辩证据）

不是线上链路，离线跑一次、产出一份可放的报告。回答的是「评分准不准」：

1. **稳定性**：同一份答案重复评 N 次，看各维分的标准差。分差越大，说明
   同一个回答在两次面试里可能拿到差别很大的分。
2. **档位校验**：按题库的「单题校准锚点」构造优秀/合格/较差三档答案，
   看技术分与总分是否严格单调（优秀 > 合格 > 较差）。这验证的是评分相对
   排序的能力，不验证「绝对分数等于人工评分」——那需要人工标注集。

依赖两项外部能力：
- 大模型：按锚点生成三档答案（`LLM_BASE_URL` / `LLM_API_KEY`）；
- P3 评估服务：打分（`AI_EVALUATOR_URL`，默认本机 8002）。

用法（必须在 backend/ 目录下）：
    python -m scripts.eval_consistency
    python -m scripts.eval_consistency --position frontend --samples 2 --repeat 3

产出：docs/reports/EVAL_CONSISTENCY_<日期>.md
"""
import argparse
import asyncio
import json
import statistics
import sys
from datetime import date
from pathlib import Path

import httpx

from app.adapters.llm import LLMError, chat
from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
SRC_DIR = BACKEND_DIR / "rag" / "数据"

# (岗位 code, 源文件名前缀, 中文岗位名)
POSITIONS = (
    ("backend", "java", "Java 后端开发工程师"),
    ("frontend", "web", "Web 前端开发工程师"),
    ("test_engineer", "test", "测试开发工程师"),
    ("algorithm", "algorithm", "算法工程师"),
    ("system_design", "system-design", "系统设计工程师"),
)

# 三档答案的构造口径。low 刻意写成「概念含糊 + 遗漏」，不是胡言乱语——
# 评估器面对完全无关的答案会拒答或给极低分，那种对比说明不了档位分辨力。
LEVELS = {
    "high": "优秀：覆盖全部基础得分点与进阶得分点，讲清原理、取舍与适用边界，结构清晰。",
    "mid": "合格：覆盖基础得分点，提到部分进阶要点但不深入。",
    "low": "较差：只答表面定义，概念表述含糊，遗漏多数基础得分点。",
}

_ANSWER_PROMPT = """你是一位参加模拟面试的考生。请按「{level}」档的作答要求，回答下面这道题。

作答要求：{requirement}

面试题：{question}

基础得分点：
{basic}

进阶得分点：
{advanced}

单题校准锚点（评分口径，供你把握深度，不要复述原文）：
{anchor}

只输出你的回答正文，不要写「优秀档」「参考答案」之类的标签。"""


def _load_questions(position_code: str, file_prefix: str, limit: int) -> list[dict]:
    """从 V5 主库取题：只取有得分点与校准锚点的，三档答案才有依据可造"""
    path = SRC_DIR / f"{file_prefix}-v5.json"
    if not path.exists():
        raise FileNotFoundError(f"题库文件不存在：{path}")
    records = json.loads(path.read_text(encoding="utf-8"))
    picked: list[dict] = []
    for rec in records:
        if not (
            rec.get("基础得分点")
            and rec.get("进阶得分点")
            and rec.get("单题校准锚点")
        ):
            continue
        picked.append(
            {
                "question": str(rec.get("题目内容") or "").strip(),
                "basic": str(rec.get("基础得分点") or ""),
                "advanced": str(rec.get("进阶得分点") or ""),
                "anchor": str(rec.get("单题校准锚点") or ""),
                "question_no": str(rec.get("题目ID") or ""),
            }
        )
        if len(picked) >= limit:
            break
    if not picked:
        raise RuntimeError(f"{path.name} 里没有同时含基础/进阶得分点与校准锚点的题")
    return picked


async def _generate_answer(question: dict, level: str) -> str:
    prompt = _ANSWER_PROMPT.format(
        level=level,
        requirement=LEVELS[level],
        question=question["question"],
        basic=question["basic"],
        advanced=question["advanced"],
        anchor=question["anchor"],
    )
    return await chat(
        [
            {"role": "system", "content": "你正在参加一场技术面试，只输出回答正文。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,  # 生成答案要稳定，避免同一档每次内容差异过大
    )


def _evaluator_url() -> str:
    return (settings.AI_EVALUATOR_URL or "http://localhost:8002").rstrip("/")


async def _health_ok(client: httpx.AsyncClient) -> bool:
    try:
        resp = await client.get(f"{_evaluator_url()}/health", timeout=5.0)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def _evaluate_once(
    client: httpx.AsyncClient, position_code: str, question: dict, answer: str
) -> dict:
    """调 P3 /evaluate 评一条问答，返回 5 维 + 总分

    position 传 **code**（backend/frontend/…）：主后端适配器与权重表
    （app/core/evaluation_weights.py）都按 code 取权重，传中文名会悄悄落到
    通用权重上——分数看起来正常，口径是错的。
    """
    payload = {
        "position": position_code,
        "qa_list": [
            {
                "round": 1,
                "question": question["question"],
                "answer": answer,
                "audio_url": None,
                "materials": {
                    "basic_score_points": question["basic"],
                    "advanced_score_points": question["advanced"],
                    "calibration_anchor": question["anchor"],
                },
            }
        ],
    }
    resp = await client.post(
        f"{_evaluator_url()}/evaluate",
        json=payload,
        timeout=settings.ADAPTER_TIMEOUT_SECONDS * 2,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "total_score": float(data["total_score"]),
        "tech_score": float(data["tech_score"]),
        "logic_score": float(data["logic_score"]),
        "expression_score": float(data["expression_score"]),
        "adaptability_score": float(data["adaptability_score"]),
        "match_score": float(data["match_score"]),
    }


def _std(values: list[float]) -> float:
    return round(statistics.pstdev(values), 1) if len(values) > 1 else 0.0


async def run(args: argparse.Namespace) -> int:
    if not settings.LLM_API_KEY or not settings.LLM_BASE_URL:
        print("错误：未配置大模型（LLM_BASE_URL / LLM_API_KEY），无法生成三档答案。", file=sys.stderr)
        return 2

    position = next((p for p in POSITIONS if p[0] == args.position), None)
    if position is None:
        print(f"错误：未知岗位 {args.position}，可选：{'/'.join(p[0] for p in POSITIONS)}", file=sys.stderr)
        return 2
    code, prefix, _ = position

    async with httpx.AsyncClient() as client:
        if not await _health_ok(client):
            print(
                f"错误：P3 评估服务不可用（{_evaluator_url()}/health）。"
                "请先启动 8002，或在 .env 配置 AI_EVALUATOR_URL。",
                file=sys.stderr,
            )
            return 2

        questions = _load_questions(code, prefix, args.samples)
        rows: list[dict] = []
        for index, question in enumerate(questions, 1):
            print(f"[{index}/{len(questions)}] {question['question_no']} {question['question'][:30]}…")
            scores_by_level: dict[str, list[dict]] = {}
            answers: dict[str, str] = {}
            for level in ("high", "mid", "low"):
                try:
                    answer = await _generate_answer(question, level)
                except LLMError as exc:
                    print(f"  生成 {level} 档答案失败：{exc}", file=sys.stderr)
                    return 3
                answers[level] = answer
                repeats = []
                for _ in range(args.repeat):
                    repeats.append(await _evaluate_once(client, code, question, answer))
                scores_by_level[level] = repeats

            rows.append(
                {
                    "question_no": question["question_no"],
                    "question": question["question"],
                    "scores": scores_by_level,
                    "answers": answers,
                }
            )

    report = _render_markdown(rows, args)
    out_path = PROJECT_DIR / "docs" / "reports" / f"EVAL_CONSISTENCY_{date.today():%Y%m%d}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\n报告已写入：{out_path}")
    print(_summary_line(rows))
    return 0


def _render_markdown(rows: list[dict], args: argparse.Namespace) -> str:
    lines: list[str] = [
        f"# 评分一致性实验报告（{date.today():%Y-%m-%d}）",
        "",
        "## 实验口径",
        "",
        f"- 岗位：{args.position}",
        f"- 题目数：{len(rows)}（题库中同时含基础/进阶得分点与校准锚点的题）",
        f"- 每份答案重复评分：{args.repeat} 次",
        f"- 评估服务：{_evaluator_url()}",
        "- 三档答案由大模型按「单题校准锚点」生成：优秀 / 合格 / 较差",
        "",
        "## 一、稳定性（同一答案重复评分的分差）",
        "",
        "| 题目 | 档位 | 总分均值 | 总分标准差 | 技术分标准差 | 最大极差 |",
        "| :--- | :--- | ---: | ---: | ---: | ---: |",
    ]
    all_std: list[float] = []
    tech_std: list[float] = []
    for row in rows:
        for level in ("high", "mid", "low"):
            scores = row["scores"][level]
            totals = [s["total_score"] for s in scores]
            techs = [s["tech_score"] for s in scores]
            std = _std(totals)
            all_std.append(std)
            tech_std.append(_std(techs))
            lines.append(
                f"| {row['question_no']} | {level} | {statistics.mean(totals):.1f} | "
                f"{std:.1f} | {_std(techs):.1f} | {max(totals) - min(totals):.1f} |"
            )

    monotonic = 0
    lines += [
        "",
        "## 二、校准锚点档位校验（优秀 > 合格 > 较差）",
        "",
        "| 题目 | 优秀总分 | 合格总分 | 较差总分 | 技术分单调 | 总分单调 |",
        "| :--- | ---: | ---: | ---: | :---: | :---: |",
    ]
    for row in rows:
        means = {
            level: statistics.mean(s["total_score"] for s in row["scores"][level])
            for level in ("high", "mid", "low")
        }
        tech_means = {
            level: statistics.mean(s["tech_score"] for s in row["scores"][level])
            for level in ("high", "mid", "low")
        }
        tech_ok = tech_means["high"] > tech_means["mid"] > tech_means["low"]
        total_ok = means["high"] > means["mid"] > means["low"]
        monotonic += int(tech_ok and total_ok)
        lines.append(
            f"| {row['question_no']} | {means['high']:.1f} | {means['mid']:.1f} | "
            f"{means['low']:.1f} | {'✓' if tech_ok else '✗'} | {'✓' if total_ok else '✗'} |"
        )

    lines += [
        "",
        "## 三、汇总",
        "",
        f"- 重复评分总分标准差均值：{statistics.mean(all_std):.1f} 分",
        f"- 技术分标准差均值：{statistics.mean(tech_std):.1f} 分",
        f"- 三档严格单调的题目：{monotonic}/{len(rows)}",
        "",
        "## 四、口径边界（答辩时要说清）",
        "",
        "- 本实验证明两件事：同一答案的评分波动可控；评分能把「优秀/合格/较差」按顺序排开。",
        "- 它**不证明**绝对分数与人工评分完全一致——那需要人工标注集，本次没有。",
        "- 三档答案由大模型按锚点生成，代表「典型的三档作答」，不等于真实考生分布。",
        "- P3 服务的 LLM 与生成答案的 LLM 若为同一模型族，档位判断可能偏乐观；",
        "  结论应按「相对排序有效」表述，不宜说「准确率 90%」这类绝对数字。",
    ]
    return "\n".join(lines) + "\n"


def _summary_line(rows: list[dict]) -> str:
    total_stds = [
        _std([s["total_score"] for s in row["scores"][level]])
        for row in rows
        for level in ("high", "mid", "low")
    ]
    monotonic = 0
    for row in rows:
        means = {
            level: statistics.mean(s["total_score"] for s in row["scores"][level])
            for level in ("high", "mid", "low")
        }
        monotonic += int(means["high"] > means["mid"] > means["low"])
    return (
        f"总分标准差均值 {statistics.mean(total_stds):.1f} 分；"
        f"三档单调 {monotonic}/{len(rows)} 道题。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="评分一致性实验（稳定性 + 锚点档位校验）")
    parser.add_argument("--position", default="backend", help="岗位 code（默认 backend）")
    parser.add_argument("--samples", type=int, default=2, help="抽取几道题（默认 2）")
    parser.add_argument("--repeat", type=int, default=3, help="每份答案重复评分次数（默认 3）")
    args = parser.parse_args()
    if args.samples < 1 or args.repeat < 1:
        parser.error("--samples 与 --repeat 必须为正整数")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
