# -*- coding: utf-8 -*-
"""
asr.py · 本地语音转写（faster-whisper）+ 由转写结果派生的表达指标
============================================================
对应赛题 2a) 语音输入 与 3b) 语音识别 / 语速 / 流畅度。
设计出处：`D:\\A11-Data\\多模态接入方案.md`（本文的实现与它逐条对应）。

四条设计约束（照方案稿，不是我自己定的）：

  1. **只做「音频进、文字出」。** 转写出来的 `text` 交给前端，仍走原来的
     `POST /chat` 的 `message` 字段 —— 评分 / 追问 / 判档 / 换题 / 复读守卫
     全部零改动复用。这是接语音最容易犯错的地方（把音频塞进 /chat 会让
     已经验收过的文字通路跟着变成待验状态）。
  2. **音频不落盘、不进 `raw`**（与 `rag.py` 的「片段绝不进 raw」同一条铁律）。
     端点把上传的字节写进**临时文件**、转写完**立刻删**；`raw` 里只有本模块
     派生的**数字**（时长 / 语速 / 停顿 / 填充词），一份转写原文也不额外落
     —— 转写文本只作为 `message` 进会话，与考生手打的那句话没有区别。
  3. **三态健康**（enabled / ready / error）+ 懒加载 + 内存预检，与
     `kg.py` / `rag.py` 同构。必须能区分「没开」（配置）与「坏了」（故障）。
  4. **绝不阻塞**：模型没就绪时立刻给 503（可带 Retry-After），不让 /asr
     挂在那儿等十秒。内存预检**取不到值就跳过**（照抄 `rag.py:63-76` 的语义）
     —— 把「测不出来」当成「内存不足」，会让它在能跑的机器上也永远起不来。

⚠️ 为什么是 faster-whisper 而不是「浏览器 Web Speech」或云 ASR：
   赛题 3b 要的「语速 / 停顿 / 流畅度」**只能从词/句级时间戳里算出来**，
   只有本地 ASR 给得出（方案 §三 的三条路线对比）。它还有两个现实好处：
   音频不出本机（合规）、复用 `HF_HOME` 缓存机制（与既有的 `check_env.py` /
   `环境变量.模板.ps1` 约定不用改）。

⚠️ 依赖是**懒加载**的：`faster_whisper` 只在第一次真正转写时 import。
   没装、没开（`A11_ASR=0`）、或模型没下载，本模块都不会让服务起不来 ——
   `/health` 会如实报出是哪一种。
"""
import os
import re
import tempfile
import threading
import time
from typing import Optional

from app import config
from app.core.rag import free_mb          # 复用，不抄第二份（方案 §四 明确要求）
from app.logging_conf import get_logger

logger = get_logger(__name__)


# ============================================================
# 表达指标：固定键的空值（键恒在，消费方不用判空）
# ============================================================
# 与 `rag_meta` / `dim1_labels` 同一条原则：**键恒在**。理由是「这一段数据不存在」
# 与「有这段数据但值为 0」必须能分开 —— 前者是没启用语音，后者是考生真的
# 一个字都没说。空值一律用 None（不是 0）。
# ⚠️ 2026-09-25 加情感/自信度后，**「全是数字」这句话不再成立**，要知情：
#    17 个键里 13 个是数字或空（duration_ms … confidence），另 4 个的取值域是**封闭**的
#    —— `used` 是布尔、`asr_model` 是模型标签串、`emotion` 是模型 config 里的闭集标签
#    （neu/hap/ang/sad，直接来自 id2label）、`emotion_dist` 是「那些标签→数字」的字典。
#    **「不可能夹带题目或得分点文本」这条结论仍然成立，但它的依据换了**：
#    原来靠「全是数字」，现在靠「取值域封闭」。所以**别再加自由文本字段进来**
#    —— 一加，这条论证立刻失效，而它守的是 /asr 不进 raw 的那条铁律。
SPEECH_EMPTY = {
    "used": False,          # 这一次回答是否有语音指标（false = 文字作答/未启用）
    "asr_model": "",        # 转写模型标签，换模型后语速口径会变，靠它分辨
    "duration_ms": None,    # 净语音时长（VAD 人声块之和，段内静音也不计）
    "audio_ms": None,       # 音频文件本身的时长（含静音），仅诊断用
    "chars": None,          # 计入语速的字数（去标点空白）
    "chars_per_min": None,  # 语速（字/分）
    "pauses": None,         # 长停顿次数（相邻段间隔 > PAUSE_MIN_MS）
    "pause_total_ms": None, # 长停顿累计毫秒
    "fillers": None,        # 填充词个数
    "filler_rate": None,    # 填充词占字数比
    # ---- 韵律：音量三指标（赛题 3b「语气自信度」的**可解释**那一半）----
    # ⚠️ 量的单位是「**窗**」不是「VAD 人声段」：人声先按**不超过 3 秒**等分切窗
    #    （`_loudness_windows`，2026-09-25 改）。原来一人声段出一个数，而 silero
    #    要静音 >2 秒才断开 ⇒ 连读的答案只切出 1 段 ⇒ cv/tail 恒为 None。
    "loudness": None,       # 各窗 RMS 的均值（声音洪不洪亮）
    "loudness_cv": None,    # 各窗 RMS 的变异系数（越小越稳；大=忽大忽小）
    "tail_ratio": None,     # 最后一窗 RMS / 各窗均值（<1 = 收尾发虚）
    # ---- 情感：真 SER 模型的输出（另一半）----
    "emotion": None,        # 占比最高的情感标签（闭集，来自模型 id2label）
    "emotion_score": None,  # 那个标签的概率
    "emotion_dist": None,   # 全部标签→概率（数字字典）
    # ---- 融合（**不是**模型直接给的）----
    "confidence": None,     # 「偏低/中等/偏高」；由韵律两指标按写死的规则算出
                            # （**不含情感、不含语速** —— 理由见 `confidence_band`）
}

# 长停顿阈值：相邻语段之间的静音超过它算一次「停顿」。
# 1.5 秒是口语研究的常用界（正常句间换气在 0.2~0.8 秒）。
PAUSE_MIN_MS = 1500

