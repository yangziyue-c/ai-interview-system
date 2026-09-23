# -*- coding: utf-8 -*-
"""
config.py · 全局配置（唯一真值源）
============================================================
岗位表、五维权重、面试流程参数、路径、端口，全部集中在这里。
其它模块不许再定义岗位名或权重。

敏感信息（API key）一律走环境变量，不写死在代码里。
"""
import os

# ============================================================
# 路径
# ============================================================
# 项目根目录（本文件在 <root>/app/config.py）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 主库题库（5012 题，5 个岗位 JSON）—— 只读，不要改这里的文件
MAIN_DB_DIR = os.environ.get(
    "A11_MAIN_DB",
    r"C:\Users\litao\WorkBuddy\2026-09-10-21-25-17\ai-interview-data\v5",
)

# 岗位人设 markdown 目录
PERSONA_DIR = os.path.join(BASE_DIR, "app", "personas")

# 日志目录
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 模型缓存（bge-m3 / bge-reranker-v2-m3，已下载完整，可离线跑）
HF_HOME = os.environ.get("HF_HOME", r"D:\A11-Data\hf_cache")


# ============================================================
# 岗位表
# ============================================================
# 注意：这 5 个名字必须与主库 JSON 里「所属岗位」字段的值**逐字一致**。
# 数据里的真实取值就是这 5 个（system-design-v5.json 写的是「系统设计工程师」，
# 不是早期文档里出现过的「系统架构设计师」）。
JOBS = [
    "Java 后端开发工程师",
    "Web 前端开发工程师",
    "测试开发工程师",
    "算法工程师",
    "系统设计工程师",
]
DEFAULT_JOB = JOBS[0]

JOB_FILE_MAP = {
    "Java 后端开发工程师": "java-v5.json",
    "Web 前端开发工程师": "web-v5.json",
    "测试开发工程师": "test-v5.json",
    "算法工程师": "algorithm-v5.json",
    "系统设计工程师": "system-design-v5.json",
}

# 每组题量（只用于日志自查，实际以加载结果为准）
JOB_BANK_SIZE = {
    "Java 后端开发工程师": 2146,
    "Web 前端开发工程师": 734,
    "测试开发工程师": 667,
    "算法工程师": 655,
    "系统设计工程师": 810,
}

PERSONA_FILE_MAP = {
    "Java 后端开发工程师": "java.md",
    "Web 前端开发工程师": "web.md",
    "测试开发工程师": "test.md",
    "算法工程师": "algorithm.md",
    "系统设计工程师": "system-design.md",
}


# ============================================================
# 五维权重
# ============================================================
# 顺序固定：技术水平 / 逻辑思维 / 沟通表达 / 应变能力 / 岗位匹配度
# 1~5 分，允许 0.5 步进；总分 = Σ(维度分 × 权重)
#
# 来源：《工作成果描述-截止RAG完成.md》「阶段 2」五维评分模型表。
# ⚠️ 唯一真值源其实是主库 Excel 的「五维评分基准」sheet
#    （C:\...\v5\A11-岗位结构化主库-v5.xlsx）。
#    本表与旧版 D:\A11-Data\interview_framework\config.py 有两处差异（已按文档修正）：
#      算法工程师     旧 40/30/10/10/10 → 本表 35/30/10/10/15
#      系统设计工程师  旧 30/25/10/15/20 → 本表 30/30/15/10/15
#    核完 Excel 若发现不一致，改这里一行即可。
# ⚠️ 「技术水平」是**键**，不是显示名。行为素质题的第一维在界面上叫
#    「岗位胜任力关联度」（见本文件底部的 dim1_label），但写分时键恒为此处的
#    DIMENSIONS[0] —— 因为它是权重表的列名、five_dim_avg 的键、blindspot 的
#    遍历键、以及 /start 返回给前端的 dimensions 列表。改动键名要同时动这四处
#    + 3 号的报告代码，而收益只是「标签好看」—— 不划算。标签单独暴露。
DIMENSIONS = ["技术水平", "逻辑思维", "沟通表达", "应变能力", "岗位匹配度"]

