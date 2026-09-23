"""从简历纯文本里推测可回填的字段（纯函数，无 IO）

**总原则：抽不到就返回 None 并说明原因，绝不猜。**
抽错会把用户已经填对的信息引导成错的（预填了用户就懒得改），比留空危害大得多。
因此每条规则都配反例测试，规则本身按可信度分层：
标签命中（强）> 位置/格式约束（弱）> 全文计分（最弱）。

本模块与文本从哪来无关——PDF 文本层提取的、将来 OCR / 多模态出来的，
都是文本，规则原样复用。
"""
import re
import unicodedata
from dataclasses import dataclass, field

from app.models.resume import (
    PARSE_STATUS_GARBLED,
    PARSE_STATUS_NO_TEXT_LAYER,
    PARSE_STATUS_PARSED,
)

# 只回填 users 表已有的三个字段。头像无法从文本中得到，故不在此列。
FIELD_NAMES = ("nickname", "student_id", "target_position")


@dataclass
class FieldGuess:
    """单个字段的推测结果：值 + 给用户看的原因（note 为空表示无需解释）"""

    value: str | None = None
    note: str = ""


@dataclass
class FieldGuesses:
    nickname: FieldGuess = field(default_factory=FieldGuess)
    student_id: FieldGuess = field(default_factory=FieldGuess)
    target_position: FieldGuess = field(default_factory=FieldGuess)


def normalize(text: str) -> str:
    """全角数字/字母/冒号与 U+3000 空格归一为半角，统一换行

    一行解决「姓名：/姓名:」「２０２１」「姓　名」三类变体。
    NFKC 只动 ASCII 兼容形式与全角标点，不动汉字，可安全对全文施加。
    """
    t = unicodedata.normalize("NFKC", text or "")
    return t.replace("\r\n", "\n").replace("\r", "\n")


_CID_RE = re.compile(r"\(cid:\d+\)")
# 私用区（U+E000–U+F8FF）与替换字符（U+FFFD）用 chr() 构造：不在源码里写这两个
# 不可见字面量——它们在编辑器里显示为空，极易被后续编辑吃掉（本行初稿就踩过一次）。
_PUA_START, _PUA_END = chr(0xE000), chr(0xF8FF)
_REPLACEMENT_CHAR = chr(0xFFFD)


def looks_garbled(text: str, sample_size: int = 4000) -> bool:
    """判断提取出的文字是否为乱码

    **不能用「没有中文」来判**——英文简历是合法的。只认三种显式信号：
    字体子集缺 ToUnicode 表时的 `(cid:12)` 形式、Unicode 替换字符 U+FFFD、
    以及私用区字符（U+E000–U+F8FF，字体映射错乱时的典型产物）。
    """
    s = (text or "").strip()
    if not s:
        return False
    sample = s[:sample_size]
    if _CID_RE.search(sample):
        return True
    bad = sum(
        1 for ch in sample if ch == _REPLACEMENT_CHAR or _PUA_START <= ch <= _PUA_END
    )
    return bad / len(sample) > 0.05


def decide_status(text: str) -> str:
    """由提取结果判定 parse_status（图片分支由解析适配器先行返回，不走这里）"""
    if not (text or "").strip():
        return PARSE_STATUS_NO_TEXT_LAYER
    if looks_garbled(text):
        return PARSE_STATUS_GARBLED
    return PARSE_STATUS_PARSED


# ---------------- 学号 ----------------

_SID_LABEL_RE = re.compile(
    r"(?:学\s*号|学籍号|学生编号|考生号|student\s*id|stu(?:dent)?\s*no\.?)"
    r"\s*[:：]?\s*([A-Za-z0-9]{6,20})",
    re.I,
)
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def _looks_like_student_id(s: str) -> bool:
    """编号形似学号：长度 6~14（排 4 位年份与 15/18 位身份证），且至少含 4 位数字

    刻意不做身份证 mod-11-2 校验——长度排除已经够用，加校验是给一个已知错误源加代码。
    """
    if not (6 <= len(s) <= 14):
        return False
    if sum(c.isdigit() for c in s) < 4:
        return False  # 排掉 SpringBoot 这类纯字母词
    return not (_PHONE_RE.match(s) or _YEAR_RE.match(s))


