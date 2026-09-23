# -*- coding: utf-8 -*-
"""
kg.py · 知识图谱只读索引
============================================================
产出三件事，全部是**加法**，一件都不参与评分：

  1. 出题避重 —— 整场累计「已考过的知识点」，抽新题时避开重叠度高的候选
  2. 追问深挖 —— 从共现图里取「可拓展的关联方向」当提示
  3. 盲区诊断 —— 面试结束时按知识点/领域汇总哪些没考出来（见 blindspot.py）

产物结构（实测，不是猜的）：
    {'graph': nx.Graph(无向), 'questions': dict(5012), 'kp_names': dict(1340)}
    questions[qid] 自带 知识点 / 知识点层级 / 题目 / 难度 / 岗位 ……
    graph 边 4 类：has_kw / has_kp / cooccur_kw / cooccur_kp

⚠️ 本文件是 networkx 与 pickle 唯一出现的地方。别的模块一律不碰图谱。

⚠️ 图谱的知识点是**不全的**（这条决定了整个设计）：
    按 java 2146 题实测 —— 主库 kp 集合与图谱 kp 集合相等的只有 1207 题，
    不一致 939 题（43%），图谱 kp 为空列表的有 444 题（21%）。
    所以**绝不能「图谱优先、主库兜底」**：那样写会有 21% 的题拿到零个知识点、
    避重静默失效。本模块一律**取并集**，主库是真值源（100% 覆盖），
    图谱只做增量富化 —— 见 kp_map()。
"""
import os
import pickle
import re
import threading
from typing import Optional

from app import config
from app.logging_conf import get_logger

logger = get_logger(__name__)

# 拿不到 domain 时的兜底名。3 号按这个桶的名字取值，不是空串 —— 空串会让
# groupby 把「不知道」和「字段缺失」混成一个东西。
UNCLASSIFIED = "未归类"

_Q_PREFIX = "Q:"
_KP_PREFIX = "KP:"

# 问句式名字的形态判别。
#
# 为什么不能只靠长度：本来的设计是「名字 > 24 字就丢」，想滤掉那个
# 「线程池的核心参数有哪些线程池的执行流程是怎样的」。但它**只有 23 字**，
# 长度阈值根本拦不住 —— 代理指标失效。实测 kp_names 里这种问句形态的名字
# 有 88 个（6.6%），全部是「Redis 如何解决集群情况下分布式锁的可靠性」
# 「构造方法有哪些特点是否可被 override」这种。
#
# 为什么必须滤：这个名字要填进 prompt 的【可拓展的关联方向】槽位，那个槽位
# 明确写着「只是方向，不要照念，也不要变成一道新题」。把一句现成的问句放进去，
# 等于把最容易被照念的东西放在最容易被照念的位置上。
# 过度过滤的代价只是少几个备选方向（我们只要 3 个），而漏过的代价是
# 面试官当场念出一道新题 —— 两边不对称，所以宁严勿宽。
_RE_QUESTIONISH = re.compile(
    r"[？?]|有哪些|哪些|是什么|什么是|是怎样的|怎么|如何|为什么|多少|哪一个|了解吗")


def _is_usable_name(name: str) -> bool:
    """这个名字能不能当「关联方向」给面试官看。长度与形态两道都要过。"""
    if not name:
        return False
    if len(name) > config.DEEPEN_NAME_MAX:
        return False
    return not _RE_QUESTIONISH.search(name)


