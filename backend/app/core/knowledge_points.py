"""知识点素材解析（questions.related_knowledge → 结构化知识点）

字段格式（V5 交付包实测：5 个文件 9419 行全部恰好 3 段，零畸形零空值）：
    {知识点ID}|{名称}|{学习建议}，多行以 \\n 分隔
全库共 1513 个去重知识点。

主要使用者：`app/api/reports.py` 的学习计划接口——它把面试题干反查回题库，
从命中题目的该字段取出「待巩固知识点」与题库自带的学习建议原文。
"""
from typing import NamedTuple

# 考点优先级排序权重（值越小越优先）。取值来自题库「考点优先级」列，
# 该列不受导入脚本词表强校验，将来扩值时这里按「未知排最后」降级而非报错
# （推荐结果少排一条不会中断，报错会）。
PRIORITY_RANK = {"高频必考题": 0, "常规题": 1, "拓展题": 2}
DEFAULT_PRIORITY_RANK = len(PRIORITY_RANK)


class KpRef(NamedTuple):
    """一条关联知识点（related_knowledge 字段的一行）"""

    kp_id: str
    name: str
    advice: str


def extract_knowledge_points(raw: str | None) -> list[KpRef]:
    """解析 related_knowledge 字段 → 知识点列表

    解析口径照搬 `backend/rag/代码/01_generate_rag_data.py:97-110` 的
    `extract_knowledge_points`：那个实现位于 P5 交付包目录（不在 app 包内、
    无法 import），故在此复刻。口径必须一字不差——不足 2 段的行整行丢弃，
    第 3 段（学习建议）缺省为空串，空行跳过。
    """
    if not raw:
        return []
    points: list[KpRef] = []
    for line in str(raw).split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 2:
            points.append(
                KpRef(
                    kp_id=parts[0].strip(),
                    name=parts[1].strip(),
                    advice=parts[2].strip() if len(parts) >= 3 else "",
                )
            )
    return points


def knowledge_token(kp_id: str) -> str:
    """知识点 ID 的完整 token（ID 后紧跟竖线）——反查练习题必须用它

    不能只搜裸 ID：`java-backend-kp-318` 的 LIKE 会命中 `java-backend-kp-3180`。
    当前 1513 个 ID 两两之间没有前缀/子串关系（实测 0 冲突，裸搜暂时不会出错），
    但完整 token 是唯一的语义正确形式——数据里一旦出现数字前缀关系就会
    **静默串题**，而串题后的推荐结果看起来完全正常，比报错难发现得多。

    调用侧还须带 autoescape：知识点 ID 里确实含下划线
    （如 java_backend-kp-soft-40155），而 `_` 在 LIKE 中是单字符通配符。
    """
    return f"{kp_id}|"


def priority_rank(exam_priority: str) -> int:
    """考点优先级 → 排序权重（越小越优先），未知值排最后"""
    return PRIORITY_RANK.get(exam_priority, DEFAULT_PRIORITY_RANK)