def _guess_student_id(text: str) -> FieldGuess:
    m = _SID_LABEL_RE.search(text)
    if m:
        cand = m.group(1).strip()
        if _looks_like_student_id(cand):
            return FieldGuess(cand, f"命中「学号」标签：{cand}")
        return FieldGuess(None, f"「学号」标签后的内容不像学号（{cand}），未采用")

    # 弱规则：只在文档前 600 字里找独占一行的编号。
    # 已知残余风险：项目经历区里独立成行的数字串也可能被采纳，靠 600 字窗口压制。
    for line in text[:600].split("\n"):
        line = line.strip()
        if _looks_like_student_id(line) and line.isalnum():
            return FieldGuess(line, f"据文档前部独立成行的编号推测：{line}（请核对）")
    return FieldGuess(None, "未找到学号")


# ---------------- 姓名 ----------------

_NAME_LABEL_RE = re.compile(
    r"(?:姓\s*名|名\s*字)\s*[:：]\s*"
    r"([一-龥]{2,4}(?:[·•][一-龥]{2,6})?)"
    r"(?=\s|$|[，。；;|,、/\\()（）])"
)
_EN_NAME_LABEL_RE = re.compile(r"\bname\s*[:：]\s*([A-Za-z][A-Za-z .'\-]{1,40})", re.I)
_FIRST_LINE_NAME_RE = re.compile(r"[一-龥]{2,4}(?:[·•][一-龥]{2,6})?")

# 首行弱规则的黑名单：整行命中即跳过
_NAME_BLACKLIST = {
    "个人简历", "求职简历", "应聘简历", "简历", "个人简介", "自我介绍", "个人信息",
    "教育背景", "工作经历", "项目经历", "专业技能", "自我评价", "联系方式",
    "求职意向", "实践经历", "校园经历", "获奖情况", "基本情况",
}
# 含以下子串的行不是姓名（"北京大学"、"李工程师"、"教育背景"）
_NAME_BAD_SUBSTR = (
    "工程", "开发", "测试", "算法", "架构", "经理", "专员", "主管", "助理",
    "大学", "学院", "简历", "专业", "岗位", "职位",
)


def _nickname_from_first_line(text: str) -> FieldGuess:
    """弱规则：只看前 3 个非空行里「整行就是姓名」的情形

    中文简历最常见的排版就是首行孤零零一个姓名，关掉它会让功能在多数真实简历上
    「学号抽到了、姓名抽不到」。它由黑名单 + 坏子串 + fullmatch + 仅前 3 行四重约束保护。

    **单独成函数是刻意的**：线上若发现误判，删掉这一个函数即可，强规则不受影响。
    """
    for line in [ln.strip() for ln in text.split("\n") if ln.strip()][:3]:
        if line in _NAME_BLACKLIST or any(bad in line for bad in _NAME_BAD_SUBSTR):
            continue
        if _FIRST_LINE_NAME_RE.fullmatch(line):
            return FieldGuess(line, f"据文档首行推测：{line}（请核对）")
    return FieldGuess(None, "")


def _guess_nickname(text: str) -> FieldGuess:
    m = _NAME_LABEL_RE.search(text)
    if m:
        return FieldGuess(m.group(1).strip(), f"命中「姓名」标签：{m.group(1).strip()}")
    m = _EN_NAME_LABEL_RE.search(text)
    if m:
        cand = m.group(1).strip()
        return FieldGuess(cand, f"命中「Name」标签：{cand}")

    guess = _nickname_from_first_line(text)
    if guess.value:
        return guess
    return FieldGuess(None, "未找到姓名")


# ---------------- 目标岗位 ----------------

_POSITION_LABEL_RE = re.compile(
    r"(?:求职意向|求职目标|求职岗位|应聘岗位|应聘职位|意向岗位|意向职位|目标岗位|目标职位"
    r"|期望岗位|期望职位|职位意向|job\s*objective|target\s*position"
    r"|position\s*applied|applied\s*for)\s*[:：]\s*([^\n]{1,40})",
    re.I,
)

