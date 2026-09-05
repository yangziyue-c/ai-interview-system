# P2 代码审查与整改清单（interviewwaibao）

> 审查时间：2026-09-04。审查对象：`interviewwaibao/` 目录交付的初步模拟面试算法。
> 接入契约与选题约定见 [REPORT_TO_P2.md](REPORT_TO_P2.md)，本文档只讲**代码问题与怎么改**。
>
> **总体结论**：策略骨架正确（题库驱动开场/追问/收尾 + 触发条件解析），
> 但代码残缺、只实现了 L1、存在多处 bug，当前**无法直接运行**。逐条整改后即可接入。

## 一、问题总览（按严重度）

| # | 位置 | 问题 | 严重度 |
| :--- | :--- | :--- | :---: |
| 1 | `ai_service.py` | 代码残缺：`create_session` / `ask_question` / `is_interview_over` / `save_question` 均未定义（`# ... 其他方法保持不变 ...` 占位），`main.py` 一调即 AttributeError | 致命 |
| 2 | `ai_service.py:73` | `follow_up` 仅在 try 块内赋值，`search_by_trigger` 抛异常后 `if follow_up is None:` 引用未定义变量 → NameError；107~116 行为死代码 | 高 |
| 3 | `rag_service.py:114` | 触发条件解析与题库 v13 真实格式不匹配：只解析 L1 关键词行，**L2/L3 未实现**；「③ 若回答笼统 → 追问」行解析不到；`_is_vague_answer` 用「简单/基本/大概」误伤正常回答（如"简单工厂模式"） | 高 |
| 4 | `ai_service.py` | **追问链只能走一层**：L1 追问文本（如"HashMap中key的hash计算过程"）不是独立题目行，下一轮 `get_question_by_text` 匹配不到 → L2/L3 永远触发不了 | 高 |
| 5 | `main.py` + `tts_service.py` | `/interview/stream`（SSE）+ edge_tts 在线合成与主项目 REST 契约不符，且同步阻塞线程、音频文件无限累积。主项目只需 `POST /generate` | 中 |
| 6 | `rag_service.py` | pandas 直接读 xlsx（全量 DataFrame）；主项目已入库 `questions` 表，走题库 API 即可 | 中 |
| 7 | 目录卫生 | `.env` 含 DEEPSEEK_API_KEY、16 个 mp3、Python 3.14 的 `__pycache__`，均不应提交 git；环境对齐 `ai_interview`（Python 3.12） | 中 |

## 二、逐条修复建议

### 1. 删除残缺的流式面试接口（致命，最省事的修法）

主项目只调用 `POST /generate` 一个接口（契约见 [REPORT_TO_P2.md](REPORT_TO_P2.md)）。
`/interview/stream` 及其依赖的会话管理（`sessions`、`create_session`、`ask_question`、
`is_interview_over`、`save_question`、`iter_lines` 流式解析）**全部删除，不要补**——
补了也用不上，还多维护成本。

保留后的 `main.py` 骨架：

```python
app = FastAPI()
ai_service = AIService()          # 内部即 generate_question + 题库检索

@app.post("/generate")
async def generate_question(request: GenerateRequest):
    question = ai_service.generate_question(
        position=request.position,
        round_num=request.round,
        is_follow_up=request.is_follow_up,
        history=request.history,
    )
    return {"question": question}
```

`GenerateRequest` 字段必须与契约一致（`position` / `round` / `is_follow_up` / `history`，
删掉 `need_audio` —— 主项目不需要 TTS，语音是候选人录音上传，见第 5 条）。

### 2. `follow_up` 未定义 + 死代码

```python
def generate_question(self, position, round_num, is_follow_up, history):
    ...
    follow_up = None                     # ← 函数开头初始化，异常也不崩
    try:
        follow_up = self.rag.search_by_trigger(position, candidate_answer, history, question_row=question_row)
        if follow_up:
            return follow_up
    except Exception as e:
        print(f"⚠️ 追问匹配失败: {e}")

    # 匹配失败 → 收尾/换新题 → 兜底（107~116 行死代码删除，
    # 收尾判断只保留这一处）
    if round_num >= 6:
        row = self.rag.get_closing_question(position)
        if row is not None:
            return row["面试问题"]
    ...
    return FALLBACK_QUESTION
```

### 3. 触发条件解析：对齐 v13 四层真实格式

你现在的正则只匹配 `若提到"X" → 追问：Y`。题库 v13 真实格式（抽查 `Java后端…v13.xlsx`）是四段结构：

```
【L1-触发追问】根据候选人回答中的关键词触发
  ① 若提到"hashCode" → 追问：HashMap中key的hash计算过程
  ② 若提到"String" → 追问：String为什么设计为不可变
  ③ 若回答笼统/缺乏细节 → 追问：能否结合你实际项目中的经验，举一个具体的使用场景？

【L2-递进追问】在L1基础上进一步深入，考察实践深度
  ① 承接L1-①深入 → 在实际项目中这个知识点是如何应用的？能否举一个你踩过的坑？
  ② 承接L1-②深入 → 如果让你重新设计这个机制，你会做哪些改进？

【L3-极限追问】仅当候选人L1和L2回答流畅准确时使用，考察知识融会贯通
  → 综合场景：假设你需要设计一个高并发的缓存系统，……请从三个维度阐述。

【降级策略】当候选人回答困难或明显不熟悉时使用
  → 那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？
```

建议改为**按段解析**（段标题只匹配前缀 `【L1` / `【L2` / `【L3` / `降级策略`，别写死全称——题库措辞会微调）：