# 填充词（口头语）。**故意用字面匹配、不做 NLP** —— 这一层要的是「可复现的
# 粗糙信号」，而不是一个会随模型版本漂移的情感判断。刻意不含「就」「那」这种
# 单字：它们单独出现时正常语义太多，数出来的是噪声。
# ⚠️ 2026-09-25：本框架**确实**另起了一层真情感模型（3b 的情感分析，
#    `emotion_metrics`）—— 但那是**另一个键、另一层**，且文档里明写它在中文上
#    不可信、也没进 `confidence`。**别**因为有了那层就把这行读成「情感分析已经
#    用模型做了，所以填充词也可以上模型」：这一层要的就是**字面、可复现**。
FILLERS = ("嗯", "呃", "啊", "那个", "就是说", "这个", "然后", "其实", "怎么说")


def _count_chars(s: str) -> int:
    """
    计入语速的**字数**：去掉空白与标点后的字符数。

    `\\w` 在 Python 3 里是 unicode 语义，汉字属 word 字符 —— 所以这个正则
    留下的正是「汉字 + 字母 + 数字」，正是想要的分母。
    为什么不用 `len(s)`：标点与空格会把语速虚高，而 whisper 加不加标点
    并不稳定（同一段音频不同参数可能一段带标点一段不带），拿 `len` 当分母
    等于把「有没有标点」混进语速里。
    """
    return len(re.sub(r"[\W_]+", "", s or ""))


def derive_speech(text: str, duration_ms: Optional[int] = None,
                  segments: Optional[list] = None,
                  asr_model: str = "",
                  audio_ms: Optional[int] = None,
                  pauses: Optional[int] = None,
                  pause_total_ms: Optional[int] = None,
                  loudness: Optional[float] = None,
                  loudness_cv: Optional[float] = None,
                  tail_ratio: Optional[float] = None,
                  emotion: Optional[str] = None,
                  emotion_score: Optional[float] = None,
                  emotion_dist: Optional[dict] = None) -> dict:
    """
    从 `/asr` 的原始数字派生表达指标。**纯函数**，无副作用、不抛异常。

    这是「表达分析」唯一的计算处：`session.submit_answer` 收到前端回传的
    speech 数字时调它一次，派生结果既进 `exchanges[].speech`，也进轮次级
    `speech`，还被 `RoundRecord.pace_note()` 拼成评分 Prompt 里那段客观测量。

    `pauses` / `pause_total_ms`（加法，可选）：`/asr` 已经**在音频上量好**的
    长停顿次数与累计时长，给了就**直接采信**（见下面「停顿」那一段的注释）。
    不传时退回「相邻段间隔」的老算法 —— 旧前端只回传 duration/segments 时
    这条路仍然走通（宁可兜底，也不把新键变成必填）。

    韵律与情感那 6 个参数（2026-09-25 加法）：同样是「`/asr` 在音频上量好了
    就传进来、不传就是 None」。**它们都是原样采信，不在这里重算** —— 唯一的
    例外是 `confidence`：它**不是**任何一处传进来的值，而是由 `confidence_band()`
    在下面**融合**出来的，所以它只能在这里算。⚠️ 注意 `confidence_band()` 只吃
    **韵律两指标**，**不吃 `emotion_dist` 也不吃语速** —— 理由写在该函数的
    注释里（实测：情感在中文语音上近似常量，不构成证据）。
    """
    out = dict(SPEECH_EMPTY)
    out["asr_model"] = asr_model or ""
    if audio_ms is not None:
        out["audio_ms"] = int(audio_ms)
    if not duration_ms or duration_ms <= 0:
        # 没有净时长就算不了语速 —— 但**不报错**：静音录音、或前端只传了文字，
        # 都会走到这里，那是正常情况而不是故障。
        return out

    out["duration_ms"] = int(duration_ms)
    out["used"] = True

    n_chars = _count_chars(text)
    out["chars"] = n_chars
    if n_chars:
        out["chars_per_min"] = round(n_chars / (duration_ms / 60000.0), 1)

    # 停顿：**优先用 `/asr` 在音频上量出来的那两个数**（`pauses` /
    # `pause_total_ms`）—— 那是 VAD 人声块之间的真实静音，给了就照用。
    # ⚠️ 为什么不能只靠「相邻段间隔」：whisper 的 `segments` 是**把音频首尾
    #    相接切完**的产物，段与段之间天生没有缝隙 —— 静音被吞进段的跨度里。
    #    实测（`_tmp_asr_real.py`，SAPI 合成、故意插 5.0s / 2.5s / 6.0s 三处
    #    静音）：转写出来的相邻段间隔分别是 0 / 0 / 0，一次都没命中，同一份
    #    音频的语速也被算成 121.8 字/分（分母把 13.5 秒静音算进去了），而
    #    按 VAD 人声块算是 215.8 字/分 —— 真值。所以净时长与停顿都以音频为准。
    #    段间隔这条路留着，是给「只回传 duration/segments 的旧前端」兜底。
    # ⚠️ **没给段级时间戳时为 None，不是 0**：「没测到停顿」与「没测」必须能分开
    #    —— 只有净时长的话（前端没回传 segments），填 0 等于凭空说"他没停顿"。
    segs = [s for s in (segments or [])
            if isinstance(s, dict) and s.get("start_ms") is not None
            and s.get("end_ms") is not None]
    if pauses is not None:
        # 音频量出来的那一份优先，**不再看段间隔**（两处口径不一致时以音频为准）
        out["pauses"] = int(pauses)
        out["pause_total_ms"] = int(pause_total_ms or 0)
    elif segs:
        segs.sort(key=lambda s: s["start_ms"])
        gaps = [int(b["start_ms"]) - int(a["end_ms"])
                for a, b in zip(segs, segs[1:])]
        long_gaps = [g for g in gaps if g > PAUSE_MIN_MS]
        out["pauses"] = len(long_gaps)
        out["pause_total_ms"] = int(sum(long_gaps))

    # 填充词：在**去标点**的文本上数字面量（whisper 加不加逗号不稳定，
    # 在带标点的原文上数会把「嗯，那个」数漏）。
    # ⚠️ 已知代价：去标点后跨标点边界可能拼出一个假填充词（"…这个。然后…" 里的
    #    「这个然后」只会在数「然后」时命中一次，不会重复计数），量级可忽略。
    flat = re.sub(r"[\W_]+", "", text or "")
    n_fill = sum(flat.count(w) for w in FILLERS) if flat else 0
    out["fillers"] = n_fill
    out["filler_rate"] = round(n_fill / n_chars, 4) if n_chars else None

    # 韵律与情感：**原样采信 `/asr` 量好的值**，不在这里重算（音频已经不在手上了）。
    # ⚠️ 一律 `is not None` 判，**不许写 `if loudness:`** —— 音量/概率为 0 是合法值
    #    （RMS 恰好为 0、某类概率 0.0），用真值判断会把它悄悄丢掉。
    if loudness is not None:
        out["loudness"] = float(loudness)
    if loudness_cv is not None:
        out["loudness_cv"] = float(loudness_cv)
    if tail_ratio is not None:
        out["tail_ratio"] = float(tail_ratio)
    if emotion is not None:
        out["emotion"] = str(emotion)
    if emotion_score is not None:
        out["emotion_score"] = float(emotion_score)
    if emotion_dist is not None:
        out["emotion_dist"] = dict(emotion_dist)
    # ⚠️ 三态：**没开/没测到 ⇒ None**（不是「中等」）。给一个「中等」当默认值
    #    等于凭空替考生下结论 —— 与 `SPEECH_EMPTY` 那条「None 不是 0」同一条纪律。
    # ⚠️ 依据句**故意不存进 SPEECH_EMPTY**：它是一串中文，存进去就破坏了上面
    #    「取值域封闭」那条论证。`pace_note()` 需要时**重算**一次即可 ——
    #    `confidence_band()` 是纯函数，同一组输入永远给同一句话。
    out["confidence"] = confidence_band(out["loudness_cv"], out["tail_ratio"])[0]
    return out


