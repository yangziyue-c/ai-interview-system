# -*- coding: utf-8 -*-
r"""
resources.py · 薄弱项 → 学习资源推荐（赛题 4a「自动推荐针对性的学习资源」）
============================================================
把**左边**（`blindspot.diagnose()` 算出来的薄弱知识点）接到**右边**
（学习资源样例文件里的资源条目）上。纯结构化 + 一次只读的文件加载，**不加任何 LLM 调用**。

设计稿：`D:\A11-Data\学习资源推荐设计.md`。四条规则逐一对应：
  §4.1 kp_id 精确匹配  → `ResourceIndex.by_id`
  §4.2 考点名归一化兜底 → `ResourceIndex.by_title`（归一后**精确**相等，不做模糊匹配）
  §4.3 一致性校验       → `_consistent()`：领域/子类不一致就不给资源、只给得分点原文
  §4.4 宁缺毋滥         → 没命中就退回「得分点级」，绝不拿别的考点顶上
  §4.5 排序             → `score = 薄弱度 × (0.6 + 0.4×考频) × 可学性`

⚠️ 三条口径约定（改之前先读）：

  1. **只推 `hit is False`（有客观依据地判他没答到）**，不推 `hit is None`。
     设计稿 §2 那张表把 `hit=false` 写成了「即 kp_unknown」，那是笔误 ——
     `blindspot.py:200-208` 里 `kp_unknown` 对应的是 `hit is None`（没答 / 判不了）。
     「没考 ≠ 不会」，所以 `hit is None` 一律不进推荐，只进 blindspots 的
     「待覆盖」那一档。这条**照代码、不照设计稿**。

  2. **推荐里的资源文本会随 `raw` 发给前端** —— 与现状一致（`per_round.base_miss`
     本来就把得分点原文发给前端了），但只在 `/finish` / `/result` 里出现。
     `diagnose()` 只在这两处被调用（`session.py:1635`），所以调用点是天然封住的；
     冒烟测试里另有一条断言守着「`/chat` 期间不出现」。

  3. **加载失败一律静默降级成空列表**，理由写进 `summary.resource_error`。
     与 `kg` / `rag` / `asr` 同一条约定：旁路挂掉不该让整份报告拿不到。
"""
import json
import os
import threading
from typing import Optional

from app import config
from app.core import kb as kbmod          # 真知识库那一层（只读、懒加载、绝不抛）
from app.core.question_bank import norm_kp_title
from app.logging_conf import get_logger

logger = get_logger(__name__)

# 资源样例里「样例」那一层的四个取材字段（与设计稿 §5 的输出契约同名）：
#   考点讲解      ← 考点级（25 个考点都有）
#   优秀回答范例  ← 代表题的答案变体层核心答案
#   拉开差距      ← 代表题的进阶得分点（list）
#   常见卡点      ← 代表题的降级策略
# ⚠️ 只取**代表题**的那份，不把两道题的范例混起来 —— 混起来会读成一个人的回答。
_KEY_TALK = "考点讲解"
_KEY_MODEL = "优秀回答范例"
_KEY_GAP = "拉开差距"
_KEY_TRAP = "常见卡点（面试官降级时会怎么拆）"

# ---- 平索引（2026-09-25 加）：`题目范文` 顶层键 ----
# 为什么要有它：原先范文只挂在「考点 → 样例[]」上，覆盖率天花板 = 被选中的考点 ×2 题，
# 而题库里有 **1,110 道题一个考点都不挂** —— 那些题**永远取不到**范例（`/model_answer`
# 是 kp_id 中介的）。平索引按 `题目ID` 直接铺满 5,012 道题，才谈得上「每题一条」。
# ⚠️ 它**不是**第二份事实源：`样例[].优秀回答范例` 与它由**同一份缓存**填，
#    生成脚本那边有断言守着两处一致（同一条题的范文必须逐字相同）。
_KEY_PERQ = "题目范文"
# kind 是**闭集**，只有两个值。它不是装饰 —— 它决定考生看到的那段文字
# 是「一道真题的优秀范例」还是「我们为一道模板题编的示范」，两者不能混。
_KIND_ANSWER = "范文"
_KIND_DEMO = "示范作答"
KINDS = (_KIND_ANSWER, _KIND_DEMO)
# 示范作答必须带这句口径，**缺它就是拿虚构示例冒充范文给考生**（会让人背一段假经历）。
# 与生成脚本 `gen_范例重写.py` 里 `USER_DEMO` 的告示同源，但**这份是给考生看的**，
# 所以要短、要直白、要能照着做（「请替换为你自己的真实经历」）。
NOTE_DEMO = ("这道题主库给的是答题结构（STAR 骨架），不是判分内容；"
             "下文示例经历为**虚构的通用场景**，请替换为你自己的真实经历。")

