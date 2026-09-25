# -*- coding: utf-8 -*-
"""
scoring.py · 可插拔评分
============================================================
两层：
- RerankerScorer  客观命中分：本地 bge-reranker-v2-m3 算「考生回答 vs 每个得分点」的相似度
- LLMScorer       主观五维分：调 DeepSeek 按五个维度打分

对外只用 Scorer 门面。想换评分模型，只改本文件。

修的两个坑：
#8 reranker 不在请求里惰性加载 —— 启动时在后台线程预热，且加载加锁，
   避免两个并发首请求各加载一次 2.3GB 模型。
#9 device 不再硬编码 "cpu" —— 由 SCORER_DEVICE 控制（auto/cpu/cuda），
   cuda 加载失败会自动回退 cpu，而不是整个服务挂掉。
"""
import threading
import time
from typing import Optional

from app import config
from app.core import question_bank as qb
from app.logging_conf import get_logger

logger = get_logger(__name__)


# ============================================================
# 工具
# ============================================================
def _sigmoid(x: float) -> float:
    """
    reranker 原始分（可为负）→ 0~1 命中概率。

    ⚠️ **现在的 hit_scores 不再用它**。留着是为了离线复算：num_labels=1 时
    CrossEncoder 内部已过 Sigmoid，predict 的输出本身就是概率，再叠这一层
    会把 [0,1] 挤进 [0.5, 0.731]（及格线从 0.70 变 0.847）。要复现"改之前"
    的分数、或拿两套口径做 A/B，就得靠这个函数 —— 所以不删。
    """
    if x >= 0:
        z = pow(2.718281828, -x)
        return 1.0 / (1.0 + z)
    z = pow(2.718281828, x)
    return z / (1.0 + z)


def resolve_device() -> str:
    want = (config.SCORER_DEVICE or "auto").lower()
    if want != "auto":
        return want
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