SCORE_WEIGHTS = {
    "Java 后端开发工程师": {
        "技术水平": 0.35, "逻辑思维": 0.25, "沟通表达": 0.10,
        "应变能力": 0.10, "岗位匹配度": 0.20,
    },
    "Web 前端开发工程师": {
        "技术水平": 0.30, "逻辑思维": 0.20, "沟通表达": 0.15,
        "应变能力": 0.15, "岗位匹配度": 0.20,
    },
    "测试开发工程师": {
        "技术水平": 0.25, "逻辑思维": 0.25, "沟通表达": 0.20,
        "应变能力": 0.15, "岗位匹配度": 0.15,
    },
    "算法工程师": {
        "技术水平": 0.35, "逻辑思维": 0.30, "沟通表达": 0.10,
        "应变能力": 0.10, "岗位匹配度": 0.15,
    },
    "系统设计工程师": {
        "技术水平": 0.30, "逻辑思维": 0.30, "沟通表达": 0.15,
        "应变能力": 0.10, "岗位匹配度": 0.15,
    },
}
# 未知岗位兜底（等权）
DEFAULT_WEIGHTS = {d: round(1.0 / len(DIMENSIONS), 4) for d in DIMENSIONS}


def weights_for(job: str) -> dict:
    """取某岗位的五维权重，未知岗位走兜底。"""
    return SCORE_WEIGHTS.get(job, DEFAULT_WEIGHTS)


def weights_text_for(job: str) -> str:
    """权重的人类可读描述，给总结 Prompt 和前端展示用。"""
    w = weights_for(job)
    short = {"技术水平": "技术", "逻辑思维": "逻辑", "沟通表达": "沟通",
             "应变能力": "应变", "岗位匹配度": "匹配"}
    return " ".join(f"{short[d]}{w[d] * 100:.0f}%" for d in DIMENSIONS)


# ============================================================
# 第一维的题型差异
# ============================================================
# 出处：《工作成果描述-截止RAG完成.md》第 94 行 ——
#   「技术知识题 / 场景应用题 / 项目经历题均按上述五维评分；**行为素质题**的
#     第一维度为「岗位胜任力关联度」（取代 "技术水平"），其余四维不变 ——
#     因为行为题考察的不是技术深度而是岗位特质匹配。」
#
# 为什么必须修：不修的话，模型会拿「全部基础+进阶，能从源码/工程层面讲」这条
# **技术锚点**去量行为题（比如「讲一次你在项目中学到的最重要的教训」）——
# 尺子和对象不匹配，第一维的分是错的。五岗合计 495 道行为素质题会踩到。
CATEGORY_BEHAVIORAL = "行为素质题"        # 取值真值源：主库「题型分类」列
DIM1_LABEL_BEHAVIORAL = "岗位胜任力关联度"

# 第一维的两套 1~5 锚点（键 = 标签）。
#   · 技术那套是**原文照搬** prompts.py 里既有的文字，一个字没动；
#   · 岗位胜任力那套是**本次新拟的** —— 文档只规定了标签，没给档位描述，
#     所以这段文字的出处是本实现、不是需求文档，别当成需求原文引用。
DIM1_RUBRIC = {
    "技术水平": (
        "【技术水平】1=概念模糊或答错；2=少量基础点且有明显错误；"
        "3=大部分基础点、无原则错误；4=全部基础点+部分进阶点；"
        "5=全部基础+进阶，能从源码/工程层面讲。"),
    "岗位胜任力关联度": (
        "【岗位胜任力关联度】1=经历与岗位要求无关，或讲不出与岗位的关联；"
        "2=经历沾边，但说不出它体现了岗位需要的什么；3=能对上岗位的基本要求；"
        "4=能说清经历中体现的岗位所需能力，并说明如何迁移到本岗位；"
        "5=经历与岗位要求高度契合，能指出对岗位的具体价值与可复用的方法论。"),
}


