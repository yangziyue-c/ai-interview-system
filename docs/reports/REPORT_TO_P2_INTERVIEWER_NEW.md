# 给 2 号（AI 专项）· 面试官算法 V5 重做说明

> 背景：知识库由 V4（`题库/*.xlsx`，451 题）换代到 V5（`backend/rag/数据/*-v5.json`，5012 题 / 5 岗位）。
> 数据结构变了，原算法（`backend/interviewer/question_bank.py`）**无法直接跑在新数据上**，
> 1 号据此重做了算法，落在 **`backend/interviewer_new/`**。
>
> 本文回答四件事：**为什么改 / 为什么这么改 / 具体怎么用 / 之后怎么拓展**。

---

## 一、为什么必须改（三个硬伤，均有实测依据）

### 硬伤 1：追问素材的存储形态变了，119 行解析层整体失效

| | V4（旧） | V5（新） |
|---|---|---|
| 追问存放 | 全挤在一个字段 `follow_up_triggers` 里 | **拆成 4 个独立字段**：`follow_up_l1` / `l2` / `l3` / `fallback_strategy` |
| 格式 | `【L1-触发追问】① 若提到"hashCode" → 追问：…` 自由文本，实测有 6 种措辞变体 | `[触发] 条件` + `[追问] 文本`，**100% 规整**（5012/5012 实测） |

旧算法为此写了 119 行正则兼容层（`_SECTION_MARKERS`、`_L1_TRIGGER_RE`、`_split_arrow`、
`_parse_l1_part` 及 5 个前缀正则）。V5 把这些信息**前置到数据生产端**了，这层代码全部作废。

### 硬伤 2：L1 触发机制在新数据下命中率仅约 66%

旧算法的 L1 靠**关键词子串匹配**：`keyword.lower() in answer.lower()`。

但 V5 的 L1 触发条件**全是描述式**（实测 **0/5012** 是关键词式）：

```
[触发] 回答缺乏细节时触发          ← 442 条，最高频
[触发] 答出基本思路时触发          ← 285 条
[触发] 候选人回答偏笼统时触发
```

**后果（最严重）**：匹配永不命中 →
- 考生答得好 → `candidates` 为空 → **直接换新题**，追问链根本不启动
- 面试退化成「连问 7 道互不相关的题」，深度考察能力丧失

### 硬伤 3：V5 没有「收尾交流」阶段，收尾题池必然为空

V5 只有 3 个阶段：`开场热身`(1782) / `核心考察`(2800) / `深度压轴`(430)。

旧算法在 round 6/7 强制选 `interview_stage="收尾交流"` 的题（V4 有 45 道）→ **V5 池空** →
`pick_next` 返回 `None` → 面试**降级到 Mock 通用模板**。

> 讽刺的是：旧算法当初花大力气修的就是「收尾题永不出现」（0/2700 场模拟），
> 换数据后这个修复会以另一种形式失效。

---

## 二、为什么这么改（设计取舍）

### 2.1 保留：决策骨架原样不动

旧算法的**决策逻辑**是经过两轮审查 + 2700 场模拟验证的，与数据格式无关，全部保留：

| 机制 | 说明 |
|---|---|
| 锚点定位 | `find_anchor_question`：从 history 尾部向前找最近一条**题库题干原文**（精确匹配，非包含匹配） |
| 层级阶梯 | 锚点后已追问次数 n：`0→L1` / `1→L2` / `2→L3` / `≥3→换新题` |
| 收尾窗口 | `round >= MAX_FOLLOW_UP_ROUNDS`(6) 即第 6/7 轮，强制换新题 |
| 开场题不做锚点追问 | 否则会挤掉「核心考察」阶段（旧版实测得出） |
| 笼统判定 | `is_vague_answer`：<20 字或含 12 个露怯短语；刻意排除「简单/基本/大概」与裸「不会」 |
| 追问去重范围 | 仅本锚点链内（跨题共享的降级话术不互相排挤） |
| `avoid_hard` | 连续露怯者换新题时跳过深度压轴 |

**接口签名也保持不变**，`app/adapters/ai_interviewer.py` 只改了 import 路径：

```python
pick_next(session, position, round_no, history, is_follow_up) -> str | None
```

### 2.2 重写：三个适配点

**① 追问素材直读字段**（替代正则解析）

```python
def extract_follow_up_text(field: str) -> str:
    """取最后一个 [追问] 行的正文"""
    lines = [ln.strip() for ln in (field or "").splitlines()
             if ln.strip().startswith("[追问]")]
    return lines[-1][len("[追问]"):].strip() if lines else ""
```

> **为什么取「最后一个」而不是「第一个」**：V5 的 L3 字段有 **31.1%**（1558/5012）的题是这样：
> ```
> [触发] 本题为easy难度，一般不触达L3；若考生表现优异可酌情触发以下追问。   ← 元信息
> [触发] 考生答出进阶得分点时触发                                      ← 真触发条件
> [追问] 在实际项目中你用过JVM吗？…                                    ← 要取这行
> ```
> 取最后一个天然跳过元信息；L1/L2 恒为 2 行，同样适用。

