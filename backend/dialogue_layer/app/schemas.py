# -*- coding: utf-8 -*-
"""
schemas.py · 接口契约（唯一出处）
============================================================
所有请求/响应模型都在这里，`app/api/interview.py` 只负责调用它们。
改接口先改这里，再看前端要不要跟。

兼容性约束（重要，改之前先读）：
现成的 `web/test_chat.html` 是照旧接口写的，它：
- POST /start  只传 {job}                     → intro 必须有默认值
- POST /next   传 {session_id, message: ""}   → message 必须有默认值
- POST /finish 传 {session_id, message: ""}   → 同上
- 读 /start 的  data.session_id / data.message
- 读 /next  的  data.finished / data.stage / data.q_index / data.total / data.question
- 读 /finish 的 data.five_dim_avg / data.total_score / data.weights / data.summary
  （weights 是**字符串**、summary 是**字符串**，不是对象 —— 别改类型）

所以要动的是「加法」：新增字段可以，改已有字段的名字或类型会让前端静默失效
（它读不到就是 undefined，不报错，最难看）。
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app import config


# ============================================================
# 通用
# ============================================================
class Loose(BaseModel):
    """允许透传额外字段的基类：模型当文档用，但不做字段过滤器。"""
    model_config = ConfigDict(extra="allow")


class SessionReq(Loose):
    """/next、/finish 共用的请求体（旧前端会多传一个空 message，必须收下）。"""
    session_id: str = Field(..., min_length=4, description="会话 ID")
    message: str = Field("", description="旧前端固定传空串；本服务不使用该字段")


# ============================================================
# GET /health
# ============================================================
class HealthResp(Loose):
    status: str = "ok"
    version: str = ""
    port: int = 0
    llm_mock: bool = False
    reranker_mock: bool = False
    llm_configured: bool = False
    model: str = ""
    device: str = ""
    bank_loaded: bool = False
    bank_sizes: dict[str, int] = Field(default_factory=dict)
    scorer_ready: bool = False
    jobs: list[str] = Field(default_factory=lambda: list(config.JOBS))
    # 由 SessionStore.stats() 展开
    sessions_active: int = 0
    sessions_finished: int = 0
    sessions_total: int = 0
    session_capacity: int = 0
    # ---- 知识图谱 / RAG（全部带默认值：老响应体仍能通过校验）----
    # ⚠️ enabled 与 ready 是**两个**字段，不能合成一个：enabled=False 是配置
    #    （A11_KG=0），ready=False 且 enabled=True 才是故障。混起来运维分不清
    #    「我没开」和「它坏了」。错误信息同理 —— 关掉时 error 是空串。
    kg_enabled: bool = False
    kg_ready: bool = False
    kg_error: str = ""
    kg_nodes: int = 0
    rag_enabled: bool = False
    rag_ready: bool = False
    rag_error: str = ""
    rag_model: str = ""
    # ---- 语音输入 / ASR（同款四键）----
    # ⚠️ 这里的三种组合含义不同，别混：
    #   asr_enabled=False                 → 没开（配置，A11_ASR=0）
    #   enabled=True, ready=False, error="" → **还没人用过它**（懒加载，正常）
    #   enabled=True, ready=False, error!="" → 真的坏了（模型没下载/内存不够）
    asr_enabled: bool = False
    asr_ready: bool = False
    asr_error: str = ""
    asr_model: str = ""
    # ---- 学习资源推荐（同款四键；这里没有懒加载，load_index() 是毫秒级的 JSON 读）----
    # resource_ready=False 且 error 非空 = 资源样例文件没找到/读不动 —— 它是**配置数据**，
    # 缺了不影响面试，只让 recommendations 退化成空列表（得分点级兜底仍在 blindspots 里）。
    resource_enabled: bool = False
    resource_ready: bool = False
    resource_error: str = ""
    resource_kps: int = 0
    # ---- 专项强化练习（4b，赛题 4b）----
    # 只有一个键：它不依赖任何外部数据，「开没开」就是全部信息。
    # 关掉时 POST /practice 返 503 practice_disabled，别的端点一律不受影响。
    practice_enabled: bool = False
    # ---- 成长档案（错题本 / 考点地图 / 历史成绩，赛题 4）----
    # 同款单键。它比 /practice 还不依赖外部数据（连题库都不碰：
    # 摘要是调用方传进来的），关掉时 POST /growth 返 503 growth_disabled，
    # 且 /finish 与 /result 的 `digest` 会变成 **null**（不是空对象）。
    growth_enabled: bool = False
    # ---- 复盘清单（给**考生**看的那一份，`/finish` 顶层新键 `review`）----
    # 同款单键。它不依赖任何外部数据（与 growth 一样只吃已经算出来的诊断），
    # 所以没有「就绪」一说；关掉时 `/finish` 与 `/result` 的 `review` 变成 **null**。
    # ⚠️ 与 `growth_enabled` 是**两个**开关：给考生的复盘不该被「给 1 号存档」
    #    那个开关连坐，反之亦然。
    review_enabled: bool = False
    # ---- 优秀回答范例 / 考点讲解（`POST /model_answer`，赛题任务要求 4a）----
    # 同款单键。⚠️ 它**还要**看上面那四个 `resource_*`：本键是「这个端点开没开」，
    # `resource_enabled`/`resource_ready` 是「材料源可用不可用」—— 两件事，
    # 关掉时返 503 model_answer_disabled，材料源不可用时返 503 resource_unavailable。
    model_answer_enabled: bool = False
    # ---- 面试官风格三档（F）+ 考生自述进 prompt（E），2026-09-25 ----
    # 同款单键（persona_styles 除外，见下）。两条都不依赖外部数据，
    # 关掉时**不报错、也不 503** —— 只是提示词里少一块：
    #   persona_enabled=false → 任何档都按 standard 跑，`/start` 回显生效值仍是 standard
    #   intro_enabled=false   → 自述不进 prompt，`/start` 的 `intro_read.enabled=false`
    # ⚠️ 这两条正是「不上 /health 就只能靠行为反推」的典型：关掉后响应里
    #    什么都不缺，只有提示词少一块 —— 光看响应**推不出来**。
    persona_enabled: bool = False
    # 可选档名。**本响应里第二个值不是布尔的键**（第一个是 rag_kb_query_src），
    # 破例理由同款：调用方要照着它渲染选项，而写错档名会 422 ——
    # 可选集必须**问得出来**，不能只写在文档里。
    persona_styles: list[str] = Field(default_factory=list)
    intro_enabled: bool = False
    intro_max_chars: int = 0
    # ---- `raw` 的暴露档位（安全）----
    # 同样只有一个键。false（交付默认）= /finish 与 /result 的 `raw` 已脱敏成占位键,
    # 里面没有得分点原文;true = 全量明细（给 3 号 出评估报告用）。
    # 开关是**部署级**的（A11_RAW_DETAIL）,调用方无法自选 —— 见 config.py 那一段。
    raw_detail_enabled: bool = False
    # ---- 面试期的知识库背景参考（赛题 6.1)b + 6.2)b）----
    # 同样只有一个键，而且与 `kb_enabled`（4a 那条路）是**两个开关**：
    # 这个为 true 时，面试官在追问轮会检索知识库，把命中的片段当「背景参考」，
    # 默认喂进**末尾 user 旁白**（`rag_kb_aside_enabled`；=0 时退回 system；
    # 片段本身只在会话内存里，不进 `raw`、不进给考生的任何响应）。
    # ⚠️ **检索词默认就是「考生刚说的那段话」**（= 赛题 6.2)b 字面）；另有保留的
    #    实验档 `A11_RAG_KB_QUERY_SRC="miss"` 用**他没答到的得分点**当检索词
    #    （那一档漏点全空时退回考生原话，日志记 `answer_fallback`）—— 见下面
    #    `rag_kb_query_src`。
    # ⚠️ 它还要 `A11_RAG=1` 才真出得来 —— 编码器是**借** rag 那份的，
    #    借不到就不检索（绝不自己加载 1.2GB）。所以这一位 true 只代表「开关开着」。
    rag_kb_enabled: bool = False

    # ---- 「素材怎么被用」这三条（2026-09-25）----
    # 同样**各一个单键**。它们是**同题两臂对照**里 old/new 两档的全部差异，
    # 而其中两条（契约措辞、位置）在产出指标上**可能完全看不出差别** ——
    # 不暴露就只能靠行为反推，而这里推不出来。键名与 env 逐个对应：
    #   A11_RAG_TASK / A11_RAG_HEAD_ONLY / A11_RAG_KB_ASIDE
    # true 只是「开关开着」：`rag_task_enabled` 为 true 时用的是**新契约文本**，
    # `rag_head_only_enabled` 为 true 时题库片段**只留题面**（切掉参考答案），
    # `rag_kb_aside_enabled` 为 true 时知识库材料进**末尾 user 旁白**（system 里那块为空）。
    rag_task_enabled: bool = False
    rag_head_only_enabled: bool = False
    rag_kb_aside_enabled: bool = False

    # ---- 面试期检索词从哪来（2026-09-25 晚）----
    # ⚠️ **本响应里唯一一个值不是布尔的开关**，只可能是 `"answer"`（默认，赛题字面）/
    # `"miss"`（保留的实验档）之一。
    # 破例的理由：只有 `"miss"` 算实验档，env 写错（`MISS`/打错字）会**静默退回默认档**，
    # 而布尔键在这种情形下报 false 只会让人以为「没开」—— **回显原值**才看得出写错了。
    # （默认是 `"answer"` 时，回显也顺手证明「真的没被 env 覆盖」。）
    # 它真出来还要 `rag_kb_enabled=true` 且 `rag_enabled=true`（编码器是借 rag 那份的）。
    rag_kb_query_src: str = ""


# ============================================================
# POST /start
# ============================================================
class StartReq(Loose):
    job: str = Field(config.DEFAULT_JOB, description="岗位名，取值见 /health.jobs")
    # 自我介绍 / 简历摘录（2026-09-25 起**真的会进面试官 prompt** + 开场白）。
    # 空 = 与加这个功能之前逐字节相同的行为。上限见 A11_INTRO_MAX_CHARS。
    intro: Optional[str] = Field("", description="自我介绍/简历摘录（可选）")
    # 面试官风格三档（2026-09-25）。取值见 /health.persona_styles。
    # **不传 = "standard" = 提示词逐字节不变**（那一档的追加块是空串）。
    # 不认识的档名 → 422 bad_persona_style（**报错而不是静默按默认跑**：
    # 静默会让「我明明选了严厉」看不出来）。
    persona_style: Optional[str] = Field(
        None, description='面试官风格：strict / standard / relaxed；不传即 standard')


class StartResp(Loose):
    session_id: str
    job: str
    state: str = Field(description="会话状态，等同 phase")
    phase: str
    message: str = Field(description="开场白（前端直接展示）")
    total_questions: int
    weights: str
    dimensions: list[str] = Field(default_factory=lambda: list(config.DIMENSIONS))
    # **实际生效**的风格档（F）。开关关掉或传了怪值时回落到 standard ——
    # 回显生效值而不是请求值，是为了让「我选了严厉但没生效」看得见。
    persona_style: str = Field("standard", description="实际生效的面试官风格")
    persona_label: str = Field("标准", description="风格的中文名（前端可直接显示）")
    # **读到多少自述**（E）。三态：没传 → null；传了但 A11_INTRO=0 →
    # enabled=false；真进了 prompt → enabled=true + chars/snippet。
    # 键名叫 intro_read 而不是 intro —— 避免与请求里的 `intro` 混淆
    # （一个是「你发来的」，一个是「我读到了什么」）。
    intro_read: Optional[dict] = Field(
        None, description="读到自述的情况：{enabled,chars,raw_chars,truncated,snippet}")


# ============================================================
# POST /practice（专项强化练习，赛题 4b）
# ============================================================
class PracticeReq(Loose):
    """
    从一份**已交卷**的成绩单开一场专项练习。

    目标三选一（优先级从上到下）：
      `kp_id`  指定考点（取自 /finish 的 `raw.blindspots.knowledge_points[].kp_id`）
      `domain` 指定领域（取该领域里最薄弱的那个考点）
      都不传   自动取**全卷最薄弱**的那个考点
    """
    session_id: str = Field(..., min_length=4, description="**已经 /finish 过**的会话 ID")
    kp_id: str = Field("", description="要练的考点 ID；留空则按 domain 或自动挑")
    domain: str = Field("", description="要练的领域；kp_id 为空时才生效")
    count: int = Field(0, ge=0, le=20,
                       description=f"练几道（0 = 默认 {config.PRACTICE_QUESTIONS}，"
                                   f"上限 {config.PRACTICE_MAX}）")


class PracticeResp(Loose):
    """开练习的应答。**之后照样用 /next、/chat、/finish** —— 没有新端点。"""
    session_id: str
    job: str
    mode: str = "practice"
    phase: str
    message: str = Field(description="开场白（前端直接展示）")
    total_questions: int = Field(description="本次练习的题数")
    source_session_id: str = Field(description="成绩单来自哪一场")
    target: dict = Field(default_factory=dict,
                         description="要练的考点：kp_id/title/domain/subclass/"
                                     "hit/best_score/missed_base/missed_adv…")
    why: str = Field("", description="为什么挑了这个考点（可直接展示）")
    match: str = Field("", description="题库是按 kp_id 还是考点名找到题的")
    plan: list[str] = Field(default_factory=list, description="预选题的题目 ID（按出题顺序）")
    reused_asked: int = Field(0, description="其中几道是这场已经考过的（题不够时的退路）")


# ============================================================
# POST /growth（成长档案：错题本 / 考点地图 / 历史成绩，赛题 4）
# ============================================================
class GrowthReq(Loose):
    """
    一批**成绩单摘要** → 三份聚合。摘要就是 `/finish`（或 `/result`）响应里那个
    顶层 `digest` 键，原样传回来即可 —— **不需要**做任何加工。

    ⚠️ 本服务**没有状态、也不认人**：它不知道这些摘要属于谁，也不会存下来
    （零落盘、不查库）。身份与持久化在 1 号 那边 —— 谁的历史、存多久、怎么查，
    都是他的事。这里只做纯聚合，所以 `job` 必须由调用方给（摘要里的 job 必须与它
    一致，不一致直接报 422，不静默丢掉那几份）。
    """
    job: str = Field(..., description="岗位（与每份摘要里的 job 必须一致）")
    records: list[dict[str, Any]] = Field(
        default_factory=list,
        description=f"若干份成绩单摘要，**按时间无关的顺序传即可**（服务端自己排序）。"
                    f"上限 {config.GROWTH_MAX_RECORDS} 份；"
                    f"单份上限 {config.GROWTH_MAX_DIGEST_BYTES} 字节 —— "
                    f"把 raw 当成 digest 传会返 413。")


class GrowthResp(Loose):
    """
    四个视图一次给全（同一份入参的四种呈现，分四个端点等于四倍契约）。

    ⚠️ 四处最容易被读错的地方（前端展示时请照着写）：
      · `wrong_book.status="once"` 且 `enough_samples=false` ≠「他只错过一次」，
        那是「只投了一份摘要，看不出来」；
      · `kp_map` 里 `hit=null` = 练过但**判不了**，不是「不会」；
        没练过的格子**只有数量、没有考点名**（那是刻意的）；
      · `history.practice` 用 `total_score_100` 排序/画图都行，但**不要**和
        `history.exam` 比 —— 练习是针对单个考点出的 3~5 道题，不可比；
      · `plan.groups[1]`（`uncovered`）**不是薄弱** —— 那是「考到了但没判出分」，
        别渲染成错题；`plan.unpracticed_kp_total` 也**不是薄弱**，是「还没考过」，
        而且它**只有数量、没有考点名**。
    """
    ok: bool = True
    job: str
    record_count: int = Field(description="实际采用的摘要份数（= 入参份数 − skipped）")
    skipped: list[dict[str, Any]] = Field(
        default_factory=list,
        description="没被采用的条目：[{session_id, reason}]。"
                    "**空数组 = 一份没漏**，不是「没检查」")
    wrong_book: dict[str, Any] = Field(
        description="错题本：sessions_used/by_mode/enough_samples/sample_note/items[]")
    kp_map: dict[str, Any] = Field(
        description="考点地图：kg_available/cells[]（每格领域全量计数 + 练过的考点名）")
    history: dict[str, Any] = Field(
        description="历史成绩：exam{timeline,delta_total,trend_note} 与 practice{timeline}")
    plan: dict[str, Any] = Field(
        default_factory=dict,
        description="提升路径（赛题任务要求 4）：groups[]（to_fix 要补的 / uncovered "
                    "**不是薄弱**）+ unpracticed_kp_total（从没考过的**数量**）。"
                    "每条含 rank/kp_id/title/why[]/evidence/material/action —— "
                    "`material` 只说明**有没有**材料，**正文要另调 `/model_answer`**")


class ModelAnswerReq(Loose):
    """
    取某个考点**或某道题**给考生看的学习材料（`考点讲解` + `优秀回答范例`）。

    ⚠️ 两道结构性的门（**不是约定**）：
      · 源场次必须**已 `/finish`**，否则 409 `source_not_finished` ——
        所以面试途中查不到答案；
      · 给 `kp_id` ⇒ 它必须出现在**那一场的诊断**里；给 `question_id` ⇒
        它必须 ∈ 那一场的 `asked_pids`（他真的答过这道题）。两条都是
        404 `answer_target_not_found` —— 所以没法枚举 kp_id / 题号把整份资源刷下来。
    `kp_id` 用 `/finish` 的 `review.gaps[].kp_id`、`/growth` 的
    `plan.*.items[].kp_id` 或 `wrong_book.items[].kp_id` 那三种，都能对上。
    `question_id` 用 `/finish` 的 `raw.per_round[].question_id`。
    """
    session_id: str = Field(..., description="源场次的会话 ID（**这一场**必须已经 /finish）")
    kp_id: str = Field("", description="考点 ID（必须是这一场诊断里出现过的）。"
                                      "与 `question_id` **至少给一个**")
    # ⚠️ 为什么要有 `question_id`（2026-09-25 加）：题库里有 1,110 道题
    #    **不挂任何考点**，走 `kp_id` 那条路它们永远取不到范文。加这条路是为了
    #    覆盖率，**不是为了放宽权限** —— 闸还是同一道（必须是他真答过的题）。
    # ⚠️ 两个都不给 ⇒ 422（见接口层的检查）。**不给默认值**：`kp_id` 原来是必填，
    #    改成可选后如果默认成空串又不去查，就会变成「静默给一份空白材料」。
    question_id: str = Field("", description="题号（必须在那一场出过的题里）。"
                                            "与 `kp_id` **至少给一个**")


class ModelAnswerResp(Loose):
    """
    两样学习材料 + 它出自哪道题。**只有两个内容键** —— `拉开差距`（进阶得分点原文）
    与 `常见卡点`（面试官降级策略）**永远不会**从这里出去，`missed_points` 同理。
    """
    ok: bool = True
    session_id: str
    kp_id: str
    title: str = ""
    domain: str = ""
    subclass: str = ""
    talk: str = Field("", description="考点讲解（考点级教学材料，纯文本，可含换行）；"
                                      "按 `question_id` 取材料时**恒为空串**")
    model_answer: str = Field("", description="优秀回答范例（代表题的核心答案）")
    from_question_id: str = Field("", description="这条范例出自哪道代表题（**只给题号，不给题面**）")
    # ⚠️ `kind` / `note`（2026-09-25 加）**必须一起渲染**：
    #    `kind="示范作答"` 时 `note` 是一句「下文示例经历为虚构」的提醒。
    #    只渲染 `model_answer` 而不渲染这两个 ⇒ 考生会把编出来的通用经历当成
    #    优秀范例背下来。前端至少要展示 `note`。
    kind: str = Field("范文", description="范文 | 示范作答。**示范作答=该题在题库里"
                                          "只有答题结构（STAR 骨架）、没有判分内容，"
                                          "下文是按结构编的通用示例**")
    note: str = Field("", description="`kind=示范作答` 时给考生的一句提醒；范文时为空串")
    src: str = Field("", description="这条材料是按 `kp_id` / `title` / `question` 命中的")


# ============================================================
# POST /next
# ============================================================
class NextResp(Loose):
    """
    出题结果。`finished=true` 时表示没有下一题了（题问完 / 题库抽空），
    前端应停止出题并调 /finish —— 此时只有 message，没有 question。
    """
    type: str = Field("question", description="question | finished")
    finished: bool = False
    session_id: str
    phase: str
    # ---- 题目字段（finished=true 时缺省）----
    stage: Optional[str] = None
    stage_index: Optional[int] = None
    q_index: Optional[int] = None
    total: int = config.TOTAL_QUESTIONS
    difficulty: Optional[str] = None
    question_id: Optional[str] = None
    question: Optional[str] = None
    knowledge_points: list[str] = Field(default_factory=list)
    opening_text: Optional[str] = None
    # ---- finished=true 时 ----
    reason: Optional[str] = None
    message: Optional[str] = None


# ============================================================
# POST /chat（SSE）
# ============================================================
class ChatReq(Loose):
    session_id: str = Field(..., min_length=4)
    message: str = Field(..., min_length=1, description="考生这一句回答")
    # ---- 语音作答的表达指标（加法，可选）----
    # 考生用语音答题时，前端把 `POST /asr` 返回的 `duration_ms` / `segments` /
    # `audio_ms` / `asr_model` / `pauses` / `pause_total_ms` **原样**带回来
    # （不要自己算、也不要自己编）。后两个是音频上量的停顿，缺了不影响作答，
    # 只是停顿退回「段间隔」兜底（多半是 0）。
    # 不传 = 文字作答，行为与加这个字段之前逐字节相同。
    # ⚠️ `message` 仍然是唯一被当作回答内容的字段 —— 转写文本走 message，
    #    这个对象里**只有数字**，它不参与判档、评分、复读守卫。
    speech: Optional[dict] = Field(
        None, description="语音作答时由 /asr 原样回传的时长与时间戳（可选）")


# ============================================================
# POST /asr（语音转写：音频进、文字出）
# ============================================================
class AsrResp(Loose):
    """
    转写结果。**永不返回 null** —— 失败时也是这个形状，用 ok=false + error 表达
    （4 号 的假服务与真服务必须同形，否则前端只在一边能跑）。
    """
    ok: bool = True
    text: str = Field("", description="转写出的整段文字；空串=没听到人声")
    duration_ms: int = Field(0, description="净语音时长（VAD 人声块之和，段内静音不计）")
    audio_ms: int = Field(0, description="音频文件本身时长（含静音），诊断用")
    segments: list[dict] = Field(
        default_factory=list,
        description="段级时间戳 [{start_ms,end_ms,text}]，前端字幕与时间对齐用")
    # ⚠️ 停顿**必须**由转写这一侧给（音频上量的），不能靠 segments 的间隔反推：
    #    whisper 的段首尾相接，静音被吞进段跨度里 —— 实测 6 秒静音也数不出来。
    pauses: Optional[int] = Field(
        None, description="长停顿（>1.5 秒静音）次数；None=没量到（降级）")
    pause_total_ms: Optional[int] = Field(
        None, description="长停顿累计毫秒；None=没量到（降级）")
    asr_model: str = ""
    elapsed_ms: int = 0
    # ---- 韵律三指标 + 情感（赛题 3b「语气自信度」）----
    # ⚠️ 全部 `Optional` 默认 `None`，且**键恒在** —— 关掉、模型没下、VAD 没量出人声
    #    都走 None。**不是 0**：0 是「测出来真的是 0」，与「没测」是两回事。
    # ⚠️ 「窗」= 把每一段人声按**不超过 3 秒**等分切出来的小段（`asr._loudness_windows`）。
    #    这么切是为了**连读的答案也算得出**起伏与收尾：VAD 要静音 >2 秒才断开，
    #    真人连读只会切出一个人声段，那时 cv/tail 就永远是 `None`（2026-09-25 改）。
    # ⚠️ `emotion` 是**模型给的**情感标签（闭集），**不是**「自信度」。
    #    自信度是 1 号在 `/finish` 的 `pace_note` 里用这些数**融合**出来的档位，
    #    `/asr` 这一层不产出它 —— 别把这两个概念接错。
    loudness: Optional[float] = Field(
        None, description="各窗 RMS 均值（声音洪不洪亮）；只当相对量用，跨设备不可比")
    loudness_cv: Optional[float] = Field(
        None, description="各窗 RMS 的变异系数（越小越稳）；需 >=2 个窗，否则 None")
    tail_ratio: Optional[float] = Field(
        None, description="最后一窗 RMS / 各窗均值（<1=越说越小）；需 >=2 个窗")
    emotion: Optional[str] = Field(
        None, description="情感标签（闭集，来自模型 config：neu/hap/ang/sad）")
    emotion_score: Optional[float] = Field(None, description="上述标签的概率")
    emotion_dist: Optional[dict] = Field(
        None, description="全部标签 -> 概率（和恒为 1）；数字字典")
    error: str = Field("", description="错误码：asr_unavailable | asr_loading | "
                                       "file_too_large | audio_too_long | "
                                       "unsupported_format | asr_failed")
    detail: str = ""


class ChatResp(Loose):
    """仅为 /docs 展示 SSE 事件形状；实际响应是 text/event-stream。"""
    type: str = Field(description="token | done | error | question")
    text: Optional[str] = Field(None, description="token 事件的文本片段")
    follow_up: Optional[bool] = Field(
        None, description="done 事件：true=面试官在追问，等考生继续答；false=本轮结束，调 /next")
    round_finished: Optional[bool] = None
    q_index: Optional[int] = None
    follow_up_used: Optional[int] = None
    degrade_used: Optional[int] = None
    attempts: Optional[int] = None
    action: Optional[str] = Field(None, description="done 事件：L1 | L2 | degrade | close")
    reranker_score: Optional[float] = Field(
        None, description="done 事件：覆盖率 0-100（0.6*基础命中率 + 0.4*进阶命中率）")
    reranker_ok: Optional[bool] = Field(
        None, description="done 事件：false = reranker 失败，这个分不可信")
    # ↓ 判档：两个判档源各判了什么、最后听了谁。只增不改，4 号可以不看。
    reranker_band: Optional[str] = None
    judge_band: Optional[str] = Field(
        None, description="null = LLM 没判出来（超时/非 JSON），不是「判成降级」")
    judge_ok: Optional[bool] = None
    judge_why: Optional[str] = Field(None, description="LLM 给的一句话理由，仅排查用")
    fuse_rule: Optional[str] = Field(
        None, description="agree | llm_first | disagree_shallow | deepest | reranker_only")
    band_disagree: Optional[bool] = Field(
        None, description="两个判档源是否不一致，供 3 号统计判档质量")
    # ↓ 换题出路：这一轮被作废过一次还是没作废。这三条以前只在
    #   `api/interview.py` 那个手工 dict 里，`/docs` 上看不到 —— 补齐。
    swapped: Optional[bool] = Field(
        None, description="done 事件：这一轮换题了吗（恒存在，没换过是 false）")
    swaps_used: Optional[int] = Field(
        None, description="done 事件：本场已换几次")
    swaps_left: Optional[int] = Field(
        None, description="done 事件：本场还剩几次可换（默认上限 1）")
    phase: Optional[str] = None
    ms: Optional[int] = None
    session_id: Optional[str] = None
    err: Optional[str] = Field(None, description="error 事件：错误信息")
    code: Optional[str] = None


# ============================================================
# POST /finish 与 GET /result/{sid}
# ============================================================
class FinishResp(Loose):
    """
    顶层字段是**旧接口原样**，4 号前端零改动可用；
    新增的 raw 给 3 号评估报告取明细。

    注意 five_dim_avg 的值可能是 null（该维度所有轮次都没评出分），
    total_score 也可能是 null（整场没评出任何分）。
    **null 表示「没有数据」，不表示「0 分」** —— 前端要区分对待。
    """
    session_id: str
    job: str
    five_dim_avg: dict[str, Optional[float]]
    total_score: Optional[float]
    total_score_100: Optional[float] = Field(None, description="折算成百分制，同可能为 null")
    weights: str = Field(description="人类可读权重串，如 '技术30% 逻辑30% …'")
    summary: str = Field(description="面试评价正文")
    rounds: int = Field(description="参与评分的轮次数")
    partial: bool = Field(description="true=有轮次评分失败或整场无分，分数不完整")
    notes: list[str] = Field(default_factory=list)
    # ⚠️ 默认档（A11_RAW_DETAIL=0）下这里**只有**一个占位键 `note`。它装的是
    #    得分点原文（`rounds[].exchanges[].base_miss` = 未命中的得分点 = 一份答案）。
    #    ⚠️ 订正（2026-09-25）：这里原写「**唯一**会带着得分点原文出门的字段」，
    #    是**错的**，本项目另有两处会出门：
    #      · `PracticeResp.target.missed_points`（/practice 的响应，逐条原文）；
    #      · 顶层 `notes[]` —— 换题理由（`swap_reason` 来自判档模型，经常复述
    #        得分点原文），而 `_with_raw_detail()` **只换 raw、不动 notes**。
    #    两处都**只记录、不修**：动了会改 4 号 已有页面的行为。见 owed.md §13.17。
    #    键保留成 dict、不改 Optional —— 免得 4 号 那边从「有 dict」变成 null。
    #    开关见 /health.raw_detail_enabled。
    raw: dict[str, Any] = Field(default_factory=dict, description="完整明细，结构见 README")
    # ---- 成长档案摘要（加法：顶层新键，raw 里一个键都不动）----
    # 1 号 存档用：把它存起来，之后原样回传给 `POST /growth` 就能得到
    # 错题本 / 考点地图 / 历史成绩。**它无论 A11_RAW_DETAIL 都会出门**（默认档下也在），
    # 所以是**白名单**构造、**绝不含得分点原文**（得分点只可能以条数出现）。
    # ⚠️ 关掉功能（A11_GROWTH=0）时是 **null**（不是 `{}`）：null = 本次响应不含摘要，
    #    `{}` = 有摘要但是空的。两者混同会让 1 号 把「没开」存成一堆空档案。
    digest: Optional[dict[str, Any]] = Field(
        None, description="成长档案摘要（1 号 存档用；A11_GROWTH=0 时为 null）")
    # ---- 复盘清单（加法：顶层新键，给**考生**看的）----
    # `summary` 是评价，`review` 是「哪几个考点没答到 + 下一步练哪个」。
    # ⚠️ 与 digest 同款：**无论 A11_RAW_DETAIL 都会出门**（默认档下也在），
    #    所以同样是白名单构造、**绝不含得分点原文**（得分点只以条数出现）。
    # 形状：`{review_version, session_id, job, mode, headline, gaps[], covered[],
    #        uncovered[], actions[], counts{}, caveats[]}`。
    #   · `gaps[]`   = 被判「没答到」的考点（`hit is False`），每条带一句 `advice`
    #   · `covered[]`= 答到了的考点；`uncovered[]` = 判不了的（**不是漏点**）
    #   · `actions[]`= 下一步，带 `kind`/`kp_id` ⇒ 4 号 可直接调 `POST /practice`
    #   · `counts`  = 全是**整数计数**，**没有任何百分比/掌握度**（一场面试的样本
    #                不足以支撑比率）
    # ⚠️ 关掉（A11_REVIEW=0）时是 **null**，不是 `{}`：null =「本次响应不含清单」，
    #    `{}` =「有清单但是空的」—— 两者混同会让前端把「没开」画成一张空卡片。
    review: Optional[dict[str, Any]] = Field(
        None, description="给考生看的复盘清单（漏点 + 下一步；A11_REVIEW=0 时为 null）")
    cached: bool = False


class ErrorResp(Loose):
    """统一错误体。"""
    code: str = Field(description="机器可读错误码，如 session_not_found")
    err: str = Field(description="人可读错误信息")
    session_id: Optional[str] = None