```python
@dataclass
class FollowUpPlan:
    l1: list[tuple[str, str]]   # [(触发关键词, 追问文本)]
    l1_vague: list[str]         # L1 中「若回答笼统/简洁/缺乏细节/只答理论」类兜底追问
    l2: list[str]               # L2 递进追问（按 ①② 顺序）
    l3: list[str]               # L3 极限追问
    fallback: list[str]         # 降级策略追问

def parse_follow_up_triggers(text: str) -> FollowUpPlan:
    # 逐行扫描，维护 current_section（l1/l2/l3/fallback）
    # L1 行（① 若提到"X" → 追问：Y）：
    #   正则 r'若提到["“](.+?)["”]\s*[→-]\s*追问[:：]\s*(.+)' → 加入 l1
    # L1 行（③ 若回答笼统/简洁/缺乏细节/只答理论 → 追问：Y）：
    #   正则 r'若(?:回答|只答)[^"“]*?(?:笼统|简洁|缺乏细节|缺少实践)' 命中 → 加入 l1_vague
    # L2 行（① 承接L1-①深入 → Y）：
    #   line.split("→", 1)[1] → 加入 l2
    # L3 / 降级行（→ Y）：
    #   line.split("→", 1)[1] → 分别加入 l3 / fallback
```

`_is_vague_answer` 去掉误伤词：

```python
def _is_vague_answer(text: str) -> bool:
    if not text or len(text.strip()) < 20:
        return True
    # 不要用「简单/基本/大概」——「简单工厂模式」「基本类型」会被误伤
    return any(w in text for w in ("不知道", "不清楚", "不太懂", "不了解", "没接触过", "忘记了", "不会"))
```

### 4. 追问链断链：锚点 + 层级推断（不用改表）

L1 的追问文本不是题库里的独立题目行，下一轮按文本找回原题必然失败。
改为**从 history 尾部往前找锚点**，用锚点之后的追问次数判断当前层级：

```python
def find_anchor(history, questions_of_position) -> tuple[Question | None, int]:
    """返回 (锚点题, 锚点之后已追问次数)"""
    follow_count = 0
    for msg in reversed(history):
        if msg["role"] == "candidate":
            continue
        row = match_question_by_text(questions_of_position, msg["content"])
        if row is not None:
            return row, follow_count      # 锚点题 + 其后追问数
        follow_count += 1                  # 该 interviewer 消息不在题库 → 它本身就是一次追问
    return None, 0
```

层级映射（结合 `parse_follow_up_triggers` 的结果）：

| follow_count | 层级 | 动作 |
| :---: | :---: | :--- |
| 0 | L1 | 关键词命中 → 对应追问；未命中且回答笼统 → `l1_vague[0]`；否则 `fallback[0]` |
| 1 | L2 | `l2[0]`（超界取第一条） |
| 2 | L3 | `l3[0]` |
| ≥3 / 无锚点 | 换新题 | `round>=6` → 收尾交流；`round>=3` → 深度考察（无则核心考察）；再不行 `fallback` |

追问文本保持去重（`history` 中已问过的 interviewer 内容不进题库重抽），沿用你现有 `asked` 集合即可。

### 5. 架构对齐：删 SSE 与 TTS

- 删除：`/interview/stream`、`/test-sse`、`tts_service.py`、`audio_files/` 目录、`edge_tts` 依赖。
- 主项目是 REST JSON；题目以文本下发，候选人录音由前端上传（`AnswerRequest.audio_url`），面试官题目不需要语音合成。
- `requirements.txt` 同步清理（`edge_tts`、`pandas` 删掉；`requests` 若用于调题库 API 则保留）。

### 6. 数据源切换：pandas 读 xlsx → 题库 API

题库已入库 `questions` 表（450 题），你的服务不需要碰 xlsx：

```
GET /api/v1/questions?position=backend&difficulty=easy&stage=开场热身&limit=20
```

- 先注册服务账号（如 `p2_service`），请求头带 `Authorization: Bearer <token>`（见 [REPORT_TO_P2.md](REPORT_TO_P2.md)）。
- `limit` 最大 100，超一页用 `offset` 翻页拉全；建议**启动时全量拉取岗位题目缓存到内存**（每岗 150 题），后续选题不再请求。
- 选题过滤：开场题 `stage=开场热身 & difficulty=easy`；收尾 `stage=收尾交流`；阶段推进按 `核心考察 → 深度考察`；追问素材用 `follow_up_triggers` 字段（解析见第 3 条）。
- 字段名以 API 返回为准（`position_code` / `question` / `difficulty` / `interview_stage` / `follow_up_triggers` …），不要沿用你 xlsx 的列名（如 `面试问题`）。

### 7. 目录与环境卫生

- `interviewwaibao/.env` 含密钥，**不要提交 git**；`audio_files/`、`__pycache__/` 删除或 gitignore。
- 开发环境用 `ai_interview`（Python 3.12）跑，与主项目一致；当前 `__pycache__` 是 Python 3.14 的产物。
- 交付后建议把服务代码放到自己的独立目录（如 `p2_service/` 或独立仓库），`interviewwaibao/` 这个临时目录清理掉。

## 三、验收自测清单

1. 本地起服务，`POST /generate`（`round=1, is_follow_up=false`）→ 返回开场热身 + easy 题
2. `round=2` 带 history（候选人回答含"hashCode"）→ 返回 L1 对应追问
3. 同一锚点连续追问 → 依次走 L2、L3，第 4 次追问自动换新题
4. `round=6/7` → 收尾交流题
5. 联调：`backend/.env` 配 `AI_INTERVIEWER_URL` → 主服务完整面试流程走通（7 轮后自动出报告）
6. 主项目侧回归：`cd backend && pytest`（不配 URL 时走内置 Mock，11 个用例应全绿——你的服务不影响主流程）