def _f(x, default: float = 1.0) -> float:
    """
    把边权重转成 float。

    ⚠️ pickle 里的权重是**混合类型** —— 实测同一张图里既有 '1.0' 字符串也有
    1.0 浮点。直接参与算术会出事：'1.0' + 0.2 抛 TypeError，而 '1.0' * 2
    更糟 —— 它不报错，静默拼成 '1.01.0'。所以每个权重都必须过这一道。
    """
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def kp_map_bank(knowledge_points: Optional[list[dict]]) -> dict[str, str]:
    """
    主库侧「关联知识点」→ {kp_id: 标题}。空 id 丢掉。

    为什么单独抽出来：图谱侧（`KGIndex.kp_map`）和**图谱不可用时的退路**
    （`blindspot._kp_map`）必须给出**同一份**主库视图 —— 否则同一个 kp 会出现
    「避重说考过、盲区说没考过」两种说法。两份手抄的实现迟早会漂移。

    空 id 必须丢：主库「关联知识点」某一行没有 '|' 时会解析出 `id=""`，
    放它进来会让所有这类题共享同一个假 kp，避重立刻失效。
    """
    out: dict[str, str] = {}
    for kp in (knowledge_points or []):
        kid = str((kp or {}).get("id") or "").strip()
        if not kid or kid in out:
            continue
        out[kid] = str((kp or {}).get("title") or "").strip()
    return out