# 匹配来源，写进每条推荐里，便于事后复盘到底是哪条路命中的
SRC_ID = "kp_id"
SRC_TITLE = "title"
SRC_QUESTION = "question"


# ============================================================
# 归一化（§4.2）
# ============================================================
# 归一化**只有一份**，在数据层 `question_bank.norm_kp_title`——专项练习选题
# 也要用同一个键去比对考点名，两处各写一份迟早分叉（「同一个考点名在两条路上
# 归一出不同的键」是最难查的一类不一致）。这里只做个别名，不复制实现。
#
# **不做模糊匹配**：样例文件已经把噪声名、韩文名、无汉字名、过长名剔过一遍
# （`剔除计数` 里有数字），模糊匹配等于把它们放回来（设计稿 §4.2）。
_norm = norm_kp_title


# ============================================================
# 资源索引（进程内加载一次）
# ============================================================
class ResourceIndex:
    """资源样例文件的只读索引。`error` 非空即「没得用」，`available` 是唯一判据。"""

    def __init__(self, path: Optional[str] = None, data: Optional[dict] = None,
                 error: str = ""):
        self.path = path
        self.error = error
        self.meta: dict = {}          # 说明 / 口径 / 已知局限…（原样留着，供 check_env 打印）
        self.by_id: dict[str, dict] = {}
        self.by_title: dict[str, dict] = {}
        self.dup_titles: set = set()  # 归一后同名多义的标题 —— 一律弃用标题键
        # 平索引：题目ID → {"范文": str, "kind": str}。**只有正文非空的才进来**
        # —— 空串进来会让「有没有范文」这个判断变成假的「有」。
        self.by_question: dict[str, dict] = {}
        if data:
            self._build(data)

    # ---------- 构建 ----------
    def _build(self, data: dict) -> None:
        # ⚠️ `题目范文` 也要排除：`meta` 是**给人看的**（`check_env.py` 会打印它），
        #    而平索引是 5,012 条、约 4 MB —— 放进去等于每次打印环境信息都刷一屏
        #    正文，还可能被误当成「说明性字段」写进日志。它走 `by_question`，
        #    不进 `meta`。
        self.meta = {k: v for k, v in data.items()
                     if k not in ("岗位", _KEY_PERQ)}
        for job in data.get("岗位", []) or []:
            for e in job.get("考点", []) or []:
                rec = self._entry(e, job.get("岗位", ""))
                if rec["kp_id"]:
                    self.by_id[rec["kp_id"]] = rec
                nt = _norm(rec["title"])
                if not nt:
                    continue
                old = self.by_title.get(nt)
                if old is not None and old is not rec:
                    # 同名多义：宁可两个都不用，也不赌哪一个对（同 kg._level_of 的取舍）
                    self.dup_titles.add(nt)
                else:
                    self.by_title[nt] = rec
        for nt in self.dup_titles:
            self.by_title.pop(nt, None)
        # 平索引（`题目范文`）。**读的是顶层键，与 `岗位→考点→样例` 那棵树无关** ——
        # 这正是它存在的意义：覆盖那 1,110 道不挂任何考点的题。
        raw = data.get(_KEY_PERQ)
        bad_kind = 0
        if isinstance(raw, dict):
            for qid, r in raw.items():
                if not isinstance(r, dict):
                    continue
                text = (r.get("范文") or "").strip()
                if not text:
                    continue        # 空正文不进索引（见 __init__ 的注释）
                kind = r.get("kind")
                if kind not in KINDS:
                    # ⚠️ 认不出来的一律当**范文**，但**要吭声** —— 静默把
                    #    「示范作答」当「范文」发出去，是这一波最严重的一种失败
                    #    （考生会把虚构经历当成真范例背下来）。生成脚本那边有硬断言，
                    #    走到这里说明文件被手工改过。
                    bad_kind += 1
                    kind = _KIND_ANSWER
                self.by_question[str(qid)] = {"范文": text, "kind": kind}
        if bad_kind:
            logger.warning("题目范文 里有 %d 条 kind 取值非法（已按「%s」处理）—— "
                           "这份文件应当由 gen_学习资源样例.py 生成，别手工改",
                           bad_kind, _KIND_ANSWER)

    @staticmethod
    def _entry(e: dict, job: str) -> dict:
        """一条资源条目 → 内部结构。字段名一律保留原文，不翻译、不改写。"""
        samples = [s for s in (e.get("样例") or []) if isinstance(s, dict)]
        return {
            "kp_id": (e.get("kp_id") or "").strip(),
            "title": (e.get("考点") or "").strip(),
            "job": job or (e.get("job") or "").strip(),
            "domain": (e.get("领域") or "").strip(),
            "subclass": (e.get("子类") or "").strip(),
            "题量": e.get("题量"),
            "同组题量": e.get("同组题量"),
            "考点讲解": e.get("考点讲解") or "",
            "相关题目": list(e.get("相关题目") or []),
            "样例": samples,
        }

    @property
    def available(self) -> bool:
        return (not self.error) and bool(self.by_id or self.by_title)

    @property
    def kp_count(self) -> int:
        return len(self.by_id) or len(self.by_title)

    # ---------- 查（§4.1 → §4.2）----------
    def lookup(self, kp_id: str, title: str) -> tuple[Optional[dict], str]:
        rec = self.by_id.get((kp_id or "").strip())
        if rec is not None:
            return rec, SRC_ID
        nt = _norm(title)
        if nt and nt not in self.dup_titles:
            rec = self.by_title.get(nt)
            if rec is not None:
                return rec, SRC_TITLE
        return None, ""

    # ---------- 取材 ----------
    def _pick_sample(self, rec: dict, question_ids: list) -> Optional[dict]:
        """
        两道代表题里挑一道：**优先挑考生真答过的那道**（问的同一道题，范例才对得上），
        没答过就用第一道。一律只取一道 —— 两道混起来会读成一个人的回答。

        ⚠️ 2026-09-25 从 `@staticmethod` 改成实例方法：挑出来的这条要**补上 `kind`**，
           而 kind 只在平索引里（`样例[]` 那份不存它，避免同一件事有两个副本）。
           调用点写法 `idx._pick_sample(...)` 一个字没变。
        """
        if not rec["样例"]:
            return None
        want = {str(q) for q in (question_ids or [])}
        s = None
        for x in rec["样例"]:
            if str(x.get("题目ID", "")) in want:
                s = x
                break
        if s is None:
            s = rec["样例"][0]
        return self.with_kind(s)

    def with_kind(self, sample: Optional[dict]) -> Optional[dict]:
        """给一条 `样例[]` 补上 `kind`（**浅拷贝**，不改原文件那份 dict）。

        `kind` 的**唯一**事实源是平索引；样例里若也写了一份，以平索引为准 ——
        两个副本意见不合时，宁可都听那一个权威的，也不要「看谁先读到」。
        """
        if not isinstance(sample, dict):
            return None
        out = dict(sample)
        rec = self.by_question.get(str(sample.get("题目ID", "") or ""))
        if rec is not None:
            out["kind"] = rec["kind"]
        elif "kind" not in out:
            # 平索引里没有这道题 ⇒ 这是**旧文件**（或手工拼的样例）留下的条目。
            # 2026-09-25 起 `样例[]` 由生成器与平索引**同源填充**，正常路径走不到这里；
            # 落到这里默认「范文」：偏保守的一档 —— 宁可少标一个提醒，也不给真题
            # 平白贴上「示范作答」的帽子。
            out["kind"] = _KIND_ANSWER
        return out

    def sample_for_question(self, qid: str) -> Optional[dict]:
        """按**题目ID** 取范文（平索引那条路）。**只返回样本形状**，不改任何状态。

        返回的形状与 `样例[]` 一条同形（`题目ID` + `优秀回答范例` + `kind`），
        好让 `answer_block` 两条路走**同一个**出口 —— 出口只有一个，安全性只有一处要审。
        """
        rec = self.by_question.get(str(qid or "").strip())
        if not rec:
            return None
        return {"题目ID": str(qid), _KEY_MODEL: rec["范文"], "kind": rec["kind"]}

    @classmethod
    def resource_block(cls, rec: dict, sample: Optional[dict]) -> Optional[dict]:
        """§5 契约里的 `resource`。**没有可讲的东西就返回 None**（不是空字典）。"""
        if sample is None:
            return None
        gap = sample.get(_KEY_GAP)
        block = {
            _KEY_TALK: rec["考点讲解"],
            _KEY_MODEL: sample.get(_KEY_MODEL) or "",
            # 拉开差距 在样例文件里是 list[str]，契约里是字符串 —— join 成一段，
            # 空列表 join 出来是空串，下游按「空 = 没有」处理即可。
            _KEY_GAP: "\n".join(gap) if isinstance(gap, (list, tuple)) else (gap or ""),
            "常见卡点": sample.get(_KEY_TRAP) or "",
            # 加法：这条资源是围绕哪道代表题给的。前端可以据此说「针对这道题」，
            # 也便于事后核对「推荐到底对不对得上」。
            "来源题": {
                "题目ID": sample.get("题目ID", ""),
                "题目": sample.get("题目", ""),
                "难度": sample.get("难度", ""),
                "题型": sample.get("题型", ""),
                "优先级": sample.get("优先级", ""),
            },
        }
        if not any(block[k] for k in (_KEY_TALK, _KEY_MODEL, _KEY_GAP, "常见卡点")):
            return None
        return block


