# -*- coding: utf-8 -*-
"""
============================================================
03 · RAG 检索脚本（双模式：出题 / 追问深挖）
============================================================
功能：输入一个面试问题/考生表述 → 从 ChromaDB 召回 Top-20 →
      交叉编码器精排 → 按原题ID去重 → 输出命中题目。

★ 三种出题路径：

  1) 知识图谱出题模式（默认，推荐）：
     向量召回 Top-200 → reranker 精排 → 取种子 Top-K →
     图谱 2-hop 扩展（共享知识点/关键词）→ 融合打分 → 按原题ID去重取 Top-N

  2) 经典出题模式（KG 文件不存在时自动降级，或 --classic 强制）：
     向量召回 Top-20 → reranker 精排 → 按原题ID去重取 Top-N

  3) 深挖模式（--expand）：
     先选 Top-1 题（走当前出题路径），再按该原题ID 取出全部层级片段。

检索链路：
  1. bge-m3 向量召回
  2. bge-reranker-v2-m3 精排
  3. 图谱 2-hop 扩展（仅 KG 模式）
  4. 按原题ID去重 / 按题取全量

用法：
  # 默认走知识图谱
  python 03_search_rag.py "Java 里 == 和 equals 的区别？"
  python 03_search_rag.py "Redis 缓存穿透怎么办" --job "Java 后端开发工程师" --top 5

  # 深挖模式
  python 03_search_rag.py "Redis 缓存穿透怎么办" --expand

  # 强制走经典 Top-N
  python 03_search_rag.py "Redis 缓存穿透怎么办" --classic
============================================================
"""
import os, sys, argparse, pickle
from collections import defaultdict

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# ★ 不写死离线（1 号修复点 P0-2）
os.environ.setdefault("HF_HUB_OFFLINE", "0")

import torch
torch.set_num_threads(int(os.environ.get("RAG_THREADS", os.cpu_count() or 8)))
import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder

# ---- 路径自适应 ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pick(*candidates):
    """按存在性选择：交付包结构优先，开发机构建目录回退。
    ★ 全部未命中 → 明确抛错（1 号修复点 P1-4）"""
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("RAG 数据目录不存在，已尝试: " + " | ".join(candidates))


def _ensure_ascii_chroma(src_dir):
    r"""chromadb 1.5.9 的 HNSW 段 reader 不支持非 ASCII 路径（Windows 中文路径会报
    Error loading hnsw index）。路径含非 ASCII 时，自动复制到纯 ASCII 缓存目录
    （C:\Windows\Temp\a11_rag_kb\chroma_db_v2）后返回缓存路径；已缓存则跳过复制。"""
    if all(ord(ch) < 128 for ch in src_dir):
        return src_dir
    import shutil
    roots = [os.environ.get("TEMP", ""), r"C:\Windows\Temp", r"C:\ProgramData"]
    root = next((r for r in roots if r and os.path.isdir(r) and all(ord(ch) < 128 for ch in r)), r"C:\Windows\Temp")
    dst = os.path.join(root, "a11_rag_kb", "chroma_db_v2")
    marker_src = os.path.join(src_dir, "chroma.sqlite3")
    marker_dst = os.path.join(dst, "chroma.sqlite3")
    if os.path.isfile(marker_src) and os.path.isfile(marker_dst) and os.path.getsize(marker_dst) == os.path.getsize(marker_src):
        return dst
    os.makedirs(dst, exist_ok=True)
    for item in os.listdir(src_dir):
        s = os.path.join(src_dir, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    print(f"[init] 检测到非 ASCII 路径，向量库已缓存至 {dst}", flush=True)
    return dst

def _build_where(**kw):
    """ChromaDB 1.5+ 要求 where 只允许一个顶层操作符，
    多条件必须用 $and 包裹。空条件返回 None。"""
    conds = [{k: v} for k, v in kw.items() if v]
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


CHROMA_DIR = os.environ.get("RAG_CHROMA_DIR") or _pick(
    os.path.join(_PKG_ROOT, "vector_db", "chroma_db_v2"),
    os.path.join(_PKG_ROOT, "向量库", "chroma_db_v2"),
    r"E:\GitHubRepos\rag-db-v5\chroma_db_v2",
)
CHROMA_DIR = _ensure_ascii_chroma(CHROMA_DIR)
COLLECTION = "a11_interview_kb_v5v2"
EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
KG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "kg_question_graph.pkl")

# 知识图谱全局
KG_GRAPH = None
KG_QUESTIONS = None


def _load_kg():
    """加载知识图谱；不存在则返回 False，出题自动降级为经典 Top-N。"""
    global KG_GRAPH, KG_QUESTIONS
    if not os.path.exists(KG_PATH):
        print("[warn] 未找到 kg_question_graph.pkl，出题将使用经典 Top-N", flush=True)
        return False
    with open(KG_PATH, "rb") as f:
        payload = pickle.load(f)
    KG_GRAPH = payload["graph"]
    KG_QUESTIONS = payload["questions"]
    print(f"[init] 知识图谱已加载：题目={len(KG_QUESTIONS)} 边={KG_GRAPH.number_of_edges()}",
          flush=True)
    return True