**② L1 触发改语义分流**（替代关键词匹配）

```python
if follow_count == 0:
    if is_vague_answer(answer):
        candidates = [anchor.fallback_strategy]      # 完全答不出 → 降级引导话术
    else:
        candidates = [extract_follow_up_text(anchor.follow_up_l1)]   # 否则 → L1 追问
```

> **依据**：V5 的 L1 触发条件措辞虽多（"回答缺乏细节""答出基本思路""回答偏笼统"…），
> 但**语义高度一致**——都是「答了，但不完美，需要往下挖」。因此用统一的笼统判定分流：
> 真答不出（露怯）才降级，其余一律进入 L1。
> **效果**：追问链触达率 **66% → 100%**（200 场 × 5 岗位仿真实测）。

**③ 收尾题池改按题型选**（替代按阶段选）

```python
def pick_closing_question(questions, asked):
    pool = [q for q in questions
            if q.category == CLOSING_CATEGORY and q.question not in asked]
    return random.choice(pool) if pool else None
```

> **依据**：V4 的 45 道收尾题 **100% 是「行为面试」类**；V5 对应的是「行为素质题」（每岗 65~214 道），
> 题干形如「请分享一次你…的经历」，定位完全一致。不限定阶段以扩大题池。

### 2.3 一个刻意的不改动

`QUESTION_STAGES` 词表改成了 V5 的 3 个值，但新算法**按名引用**而非顺序解包：

```python
STAGE_OPENING = "开场热身"    # 而不是 STAGE_OPENING, STAGE_CORE, ... = QUESTION_STAGES
STAGE_CORE = "核心考察"
STAGE_DEEP = "深度压轴"
```

**原因**：顺序解包在词表增删值时会**静默错位**（旧算法的脆弱点）。按名引用则报错可见。
`tests/test_question_bank.py::TestPositionConstants` 有断言守护两处一致。

---

## 三、具体怎么用

### 3.1 模块位置与调用链

```
backend/interviewer_new/
├── __init__.py
├── question_bank.py     ← 算法本体（约 230 行）
└── README.md            ← 算法速览 + 与旧版差异表

调用链：app/api/interviews.py
          → app/adapters/ai_interviewer.py::_generate_via_bank
            → interviewer_new.question_bank.pick_next
```

数据源优先级（`ai_interviewer.py`）：

```
① 题库策略(interviewer_new) → ② RAG 语义检索(8003) → ③ 外部服务 → ④ LLM 直连 → ⑤ 内置 Mock
   任一级失败/未命中自动落下一级，面试流程永不中断
```

### 3.2 字段依赖（改动时务必对照）

`questions_of_position` 用 `load_only` 只投影 8 列（其余是长文本，全量加载会浪费数 MB）：

| 列 | 用途 |
|---|---|
| `question` | 出题文本 + 锚点索引键 + `asked` 去重键 |
| `interview_stage` | 开场题筛选（`开场热身`）、开场题排除锚点 |
| `difficulty` | 开场题要求 `easy` |
| `category` | **收尾题筛选**（`行为素质题`） |
| `follow_up_l1` / `l2` / `l3` | 三级追问素材 |
| `fallback_strategy` | 降级引导话术 |

### 3.3 自测

```bash
cd backend
<ai_interview 的 python.exe> -m pytest tests/test_question_bank.py -q     # 37 个用例
<ai_interview 的 python.exe> -m pytest -q                                  # 全量 66 个
```

**效果度量**（改动算法后必跑）：

```bash
<ai_interview 的 python.exe> -m scripts.simulate_interview --rounds 200
```

判据（当前基线，5 岗位 × 400 场）：
- **Mock 兜底 0 次**（题库策略不该落到 Mock）
- **收尾题出现 800 次/岗位**（= 400 场 × 2 轮，100%）
- 追问链 L1 → L2 → L3 逐级触达

---

## 四、之后怎么拓展

按"改动成本从低到高"排列，每条给出**改哪里 + 测试怎么写**。

### 拓展 1：新增一级追问（L4）

**场景**：想支持四层追问（如「跨题综合」）。

1. `app/models/question.py`：加列 `follow_up_l4`，并重建表（`import_question_bank --rebuild --yes`）
2. `interviewer_new/question_bank.py`：
   - `questions_of_position` 的 `load_only` 加 `Question.follow_up_l4`
   - `_pick_follow_up` 的层级阶梯加一档：
     ```python
     elif follow_count in (1, 2, 3):
         field = {1: anchor.follow_up_l2, 2: anchor.follow_up_l3,
                  3: anchor.follow_up_l4}[follow_count]
     ```
   - `max` 判定同步（`follow_count >= 4 → 换新题`）
3. 测试：`TestPickNextMatrix` 加一个 `test_l4_progression`，构造 `follow_count=3` 的 history 断言返回 L4 文本