# ============================================================
# 加载（懒、只做一次、失败不抛）
# ============================================================
_LOCK = threading.Lock()
_INDEX: Optional[ResourceIndex] = None


def _resolve_path() -> Optional[str]:
    """显式配置优先；否则按 config.RESOURCE_JSON_CANDIDATES 取第一个存在的。

    ⚠️ 与 `memory_retriever.py` 的 `RAG_MEM_DIR` 那条坑**故意不同**：那边环境变量
    设错会静默降级，所以那边只有在非空时直接用。这里两边都会落到同一份
    `resource_error` 上（显式设了但不存在 → 报「你设的路径不存在」），不会更难查。
    """
    if config.RESOURCE_JSON:
        return config.RESOURCE_JSON
    for c in config.RESOURCE_JSON_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def load_index(force: bool = False) -> ResourceIndex:
    """读一次资源样例文件，进程内缓存。**任何异常都变成 `error` 字段，不抛。**"""
    global _INDEX
    if _INDEX is not None and not force:
        return _INDEX
    with _LOCK:
        if _INDEX is not None and not force:
            return _INDEX
        idx = _load_uncached()
        _INDEX = idx
        if idx.available:
            logger.info("学习资源索引就绪：%s（%d 个考点）", idx.path, idx.kp_count)
        else:
            logger.warning("学习资源索引不可用：%s", idx.error)
        return idx