# ============================================================
# 客观命中分
# ============================================================
class RerankerScorer:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()          # 修 #8：加载串行化，防冷启动竞态
        self._ready = threading.Event()
        self.device = resolve_device()
        self.mock = config.RERANKER_MOCK

    # ---------- 模型加载 ----------
    def _load(self):
        from sentence_transformers import CrossEncoder
        logger.info("正在加载 %s device=%s ...", config.RERANKER_MODEL, self.device)
        t0 = time.time()
        try:
            m = CrossEncoder(config.RERANKER_MODEL, max_length=512, device=self.device)
            m.predict([["预热", "预热"]])       # 走一遍前向，把图初始化掉
            return m
        except Exception as e:
            if self.device == "cpu":
                raise
            # 显存不够等情况：回退 CPU，而不是让服务起不来
            logger.warning("device=%s 加载失败（%s），回退 CPU", self.device, e)
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            self.device = "cpu"
            m = CrossEncoder(config.RERANKER_MODEL, max_length=512, device="cpu")
            m.predict([["预热", "预热"]])
            return m
        finally:
            logger.info("reranker 就绪 device=%s 耗时 %.1fs", self.device, time.time() - t0)

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:        # double-checked locking
                    self._model = self._load()
        return self._model

    def warmup(self) -> None:
        """启动时在后台线程调用。"""
        try:
            if self.mock:
                logger.warning("RERANKER_MOCK=1 —— 用确定性假分数，不加载真模型")
                self._model = "MOCK"
            else:
                self._get_model()
        except Exception:
            logger.exception("reranker 预热失败；后续每次评分都会回退默认分")
        finally:
            self._ready.set()

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._model is not None

    # ---------- 打分 ----------
    def hit_scores(self, answer: str, base_text: str, adv_text: str
                   ) -> tuple[float, list[str], list[str], bool]:
        """
        返回 (0-100 命中分, 命中的基础点, 命中的进阶点, 是否成功)。
        第 4 个返回值区分「评分失败」和「答得差」—— 调用方必须用它。
        """
        base_pts = qb.split_points(base_text)
        adv_pts = qb.split_points(adv_text)

        if not answer or not answer.strip():
            return 0.0, [], [], True           # 空回答：真的是 0 分，不是失败

        if self.mock:
            return self._mock_hit(answer, base_pts, adv_pts)

        try:
            model = self._get_model()

            def _hit(points: list[str]) -> list[str]:
                if not points:
                    return []
                # ⚠️ 参数顺序必须是 (得分点, 回答)，**不能反过来**。
                #    这个 cross-encoder 训练时的口径是 query=得分点、passage=回答；
                #    反着传，同一对内容实测 0.9994 → 0.0069（差 145 倍）。
                #    更要命的是长度差：回答 150~400 字、得分点 20~60 字，把长的
                #    那段塞进 query 槽之后，判出来的相似度整体塌到 0 附近 ——
                #    这正是「真会的考生有一半的题被判 0 分、然后被降难度」的成因。
                raw = model.predict([[p, answer] for p in points]).tolist()
                # ⚠️ 不要再叠 _sigmoid：num_labels=1 时 CrossEncoder 内部
                #    已经过了一次 Sigmoid，predict 的输出**本身就是 0~1 概率**。
                #    再压一次会把 [0,1] 挤进 [0.5, 0.731]，等于把及格线从 0.70
                #    悄悄抬到 0.847 —— 这个方向的错只可能漏判，不可能误判。
                return [p for p, s in zip(points, raw)
                        if s >= config.MATCH_THRESHOLD]

            base_hit = _hit(base_pts)
            adv_hit = _hit(adv_pts)
            base_rate = len(base_hit) / len(base_pts) if base_pts else 1.0
            adv_rate = len(adv_hit) / len(adv_pts) if adv_pts else 0.0
            score = round((0.6 * base_rate + 0.4 * adv_rate) * 100, 1)
            return score, base_hit, adv_hit, True
        except Exception:
            logger.exception("reranker 打分失败，本轮按默认分 50 处理")
            return 50.0, [], [], False

    def _mock_hit(self, answer: str, base_pts: list[str], adv_pts: list[str]
                  ) -> tuple[float, list[str], list[str], bool]:
        """确定性桩：分数随回答长度上升，便于冒烟测试覆盖 L1/L2/degrade 三条分支。"""
        n = len(answer.strip())
        score = round(min(95.0, n * 1.5), 1)
        base_hit = base_pts[: max(1, len(base_pts) // 2)] if score >= config.LEVEL_L1_MIN else []
        adv_hit = adv_pts[:1] if score >= config.LEVEL_L2_MIN and adv_pts else []
        return score, base_hit, adv_hit, True


# ============================================================
# 主观五维分
# ============================================================
class LLMScorer:
    def __init__(self, llm):
        self.llm = llm

    def score_round(self, ctx: dict) -> tuple[dict, Optional[str]]:
        """
        对**一整轮**（首答 + 追问往来）评一次五维分。
        返回 (分数 dict, 错误信息)。分数 dict 为空表示失败 —— 不要当 0 分用。

        为什么按整轮评而不是只评首答：「应变能力」本身就是看他被追问后的表现，
        只看首答的话这一维基本没有信息量。整轮评仍然是一轮一次调用，成本不变。
        """
        from app.core.prompts import ROUND_SCORING, SYSTEM_SCORER
        # 第一维的**标签**随题型变（行为素质题 = 岗位胜任力关联度），键恒为
        # config.DIMENSIONS[0] —— 见 config.py 里 dim1_label 的注释。
        # category 缺省时 dim1_label 回落到「技术水平」，与今天的行为一致。
        label = config.dim1_label(ctx.get("category", ""))
        user = ROUND_SCORING.safe_substitute(
            dim1_label=label,
            dim1_rubric=config.DIM1_RUBRIC[label],
            question=ctx.get("question", ""),
            difficulty=ctx.get("difficulty", ""),
            stage=ctx.get("stage", ""),
            base_points=ctx.get("base_points") or "（无）",
            adv_points=ctx.get("adv_points") or "（无）",
            qa_block=ctx.get("qa_block", ""),
            # 传的是**一句话摘要**（含 reranker 失败时的说明），不是一个裸数字。
            # 原来这里是 ctx.get("reranker_score", 50) —— 缺省值 50 意味着
            # reranker 挂掉时会凭空空降一个「客观命中 50 分」给评分模型当真。
            reranker_note=ctx.get("reranker_note") or "（无客观匹配信息）",
            # 表达客观测量（用时/语速/停顿/填充词）。缺省值与上面那条同款：
            # 宁可说"没有"，也不给一个假的数字。规则文字由 session.pace_note() 拼。
            pace_note=ctx.get("pace_note") or "（无客观测量数据）",
        )
        try:
            data = self.llm.chat_json(SYSTEM_SCORER, [{"role": "user", "content": user}])
        except Exception as e:
            logger.exception("五维评分调用失败")
            return {}, f"{type(e).__name__}: {e}"

        if not data:
            return {}, "模型未返回可解析的 JSON"

        d0 = config.DIMENSIONS[0]
        dims = {}
        for d in config.DIMENSIONS:
            v = data.get(d)
            if isinstance(v, (int, float)):
                dims[d] = round(float(v), 2)
        # 第一维：模型是按**本题型的标签**回键的（行为素质题回「岗位胜任力关联度」）。
        # 这里认全所有标签、归一到存储键 —— 下游（逐轮平均 / 权重加权 /
        # blindspot._avg_five_dim / 3 号）一律不用分情况。
        if d0 not in dims:
            for alias in config.dim1_labels():
                v = data.get(alias)
                if isinstance(v, (int, float)):
                    dims[d0] = round(float(v), 2)
                    break
        if not dims:
            return {}, "返回的 JSON 里没有可用的维度分"
        # 重建一遍，保证键序恒为 DIMENSIONS 序 —— 走上面别名分支时 d0 会排到最后，
        # 而 session.py 拼面试评价时是按 items() 顺序取的。
        dims = {d: dims[d] for d in config.DIMENSIONS if d in dims}
        return {
            "five_dim": dims,
            "comment": str(data.get("comment", "") or "")[:200],
            "errors": [str(x)[:200] for x in (data.get("errors") or []) if str(x).strip()],
        }, None


# ============================================================
# 判档：LLM 判「下一句往哪个方向问」
# ============================================================
class DepthJudge:
    """
    直接问模型：这个回答该往深里问、该追基础、还是该降难度？

    为什么不让 reranker 判：它在真实数据上不稳定 —— 只换一下 (得分点, 回答)
    的传参顺序，29% 的题判档就变，最大变动 100 分（详见 config.A11_JUDGE）。
    而 LLM 判档的准确性在同一个项目里已被独立验证过：它评的五维分把三档考生
    分成 91/60/27、档内波动 4 分以内。

    ⚠️ 本类**不做任何降级兜底**，判不出来就如实返回 ok=False ——
      由调用方（session.fuse_bands）决定退回 reranker。在这里偷偷返回一个
      "L1" 会把「模型没答上来」伪装成「模型判了 L1」，是同一个文件里
      「reranker 失败返回默认 50 分」那个坑的翻版。
    """
    # "swap" 是第 4 档，语义上**不是深浅判断而是类别判断**（"这个方向他没学过"），
    # 所以它不参与 fuse_bands 的深浅比较 —— 见 session.fuse_bands 里那条提前返回。
    # 放在最后只是为了让 raw.startswith 的匹配顺序好读；四个前缀互不包含。
    BANDS = ("L2", "L1", "degrade", "swap")

    def __init__(self, llm):
        self.llm = llm

    def judge(self, question: str, difficulty: str, stage: str,
              base_text: str, adv_text: str, answer: str,
              history: Optional[list[str]] = None
              ) -> tuple[Optional[str], str, bool]:
        """
        返回 (档位, 理由, 是否成功)。档位 ∈ L2/L1/degrade；失败时是 None。

        history —— 本题**之前**的回答（由旧到新）。第一次回答时是空/None，
                   此时提示词与加这个参数之前**逐字节相同**。
                   为什么必须传：原来判档只看这一次回答，于是考生把原话复述
                   一遍，它照样判 L2 —— 「没说新的」和一个「新答出来的 L2」
                   在它眼里长得一模一样。见 config.A11_REPEAT_GUARD。
        """
        from app.core.prompts import (JUDGE_DEPTH, JUDGE_HISTORY_BLOCK,
                                      JUDGE_HISTORY_EMPTY, SYSTEM_JUDGE)
        hist = [h for h in (history or []) if h and h.strip()]
        # 只回看最近 JUDGE_HISTORY_MAX 次；但编号用**真实次序**（第 1 次就是第 1 次），
        # 否则模型会以为历史一共只有这么两条。
        shown = list(enumerate(hist, 1))[-config.JUDGE_HISTORY_MAX:]
        history_block = (JUDGE_HISTORY_BLOCK.safe_substitute(
            history="\n\n".join(
                f"第 {i} 次：{qb.truncate(h, config.JUDGE_ANSWER_TRUNCATE)}"
                for i, h in shown))
            if shown else JUDGE_HISTORY_EMPTY)
        user = JUDGE_DEPTH.safe_substitute(
            attempt_note=("考生刚答完第一次" if not shown
                          else f"考生这是在回答第 {len(hist) + 1} 次"),
            history_block=history_block,
            question=question,
            difficulty=difficulty or "medium",
            stage=stage or "核心考察",
            base_points=qb.truncate(base_text, config.POINT_TRUNCATE) or "（无）",
            adv_points=qb.truncate(adv_text, config.POINT_TRUNCATE) or "（无）",
            answer=qb.truncate(answer, config.JUDGE_ANSWER_TRUNCATE),
        )
        try:
            # 用评分的低温度：判档要的是稳定，不是文采
            data = self.llm.chat_json(SYSTEM_JUDGE, [{"role": "user", "content": user}],
                                      temperature=config.LLM_TEMPERATURE_SCORE)
        except Exception:
            logger.exception("LLM 判档调用失败，本轮退回 reranker 判档")
            return None, "", False

        if not data:
            return None, "", False
        raw = str(data.get("depth", "") or "").strip().upper()
        # 容错：模型可能回 "L2"、也可能是 "l2 原理深挖" 或 "L2。" 这种。
        # ⚠️ 两边都要 .upper() 再比 —— raw 已经被转成大写，拿它去 startswith
        #    小写的 "degrade" 永远为假。踩过：90 条真实回答里 30 条被判成
        #    「无法识别」，而那 30 条正好全是该 degrade 的弱考生 —— 等于判档
        #    在「该降难度」这条分支上完全失效，且失败是静默的（退回 reranker）。
        #    返回的是 BANDS 里的**规范小写值**，不是 raw。
        band = next((b for b in self.BANDS if raw.startswith(b.upper())), None)
        if band is None:
            logger.warning("LLM 判档返回了无法识别的 depth=%r，本轮退回 reranker", raw)
            return None, "", False
        return band, str(data.get("why", "") or "")[:60], True


def _make_judge(llm) -> Optional["DepthJudge"]:
    """
    建判档器；三种情况下返回 None。

    ⚠️ `config.LLM_MOCK` 这一条是硬约束，不是保守：冒烟测试跑在
       LLM_MOCK=1 + RERANKER_MOCK=1 下，用桩的固定分数走 decide_action 的
       三条分支，并断言收尾轮/降级轮的 system。桩模型返回的不是可解析的
       depth JSON，若不在这里关掉，判档会把每一次动作决策都改掉 ——
       带 `if` 的那些断言会成片地响（别在这里写死条数：它随 KG/RAG 开关浮动，
       而且已经涨过两轮了）。
       关掉之后判档不参与，融合结果恒等于 reranker 那一档，端到端行为与
       加这个功能之前逐字节相同（关掉 ≠ 不测：判档的纯函数部分另有冒烟断言）。
    """
    if llm is None or config.LLM_MOCK or not config.A11_JUDGE:
        return None
    return DepthJudge(llm)


# ============================================================
# 门面
# ============================================================
class Scorer:
    def __init__(self, llm=None):
        self.reranker = RerankerScorer()
        self.llm = LLMScorer(llm) if llm is not None else None
        # 判档器与主观评分器同生共死：同一个 llm、同一道门（_make_judge 里
        # 桩模式直接返回 None）。为 None 时 session 侧退回纯 reranker 判档。
        self.judge = _make_judge(llm)

    def warmup(self) -> None:
        self.reranker.warmup()

    @property
    def ready(self) -> bool:
        return self.reranker.ready

    def score_answer(self, answer: str, base_text: str, adv_text: str) -> dict:
        score, base_hit, adv_hit, ok = self.reranker.hit_scores(answer, base_text, adv_text)
        # 未命中的点也算出来一起传下去。理由：评分模型需要复核「判为没中」的那些 ——
        # 考生用自己的话把意思讲对了、跟得分点字面不重叠，是 reranker 的经典假阴性，
        # 只给命中的点，模型就没有翻案的机会。数据本来就有，只是以前丢掉了。
        base_all = qb.split_points(base_text)
        adv_all = qb.split_points(adv_text)
        return {"reranker_score": score,
                "base_hit": base_hit, "adv_hit": adv_hit,
                "base_miss": [p for p in base_all if p not in base_hit],
                "adv_miss": [p for p in adv_all if p not in adv_hit],
                "reranker_ok": ok}


_scorer: Optional[Scorer] = None
_scorer_lock = threading.Lock()


def get_scorer(llm=None) -> Scorer:
    """取全局评分器；传了 llm 就顺手把主观评分器接上（幂等，可重复调）。

    注意这里为什么把「接 llm」的判断放进锁内、而不是写成外层 if/elif：
    预热线程（main.py 的 _warmup_async）会先调 get_scorer() 建出一个 llm=None
    的实例。若会话线程的外层判断在**那之前**就读到 None，它会走 `if` 分支并
    阻塞在锁上；等预热线程出锁后，内层复查发现实例已存在就跳过了 —— 而
    `elif` 属于外层 if，此时根本不会被求值。结果会话拿到一个 .llm 永远为
    None 的评分器，整场 /finish 报「评分器未初始化」。
    这不是理论风险：交付样例的第一版就是这么挂掉的（见 README 已知问题）。
    """
    global _scorer
    with _scorer_lock:
        if _scorer is None:
            _scorer = Scorer(llm=llm)
        elif llm is not None and _scorer.llm is None:
            _scorer.llm = LLMScorer(llm)
        # 判档器补挂：与上面那个 elif 同一个理由 —— 预热线程可能先建出一个
        # llm=None 的实例。放在 if/elif **之外**、但同在锁内，所以既不会被
        # 那个 if/elif 结构漏掉，也不会被两个线程各建一个。
        if _scorer.judge is None and _scorer.llm is not None:
            _scorer.judge = _make_judge(_scorer.llm.llm)
        return _scorer