def _level_order(lv):
    """深挖模式排序：基准款→追问→得分点→其余（便于面试官按序使用）"""
    order = {"原题": 0, "L1": 1, "L2": 2, "L3": 3,
             "基础得分点": 4, "进阶得分点": 5, "语义变体": 6,
             "场景化": 7, "答案变体": 8, "基础铺垫": 9}
    return order.get(lv, 99)


def _explain_reason(pid, seed_scores, max_items=3):
    """说明这道题为什么被选中：通过哪些知识点/关键词与种子题关联。"""
    if KG_GRAPH is None or not KG_GRAPH.has_node(f"Q:{pid}"):
        return ""
    reasons = []
    for mid in KG_GRAPH.neighbors(f"Q:{pid}"):
        mtype = KG_GRAPH.nodes[mid].get("type")
        if mtype not in ("knowledge", "keyword"):
            continue
        mid_name = KG_GRAPH.nodes[mid].get("name", mid)
        for other in KG_GRAPH.neighbors(mid):
            if not other.startswith("Q:"):
                continue
            opid = other[2:]
            if opid in seed_scores:
                kind = "知识点" if mtype == "knowledge" else "关键词"
                reasons.append(f"与种子 {opid} 共享{kind}[{mid_name}]")
                if len(reasons) >= max_items:
                    return "；".join(reasons)
    return "；".join(reasons)


def _format_classic_item(sc, doc, m, iid):
    parts = doc.split("\n", 1)
    return {
        "score": round(sc, 4),
        "题目": parts[0],
        "参考答案": parts[1] if len(parts) > 1 else "",
        "原题ID": m["原题ID"],
        "题目ID": m.get("题目ID"),
        "层级": m.get("对应层级"),
        "岗位": m.get("所属岗位"),
        "题型": m.get("题型分类"),
        "难度": m.get("难度等级"),
        "面试阶段": m.get("面试阶段"),
        "考点优先级": m.get("考点优先级"),
        "图谱理由": "",
    }


def kg_select(query, qv, col, rerank, job=None, level=None, top=3,
              seed_k=50, hop_weight=0.3):
    where = _build_where(所属岗位=job, 对应层级=level)

    # ---- 优先走 query（带过滤） ----
    try:
        res = col.query(query_embeddings=[qv], n_results=200, where=where)
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        ids = res["ids"][0]
    except Exception as e:
        # ★ 降级：ChromaDB 1.5.x HNSW 索引与 SQLite 不同步时，
        #   过滤查询会报 "Error finding id"，改用 get() + 本地重排
        print(f"[warn] filtered query failed: {e}，降级为 get() + reranker 重排",
              flush=True)
        fallback_where = _build_where(对应层级="原题", 所属岗位=job)
        raw = col.get(where=fallback_where,
                      include=["documents", "metadatas"],
                      limit=500)
        docs = raw["documents"]
        metas = raw["metadatas"]
        ids = raw["ids"]

    if not docs:
        return []

    scores = rerank.predict([[query, d] for d in docs]).tolist()
    # ... 后续逻辑保持不变（seed 去重 → 图谱扩展 → Top-N）

    # 每道原题保留最高分条目
    seed = {}
    for i, m in enumerate(metas):
        pid = m.get("原题ID")
        if not pid:
            continue
        if pid not in seed or scores[i] > seed[pid][0]:
            seed[pid] = (scores[i], docs[i], m, ids[i])

    seed_sorted = sorted(seed.items(), key=lambda x: -x[1][0])[:seed_k]
    seed_scores = {pid: v[0] for pid, v in seed_sorted}

    # 图谱不可用 → 经典 Top-N 兜底
    if KG_GRAPH is None:
        return [_format_classic_item(v[0], v[1], v[2], v[3])
                for _, v in seed_sorted[:top]]

    # 图谱扩展打分
    score = defaultdict(float)
    for pid, (sc, _, _, _) in seed_sorted:
        score[pid] += sc

    for pid, (sc, _, _, _) in seed_sorted:
        node = f"Q:{pid}"
        if not KG_GRAPH.has_node(node):
            continue
        for mid in KG_GRAPH.neighbors(node):
            mtype = KG_GRAPH.nodes[mid].get("type")
            if mtype not in ("knowledge", "keyword"):
                continue
            w1 = KG_GRAPH[node][mid].get("weight", 1.0)
            for other in KG_GRAPH.neighbors(mid):
                if other == node or not other.startswith("Q:"):
                    continue
                opid = other[2:]
                # 已是种子且分数更高 → 不重复累加
                if opid in seed_scores and seed_scores[opid] >= sc:
                    continue
                w2 = KG_GRAPH[mid][other].get("weight", 1.0)
                score[opid] += sc * hop_weight * w1 * w2

    ranked = sorted(score.items(), key=lambda x: -x[1])[:top]

    results = []
    for pid, gsc in ranked:
        q = KG_QUESTIONS.get(pid, {})
        # ★ 修复：图谱扩展可能跨岗位，非目标岗位直接跳过
        if job and q.get("岗位") != job:
            continue
        doc = q.get("doc", "")
        parts = doc.split("\n", 1)
        results.append({
            "score": round(gsc, 4),
            "题目": q.get("题目", parts[0] if parts else ""),
            "参考答案": parts[1] if len(parts) > 1 else "",
            "原题ID": pid,
            "题目ID": q.get("题目ID"),
            "层级": "原题",
            "岗位": q.get("岗位"),
            "题型": q.get("题型"),
            "难度": q.get("难度"),
            "面试阶段": q.get("阶段"),
            "考点优先级": q.get("优先级"),
            "关键词": q.get("关键词", []),
            "知识点": q.get("知识点", []),
            "图谱理由": _explain_reason(pid, seed_scores),
        })
    return results