def _load_uncached() -> ResourceIndex:
    if not config.A11_RECOMMEND:
        return ResourceIndex(error="未启用（A11_RECOMMEND=0）")
    path = _resolve_path()
    if not path:
        return ResourceIndex(error="资源样例文件不存在（找过："
                                   + "；".join(config.RESOURCE_JSON_CANDIDATES) + "）")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return ResourceIndex(path=path, error=f"读取失败：{type(e).__name__}: {e}")
    if not isinstance(data, dict) or not data.get("岗位"):
        return ResourceIndex(path=path, error="文件结构不对：没有 `岗位` 数组")
    try:
        return ResourceIndex(path=path, data=data)
    except Exception as e:
        return ResourceIndex(path=path, error=f"建索引失败：{type(e).__name__}: {e}")


def resource_status() -> dict:
    """给 /health 与 check_env.py 看的四键状态（与 kg_status / rag_status 同形）。

    `resource_ready=false` 且 `resource_error` 为空是不可能的 —— 与 asr 那套
    「enabled / ready / error 三态」同一条纪律：**没开**和**坏了**必须分得开。
    """
    if not config.A11_RECOMMEND:
        return {"resource_enabled": False, "resource_ready": False,
                "resource_error": "", "resource_kps": 0}
    idx = load_index()
    return {"resource_enabled": True, "resource_ready": idx.available,
            "resource_error": idx.error, "resource_kps": idx.kp_count}