def dim1_label(category: str) -> str:
    """
    本题型的第一维**叫什么**。只有行为素质题不是「技术水平」。

    ⚠️ 返回值是**标签**（显示/喂 prompt 用），不是**键**。写五维分时键永远是
    DIMENSIONS[0]，两者不要混 —— 混了以后 3 号和前端就得判空、分情况。
    """
    return (DIM1_LABEL_BEHAVIORAL
            if str(category or "").strip() == CATEGORY_BEHAVIORAL
            else DIMENSIONS[0])


def dim1_labels() -> tuple[str, ...]:
    """第一维可能出现过的所有标签。解析模型回包时用（它按标签回键）。"""
    return (DIMENSIONS[0], DIM1_LABEL_BEHAVIORAL)


# ============================================================
# 面试流程参数
# ============================================================
TOTAL_QUESTIONS = 10

# (阶段名, 该阶段题数, 该阶段允许的难度值)
# 「难度等级」在主库里的真实取值就是这几个英文串
STAGE_RULES = [
    ("开场热身", 3, {"easy"}),
    ("核心考察", 5, {"medium"}),
    ("深度压轴", 2, {"hard"}),
]

MAX_FOLLOW_UP = 2          # 单题最多追问几轮
MAX_DEGRADE = 2            # 同一题连续降级几次后强制收尾（防止答不上来时无限空转）
MAX_ATTEMPTS_PER_QUESTION = 3   # 单题最多接受几次回答（冗余兜底，保证一定收敛）
# reranker 命中阈值。⚠️ 它比的是**模型自己输出的概率**（num_labels=1 时
# CrossEncoder 内部已过 Sigmoid），不是再叠一次 sigmoid 之后的值 —— 见
# scoring.py 的 _hit。这个数需要拿标注集重新校准，见 A11_JUDGE 那一段。
MATCH_THRESHOLD = float(os.environ.get("A11_MATCH_THRESHOLD", "0.7"))
MIN_POINT_CHARS = 15       # 得分点文本短于这个长度就丢掉（过滤标题行/残句）

# 追问层级阈值（reranker 客观命中分，0-100）
LEVEL_L2_MIN = 60          # ≥60 分 → L2 原理深挖
LEVEL_L1_MIN = 30          # 30~60 分 → L1 基础细节；<30 → 降级引导


# ============================================================
# 判档：LLM 判「下一句往哪个方向问」+ 与 reranker 融合
# ============================================================
# 为什么加这一层（实测数据，不是设计偏好）：
#   reranker 那个「命中了几条得分点」的量**不稳定**。90 条真实首答，只把
#   `(得分点, 回答)` 的传参顺序换一下 —— 一个对模型毫无意义的实现细节 ——
#   29% 的题判档就变了，15.6% 的题覆盖率变动超过 60 分（最大 100 分，
#   即从 0 跳到 100），两个方向还基本对称（改对 14 / 改错 8）。
#   一个换个写法就翻掉三成读数的量，量的显然不是「答得好不好」。
#   在它上面调阈值（无论怎么调）都没有意义。
#   反过来，同一个项目里 LLM 评的五维分把三档考生分开成 91/60/27、
#   档内波动 4 分以内 —— 判断力是够的，只是以前没人问它。
# 所以：让 LLM 来判档，reranker 降为一个**并行**发出的参考信号。
#
# 成本：判档与 reranker 并行发起，总延迟 ≈ max(两者) 而不是两者相加
#       （reranker 约 3s，判档吐一个短 JSON 约 1~2s）—— 实际几乎不多等。
A11_JUDGE = os.environ.get("A11_JUDGE", "1") == "1"