class KGIndex:
    """图谱的内存只读索引：加载时把每轮都要用的东西全部预计算一次。

    预计算换来的好处是把每轮成本压到纯 dict 查表 —— 否则每抽一次题要遍历
    几十条边、每轮省下的那点内存远不值这个开销。
    """

    def __init__(self, data: dict):
        graph = data.get("graph")
        if graph is None:
            raise ValueError("图谱产物缺少 'graph' 键")
        self.graph = graph
        self.questions: dict = data.get("questions") or {}
        kp_names: dict = data.get("kp_names") or {}

        # ---- kp_id -> 名字 ----
        # 实测 kp_names 的键集与 domain 表的键集**完全相同**（都是 1340），
        # 所以一张表同时给出名字和层级，不用查两次。
        self._kp_name: dict[str, str] = {k: str(v) for k, v in kp_names.items()}

        # ---- kp_id -> (domain, subclass) ----
        # 直接从 questions[*]['知识点层级'] 取 —— 它已经是一份解好的映射，
        # 不必遍历图。图谱的 knowledge 节点再补一层（它是那 30 个额外的来源）。
        self._kp_level: dict[str, tuple[str, str]] = {}
        for v in self.questions.values():
            for kp, lv in (v.get("知识点层级") or {}).items():
                if kp in self._kp_level:
                    continue
                if isinstance(lv, (list, tuple)) and len(lv) == 2:
                    self._kp_level[kp] = (str(lv[0]), str(lv[1]))

        # ---- qid -> 图谱侧 kp id 列表 ----
        self._q_kps: dict[str, tuple[str, ...]] = {}
        for qid, v in self.questions.items():
            kps = v.get("知识点") or []
            if kps:
                self._q_kps[qid] = tuple(str(x) for x in kps)

        # ---- qid -> {kp_id: has_kp 权重}、kp 层级、共现表 ----
        # 三类边一次遍历分派完，比分别扫三遍图省事也省时。
        self._q_kpw: dict[str, dict[str, float]] = {}
        self._cooc_raw: dict[str, list[tuple[str, float]]] = {}
        n_edge = {"has_kp": 0, "cooccur_kp": 0}
        for u, v, a in graph.edges(data=True):
            t = a.get("type")
            if t == "has_kp":
                qid = u[len(_Q_PREFIX):] if u.startswith(_Q_PREFIX) else u
                kp = v[len(_KP_PREFIX):] if v.startswith(_KP_PREFIX) else v
                self._q_kpw.setdefault(qid, {})[kp] = _f(a.get("weight"))
                n_edge["has_kp"] += 1
            elif t == "cooccur_kp":
                # PMI 是对称的，无向边在语义上就是对的表示 —— 不是缺陷。
                # 真正长得过宽的是 cooccur_kw（24870 条边），而我们**不用它**。
                ku = u[len(_KP_PREFIX):] if u.startswith(_KP_PREFIX) else u
                kv = v[len(_KP_PREFIX):] if v.startswith(_KP_PREFIX) else v
                w = _f(a.get("weight"))
                self._cooc_raw.setdefault(ku, []).append((kv, w))
                self._cooc_raw.setdefault(kv, []).append((ku, w))
                n_edge["cooccur_kp"] += 1

        # 图谱 knowledge 节点补 domain（放在 q 侧之后，不覆盖已有值）
        for n, a in graph.nodes(data=True):
            if a.get("type") != "knowledge":
                continue
            kp = a.get("kp_id")
            if kp and kp not in self._kp_level and a.get("domain"):
                self._kp_level[kp] = (str(a["domain"]), str(a.get("subclass") or ""))

        # ---- 共现表：预过滤 + 预排序 ----
        # 只留权重 >= COOCCUR_MIN_W 的，按 (-权重, id) 降序 —— 排序键带 id 是为了
        # 权重相同时顺序**稳定**，否则同一次会话里两次调用可能给出不同的方向。
        # 2812 条边过滤后总共就这么点，全存下来比按 TOPN 截断更划算：
        # 截断留到查询时做，排除掉已考过的点之后还能有替补。
        self._cooc: dict[str, list[tuple[str, float]]] = {}
        for kp, nbs in self._cooc_raw.items():
            kept = [(b, w) for b, w in nbs if w >= config.COOCCUR_MIN_W]
            if kept:
                kept.sort(key=lambda bw: (-bw[1], bw[0]))
                self._cooc[kp] = kept

        # ---- 名字 -> kp_id，**只收唯一的** ----
        # 多义标题（比如「数据库」）宁可查不到，也不要错归到某一个 id 上 ——
        # 错归会让盲区诊断把两个不同的知识点报成同一个。
        cnt: dict[str, int] = {}
        for nm in self._kp_name.values():
            cnt[nm] = cnt.get(nm, 0) + 1
        self._name2id: dict[str, str] = {
            nm: kp for kp, nm in self._kp_name.items() if cnt.get(nm) == 1
        }

        self._n_node = graph.number_of_nodes()
        self._n_edge = graph.number_of_edges()

    # ---------- 加载 ----------
    @classmethod
    def load(cls, path: str) -> "KGIndex":
        if not os.path.exists(path):
            raise FileNotFoundError(f"知识图谱文件不存在：{path}")
        with open(path, "rb") as f:
            data = pickle.load(f)          # ⚠️ pickle 只许读可信文件
        if not isinstance(data, dict):
            raise ValueError(f"图谱产物格式异常（应为 dict）：{path}")
        return cls(data)

    # ---------- 查询 ----------
    def kps_of(self, qid: str) -> tuple[str, ...]:
        """图谱侧的知识点 id（可能是空的 —— 21% 的题就是空的，这是常态）。"""
        return self._q_kps.get(qid, ())

    def kp_weight(self, qid: str, kp_id: str) -> float:
        """
        has_kp 边权重：1.2 / 1.0 / 0.8。
        语义就是题目自带的考点优先级 —— 高频必考 / 常规 / 拓展。
        主库侧的知识点没有权重（库里没这个字段），缺省 1.0。
        """
        return self._q_kpw.get(qid, {}).get(kp_id, 1.0)

    def kp_name(self, kp_id: str) -> str:
        """kp_id -> 中文名。查不到就返回空串（调用方自行决定要不要退回 id）。"""
        return self._kp_name.get(kp_id, "")

    def level_of(self, kp_id: str) -> tuple[str, str]:
        """kp_id -> (domain, subclass)，未知返回 (UNCLASSIFIED, '')。"""
        return self._kp_level.get(kp_id, (UNCLASSIFIED, ""))

    def level_of_name(self, title: str) -> Optional[tuple[str, str]]:
        """
        标题 -> (domain, subclass)。**只在标题唯一时才生效** ——
        多义标题宁可返回 None 让它落到「未归类」，也不要错归。
        """
        kp = self._name2id.get((title or "").strip())
        if not kp:
            return None
        return self._kp_level.get(kp)

    def cooccur(self, kp_id: str) -> list[tuple[str, float]]:
        """共现邻居，已过滤（>= COOCCUR_MIN_W）并按权重降序。"""
        return self._cooc.get(kp_id, [])

    def kp_map(self, qid: str, knowledge_points: Optional[list[dict]]) -> dict[str, dict]:
        """
        **主库 ∪ 图谱** 的知识点并集 —— 本模块最重要的一个函数。

        避重与盲区诊断**必须共用这一个函数**，否则同一个 kp 在两条路径上
        会有两种说法（"避重说考过、盲区说没考过"），那种不一致查起来极痛苦。

        返回 {kp_id: {"title": str, "weight": float, "src": "bank"|"kg"|"both"}}
        title 的兜底链：主库标题 → kp_names → kp_id 本身。**永远不为空**。
        """
        out: dict[str, dict] = {}
        bank_titles = kp_map_bank(knowledge_points)
        kg_ids = self.kps_of(qid)
        for kid in list(bank_titles) + [k for k in kg_ids if k not in bank_titles]:
            in_bank = kid in bank_titles
            in_kg = kid in kg_ids
            title = bank_titles.get(kid) or self.kp_name(kid) or kid
            out[kid] = {
                "title": title,
                "weight": self.kp_weight(qid, kid),
                "src": "both" if (in_bank and in_kg) else ("bank" if in_bank else "kg"),
            }
        return out

    # ---------- 给 /health 与日志 ----------
    def stats(self) -> dict:
        return {
            "nodes": self._n_node,
            "edges": self._n_edge,
            "questions": len(self.questions),
            "kp": len(self._kp_name),
            "kp_with_domain": len(self._kp_level),
            "cooccur_nodes": len(self._cooc),
        }