# ============================================================
# 给考生的材料（成长档案「提升路径」问有没有，`/model_answer` 取正文）
# ============================================================
# 四态，**不许塌成一个 bool**：「没开」（A11_RECOMMEND=0）/「坏了」（文件加载失败）/
# 「这个考点没有材料」（查不到，或一致性校验没过）/「有」。前两个是**服务端**的事，
# 第三个是**这个考点**的事 —— 三句话对考生完全不同（「过几天再来」vs「这个考点没材料」）。
MATERIAL_READY = "ready"
MATERIAL_DISABLED = "disabled"
MATERIAL_BROKEN = "broken"
MATERIAL_NOT_FOUND = "not_found"

_MATERIAL_NOTES = {
    MATERIAL_DISABLED: "本机未启用学习资源（A11_RECOMMEND=0）—— 不是这个考点没有材料。",
    MATERIAL_BROKEN: "资源文件加载失败 —— 不是这个考点没有材料。",
    MATERIAL_NOT_FOUND: ("资源文件里没有这个考点的材料（或它的领域/子类与考点对不上，"
                         "按既有取舍弃用 —— 宁可不给，也不给错的）。"),
}


def material_status(idx, res_st, kp_id: str, title: str,
                    domain: str = "", subclass: str = "") -> dict:
    """
    这个考点**有没有**可给考生的材料 → `{status, src, has_talk, has_model, note}`。

    ⚠️ 本函数**只回答「有没有」，正文一个字都不出** —— 正文全项目只有一个出口
    （下面的 `answer_block`），这样「哪些字段能出门」只有一处要审。
    `src` 是命中方式（`kp_id` / `title` / 空），便于事后复盘「这条材料是怎么对上的」。
    """
    res_st = res_st if isinstance(res_st, dict) else {}

    def out(status, src="", has_talk=False, has_model=False, note=""):
        return {"status": status, "src": src, "has_talk": has_talk,
                "has_model": has_model, "note": note or _MATERIAL_NOTES.get(status, "")}

    if not res_st:
        # 调用方没注入状态（只可能发生在直调本模块的测试里）。**不许冒充
        # `A11_RECOMMEND=0`** —— 那句话会把「我没传参数」说成「本机没开这个功能」。
        return out(MATERIAL_DISABLED,
                   note="未注入资源状态（调用方应传 resource_status()）—— 不知道有没有材料。")
    if not res_st.get("resource_enabled"):
        return out(MATERIAL_DISABLED)
    if idx is None or not res_st.get("resource_ready"):
        return out(MATERIAL_BROKEN)
    rec, src = idx.lookup(kp_id, title)
    if rec is None:
        return out(MATERIAL_NOT_FOUND)
    if not _consistent(rec, {"domain": domain, "subclass": subclass}):
        return out(MATERIAL_NOT_FOUND)
    has_talk = bool((rec["考点讲解"] or "").strip())
    # ⚠️ 「有没有范例」看的是**这条资源下全部代表题**，不是 `_pick_sample` 挑中的那一道 ——
    #    挑哪道要看调用方手里有没有该场出过的题号。若按挑中的那道算，提升路径会说
    #    「有材料」，而 `/model_answer`（它手里有题号）挑到另一道、返回空 —— 两处打架。
    has_model = any((s.get(_KEY_MODEL) or "").strip() for s in rec["样例"])
    if not (has_talk or has_model):
        return out(MATERIAL_NOT_FOUND)
    return out(MATERIAL_READY, src=src, has_talk=has_talk, has_model=has_model)