# 融合规则：两边各给一个档（L2 / L1 / degrade），不一致时听谁的。
#   llm_first  听 LLM；LLM 没判出来（超时/解析失败）才退回 reranker   ← 默认
#   agree      一致才用；不一致取**较浅**那个（拿不准就别往深里挖）
#   deepest    取较深那个（更爱追问，宁可多问不少问）
#   reranker   只用 reranker（= 关掉判档；留给 A/B 对照用的那一臂）
JUDGE_FUSE = os.environ.get("A11_JUDGE_FUSE", "llm_first")
# 判档时喂进去的回答截断长度（判深度不需要全文，短一点更快更稳）
JUDGE_ANSWER_TRUNCATE = int(os.environ.get("A11_JUDGE_ANSWER_TRUNCATE", "800"))

# ------------------------------------------------------------
# 重复作答守卫：考生把同一句话说第二遍时，别读成"他又答对一次"
# ------------------------------------------------------------
# 为什么要有这一条（是补结构性缺陷，不是调优）：
#   判档原来只看**这一次**的回答 —— DepthJudge.judge 的入参里没有任何历史，
#   JUDGE_DEPTH 模板里也没有对应占位符。于是考生把原话复述一遍：
#   reranker 覆盖率一模一样（同一段文本、同一批得分点），LLM 照样判 L2。
#   后果是**追问被白白花掉**：系统拿着同一段内容再往深里问一次，考生只能再复述一遍。
#
# ⚠️ 这里原来还写着一句「L2 会被 _trajectory() 记成走势偏强的样本 → 难度向上
#    扩一档 → 复读反而把题变难」。**这句话是错的**，2026-09-23 真跑数据推翻了它：
#    `_trajectory()` 取的是 `r.attempts[0].band`（**只取首答**），而复读只可能出现在
#    第 2/3 次（第 1 次没有历史，detect_repeat 必返 False）——
#    复读压出来的 degrade 永远进不了走势。别再把这条理由抄回来。
# 两道闸，故意的冗余：
#   ① 把本轮之前的回答喂给判档器（JUDGE_HISTORY_BLOCK），让它自己识别
#      "这次没说新的东西"。语义层面，能认出换汤不换药。
#   ② 与历史回答文本相似度 ≥ REPEAT_SIM 时，**确定性**地把档位压到 degrade。
#      逐字复述这种最好认的重复，不该依赖一个会超时、会返回非 JSON 的组件。
A11_REPEAT_GUARD = os.environ.get("A11_REPEAT_GUARD", "1") == "1"
# 归一化后（去掉空白与标点）的 SequenceMatcher 相似度阈值。
# 0.90 ≈ "几乎逐字复述"。故意不取更低：把 0.80 那类"同一件事换个说法再说"
# 算不算重复取决于人，先保守；要放宽就改这个数，不必动代码。
REPEAT_SIM = float(os.environ.get("A11_REPEAT_SIM", "0.90"))
# 短于此长度的回答不参与重复判定：那是 degrade 的活（"不会""没做过"），
# 而且太短的串比对噪声大，容易把两次"不会"当成复读。
REPEAT_MIN_CHARS = int(os.environ.get("A11_REPEAT_MIN_CHARS", "12"))
# 判档时最多回看几次历史回答（更早的更无关，且白占 token）
JUDGE_HISTORY_MAX = int(os.environ.get("A11_JUDGE_HISTORY_MAX", "2"))