# 岗位名级强信号给 3~4 分，技术栈弱信号给 1~2 分。**通用编程语言（Java/Python/C++/Go）
# 刻意不在表内**——算法岗简历常同时写 Java，给了分就会把后端方向顶上来。
# 跨岗位词（MySQL/Redis/Kafka/Docker/高并发）只给 1~2 分，不足以单独越过阈值。
_POSITION_KEYWORDS: dict[str, tuple[tuple[str, int], ...]] = {
    "backend": (
        ("后端", 3), ("服务端", 3), ("后台开发", 3), ("Java开发", 3),
        ("Backend", 3), ("Back-end", 3),
        ("Spring", 2), ("MyBatis", 2), ("Django", 2), ("Flask", 2), ("FastAPI", 2),
        ("MySQL", 1), ("Redis", 1), ("分布式", 1), ("微服务", 1), ("消息队列", 1), ("Kafka", 1),
    ),
    "frontend": (
        ("前端", 3), ("Web前端", 3),
        ("Frontend", 3), ("Front-end", 3),
        ("Vue", 2), ("React", 2), ("Angular", 2), ("JavaScript", 2), ("TypeScript", 2),
        ("小程序", 2), ("uni-app", 2),
        ("HTML", 1), ("CSS", 1), ("Webpack", 1), ("Vite", 1),
    ),
    "test_engineer": (
        ("测试开发", 4), ("测试工程师", 4), ("自动化测试", 3), ("接口测试", 3),
        ("Test Engineer", 3), ("QA", 2),
        ("测试", 2), ("用例", 2), ("Pytest", 2), ("Selenium", 2), ("JMeter", 2),
        ("质量保障", 2), ("缺陷", 2), ("Postman", 1), ("Jenkins", 1),
    ),
    "algorithm": (
        ("算法工程师", 4), ("机器学习", 3), ("深度学习", 3), ("算法", 3),
        ("Machine Learning", 3), ("Algorithm", 3),
        ("PyTorch", 2), ("TensorFlow", 2), ("神经网络", 2), ("模型训练", 2),
        ("数据挖掘", 2), ("自然语言处理", 2), ("NLP", 2), ("推荐系统", 2),
        ("计算机视觉", 2), ("大模型", 2), ("LLM", 2),
    ),
    "system_design": (
        ("系统设计", 4), ("系统架构", 4), ("架构设计", 4), ("架构师", 4),
        ("System Design", 4), ("Architect", 3),
        ("高可用", 2), ("容器化", 2), ("Kubernetes", 2), ("K8s", 2), ("Docker", 2),
        ("中间件", 2), ("容量规划", 2), ("灾备", 2), ("高并发", 1),
    ),
}
_POSITION_MIN_SCORE = 3   # 低于此分不猜（只有技术栈弱词时够不着）
_POSITION_MIN_MARGIN = 2  # 与第二名差距小于此值不猜（两个方向都像）


def _score_positions(fragment: str) -> dict[str, int]:
    """片段 → 各岗位得分

    大小写不敏感（英文岗位名与技能词的大小写很随意）；同一个词最多计 2 次，
    防止一个词反复出现刷分。
    """
    lowered = fragment.lower()
    scores: dict[str, int] = {}
    for code, words in _POSITION_KEYWORDS.items():
        total = 0
        for word, weight in words:
            count = lowered.count(word.lower())
            if count:
                total += weight * min(count, 2)
        if total:
            scores[code] = total
    return scores


def _pick_position(scores: dict[str, int]) -> tuple[str | None, str]:
    """双门槛挑一个 code：低于阈值不猜、与第二名差距不足不猜"""
    if not scores:
        return None, ""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_score = ranked[0][1]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    if top_score < _POSITION_MIN_SCORE:
        return None, "命中的关键词权重不足，不猜"
    if top_score - second_score < _POSITION_MIN_MARGIN:
        return None, "同时出现多个岗位方向的关键词，不猜"
    return ranked[0][0], ""


def _guess_target_position(text: str) -> FieldGuess:
    m = _POSITION_LABEL_RE.search(text)
    if m:
        fragment = m.group(1)
        code, why = _pick_position(_score_positions(fragment))
        if code:
            return FieldGuess(code, f"据「{fragment.strip()}」判定为 {code}")
        return FieldGuess(None, f"求职意向「{fragment.strip()}」{why or '无法判定'}")

    code, why = _pick_position(_score_positions(text))
    if code:
        return FieldGuess(code, f"据全文关键词推测为 {code}（请核对）")
    return FieldGuess(None, why or "未找到岗位方向")


# ---------------- 总入口 ----------------


def extract_fields(text: str) -> FieldGuesses:
    """推测三个可回填字段。不返回 avatar_url——头像无法从简历文本中得到。"""
    if not (text or "").strip():
        return FieldGuesses()
    norm = normalize(text)
    return FieldGuesses(
        nickname=_guess_nickname(norm),
        student_id=_guess_student_id(norm),
        target_position=_guess_target_position(norm),
    )