def answer_block(rec: dict, sample: Optional[dict]) -> Optional[dict]:
    """
    给考生的**正文**（`POST /model_answer` 的唯一取材处）。

    ⛔ 只出**五个**键：`考点讲解` + `优秀回答范例` + `from_question_id` + `kind` + `note`。
       **白名单构造**，不做「先建全再删键」—— `resource_block()` 那份里还有
       `拉开差距`（= 进阶得分点原文）与 `常见卡点`（= 面试官降级策略），
       那两个**绝不能对考生出**；多一个键就多一次泄漏机会。
       ⚠️ 2026-09-25 从三个键改成五个：加 `kind`（范文 / 示范作答）与 `note`。
          这一改是**知情**的 —— 它放宽了那道白名单。理由：951 道题的「判分素材」
          在库里其实是**答题结构**（STAR 骨架），拿它生成的只能是「示范作答」，
          不标注就等于让考生把一段**虚构经历**当优秀范例背下来。
          放宽的是**键数**，不是**来源**：两个新键都取自样例本身，没有一个字来自
          `拉开差距` / `常见卡点` / 题干 / 进阶得分点。
    ⛔ **不返回代表题的题面**：`_pick_sample` 可能挑中他没做过的那道（见该函数的兜底），
       连题面一起给就等于顺带泄露一份没考过的题。只给题号，前端足以说「针对这道题」。
    两样正文全空 ⇒ `None`（**不是空字典** —— 调用方要据此返 404，而不是给一个空壳）。
    """
    if not isinstance(rec, dict):
        return None
    talk = rec.get(_KEY_TALK) or ""
    model = ((sample or {}).get(_KEY_MODEL) or "").strip()
    if not (talk.strip() or model):
        return None
    kind = (sample or {}).get("kind")
    if kind not in KINDS:
        # 认不出来就当范文（与 `with_kind` 同一条兜底），**但 note 一定给空串**：
        # 不确定它是不是示范作答时，宁可不多说，也不要给范文挂一句「这是虚构的」。
        kind = _KIND_ANSWER
    return {
        "talk": talk,
        "model_answer": model,
        "from_question_id": str((sample or {}).get("题目ID", "") or ""),
        # ⚠️ `note` 与 `kind` **必须同时到位**：`kind="示范作答"` 而 `note=""`
        #    就是「标了却没解释」，前端可能只渲染 note ⇒ 标注静默丢失。
        #    冒烟里有 `kind==示范作答 ⇔ note 非空` 的断言守着。
        "kind": kind,
        "note": NOTE_DEMO if kind == _KIND_DEMO else "",
    }


# ============================================================
# 推荐（§4.3 / §4.4 / §4.5）
# ============================================================
def _consistent(rec: dict, kp: dict) -> bool:
    """
    §4.3 一致性校验。**两侧都非空才比**（空 = 没这个字段，不是「不一致」）。

    为什么必须有这道闸：知识库里已有「题 ↔ 考点跨岗位误挂」的缺陷
    （实测例：`kp_id=algorithm-kp-0242` 的 title 是「冗余连接II」（算法题），
    domain 却是「分布式基础/分布式理论」）。`title` 一旦误挂，按名字匹配就会
    把「负载均衡」的资源塞给一道算法题 —— 所以宁可只给得分点原文。

    ⚠️ 左侧 domain 是 `未归类` 时不匹配任何资源条目 —— 这是对的：
    「归不了类的考点」本来就不该拿到一份按领域挑出来的资源。
    """
    if rec["domain"] and kp.get("domain") and rec["domain"] != kp["domain"]:
        return False
    if rec["subclass"] and kp.get("subclass") and rec["subclass"] != kp["subclass"]:
        return False
    return True


def missed_points(kp: dict) -> tuple[list, list]:
    """
    该考点各轮漏掉的得分点原文，**基础在前、进阶在后**，各自按出现顺序去重。

    ⚠️ 只取 `reranker_ok is True` 的轮：reranker 挂着时 `base_miss` 是把**全部**
    得分点当成未命中倒出来的（覆盖率不可用 → 无从判断哪条答到了），
    拿它当「你漏了这些」会凭空冤枉考生。
    """
    base, adv = [], []
    for p in kp.get("per_round") or []:
        if p.get("reranker_ok") is not True:
            continue
        for src, dst in ((p.get("base_miss"), base), (p.get("adv_miss"), adv)):
            for t in (src or []):
                t = (t or "").strip()
                if t and t not in dst:
                    dst.append(t)
    return base, adv


