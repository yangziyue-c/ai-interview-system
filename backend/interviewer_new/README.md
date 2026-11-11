# 面试官算法（V5 结构化数据源版）

> 数据源：`questions` 表（V5 交付包 **5012 题 / 5 岗位**）
> 调用链：`app/adapters/ai_interviewer.py` → 本目录 `pick_next`（最高优先级数据源）

## 算法速览

| 环节 | 规则 |
|---|---|
| 开场题（round 1） | `interview_stage="开场热身"` 且 `difficulty="easy"` 随机 |
| 追问锚点 | 从 history 尾部向前找最近一条题库题干原文（精确匹配，非包含匹配） |
| 层级推进 | 锚点之后已追问次数 n：`0→L1` / `1→L2` / `2→L3` / `≥3→换新题` |
| L1 触发 | 回答笼统（<20 字或含露怯短语）→ 降级引导话术；否则 → L1 追问 |
| 收尾窗口 | `round ≥ MAX_FOLLOW_UP_ROUNDS`(默认 6) 即第 6/7 轮，强制换新题 |
| 收尾题池 | `category="行为素质题"`（每岗 65~214 道） |
| 换新题阶段 | `round≥3` 且未连续露怯 → 优先「深度压轴」，池空落「核心考察」；否则「核心考察」 |
| 开场题不做锚点追问 | 否则会挤掉「核心考察」阶段（旧版实测得出） |

## 与旧版（`backend/interviewer/`）的差异

| | 旧版（V4 xlsx 源） | 本版（V5 结构化源） |
|---|---|---|
| 追问素材 | 正则解析 `follow_up_triggers` 混合文本<br>（119 行解析层、6 种格式变体兼容） | 直接读 `follow_up_l1/l2/l3`、`fallback_strategy` 四列 |
| L1 触发 | 关键词子串匹配，V5 的触发条件是描述式，实测命中率仅约 66% | 语义分流（`is_vague_answer`），命中率 100% |
| 收尾题池 | `interview_stage="收尾交流"`，V5 无此阶段，会池空并降级 Mock | `category="行为素质题"` |
| 阶段常量 | 4 个（含收尾交流），按顺序解包 | 3 个，按名引用（词表增删时不会静默错位） |

**刻意保留未变的部分**（经两轮审查 + 2700 场模拟验证）：锚点精确匹配机制、
层级阶梯、收尾窗口强制、笼统判定 `is_vague_answer` 口径。

## 自测

```bash
cd backend
<ai_interview 的 python.exe> -m pytest tests/test_question_bank.py -q
```

## 扩展指南

扩展点（新增追问层级、替换笼统判定、接入语义检索、新增岗位）的改法与测试写法，
详见 `docs/reports/REPORT_TO_P2_INTERVIEWER_NEW.md` 的「四、之后怎么拓展」。