# ============================================================
# 音频侧的真实测量：VAD 人声块（净时长与停顿的唯一真值源）
# ============================================================
def speech_regions(audio, sampling_rate: int = 16000) -> list:
    """
    量出音频里的**人声区间**，返回 `[{start_ms, end_ms}]`（与 segments 同形，
    好直接喂给 `derive_speech`）。用的是 faster-whisper 自带的那个 silero VAD
    （`faster_whisper.vad`），参数取 `VadOptions()` 的默认值 —— 与
    `model.transcribe(vad_filter=True)` 内部那一遍**完全同一套**，所以
    「哪一段算人声」两处口径一致。

    ⚠️ 为什么要在 `transcribe(vad_filter=True)` 之外**再跑一遍** VAD：
       `transcribe()` 把 VAD 结果喂进解码器，但**不返回**；而它返回的
       `segments` 是「把音频首尾相接切完」的产物 —— 段与段之间天生没有缝隙，
       静音被吞进段的跨度里。实测：故意插 5.0 / 2.5 / 6.0 秒三处静音，
       转写出的相邻段间隔是 0 / 0 / 0（一次都不命中），净时长 30540ms
       （真值 17239ms）→ 语速被算成 121.8 字/分（真值 215.8）。
       这一遍 VAD 约几十毫秒（同一段音频转写要 2~4 秒），换来两个指标是真的。

    抛异常由调用方兜住（转写本身不该因为量停顿失败而失败）。
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    chunks = get_speech_timestamps(audio, VadOptions(),
                                   sampling_rate=sampling_rate)
    out = []
    for c in chunks:
        s, e = int(c["start"]), int(c["end"])
        if e > s:
            out.append({"start_ms": s * 1000 // sampling_rate,
                        "end_ms": e * 1000 // sampling_rate})
    return out


# ============================================================
# 情感 / 语气自信度（赛题 3b「集成语音识别**与情感分析**」的「情感」那半）
# ============================================================
# ⚠️ 三层，口径必须分开说，**不许混成一句「模型给出的自信度」**：
#   ① 韵律三指标 —— **测出来的**。算法就在下面，拿一段音频可以手算复核。
#   ② 情感分布 —— **模型给出来的**，但那个模型是 IEMOCAP（英语、表演式情感）训的，
#      在中文面试语音上多半输出 neu。它是一个**韵律信号**，
#      **不是**「这段中文表达了什么情绪」的语义判断。
#   ③ `confidence` —— **不是**模型输出的任何东西。它是 ①+② 按 `confidence_band()`
#      里写死的阈值融合出的一个档位。文档 / prompt / 交付材料里都不许写成
#      「模型给出的自信度」。
CONFIDENCE_LOW = "偏低"
CONFIDENCE_MID = "中等"
CONFIDENCE_HIGH = "偏高"

# 喂给情感模型的最长**人声**秒数。为什么必须有这个上限（2026-09-25 实测）：
#   · 慢：CPU 上约 65ms/秒音频 —— 40 秒就是 2.7 秒，而这一层是加在 `/asr` 上的，
#     whisper 本身才 2~4 秒，不封顶等于把转写耗时翻倍。
#   · 而且**不定长就不可复现**：同一段音频截 20 秒与 40 秒，模型给出的分布不同
#     （实测同一段正弦波 20s→neu 0.986、40s→neu 0.597 / ang 0.403）。
#     固定窗口让「同一份音频 ⇒ 同一组数」成立。
# 取的是**前 N 秒的人声**（VAD 人声块按序拼接、不含静音），不是前 N 秒音频。
A11_ASR_EMOTION_MAX_SEC = float(os.environ.get("A11_ASR_EMOTION_MAX_SEC", "15"))


# 音量起伏 / 收尾用的**窗长**：把人声切成「每段不超过 3 秒」的等长窗。
# 3 秒的依据是「一句正常口语的长度」——比它短会跟着音节起伏抖，比它长就分不出
# 「越说越小」这件事（一段 20 秒的答案只出一个数，等于没测）。
LOUDNESS_WINDOW_MS = 3000


def _loudness_windows(regions: list, window_ms: int = LOUDNESS_WINDOW_MS) -> list:
    """把人声区间切成等长窗 → `[(start_ms, end_ms)]`。

    **只吃人声区间，静音永远不进来**；每个区间**等分**成
    `ceil(区间长 / window_ms)` 个窗（3 秒的段 = 1 个窗、6 秒 = 2 个、19 秒 = 7 个），
    所以不会剩一个几十毫秒的尾巴窗（那种窗的 RMS 是噪声）。

    为什么要等分而不是「固定 3 秒硬切」：硬切会把 22 秒的答案切成 7×3 秒 + 1 秒，
    最后那个 1 秒窗的 RMS 与 3 秒窗**不等价**，`tail_ratio` 就变成在比两种东西。
    ⚠️ 等分之后 `tail_ratio` 的读法不变（「最后一窗 ÷ 全窗均值」），
       仍然是「收尾那一段比整体大还是小」。
    """
    out: list = []
    for r in regions or []:
        try:
            s, e = int(r["start_ms"]), int(r["end_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        if e <= s:
            continue
        n = max(1, -(-(e - s) // window_ms))        # ceil，整数算法（不用 float 除法）
        step = (e - s) / n
        for i in range(n):
            ws = int(round(s + i * step))
            we = int(round(s + (i + 1) * step))
            if we > ws:
                out.append((ws, we))
    return out


def loudness_metrics(audio, regions: list, sampling_rate: int = 16000) -> dict:
    """
    人声的音量三指标。**只在人声上算** —— 静音不许参与：一段长静音会把
    「声音洪亮」拖成「声音小」，那是**测量错误**，不是考生的表现。

    入参 `audio` 是 `decode_audio()` 的 float32 单声道 `[-1,1]` 一维数组；
    `regions` 是 `speech_regions()` 的 `[{start_ms,end_ms}]`。

    返回 `{loudness, loudness_cv, tail_ratio}`；**量不出来是 None（不是 0）**：
      · `loudness`    各窗 RMS 的均值
      · `loudness_cv` 这些 RMS 的标准差 / 均值 —— **要 >=2 个窗**才有意义，否则 None
      · `tail_ratio`  最后一窗 RMS / 全部均值 —— **要 >=2 个窗**，否则恒为 1，那是假的

    ⚠️ 为什么是「窗」而不是「VAD 人声段」（2026-09-25 改，见 `_loudness_windows`）：
       原来一人声段出一个 RMS。但 silero 的默认切分阈值是**静音 >2 秒**才断开
       （`VadOptions.min_silence_duration_ms=2000`），而**连读的答案**（句间只停
       0.3~1 秒，真人常态）只会切出**一个**人声段 ⇒ `loudness_cv` / `tail_ratio`
       恒为 None ⇒ `confidence_band` 返回 None ⇒ **整个「语气自信度」在实际使用中
       根本不会出现**。实测 3 段真中文 TTS 语音（19.0 / 18.7 / 30.8 秒）里
       **前两段只有 1 个人声段**，第三段是**故意插了 5.0/2.7/5.7 秒静音**的那份
       （4 段）才有值 —— 也就是说，不改成切窗，这个功能只有「说话带长停顿的人」
       才享受得到，那不是我们要的东西。
       切窗之后：**同一段真语音，有没有长停顿都算得出**，且 `loudness` 仍是
       「人声的整体响度」（等长窗时与整体 RMS 逐位相同）。

    ⚠️ 为什么不报「音量分贝」：RMS 是**相对量**，麦克风增益、说话距离、房间
       混响都会改它 —— 同一个人在两台机器上能差几倍。所以这三个都只当**段间
       相对量**用，绝对水平**不参与**任何判断（见 `confidence_band`）。
    """
    out = {"loudness": None, "loudness_cv": None, "tail_ratio": None}
    if audio is None or not regions:
        return out
    try:
        import numpy as np
        a = np.asarray(audio, dtype="float32").reshape(-1)
    except Exception:
        return out
    if a.size == 0:
        return out
    min_len = max(1, sampling_rate // 100)      # 短于 10ms 的块没意义，剔掉
    rms: list = []
    for ws, we in _loudness_windows(regions):
        s = max(0, ws * sampling_rate // 1000)
        e = min(a.size, we * sampling_rate // 1000)
        if e - s < min_len:
            continue
        seg = a[s:e].astype("float64")
        rms.append(float(np.sqrt(float(np.mean(seg * seg)))))
    if not rms:
        return out
    mean = sum(rms) / len(rms)
    if mean <= 0:
        return out
    out["loudness"] = round(mean, 6)
    if len(rms) >= 2:
        var = sum((x - mean) ** 2 for x in rms) / len(rms)
        out["loudness_cv"] = round((var ** 0.5) / mean, 4)
        out["tail_ratio"] = round(rms[-1] / mean, 4)
    return out


def emotion_clip(audio, regions: list, sampling_rate: int = 16000,
                 max_sec: float = A11_ASR_EMOTION_MAX_SEC):
    """取**前 `max_sec` 秒的人声**拼成一段（静音不要），喂给情感模型。

    静音对情感模型是噪声；而 whisper 那条链要的是带静音的原始音频（它自己 VAD），
    两处需求不同，所以这里单独拼一份，**不改动 `transcribe()` 用的那个数组**。
    """
    if audio is None or not regions:
        return None
    try:
        import numpy as np
        a = np.asarray(audio, dtype="float32").reshape(-1)
    except Exception:
        return None
    if a.size == 0:
        return None
    want = int(max_sec * sampling_rate)
    parts, got = [], 0
    for r in regions:
        if got >= want:
            break
        try:
            s = max(0, int(r["start_ms"]) * sampling_rate // 1000)
            e = min(a.size, int(r["end_ms"]) * sampling_rate // 1000)
        except (KeyError, TypeError, ValueError):
            continue
        if e <= s:
            continue
        parts.append(a[s:e])
        got += e - s
    if not parts:
        return None
    clip = np.concatenate(parts)
    return clip[:want] if clip.size > want else clip


def confidence_band(loudness_cv, tail_ratio) -> tuple:
    """`(档位, 依据列表)` —— 只由**韵律两指标**推出的启发式档位。

    ⛔ 这不是心理测量学意义上的自信度量表，**也不是模型输出**。规则写死在这里，
       唯一的目的是「同一组输入 ⇒ 同一个档位」，可复现、可争辩、可改。

    四条刻意的设计（前三条是取舍，第四条是**实测逼出来的**）：
      · **不用 `loudness` 的绝对值** —— 见 `loudness_metrics` 的注释，它跨设备不可比。
        它照样报出来（当事实），但**不参与判档**。
      · **不用语速** —— 语速已有自己的口径，且本模块明写「答得快不等于答得好」。
        让自信度再去解读一次语速，等于从后门把那句话推翻。
      · **也不用情感分布** —— 见下。
      · ⚠️ **情感分布为什么被踢出判档**（2026-09-25 实测，`_tmp_r5_emo_zh.py`）：
        在 3 段**真中文**语音（SAPI 合成的、与 ASR 核验同一批）上，
        `superb/wav2vec2-base-superb-er` **3/3 都给 `hap`**、置信 0.71/0.95/0.71，
        `sad` 恒为 0.000 —— **一次都没落在「中性」**。我原本写在这里的假设
        「中文语音上多半输出 neu」**是错的**（探针一跑就露）。同时它对一段完全
        平铺的合成音敢给 0.95，说明它**在域外输入上过度自信**。
        一个在目标域上近似**常量**的信号不是证据：把它算进档位，等于给每个人
        加同一个固定偏置（实测会一致地推向「偏高」），看着像有信息，其实没有。
        ⇒ 情感**照报**（赛题 3b 要求集成情感分析，且它是有用的原始观察），
          但**不参与**这里的融合。要把它加回来，先拿带标注的中文情感语料
          证明它在目标域上有区分度 —— 没有那个证据就不要加。

    两个韵律信号的读法：`loudness_cv` 小 = 音量稳；`tail_ratio` >= 1 = 收得住、
    <= 0.7 = 越说越小。阈值 ±0.5，单项权重最大 1.0，所以**要推出两档
    （偏低/偏高）需要两个信号方向一致** —— 单个信号只能到「中等」。
    """
    score = 0.0
    n = 0
    ev: list = []
    if loudness_cv is not None:
        n += 1
        if loudness_cv >= 0.5:
            score -= 1.0
            ev.append(f"段间音量起伏大（变异系数 {loudness_cv:.2f}）")
        elif loudness_cv <= 0.2:
            score += 1.0
            ev.append(f"段间音量稳（变异系数 {loudness_cv:.2f}）")
        else:
            ev.append(f"段间音量起伏中等（变异系数 {loudness_cv:.2f}）")
    if tail_ratio is not None:
        n += 1
        if tail_ratio <= 0.7:
            score -= 1.0
            ev.append(f"收尾音量降到全段均值的 {tail_ratio:.2f}（越说越小）")
        elif tail_ratio >= 1.0:
            score += 0.5
            ev.append(f"收尾音量是全段均值的 {tail_ratio:.2f}（收得住）")
        else:
            ev.append(f"收尾音量是全段均值的 {tail_ratio:.2f}")
    if n == 0:
        return None, []
    if score >= 0.5:
        return CONFIDENCE_HIGH, ev
    if score <= -0.5:
        return CONFIDENCE_LOW, ev
    return CONFIDENCE_MID, ev


class EmotionEngine:
    """
    情感模型（懒加载 / 失败永久降级 / **三态可分辨**）。

    状态机与 `AsrEngine`、`RagIndex` 逐条同构（**故意不另创一套**）：
        未加载 → load() 成功 → usable=True
        未加载 → load() 失败 → _failed=True，本进程内**永久降级**（重启才重试）
    失败只影响情感那 4 个键（恒为 None），面试链路与转写一个字节都不受影响。

    ⚠️ **没开**（`A11_ASR_EMOTION=0`）与**坏了**（依赖/权重不在）必须分得开 ——
       前者是运维选择，后者要看得见（见 `emotion_status()`）。
    ⚠️ `local_files_only=True` 是**刻意**的：绝不允许在一次真实面试的请求里
       触发一个 360MB 的下载（那会让 `/asr` 卡几十秒甚至超时）。权重必须**预先**
       下好，没下好就走「坏了」这条三态，如实报出来。
    """

    def __init__(self, model_id: str = ""):
        self.model_id = model_id or config.A11_ASR_EMOTION_MODEL
        self._model = None
        self._extractor = None
        self._failed = False
        self._lock = threading.Lock()
        self.error = ""
        self.tag = ""

    @property
    def usable(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if not config.A11_ASR_EMOTION or self._failed or self._model is not None:
            return
        with self._lock:
            if self._failed or self._model is not None:
                return
            try:
                from transformers import (AutoFeatureExtractor,
                                          AutoModelForAudioClassification)
                t0 = time.time()
                self._extractor = AutoFeatureExtractor.from_pretrained(
                    self.model_id, local_files_only=True)
                self._model = AutoModelForAudioClassification.from_pretrained(
                    self.model_id, local_files_only=True)
                self._model.eval()
                self._model.to(self._device())
                labels = sorted((self._model.config.id2label or {}).values())
                self.tag = f"{self.model_id}({'/'.join(labels)})"
                logger.info("情感模型就绪：%s（%dms）", self.tag,
                            int((time.time() - t0) * 1000))
            except Exception as e:
                self._failed = True
                self.error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "情感模型加载失败，本进程内不再重试（情感四项恒为 None，"
                    "转写与面试不受影响）：%s", self.error)

    def _device(self) -> str:
        d = (config.A11_ASR_EMOTION_DEVICE or "cpu").strip().lower()
        if d and not d.startswith("cpu"):
            try:
                import torch
                if torch.cuda.is_available():
                    return d
            except Exception:
                pass
            logger.warning("A11_ASR_EMOTION_DEVICE=%s 但 CUDA 不可用，退回 cpu", d)
        return "cpu"

    def infer(self, audio, regions: list) -> Optional[dict]:
        """→ `{emotion, emotion_score, emotion_dist}`；没开/坏了/量不出 → None。"""
        if not config.A11_ASR_EMOTION:
            return None
        clip = emotion_clip(audio, regions)
        if clip is None or clip.size == 0:
            return None
        if not self.usable:
            self.load()
            if not self.usable:
                return None
        try:
            import torch
            dev = self._device()
            inp = self._extractor(clip, sampling_rate=16000, return_tensors="pt")
            inp = {k: (v.to(dev) if hasattr(v, "to") else v) for k, v in inp.items()}
            with torch.no_grad():
                logits = self._model(**inp).logits
            probs = torch.softmax(logits.float(), dim=-1)[0].tolist()
            id2 = self._model.config.id2label or {}
            dist = {str(id2.get(i, i)): round(float(p), 6)
                    for i, p in enumerate(probs)}
            top = max(dist, key=lambda k: dist[k])
            return {"emotion": top, "emotion_score": dist[top],
                    "emotion_dist": dist}
        except Exception as e:
            # 推理失败也**永久降级**：同一段代码在同一个进程里再试一次不会变好，
            # 而每轮都白等几百毫秒是实打实的代价。
            self._failed = True
            self.error = f"{type(e).__name__}: {e}"
            logger.warning("情感模型推理失败，本进程内不再重试：%s", self.error)
            return None


_emotion: Optional["EmotionEngine"] = None
_emotion_lock = threading.Lock()


def get_emotion() -> "EmotionEngine":
    """情感模型单例（双检锁，与 `get_asr()`／`scoring` 同款）。**不在这里加载权重。**"""
    global _emotion
    if _emotion is None:
        with _emotion_lock:
            if _emotion is None:
                _emotion = EmotionEngine()
    return _emotion


def emotion_status() -> dict:
    """给 /health 与 check_env.py 看的四键状态（与 `resource_status()` 同形）。

    ⚠️ 只**问**状态、不加载模型 —— 一次 `/health` 不该把 360MB 权重读进内存。
       `emotion_ready` 因此是「**本进程内已知可用**」，冷启动时它可能是 false
       而同一次请求真的去转写时又会变 true。这个差别写在这里，别被误读成
       「模型坏了」—— 那是 `emotion_error` 非空才代表的事。
    """
    if not config.A11_ASR_EMOTION:
        return {"emotion_enabled": False, "emotion_ready": False,
                "emotion_error": "", "emotion_model": ""}
    eng = get_emotion()
    return {"emotion_enabled": True, "emotion_ready": eng.usable,
            "emotion_error": eng.error, "emotion_model": eng.model_id}


# ============================================================
# 转写引擎
# ============================================================
class AsrEngine:
    """
    一个进程一个实例（`get_asr()` 双检锁，与 scoring.py / rag.py 同款）。

    状态机（与 RagIndex 逐条同构，**故意不另创一套**）：
        未加载 → load() 成功 → usable=True
        未加载 → load() 失败 → _failed=True，本进程内**永久降级**（重启才重试）
    失败只影响 /asr，面试链路一个字节都不受影响。
    """

    def __init__(self):
        self.model_name = config.A11_ASR_MODEL
        self.device = config.A11_ASR_DEVICE
        self.compute_type = config.A11_ASR_COMPUTE_TYPE
        self.error = ""
        self.warmup_sec: Optional[float] = None
        self.last_elapsed_ms: Optional[int] = None
        self._model = None
        self._failed = False
        self._loading = False          # 有线程正在加载（别的请求别再起一个）
        self._ready_ev = threading.Event()
        self._lock = threading.Lock()

    # ---------- 标签 ----------
    @property
    def tag(self) -> str:
        """进 /health 与 `speech.asr_model`。换档位后历史语速口径会变，靠它分辨。"""
        return f"faster-whisper-{self.model_name}({self.compute_type})"

    @property
    def usable(self) -> bool:
        return (self._ready_ev.is_set() and not self._failed
                and self._model is not None)

    @property
    def loading(self) -> bool:
        return self._loading and not self._ready_ev.is_set()

    # ---------- 加载 ----------
    def load(self) -> None:
        """
        加载模型。**任何异常都必须吞掉**（照抄 rag.py::warmup 的理由）：
        失败后置 `_failed` 闩，/health 报出原因，面试照常。
        """
        if self._ready_ev.is_set():
            return
        with self._lock:
            if self._ready_ev.is_set():
                return
            self._loading = True
            t0 = time.time()
            try:
                if config.A11_ASR_MOCK:
                    # 桩模式：不 import 也不加载任何模型，返回确定性假转写。
                    # 冒烟测试与 4 号 的假服务用同一条路（与 RERANKER_MOCK 同款）。
                    self._model = "mock"
                    self.warmup_sec = 0.0
                    logger.info("ASR 以桩模式就绪（A11_ASR_MOCK=1，不加载真模型）")
                    return

                # ① 内存预检 —— 放在加载任何东西之前。取不到值就跳过（不是当 0）
                avail = free_mb()
                if avail is not None and avail < config.A11_ASR_MIN_FREE_MB:
                    raise MemoryError(
                        f"空闲内存 {avail}MB < 门槛 {config.A11_ASR_MIN_FREE_MB}MB")
                logger.info("ASR 内存预检通过：空闲 %s MB（门槛 %d MB）",
                            avail if avail is not None else "未知",
                            config.A11_ASR_MIN_FREE_MB)

                # ② 真加载（这里才 import faster_whisper）
                from faster_whisper import WhisperModel
                self._model = WhisperModel(
                    self._repo_id(), device=self.device,
                    compute_type=self.compute_type,
                    # ⚠️ 显式给 download_root：不给的话 huggingface_hub 会落到
                    #    ~/.cache/huggingface（C 盘），违反「数据放 D/E 盘」。
                    download_root=config.HF_HOME,
                )
                self.warmup_sec = time.time() - t0
                logger.info("ASR 就绪 model=%s device=%s compute=%s 耗时 %.1fs"
                            "（空闲内存现为 %s MB）",
                            self.tag, self.device, self.compute_type,
                            self.warmup_sec,
                            free_mb() if free_mb() is not None else "?")
            except Exception as e:
                self._failed = True
                self.error = f"{type(e).__name__}: {e}"
                logger.error("ASR 加载失败，本进程内永久降级（面试与文字输入照常）：%s",
                             self.error)
            finally:
                self._loading = False
                self._ready_ev.set()

    def _repo_id(self) -> str:
        """`small` → `Systran/faster-whisper-small`；带 `/` 的按完整 repo id 用。"""
        m = self.model_name
        return m if "/" in m else f"Systran/faster-whisper-{m}"

    def ensure_loaded(self, wait_sec: float) -> str:
        """
        确保模型已就绪，返回状态字符串：
            "ready"    可以用
            "failed"   本进程内已永久降级（error 里有原因）
            "loading"  正在加载且 wait_sec 内没等到（调用方应回 503 + Retry-After）
        并发语义：第一个请求起加载线程，其余请求**等同一个事件**，不会重复加载。
        """
        if self.usable:
            return "ready"
        if self._failed:
            return "failed"
        if not self._loading:
            threading.Thread(target=self.load, name="asr-load",
                             daemon=True).start()
        self._ready_ev.wait(max(0.0, wait_sec))
        if self.usable:
            return "ready"
        return "failed" if self._failed else "loading"

    # ---------- 转写 ----------
    def transcribe(self, path: str) -> dict:
        """
        音频文件 → {text, audio_ms, duration_ms, segments, pauses,
        pause_total_ms, elapsed_ms, loudness, loudness_cv, tail_ratio,
        emotion, emotion_score, emotion_dist}。

        段级时间戳（`segments`）是**必须**的（不是锦上添花）：它是转写文本与
        时间的对应，前端字幕也用它。

        后 6 个键（韵律 + 情感）全部**可以同时为 None**：没开情感
        （`A11_ASR_EMOTION=0`）、模型没下、VAD 没量出人声 —— 都会让它们为 None，
        而**这不影响 `text` 与 `duration_ms`**（转写本身从不因附加测量而失败）。

        `duration_ms`（净语音时长）取 **VAD 人声块之和**，不是整个文件的时长
        （后者会把「录音后忘了按停」的静音也算进语速分母），也不是 whisper 段
        跨度之和（段会把静音吞进去，实测能把语速压掉一半 —— 见
        `speech_regions()`）。`pauses` / `pause_total_ms` 一并在这里量好返回，
        前端原样回传即可；`derive_speech` 优先采信它们。

        抛异常由调用方兜住（端点转成 500/503），本函数不吞异常 —— 与
        `RagIndex.search` 的「吞掉并返回空」不同：那边少一份参考材料无所谓，
        这里吞掉就等于给考生一个空转写，那比报错更糟。
        """
        if config.A11_ASR_MOCK:
            return self._mock_result()

        from faster_whisper import WhisperModel      # noqa: F401  （仅为类型可读性）
        from faster_whisper.audio import decode_audio

        t0 = time.time()
        # 先解码再判时长：这样超长音频在**转写之前**就能被拒，不用白跑一遍
        audio = decode_audio(path, sampling_rate=16000)
        audio_ms = int(len(audio) / 16000 * 1000)
        if audio_ms > config.A11_ASR_MAX_SEC * 1000:
            raise AudioTooLong(
                f"音频 {audio_ms / 1000:.1f} 秒 > 上限 {config.A11_ASR_MAX_SEC} 秒")

        segments, _info = self._model.transcribe(
            audio,
            language=config.A11_ASR_LANGUAGE,
            beam_size=config.A11_ASR_BEAM,
            # VAD 去静音：whisper 系在纯静音上会**幻觉**出一句完整的话
            # （训练数据里「请订阅」一类），不去 VAD 会凭空多出考生没说过的话。
            vad_filter=True,
            condition_on_previous_text=False,   # 同理：防止幻觉沿上下文传染
        )
        segs = []
        for s in segments:                      # 生成器，必须迭代完
            txt = (s.text or "").strip()
            if not txt:
                continue
            segs.append({"start_ms": int(s.start * 1000),
                         "end_ms": int(s.end * 1000),
                         "text": txt})
        text = "".join(s["text"] for s in segs).strip()

        # 净时长与停顿：**在音频上量**（VAD 人声块），不是从上面这些段推 ——
        # 理由见 `speech_regions()`。量不到（VAD 版本变了 / onnxruntime 没装）
        # 就退回「段跨度之和 + 停顿给 None」：这是**降级**，转写照常出结果，
        # 但绝不用假的 0 冒充「他没停顿」。
        try:
            regions = speech_regions(audio)
        except Exception as e:
            logger.warning("VAD 人声区间测量失败，净时长退回段跨度之和、"
                           "停顿记 None（本次转写照常）：%s", e)
            regions = []
        if regions:
            net_ms = sum(r["end_ms"] - r["start_ms"] for r in regions)
            # 停顿的判据（>PAUSE_MIN_MS）只有 derive_speech 一处实现 ——
            # 这里把 VAD 人声块当「段」喂进去，只取回那两个数。
            sp = derive_speech(text, duration_ms=net_ms, segments=regions)
            pauses, pause_total_ms = sp["pauses"], sp["pause_total_ms"]
        else:
            net_ms = sum(s["end_ms"] - s["start_ms"] for s in segs)
            pauses = pause_total_ms = None

        # ---- 韵律三指标 + 情感（2026-09-25，赛题 3b）----
        # ⚠️ 这里是**全仓唯一**能在真音频上算它们的地方：`audio` 是上面
        #    `decode_audio` 出来的局部数组，函数一返回就回收；全仓只有这一处
        #    调 `decode_audio`。错过这里，后面谁也没有音频了。
        # ⚠️ 三件事分别兜异常、**互不牵连**：音量算不出来不该连累情感，
        #    情感模型没装不该连累转写，转写更不该因为这两个附加项而失败。
        #    这与上面 VAD 那段同一条姿态：附加测量失败就降级成 None，如实报出来。
        loud = {"loudness": None, "loudness_cv": None, "tail_ratio": None}
        if regions:
            try:
                loud = loudness_metrics(audio, regions)
            except Exception as e:
                logger.warning("音量三指标测量失败，记 None（本次转写照常）：%s", e)
        emo = None
        try:
            emo = get_emotion().infer(audio, regions)
        except Exception as e:      # `infer` 自己已经吞了，这里是最后一道
            logger.warning("情感测量失败，记 None（本次转写照常）：%s", e)

        self.last_elapsed_ms = int((time.time() - t0) * 1000)
        return {
            "text": text,
            "audio_ms": audio_ms,
            "duration_ms": net_ms,
            "segments": segs,
            "pauses": pauses,
            "pause_total_ms": pause_total_ms,
            "elapsed_ms": self.last_elapsed_ms,
            # 韵律与情感：**量不出来就是 None**，不是 0 —— 与 SPEECH_EMPTY 同一条纪律。
            # ⚠️ 这 6 个键是**加法**（老前端不认识也无妨），但它们必须**恒在**，
            #    否则 4 号在真服务与桩之间会看到两套键集（见下面 `_mock_result`）。
            "loudness": loud["loudness"],
            "loudness_cv": loud["loudness_cv"],
            "tail_ratio": loud["tail_ratio"],
            "emotion": (emo or {}).get("emotion"),
            "emotion_score": (emo or {}).get("emotion_score"),
            "emotion_dist": (emo or {}).get("emotion_dist"),
        }

    def _mock_result(self) -> dict:
        """
        桩结果：固定的一小段话，**刻意带一个填充词和一次长停顿**，
        好让冒烟测试能把「语速/停顿/填充词」三条派生路径都走一遍。
        2026-09-25 起同样带韵律与情感 —— 且**键集与真服务逐字相同**
        （4 号 的假服务与本桩同形，否则前端只在一边能跑：本模块开头那条契约）。
        """
        segs = [
            {"start_ms": 0, "end_ms": 2600, "text": "嗯这道题我先说结论"},
            # 与上一段之间有 2.2 秒静音 → 一次长停顿（>1.5s）
            {"start_ms": 4800, "end_ms": 8400, "text": "然后缓存穿透是查不到的数据"},
        ]
        # 韵律：与上面两段的时长**自洽**的一组固定值（第二段比第一段轻 ⇒
        # tail_ratio < 1、loudness_cv > 0）。桩不许给出自相矛盾的数字 ——
        # 那是给 4 号看的样例，自相矛盾的样例会被照抄进前端。
        loud = {"loudness": 0.0525, "loudness_cv": 0.1429, "tail_ratio": 0.8571}
        # 情感：**跟着开关走**，否则 `A11_ASR_EMOTION=0` 时桩会凭空报出情感，
        # 与真服务（那几个键恒 None）在同一个开关下给出两套行为 —— 桩就失去意义了。
        # 分布**和为 1**（真服务由 softmax 保证，桩必须自己对上）。
        emo = ({"emotion": "neu", "emotion_score": 0.72,
                "emotion_dist": {"neu": 0.72, "hap": 0.18, "ang": 0.07, "sad": 0.03}}
               if config.A11_ASR_EMOTION
               else {"emotion": None, "emotion_score": None, "emotion_dist": None})
        self.last_elapsed_ms = 1
        return {
            "text": "".join(s["text"] for s in segs),
            "audio_ms": 9000,
            "duration_ms": sum(s["end_ms"] - s["start_ms"] for s in segs),
            "segments": segs,
            # 桩也要给出这两个键：4 号 的假服务与本桩同形，否则前端只在
            # 一边能跑（这是本模块开头就写下的契约）。数值与上面的段一致：
            # 段间 2.2 秒静音 = 一次长停顿 —— 桩刻意保留这个可验证的形状。
            "pauses": 1,
            "pause_total_ms": 2200,
            "elapsed_ms": 1,
            **loud, **emo,
        }


class AudioTooLong(ValueError):
    """音频超过 `A11_ASR_MAX_SEC`。单独一个类型，好让端点给出专门的错误码。"""


# ============================================================
# 单例（照抄 scoring.py / rag.py 的双检锁）
# ============================================================
_asr: Optional[AsrEngine] = None
_asr_lock = threading.Lock()


def get_asr() -> Optional[AsrEngine]:
    """
    取全局 ASR 引擎。`A11_ASR=0` 时返回 None（那是配置，不是故障）。

    与 `get_rag()` 同款：**不因为加载失败而返回 None** —— 失败原因要能被
    /health 报出来（对象留着，由 usable / error 表达状态）。
    """
    global _asr
    if not config.A11_ASR:
        return None
    if _asr is None:
        with _asr_lock:
            if _asr is None:
                _asr = AsrEngine()
    return _asr


def asr_status() -> dict:
    """ /health 用。区分「关掉」与「失败」，理由同 kg_status() / rag_status()。"""
    e = _asr
    return {
        "asr_enabled": config.A11_ASR,
        "asr_ready": bool(e is not None and e.usable),
        "asr_error": (e.error if e is not None else ""),
        "asr_model": (e.tag if e is not None else ""),
    }


def allowed_format(filename: str) -> bool:
    """格式白名单（按扩展名）。白名单而不是黑名单 —— 黑名单总会漏。"""
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return ext in config.ASR_FORMATS


def save_temp(data: bytes, filename: str) -> str:
    """
    把上传字节落到**临时文件**（转写库要的是路径，不是字节）。

    ⚠️ 这是全项目唯一一处把考生音频写到磁盘的地方，且：
      · 落在系统临时目录，**不在** `logs/`、不在项目里、不在 raw 里；
      · 调用方负责在 finally 里 `os.unlink`（见 api/interview.py 的 /asr）。
    为什么不留内存：faster-whisper 的 `decode_audio` 只吃路径，要走内存
    得自己引 av 解容器，等于把「格式兼容」这件事从库手里拿回来自己做。
    """
    ext = os.path.splitext(filename or "")[1].lower() or ".bin"
    fd, path = tempfile.mkstemp(prefix="a11_asr_", suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path