def _entry_recommendation(kp: dict, idx: ResourceIndex,
                          job: Optional[str] = None) -> Optional[dict]:
    """单个薄弱考点 → 一条推荐；**没有任何可给的东西就返回 None**。

    `job` **只用于知识库检索的岗位过滤**（`kb.py` 按 `ai-reference\\README.md` 的
    「岗位与文件对应」表过滤），不参与那套题库派生的资源匹配 —— 后者靠
    kp_id/考点 连接，与岗位无关。`job=None` 时不过滤，行为与加这个参数之前相同。
    """
    best = kp.get("best_score")
    if not isinstance(best, (int, float)):
        # hit=False 蕴含 best_score 非空（blindspot.py:199-201），这里是第二道保险：
        # 拿不到覆盖率就算不出「薄弱度」，也就不该出现在排序里。
        return None
    weakness = max(0.0, min(1.0, 1.0 - float(best) / 100.0))

    rec, src = idx.lookup(kp.get("kp_id", ""), kp.get("title", ""))
    manual = False
    mismatch = False        # 「命中了但对不上」与「压根没命中」是两回事，说明文案要分开
    resource = None
    sample = None
    freq = None
    if rec is not None:
        if _consistent(rec, kp):
            sample = idx._pick_sample(rec, kp.get("question_ids") or [])
            resource = idx.resource_block(rec, sample)
            n, d = rec.get("题量"), rec.get("同组题量")
            if isinstance(n, (int, float)) and isinstance(d, (int, float)) and d:
                freq = max(0.0, min(1.0, float(n) / float(d)))
        else:
            # §4.3：不一致 → 不给资源。但仍然进推荐（得分点原文是按题给的真数据）
            manual = True
            mismatch = True
    else:
        # 没命中：样例库没有这个考点，或**整个资源索引不可用**（`_resolve_path()`
        # 两个候选都没找到时 `idx` 是空索引，`lookup` 恒返回 None）。
        # ⚠️ 2026-09-24 改：这里以前**不置 manual**，于是「`manual_check=false` ⇒
        #    必定有资源」这条对外契约在索引缺失时被破（resource=None 却报 false），
        #    下游会以为「字段自洽、可以直接用 resource」而拿到 null。
        #    `manual_check` 的口径就是「`resource` 这个字段能不能直接用」——
        #    没有资源就是没有资源，无论是因为对不上还是因为库不在。
        manual = True

    base, adv = missed_points(kp)
    missed = (base + adv)[:config.RECOMMEND_MAX_POINTS]
    if resource is None and not missed:
        # 既没资源、又没有可列的得分点 —— 这条推出去是空的（§4.4 宁缺毋滥）
        return None

    # §4.5 三因子。**考频未知取 0.5**（域中位），不取 0：
    # 「没有资源条目」不等于「这个考点不常考」，用它去乘等于悄悄加了一层惩罚。
    learn = 1.0 if (resource and resource.get(_KEY_TALK) and resource.get(_KEY_MODEL)) \
        else (0.8 if resource else 0.6)
    score = weakness * (0.6 + 0.4 * (freq if freq is not None else 0.5)) * learn

    reason = (f"最好一轮的得分点覆盖率 {float(best):.0f}%"
              f"（该考点在 {len(kp.get('rounds') or [])} 轮里出现 "
              f"{int(kp.get('appearances') or 0)} 次），"
              f"漏掉 {len(base)} 条基础点、{len(adv)} 条进阶点")
    if mismatch:
        reason += (f"；资源条目与本考点的领域/子类不一致"
                   f"（资源 {rec['domain']}/{rec['subclass']} vs 考点"
                   f" {kp.get('domain')}/{kp.get('subclass')}），只给得分点原文")
    elif resource is None:
        # 两种情形共用这一句（库不在 / 库在但没有这个考点）：对下游而言都是「没有资源」。
        # 具体是哪种看 `raw.blindspots.summary.recommend_error` 与 `resource_ready`。
        reason += "；样例库没有这个考点的资源，只给得分点原文"
    else:
        reason += f"；已匹配到资源（{src}）"
        if sample is not None:
            reason += f"，范例取自 {sample.get('题目ID', '')}"

    # ---- 知识库参考（真知识库那一层，见 kb.py）----
    # query 就用**考点名** —— 与考生自己会去搜的东西一致；不拼岗位/领域，
    # 岗位过滤交给 metadata（那比拼进 query 里稳，见 kb.py 的 search）。
    kb_refs = kbmod.lookup(kp.get("title", ""), job) if config.A11_KB_REC else []
    if kb_refs:
        repos = []
        for r in kb_refs:
            if r.get("来源仓库") and r["来源仓库"] not in repos:
                repos.append(r["来源仓库"])
        reason += f"；另附 {len(kb_refs)} 条知识库参考（{'/'.join(repos)}）"

    item = {
        "kp_id": kp.get("kp_id", ""),
        "title": kp.get("title", ""),
        "domain": kp.get("domain", ""),
        "subclass": kp.get("subclass", ""),
        "weakness": round(weakness, 3),
        "reason": reason,
        "resource": resource,
        "missed_points": missed,      # 兜底：命中与否都尽量有
        "manual_check": manual,
        # ---- 以下是加法（契约里没有，但省得下游自己反推）----
        "match": src or "",           # kp_id / title / 空 = 没命中
        "score": round(score, 4),     # §4.5 的排序分
        "best_score": float(best),
        "rounds": kp.get("rounds") or [],
        "missed_base": len(base),
        "missed_adv": len(adv),
    }
    # ⚠️ **只在有命中时才挂**（不是恒挂一个空列表）—— 这是「索引不在 ⇒ 既有键
    #    一个字节都没变」的实现方式，也是 A11_KB_REC 敢默认开的前提。
    #    消费方要判「有没有」请用 `if item.get("kb_refs"):`。
    #    注意**有命中时 `reason` 会被改**（上面 :370 那句尾巴）—— 这是本功能
    #    唯一改动的既有键，端到端 diff 验过（见 交付说明 §9.4），别当成漏网之鱼。
    if kb_refs:
        item["kb_refs"] = kb_refs
    return item