> ⚠️ 注意 `MAX_FOLLOW_UP_ROUNDS`(6) 与总轮数的关系：`总轮数 = 1 + MAX_FOLLOW_UP_ROUNDS`。
> 加一层追问意味着锚点链更长，需评估收尾窗口是否还够（收尾是**按轮次**强制，不是按链长）。

### 拓展 2：替换笼统判定策略

**场景**：想接入 LLM 判断"回答是否够深入"，而非长度+短语。

1. `question_bank.py` 的 `is_vague_answer` 是**全项目唯一口径**（Mock 追问也复用），
   替换时保持签名 `(text: str) -> bool`，或改成可注入的策略对象
2. ⚠️ 注意它被两处复用：`ai_interviewer.py` 的 Mock 路径、`simulate_interview.py`
3. 测试：`TestIsVagueAnswer` 的 4 个用例是**行为契约**（尤其 `test_buhui_negation_not_vague`
   那条「不会产生脏读」不误判），改判定逻辑后必须全过

### 拓展 3：让 RAG 参与出题（改变优先级）

**现状**：RAG（`POST /rag/search`）挂在数据源链**第 2 级**，但 V5 题库覆盖 5 岗位共 5012 题，
题库策略极少返回 `None`，所以这一级多数场次不会被调用——它是「题库缺失时的语义兜底」。

**若要让它主动参与出题**（如"根据考生回答动态选相关题"）：

1. 在 `_pick_follow_up` 的换新题分支里插一次 RAG 调用：
   ```python
   # 示例：换新题时优先用 RAG 找与考生回答语义相关的题
   from app.adapters.ai_interviewer import get_interviewer_adapter
   rag_q = await get_interviewer_adapter()._generate_via_rag(position, round_no, history, is_follow_up)
   if rag_q:
       return rag_q
   ```
   ⚠️ 但 `question_bank` 目前是**纯函数 + 无外部依赖**的设计（便于单测），
   引入网络调用会破坏这一点。**更推荐**：把 RAG 作为 adapter 层的独立数据源
   （见 `_generate_via_rag`），在 `generate_question` 里调整优先级顺序即可，算法层保持纯净。
2. 测试：`TestQuestionBankFlow` 加一个 mock 掉 RAG 响应的集成用例

### 拓展 4：新增岗位

1. `backend/rag/数据/` 放入新岗位的 `{前缀}-v5.json`（18 字段格式见 `REPORT_TO_P5.md`）
2. `scripts/import_question_bank.py` 的 `SOURCE_FILES` 加一行 `("新前缀", "新code")`，
   `POSITION_MAP` 加岗位全名 → code
3. `app/models/position.py` 的 `DEFAULT_POSITIONS` 加岗位（老库由 `_align_positions` 自动补插）
4. `app/core/evaluation_weights.py` 的 `POSITION_CONFIG` 加权重，
   `评估维度.csv` 加列——否则 `test_weights_match_csv` 会挂
5. `ai_interviewer.py` 的 `_POSITION_LABELS` 与 `_RAG_JOB_LABELS` 各加一行
6. 验证：`python -m scripts.import_question_bank --rebuild --yes` + `pytest`

### 拓展 5：调整层级推进策略（按回答质量而非追问次数）

**现状**：层级由"追问了几次"决定（n=0/1/2），简单可靠。

**可探索**：按回答质量动态跳级（如答得特别好时 L1 跳过直接 L2）。

改法：`_pick_follow_up` 里把 `follow_count` 的映射改成函数：

```python
def _next_level(anchor, answer: str, follow_count: int) -> str:
    """返回该读哪个字段"""
    if follow_count == 0:
        return "fallback_strategy" if is_vague_answer(answer) else "follow_up_l1"
    ...
```

测试：`TestPickNextMatrix` 的矩阵用例正是为这类策略变化准备的——每个决策分支一个用例，
改策略时**先改测试期望、再改实现**，矩阵会自动告诉你影响了哪些场景。

---

## 五、与旧版的行为对照（回归时对照这张表）

| 场景 | 旧算法（V4 数据） | 新算法（V5 数据） |
|---|---|---|
| 开场题 | `开场热身 + easy` 随机 | **相同** |
| 开场题后的追问 | 不做锚点追问，换新题 | **相同** |
| 考生答得好 | 关键词命中才追问（V5 下≈不追问） | **一定发 L1**（100%） |
| 考生答不出 | 笼统 → 降级话术 | **相同**（但触发条件更准） |
| 已追问 1 次 | 发 L2 | **相同** |
| 已追问 2 次 | 发 L3 | **相同** |
| 已追问 ≥3 次 | 换新题 | **相同** |
| round 6/7 | 选「收尾交流」阶段题（V5 下池空 → Mock） | **选「行为素质题」**（池 65~214 道/岗） |
| round≥3 换新题 | 优先「深度考察」 | **优先「深度压轴」**（V5 的阶段名） |
| 连续露怯 | 跳过深度题 | **相同** |

---

**有疑问或要改算法，直接动 `backend/interviewer_new/`（该目录已移交 2 号）。**
旧版 `backend/interviewer/` 已冻结留档，不再被任何代码引用，可安全忽略。