# ============================================================
# 覆盖率累计（出题避重用）
# ============================================================
def overlap_weights(kp_map: dict) -> dict[str, float]:
    """
    kp_map → {kp_id: 权重}，喂给 CoverageTracker。

    KP_OVERLAP_WEIGHTED=0 时全部按 1.0（退化成纯计数），留个后门方便对比效果。
    """
    if not config.KP_OVERLAP_WEIGHTED:
        return {k: 1.0 for k in kp_map}
    return {k: max(0.0, float(v.get("weight") or 1.0)) for k, v in kp_map.items()}


class CoverageTracker:
    """
    整场累计「已经考过哪些知识点」。

    ⚠️ 重叠度的分母是**候选自己**（Σw(cand)），不是全集。这样一道知识点少的题
    不会因为「能命中的少」而被系统性惩罚 —— 它答的是「我这个候选题有多少
    比例是重复的」，这正是我们要问的问题。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}
        self._rounds: dict[str, list[int]] = {}

    def overlap(self, kp_w: dict[str, float]) -> float:
        """候选题的已考重叠度 0~1。空 dict 返回 0.0（没知识点 = 不算重复）。"""
        tot = sum(kp_w.values())
        if tot <= 0:
            return 0.0
        with self._lock:
            hit = sum(w for kp, w in kp_w.items() if kp in self._seen)
        return round(hit / tot, 4)

    def add(self, kp_w: dict[str, float], round_no: int) -> None:
        with self._lock:
            for kp, w in kp_w.items():
                self._seen[kp] = self._seen.get(kp, 0.0) + w
                self._rounds.setdefault(kp, []).append(round_no)

    def remove(self, kp_w: dict[str, float], round_no: int) -> None:
        """
        撤回一次 add。**只给换题用**：被换掉的那道题的考点从没被真正考过，
        留在 _seen 里会让避重与盲区诊断都以为"这个考点考过了"。

        ⚠️ 按 round_no 精确退，而不是无脑减权重：同一个 kp 可能被多轮 add 过，
        只能退掉**属于这一轮**的那一份。权重按加进来的原值减回去，算术上严格互逆
        （浮点残差用 1e-9 兜底清零）。
        """
        with self._lock:
            for kp, w in kp_w.items():
                if kp not in self._seen:
                    continue
                left = self._seen[kp] - w
                if left <= 1e-9:
                    self._seen.pop(kp, None)
                else:
                    self._seen[kp] = left
                rounds = self._rounds.get(kp)
                if rounds and round_no in rounds:
                    rounds.remove(round_no)
                    if not rounds:
                        self._rounds.pop(kp, None)

    def seen_ids(self) -> set[str]:
        with self._lock:
            return set(self._seen)

    def rounds_of(self, kp_id: str) -> list[int]:
        with self._lock:
            return list(self._rounds.get(kp_id, ()))

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._seen)


# ============================================================
# 追问深挖方向（纯函数，便于单测）
# ============================================================
def deepen_directions(seeds: dict[str, float], covered: set[str],
                      idx: Optional["KGIndex"]) -> list[dict]:
    """
    从共现图里给本题挑几个「可拓展的关联方向」。

    seeds   —— 本题的知识点 {kp_id: 权重}
    covered —— 本场**之前**已经考过的 kp（不含本题，调用时尚未 add）
    idx     —— 图谱索引；None 时返回空列表（图谱关掉/加载失败）

    三重过滤缺一不可：
      1. 权重 >= COOCCUR_MIN_W（在 cooccur() 里已做）—— 砍枢纽的长尾弱关联
      2. 名字可当方向用（_is_usable_name：形态 + 长度）—— 滤掉「名字本身就是
         一道题」的噪声节点。实测 kp_names 里有 88 个这种名字（6.6%），
         最典型的是「线程池的核心参数有哪些线程池的执行流程是怎样的」（度 42）。
         把它当方向喂过去，等于直接给面试官出了一道新题。
      3. 名字必须在 kp_names 里 —— 查不到名字的 id 对模型毫无意义
    """
    if idx is None or not seeds:
        return []

    best: dict[str, float] = {}
    for seed in seeds:
        for nb, w in idx.cooccur(seed)[:config.COOCCUR_TOPN]:
            if nb in covered or nb in seeds:
                continue
            # 多路径到达取**最大**权重：从两个不同种子都能走到，说明关联更强
            if w > best.get(nb, 0.0):
                best[nb] = w

    ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[dict] = []
    for kp_id, w in ranked:
        name = idx.kp_name(kp_id)
        if not _is_usable_name(name):
            continue
        out.append({"kp_id": kp_id, "title": name, "weight": round(w, 4)})
        if len(out) >= config.DEEPEN_TOPN:
            break
    return out


# ============================================================
# 单例（照抄 scoring.py:237-258 的双检锁）
# ============================================================
_kg: Optional[KGIndex] = None
_kg_lock = threading.Lock()
_kg_failed = False
_kg_error = ""


def get_kg() -> Optional[KGIndex]:
    """
    取全局图谱索引。**失败返回 None，绝不抛** —— 这是本模块的降级契约。

    为什么是 None 而不是抛异常：图谱是纯增量功能（避重/深挖/盲区），
    它挂掉不该让面试开不起来。若改成抛，每个调用点都得写 try/except，
    那才是真正的脆弱 —— 漏一处就是一个 500。

    _kg_failed 闩防止反复重试：加载失败通常是路径错/文件损坏，
    每次 /next 都重试一遍只会让每一轮白等。
    """
    global _kg, _kg_failed, _kg_error
    if not config.A11_KG:
        return None
    if _kg is not None:
        return _kg
    with _kg_lock:
        if _kg is not None:
            return _kg
        if _kg_failed:
            return None
        try:
            _kg = KGIndex.load(config.KG_PATH)
            _kg_error = ""
            logger.info("知识图谱已加载 %s", _kg.stats())
        except Exception as e:
            _kg_failed = True
            _kg_error = f"{type(e).__name__}: {e}"
            logger.error("知识图谱加载失败，本进程内永久降级（避重/深挖/盲区全部关闭）：%s",
                         _kg_error)
        return _kg


def kg_status() -> dict:
    """
    /health 用。

    ⚠️ 必须能区分「关掉」和「失败」：
       A11_KG=0      → enabled=False, ready=False, error=""      ← 是配置，不是故障
       路径不存在/failed → enabled=True,  ready=False, error="FileNotFoundError: …"
    把两者混成一个 False，运维就分不清「我没开」和「它坏了」。
    """
    return {
        "kg_enabled": config.A11_KG,
        "kg_ready": _kg is not None,
        "kg_error": _kg_error,
        "kg_nodes": (_kg.stats()["nodes"] if _kg is not None else 0),
    }