def _kb_summary(items: list) -> dict:
    """
    知识库那一层的四个说明键，形状照 `recommend_*` 那四个（enabled/ready/error + 一个量）。
    与它们一样，「关掉」「没装」「跑了但没有命中」三种情形必须分得开。
    """
    st = kbmod.kb_status()
    return {
        "kb_enabled": st["kb_enabled"],
        "kb_ready": st["kb_ready"],
        # 真挂上去的条数（不是「候选数」）—— 三条以上考点命中时会大于 KB_TOP_N
        "kb_refs_total": sum(len(it.get("kb_refs") or []) for it in (items or [])),
        "kb_error": st["kb_error"],
    }


def recommend(knowledge_points: list, top_n: Optional[int] = None,
              job: Optional[str] = None) -> dict:
    """
    `blindspot.diagnose()` 的 knowledge_points → 一份推荐清单。

    返回 `{"items": [...], "candidates": n, "ready": bool, "error": str,
    "kb_enabled": bool, "kb_ready": bool, "kb_refs_total": int, "kb_error": str}`
    —— **`items` 才是契约字段**，其余是「为什么是这些 / 为什么空」的说明，
    由 diagnose() 拆进 `summary`。**本函数绝不抛异常。**

    `job` 只透给知识库检索做岗位过滤（见 `_entry_recommendation`）。
    """
    top_n = int(top_n or config.RECOMMEND_TOP_N)
    if not config.A11_RECOMMEND:
        return {"items": [], "candidates": 0, "ready": False,
                "error": "未启用（A11_RECOMMEND=0）", **_kb_summary([])}
    try:
        idx = load_index()
        cands = []
        for kp in knowledge_points or []:
            # §2：只推「有客观依据判他没答到」的。`hit is None`（没答/判不了）不进 ——
            # 「没考 ≠ 不会」。`is not False` 一句同时挡住 None 与键缺失两种情况。
            if kp.get("hit") is not False:
                continue
            it = _entry_recommendation(kp, idx, job)
            if it is not None:
                cands.append(it)
        # §4.5：分高的在前；同分先看薄弱度，再按 kp_id 定序（结果稳定、可复现）
        cands.sort(key=lambda x: (-x["score"], -x["weakness"], x["kp_id"]))
        top = cands[:top_n]
        return {"items": top, "candidates": len(cands),
                "ready": idx.available, "error": idx.error, **_kb_summary(top)}
    except Exception as e:                                   # noqa: BLE001
        # 诊断报告不能因为推荐挂了就整个拿不到（与 kg/rag/asr 同一条旁路纪律）
        logger.exception("生成学习资源推荐失败")
        return {"items": [], "candidates": 0, "ready": False,
                "error": f"{type(e).__name__}: {e}", **_kb_summary([])}