def _expand_pid(col, pid):
    """按原题ID 取该题全部层级片段并打印"""
    full = col.get(where={"原题ID": pid})
    items = sorted(
        zip(full["ids"], full["documents"], full["metadatas"]),
        key=lambda x: _level_order(x[2].get("对应层级", "")),
    )
    print(f"\n=== 深挖模式：原题ID={pid} 的全部 RAG 片段 ===")
    print(f"共 {len(items)} 条（覆盖全部层级）:")
    for i, (iid, doc, m) in enumerate(items):
        head = doc.replace("\n", " ")[:150]
        print(f"\n[{i+1}] 层级={m.get('对应层级')} 考点={m.get('考点优先级')} 难度={m.get('难度等级')}")
        print(f"    内容: {head}...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="检索问题（面试官视角或考生表述）")
    ap.add_argument("--job", default=None, help="按岗位过滤")
    ap.add_argument("--level", default=None,
                    help="按层级过滤（原题/语义变体/L1/L2/L3/基础得分点/进阶得分点/基础铺垫/场景化/答案变体）")
    ap.add_argument("--top", type=int, default=3, help="出题模式返回几道题")
    ap.add_argument("--expand", action="store_true",
                    help="追问/深挖模式：命中后按原题ID取该题全部层级片段")
    ap.add_argument("--classic", action="store_true",
                    help="禁用知识图谱，使用经典 Top-N 出题")
    args = ap.parse_args()

    print(f"[load] embedding model ...", flush=True)
    emb_model = SentenceTransformer(EMBED_MODEL)
    emb_model.max_seq_length = 512
    print(f"[load] reranker ...", flush=True)
    rerank = CrossEncoder(RERANK_MODEL, max_length=512)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_collection(COLLECTION)
    print(f"[chroma] collection size: {col.count()}", flush=True)

    use_kg = (not args.classic) and _load_kg()

    # 查询向量化
    qv = emb_model.encode([args.query], normalize_embeddings=True)[0].tolist()

    # ============================================================
    # 知识图谱出题模式（默认）
    # ============================================================
    if use_kg:
        results = kg_select(
            args.query, qv, col, rerank,
            job=args.job, level=args.level, top=args.top,
        )
        print(f"\n=== 知识图谱命中 Top-{args.top} 道题 ===")
        if not results:
            print("（无命中）")
        for r in results:
            print(f"\n[score {r['score']:.3f}] 原题ID={r['原题ID']} 层级={r.get('层级')}")
            print(f"  岗位={r['岗位']} 题型={r['题型']} 难度={r['难度']} 优先级={r['考点优先级']}")
            print(f"  题目: {r['题目']}")
            if r.get("知识点"):
                print(f"  知识点: {', '.join(r['知识点'][:5])}")
            if r.get("图谱理由"):
                print(f"  图谱理由: {r['图谱理由']}")
        if args.expand and results:
            _expand_pid(col, results[0]["原题ID"])
        return

    # ============================================================
    # 经典 Top-N 兜底
    # ============================================================
    where = _build_where(所属岗位=args.job, 对应层级=args.level)
    res = col.query(query_embeddings=[qv], n_results=20, where=where)
    docs, metas, ids = res["documents"][0], res["metadatas"][0], res["ids"][0]

    pairs = [[args.query, d] for d in docs]
    scores = rerank.predict(pairs)

    best = {}
    for i, m in enumerate(metas):
        pid = m["原题ID"]
        if pid not in best or scores[i] > best[pid][0]:
            best[pid] = (scores[i], docs[i], m, ids[i])
    ranked = sorted(best.values(), key=lambda x: -x[0])[:args.top]

    print(f"\n=== 经典模式 命中 Top-{args.top} 道题（按原题ID去重）===")
    for sc, doc, m, i in ranked:
        print(f"\n[score {sc:.3f}] id={i} 层级={m['对应层级']} 原题ID={m['原题ID']}")
        print(f"  岗位={m['所属岗位']} 题型={m['题型分类']} 难度={m['难度等级']}")
        print(f"  内容: {doc[:180].replace(chr(10), ' ')}...")

    if args.expand and ranked:
        _expand_pid(col, ranked[0][2]["原题ID"])


if __name__ == "__main__":
    main()
