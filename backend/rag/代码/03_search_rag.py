# -*- coding: utf-8 -*-
"""
============================================================
03 · RAG 检索脚本（双模式：出题 / 追问深挖）
============================================================
功能：输入一个面试问题/考生表述 → 从 ChromaDB 召回 Top-20 →
      交叉编码器精排 → 按原题ID去重 → 输出命中题目。

★ 双模式（对应两个真实面试场景）：

  模式一 · 出题模式（默认）：
      面试官要"下一道题问什么" → 按原题ID去重取 Top-N 道不同题。
      理由：3 道不同的题 > 3 条同一题的不同说法（后者是冗余）。

  模式二 · 追问/深挖模式（--expand）：
      考生答完一道题后，面试官需要追问/评分 → 只取最高分 1 条
      会丢信息（命中的可能是碎片得分点，完整答案在基准款里）。
      因此：先命中 Top-1 题，再按该「原题ID」把这一题的
      全部层级片段（原题/L1/L2/L3/得分点/铺垫/变体）取出来，
      支撑追问、逐点评分、降级引导。

检索链路：
  1. bge-m3 向量召回 Top-20（双塔，毫秒级，先捞全）
  2. bge-reranker-v2-m3 精排（交叉编码器，逐对打分，精度高）
  3. 按原题ID去重（出题模式）或按题取全量（深挖模式）

用法：
  # 出题模式：返回 Top-3 道不同题
  python 03_search_rag.py "Java 里 == 和 equals 的区别？"

  # 深挖模式：命中 1 题 + 该题全部层级素材
  python 03_search_rag.py "Java 里 == 和 equals 的区别？" --expand

  # 过滤/定制
  python 03_search_rag.py "Redis 缓存穿透怎么办" --job "Java 后端开发工程师" --top 5
============================================================
"""
import os, sys, argparse
# 模型下载源：默认走 huggingface.co（本机实测可直连；hf-mirror 反而超时）。
# 网络受限的环境请自行设置 HF_ENDPOINT=https://hf-mirror.com 走镜像。
# 默认允许联网下载模型（交付包不含 4.5GB 模型文件）；模型就位后可设 HF_HUB_OFFLINE=1
os.environ.setdefault("HF_HUB_OFFLINE", "0")
import torch
torch.set_num_threads(int(os.environ.get("RAG_THREADS", os.cpu_count() or 8)))
import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder

# ---- 路径自适应：优先使用交付包内的相对路径（成员机器解压即用） ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 交付包根目录
def _pick(*candidates):
    """按存在性选择：交付包结构优先，开发机构建目录回退。

    全部候选都不存在时快速失败（原先返回 candidates[0] 会让 chromadb
    静默创建空库，表现为「检索永远无结果」而非「路径配错」）。
    """
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        "路径不存在，已尝试：\n  " + "\n  ".join(candidates)
        + "\n请确认交付包结构完整（vector_db/ 与本脚本所在目录同级）。"
    )

# ★ 向量库目录名必须是纯 ASCII：chromadb 打不开「含非 ASCII 字符的绝对路径」
#   （实测 100% 失败，报 Error loading hnsw index）。旧名为「向量库/」，此处自动升级。
VECTOR_DIR = os.path.join(_PKG_ROOT, "vector_db")
_LEGACY_VECTOR_DIR = os.path.join(_PKG_ROOT, "向量库")
if not os.path.exists(VECTOR_DIR) and os.path.exists(_LEGACY_VECTOR_DIR):
    print("[init] 旧目录名「向量库」→ vector_db（chromadb 不支持含中文的绝对路径）",
          flush=True)
    os.rename(_LEGACY_VECTOR_DIR, VECTOR_DIR)

CHROMA_DIR = _pick(os.path.join(VECTOR_DIR, "chroma_db_v2"),
                   os.path.join(_PKG_ROOT, "chroma_db_v2"))     # 向量库目录
if not os.path.abspath(CHROMA_DIR).isascii():
    raise RuntimeError(
        f"向量库路径含非 ASCII 字符，chromadb 无法打开：{CHROMA_DIR}\n"
        f"  请移动到纯 ASCII 路径（推荐 {VECTOR_DIR}）。")