# ------------------------------------------------------------
# 换题出路：考生明确说「这个方向我从没接触过」时，换一道别的方向的题
# ------------------------------------------------------------
# 要解决什么：现在只有"追问"和"收尾"两条路。考生说「这块我没学过」，
# 系统只能给一次提示、他不接、然后收尾 —— 一道题就这么耗掉了，
# 而他本可以答一道他学过的。**这不是考生的失败，是选题没给他机会。**
#
# 判定**由判档 LLM 顺带给出**（depth="swap"），不另加一次 API 往返，零额外延迟。
# 不用关键词匹配：它分不清「这题我没做过」和「这题我没做过，但我的思路是…」，
# 后者是真回答，换题就误伤了。
#
# ⚠️ 与 repeat 守卫一样，桩模式下天然关着 —— 判档在 LLM_MOCK 时是 None，
#    拿不到 swap 档，所以冒烟测试的行为与加这个功能之前逐字节相同。
A11_SWAP = os.environ.get("A11_SWAP", "1") == "1"
# 一场最多换几次。取 1：够覆盖"偶尔撞到一个完全没接触过的方向"，
# 又封住"一直说不熟、把整场躲掉"这条路（换题**不占** 10 题名额，
# 所以上限就是"他能白白跳过几道题"的直接度量）。
MAX_SWAP_PER_SESSION = int(os.environ.get("A11_MAX_SWAP", "1"))


# ============================================================
# 难度自适应：让难度跟着考生的**整场走势**走，而不是每场同一个序列
# ============================================================
# 为什么加这一层（实测数据）：9 场真实面试，每场的难度序列**逐题完全相同** ——
# 3 easy → 5 medium → 2 hard，90 轮的分布是 easy 27 / medium 45 / hard 18。
# STAGE_RULES 只按「第几题」给难度，**完全不看考生答成什么样**。后果实测到了：
# 弱考生（覆盖率长期 0）在第 9、10 题照样拿到 hard，还是在「深度压轴」阶段 ——
# 那两题对他等于白问，既没测出信息量，体验上也是干耗。
# 这一段让**阶段该出什么难度**由前几轮的实际走势决定：
#   前几轮多半被判深挖（L2）  → 该阶段的难度集合**向上扩一档**
#   前几轮多半被判降难度      → 该阶段**向下扩一档**
# 只扩不缩：集合是「可从中抽」的范围，扩一档等于给题库多一个选项，
# 由 qb.sample 在集合内选，实际难度仍受题目分布约束。
#
# ⚠️ 开场热身**不参与调整**：它是固定的 easy 打底，且冒烟测试里有一条
#    「阶段↔难度同源」的断言依赖它逐字节可预测（见 smoke_test.py 修 #2 那段）。
A11_ADAPTIVE = os.environ.get("A11_ADAPTIVE", "1") == "1"
# 只调这两个阶段。开场热身不调，理由见上。
ADAPT_STAGES = ("核心考察", "深度压轴")
# 至少要有这么多轮的实际走势才动难度 —— 正好是开场热身那 3 题。
# 少于 3 轮时样本太薄，宁可先按原计划走。
ADAPT_MIN_ROUNDS = 3
# 取每轮**首答**的判档结果当走势样本（一题一次，不重复计权）。
# 首答里被判深挖的比例 ≥ 此值 → 认定偏强，向上扩一档。
ADAPT_L2_RATE = 0.6
# 首答里被判降难度的比例 ≥ 此值 → 认定偏弱，向下扩一档。
# ⚠️ 这两个阈值**不可能同时满足**，不是靠优先级的写法兜住的：同一条首答不可能
#    既判 L2 又判 degrade，所以两个比例之和恒 ≤ 1，而 0.6 + 0.5 > 1。
#    所以「偏弱优先」这种判断顺序根本用不上 —— 但**别去调这两个数让它们相加
#    超过 1**，那才会真的需要一条优先级规则（冒烟测试里有一条断言守着这个不变量）。
ADAPT_DEGRADE_RATE = 0.5

# 传给 LLM 的上下文封顶：只带最近 N 条 transcript 消息
TRANSCRIPT_LIMIT = 24
# 单轮 Prompt 里得分点文本的截断长度
POINT_TRUNCATE = 500
# 单条考生回答进 Prompt 前的截断长度（防止超长回答撑爆上下文）
ANSWER_TRUNCATE = 1200
# 追问素材（L1/L2/L3 追问、降级策略）进 Prompt 前的截断长度
HINT_TRUNCATE = 300