COLLECTION = "a11_interview_kb_v5v2"
EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="检索问题（面试官视角或考生表述）")
    ap.add_argument("--job", default=None, help="按岗位过滤")
    ap.add_argument("--level", default=None,
                    help="按层级过滤（原题/语义变体/L1/L2/L3/基础得分点/进阶得分点/基础铺垫/场景化/答案变体）")
    ap.add_argument("--top", type=int, default=3, help="出题模式返回几道题")
    ap.add_argument("--expand", action="store_true",
                    help="追问/深挖模式：命中后按原题ID取该题全部层级片段")
    args = ap.parse_args()

    print(f"[load] embedding model ...", flush=True)
    emb_model = SentenceTransformer(EMBED_MODEL)
    emb_model.max_seq_length = 512
    print(f"[load] reranker ...", flush=True)
    rerank = CrossEncoder(RERANK_MODEL, max_length=512)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_collection(COLLECTION)
    print(f"[chroma] collection size: {col.count()}", flush=True)

    # 查询向量化（与构建时同一模型/同一 normalize）
    qv = emb_model.encode([args.query], normalize_embeddings=True)[0].tolist()

    # 可选元数据过滤（岗位/层级）
    where = {}
    if args.job:
        where["所属岗位"] = args.job
    if args.level:
        where["对应层级"] = args.level

    # 第一段：向量召回 Top-20
    res = col.query(query_embeddings=[qv], n_results=20, where=where or None)
    docs, metas, ids = res["documents"][0], res["metadatas"][0], res["ids"][0]

    # 第二段：交叉编码器精排（问题 vs 每条候选）
    pairs = [[args.query, d] for d in docs]
    scores = rerank.predict(pairs)

    # ============================================================
    # 模式一：出题模式 —— 按原题ID去重，保留每道题最高分条目
    # ============================================================
    best = {}
    for i, m in enumerate(metas):
        pid = m["原题ID"]
        if pid not in best or scores[i] > best[pid][0]:
            best[pid] = (scores[i], docs[i], m, ids[i])
    ranked = sorted(best.values(), key=lambda x: -x[0])[:args.top]

    print(f"\n=== 命中 Top-{args.top} 道题（按原题ID去重）===")
    for sc, doc, m, i in ranked:
        print(f"\n[score {sc:.3f}] id={i} 层级={m['对应层级']} 原题ID={m['原题ID']}")
        print(f"  岗位={m['所属岗位']} 题型={m['题型分类']} 难度={m['难度等级']}")
        print(f"  内容: {doc[:180].replace(chr(10),' ')}...")

    # ============================================================
    # 模式二：追问/深挖模式 —— 命中 Top-1 题后取该题全部层级
    # ============================================================
    if args.expand and ranked:
        pid = ranked[0][2]["原题ID"]          # 最高分题的原始ID
        print(f"\n=== 深挖模式：原题ID={pid} 的全部 RAG 片段 ===")
        full = col.get(where={"原题ID": pid})  # Chroma 按元数据精确取该题全部条目
        items = sorted(zip(full["ids"], full["documents"], full["metadatas"]),
                       key=lambda x: _level_order(x[2].get("对应层级", "")))
        print(f"共 {len(items)} 条（覆盖全部层级）:")
        for i, (iid, doc, m) in enumerate(items):
            head = doc.replace("\n", " ")[:110]
            print(f"\n[{i+1}] 层级={m.get('对应层级')} 考点={m.get('考点优先级')} 难度={m.get('难度等级')}")
            print(f"    题目: {head.split(' ',1)[0][:50]}")
            print(f"    内容: {head[:150]}...")


def _level_order(lv):
    """深挖模式排序：基准款→追问→得分点→其余（便于面试官按序使用）"""
    order = {"原题": 0, "L1": 1, "L2": 2, "L3": 3,
             "基础得分点": 4, "进阶得分点": 5, "语义变体": 6,
             "场景化": 7, "答案变体": 8, "基础铺垫": 9}
    return order.get(lv, 99)


if __name__ == "__main__":
    main()