# ============================================================
# LLM（DeepSeek，OpenAI 兼容接口）
# ============================================================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

LLM_TEMPERATURE = 0.6      # 对话（要有人味）
LLM_TEMPERATURE_SCORE = 0.2  # 评分（要稳定）
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))

# 测试用桩：置 1 时不调真 API，返回固定话术/固定分数，不烧额度
LLM_MOCK = os.environ.get("LLM_MOCK", "") == "1"


# ============================================================
# 评分器
# ============================================================
RERANKER_MODEL = os.environ.get(
    "RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

# auto = 有 CUDA 用 CUDA，否则 CPU；也可强制 "cpu" / "cuda"
# 注意：交接说明提到 reranker 上 GPU 可能 OOM，所以 run.ps1 默认仍走 CPU。
SCORER_DEVICE = os.environ.get("SCORER_DEVICE", "auto")

# 测试用桩：置 1 时不加载真 reranker，用确定性假分数（冒烟测试用，秒级返回）
RERANKER_MOCK = os.environ.get("RERANKER_MOCK", "") == "1"


# ============================================================
# 知识图谱（默认开，常驻增量约 30-60MB）
# ============================================================
# 图谱产物：{'graph': nx.Graph(无向), 'questions': dict(5012), 'kp_names': dict(1340)}
#
# ⚠️ pickle 反序列化等于任意代码执行 —— KG_PATH 只许指向可信文件，
#    绝不要从外部下载一个 .pkl 再指过来。
A11_KG = os.environ.get("A11_KG", "1") == "1"
KG_PATH = os.environ.get("A11_KG_PATH",
                         r"D:\A11-Data\kg-enhanced\kg_question_graph.pkl")

# 出题避重：候选题的「已考知识点重叠度」超过阈值就不要
#
# 0.6 不是新拍的 —— 沿用参照实现 07_interview_session.py:107 里已有的值；
# 0.85 是它上面加的一层缓冲（先严后宽，保证抽得出来）。
KP_OVERLAP_THRESHOLD = float(os.environ.get("A11_KP_OVERLAP_THRESHOLD", "0.6"))
KP_OVERLAP_RELAXED = float(os.environ.get("A11_KP_OVERLAP_RELAXED", "0.85"))
# 权重取 has_kp 边权（1.2 高频必考 / 1.0 常规 / 0.8 拓展）。
# 用题库自带的考点优先级做权重，而不是「见过几次」—— 重复一道高频必考题
# 比重复一道拓展题更伤覆盖多样性，边权重本来就表达了这个偏好。
KP_OVERLAP_WEIGHTED = os.environ.get("A11_KP_OVERLAP_WEIGHTED", "1") == "1"

# 追问深挖：从共现图里取「关联方向」
#
# 实测 cooccur_kp 共 2812 条边，权重域 [0.0069, 1.0]、中位 0.6176、均值 0.6035。
# 0.35 砍掉的是枢纽节点的长尾弱关联（Redis缓存数据库 度 66 → 长尾低到 0.011）。
COOCCUR_MIN_W = float(os.environ.get("A11_COOCCUR_MIN_W", "0.35"))
COOCCUR_TOPN = int(os.environ.get("A11_COOCCUR_TOPN", "8"))     # 枢纽节点的工作量上限
DEEPEN_TOPN = int(os.environ.get("A11_DEEPEN_TOPN", "3"))       # 最终注入条数
# 名字长度上限 —— 只是**次级**兜底，主要过滤走 kg._is_usable_name() 的问句形态判别。
#
# ⚠️ 别以为调小这个值就能滤掉问句名：最典型的那个噪声节点
#    「线程池的核心参数有哪些线程池的执行流程是怎样的」（度 42）**只有 23 字**，
#    任何 >=23 的阈值都拦不住它。长度是个失效的代理指标，真正的判别在 kg.py。
DEEPEN_NAME_MAX = int(os.environ.get("A11_DEEPEN_NAME_MAX", "24"))


# ============================================================
# RAG 参考片段（默认关 —— 实测本机内存装不下，见下）
# ============================================================
# ⚠️ 默认关不是保守，是实测结论：本机空闲 3854MB，而 bge-m3 + reranker 两个
#    fp32 模型合计约 4.5GB，加索引 303MB 与题库约 100MB → 约 5.2GB，放不下。
#    「默认开」在本机会永远走内存预检降级、永不生效，等于一句空话。
#    换台内存充足的机器（或 RAG_DTYPE=fp16 把编码器降到约 1.14GB）再 A11_RAG=1。
A11_RAG = os.environ.get("A11_RAG", "0") == "1"

# 检索器的 .py 路径 —— 它是第三方独立模块（memory_retriever.py），不是本项目的包
RAG_RETRIEVER_PY = os.environ.get(
    "A11_RAG_RETRIEVER_PY", r"E:\GitHubRepos\rag-db-v5\memory_retriever.py")
# ⚠️ RAG_MEM_DIR 这个名字**不能加 A11_ 前缀**：它由 memory_retriever.py:74
#    自己 os.environ.get 读取，改名等于切断它的路径解析。新变量一律走 A11_*。
RAG_ENCODER = os.environ.get("A11_RAG_ENCODER", "BAAI/bge-m3")
RAG_DTYPE = os.environ.get("A11_RAG_DTYPE", "fp32")        # fp32 | fp16
RAG_TOP_N = int(os.environ.get("A11_RAG_TOP_N", "3"))
RAG_SNIPPET_CHARS = int(os.environ.get("A11_RAG_SNIPPET_CHARS", "150"))
RAG_BLOCK_MAX_CHARS = int(os.environ.get("A11_RAG_BLOCK_MAX_CHARS", "600"))
# 开启 RAG 前的内存预检门槛（MB）。低于它就直接放弃，不做无畏的加载尝试。
RAG_MIN_FREE_MB = int(os.environ.get("A11_RAG_MIN_FREE_MB", "1800"))
# 取哪些层。实测只有这两层值得取：
#   原题      —— 题目 + 答题要点 + 示例话术（信息密度最高）
#   语义变体  —— 问法改写（直接服务「换个角度问」）
# 被排除的：L1/L2/L3（raw 与 hint_for 已在用，重复注入是浪费）；
#           基础/进阶得分点（实测是 "该题的基础核心要点是什么？\nif (N <= 6)" 这种
#           碎片，价值为负，而主库的 base_points/adv_points 更干净且已在 prompt 里）；
#           基础铺垫/场景化/答案变体（边际价值更低）。
RAG_LAYERS = tuple(x.strip() for x in
                   os.environ.get("A11_RAG_LAYERS", "原题,语义变体").split(",")
                   if x.strip())


# ============================================================
# 本服务
# ============================================================
THIS_PORT = int(os.environ.get("FRAMEWORK_PORT", "8005"))
HOST = os.environ.get("FRAMEWORK_HOST", "0.0.0.0")

# 会话在内存里保留多久（秒）。超时由 SessionStore 懒清扫回收。
SESSION_TTL = int(os.environ.get("SESSION_TTL", str(2 * 60 * 60)))  # 2 小时
# 已 /finish 的会话保留更久，好让 /result/{sid} 能复查
RESULT_TTL = int(os.environ.get("RESULT_TTL", str(6 * 60 * 60)))   # 6 小时
# 会话数上限（超出按最久未活动淘汰，防止内存无上限增长）
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "200"))

# 启动时是否预加载全部 5 个岗位题库（约 16MB JSON → 60~100MB 常驻，换首题 0 延迟）
PRELOAD_BANK = os.environ.get("PRELOAD_BANK", "1") == "1"

# 日志级别
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
