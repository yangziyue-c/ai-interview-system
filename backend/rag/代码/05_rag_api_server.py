# -*- coding: utf-8 -*-
"""
05 · RAG 检索 HTTP 服务（FastAPI 封装）
============================================================
给 1 号（后端主程）用的现成服务：把 03_search_rag.py 的检索逻辑
封装成 POST /rag/search HTTP 接口，供 2 号（AI 对话）调用。

启动方式（在 code 目录下）：
    pip install fastapi uvicorn
    python 05_rag_api_server.py

服务启动后：
    POST http://localhost:8003/rag/search
    Body: {"query": "Redis 缓存穿透怎么办",
           "job": "Java 后端开发工程师",      # 可空
           "mode": "select",                  # select=出题（优先图谱）| expand=深挖
           "top": 3, "level": null}           # level 可空（按层级过滤）

    GET  http://localhost:8003/health   → 健康检查

模式说明：
  - select（默认）：知识图谱增强出题（kg_question_graph.pkl 存在时）；
    KG 文件缺失时自动降级为经典 Top-N 出题，返回 mode 字段区分。
  - expand：先选 Top-1 题（同样走图谱/降级路径），再返回该题全层级片段。

环境变量覆盖位：
  RAG_PORT        端口，默认 8003
  RAG_THREADS     torch 线程数
  RAG_CHROMA_DIR  向量库目录
  RAG_MAIN_DIR    主库 JSON 目录
  HF_HUB_OFFLINE  模型离线开关，默认 "0"
"""
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# ★ 不写死离线：交付包不带模型（bge-m3+reranker 约 4.5GB），
#   成员机器无 HF 缓存时若写死 "1" 会在首次启动抛 OSError（1 号修复点 P0-2）
os.environ.setdefault("HF_HUB_OFFLINE", "0")

import torch
torch.set_num_threads(int(os.environ.get("RAG_THREADS", os.cpu_count() or 8)))
import chromadb
import json
import pickle
from collections import defaultdict
from sentence_transformers import SentenceTransformer, CrossEncoder
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn

# ---- 路径自适应 ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pick(*candidates):
    """按存在性选择。★ 全部未命中 → 明确抛错（1 号修复点 P1-4）"""
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("RAG 数据目录不存在，已尝试: " + " | ".join(candidates))


def _ensure_ascii_chroma(src_dir):
    """chromadb 1.5.9 的 HNSW 段 reader 不支持非 ASCII 路径（Windows 中文路径会报
    Error loading hnsw index）。路径含非 ASCII 时，自动复制到纯 ASCII 缓存目录
    （C:\\Windows\\Temp\\a11_rag_kb\\chroma_db_v2）后返回缓存路径；已缓存则跳过复制。"""
    if all(ord(ch) < 128 for ch in src_dir):
        return src_dir
    import shutil
    roots = [os.environ.get("TEMP", ""), r"C:\\Windows\\Temp", r"C:\\ProgramData"]
    root = next((r for r in roots if r and os.path.isdir(r) and all(ord(ch) < 128 for ch in r)), r"C:\\Windows\\Temp")
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
    r"E:\GitHubRepos\rag-db-v5\chroma_db_v2")
CHROMA_DIR = _ensure_ascii_chroma(CHROMA_DIR)
COLLECTION = "a11_interview_kb_v5v2"
EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
MAIN_DIR = os.environ.get("RAG_MAIN_DIR") or _pick(
    os.path.join(_PKG_ROOT, "data"),
    os.path.join(_PKG_ROOT, "数据"),
    r"C:\Users\litao\WorkBuddy\2026-09-10-21-25-17\ai-interview-data\v5")
KG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "kg_question_graph.pkl")

app = FastAPI(title="A11 RAG 检索服务", version="1.1")
# ★ CORS 放开（1 号修复点 P1-3）
app.add_middleware(CORSMiddleware,
                   allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---- 主库索引：题目ID -> 18 字段完整记录（启动时加载一次） ----
MAIN_INDEX = {}
for _p in ("java", "web", "test", "algorithm", "system-design"):
    _path = os.path.join(MAIN_DIR, f"{_p}-v5.json")
    if os.path.exists(_path):
        for _rec in json.load(open(_path, encoding="utf-8")):
            if "题目ID" in _rec:
                MAIN_INDEX[_rec["题目ID"]] = _rec

print(f"[init] 向量库目录 = {CHROMA_DIR}", flush=True)
print(f"[init] 主库目录   = {MAIN_DIR}", flush=True)
print(f"[init] main library loaded: {len(MAIN_INDEX)} 题", flush=True)

# ---- 知识图谱加载（可选，缺失时自动降级） ----
KG_GRAPH = None
KG_QUESTIONS = None
if os.path.exists(KG_PATH):
    with open(KG_PATH, "rb") as _f:
        _payload = pickle.load(_f)
    KG_GRAPH = _payload["graph"]
    KG_QUESTIONS = _payload["questions"]
    print(f"[init] KG loaded: questions={len(KG_QUESTIONS)} "
          f"edges={KG_GRAPH.number_of_edges()}", flush=True)
else:
    print("[init] KG file not found, mode=select 将降级为经典 Top-N", flush=True)


# ---- 请求/响应模型 ----
class SearchReq(BaseModel):
    query: str
    job: Optional[str] = None          # 岗位过滤
    mode: str = "select"               # select | expand | kg_select
    top: int = 3                       # select 模式返回几道题
    level: Optional[str] = None        # 层级过滤


# ---- 服务启动时加载模型（只加载一次） ----
print("[init] loading bge-m3 ...", flush=True)
emb_model = SentenceTransformer(EMBED_MODEL)
emb_model.max_seq_length = 512
print("[init] loading reranker ...", flush=True)
rerank = CrossEncoder(RERANK_MODEL, max_length=512)
client = chromadb.PersistentClient(path=CHROMA_DIR)
col = client.get_collection(COLLECTION)
print(f"[init] collection size: {col.count()}", flush=True)


# ============================================================
# 知识图谱出题：kg_select
# ============================================================
def _kg_explain(pid, seed_scores, max_items=3):
    if KG_GRAPH is None or not KG_GRAPH.has_node(f"Q:{pid}"):
        return ""
    reasons = []
    for mid in KG_GRAPH.neighbors(f"Q:{pid}"):
        mtype = KG_GRAPH.nodes[mid].get("type")
        if mtype not in ("knowledge", "keyword"):
            continue
        name = KG_GRAPH.nodes[mid].get("name", mid)
        for other in KG_GRAPH.neighbors(mid):
            if not other.startswith("Q:"):
                continue
            opid = other[2:]
            if opid in seed_scores:
                kind = "知识点" if mtype == "knowledge" else "关键词"
                reasons.append(f"与种子 {opid} 共享{kind}[{name}]")
                if len(reasons) >= max_items:
                    return "；".join(reasons)
    return "；".join(reasons)


def _format_classic(sc, doc, m, iid):
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


def kg_select(query, qv, job=None, level=None, top=3,
              seed_k=50, hop_weight=0.3):
    """
    知识图谱增强出题：
      1. 向量召回 Top-200
      2. reranker 精排 → 种子 Top-K
      3. 图谱 2-hop 扩展（共享知识点/关键词）
      4. 融合打分 → 按原题ID 去重取 Top-N
    KG 不可用时返回经典 Top-N。
    """
    where = _build_where(所属岗位=job, 对应层级=level)
    res = col.query(query_embeddings=[qv], n_results=200, where=where)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    ids = res["ids"][0]
    if not docs:
        return []

    scores = rerank.predict([[query, d] for d in docs]).tolist()

    seed = {}
    for i, m in enumerate(metas):
        pid = m.get("原题ID")
        if not pid:
            continue
        if pid not in seed or scores[i] > seed[pid][0]:
            seed[pid] = (scores[i], docs[i], m, ids[i])

    seed_sorted = sorted(seed.items(), key=lambda x: -x[1][0])[:seed_k]
    seed_scores = {pid: v[0] for pid, v in seed_sorted}

    # KG 不可用 → 经典 Top-N
    if KG_GRAPH is None:
        return [_format_classic(v[0], v[1], v[2], v[3])
                for _, v in seed_sorted[:top]]

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
            "图谱理由": _kg_explain(pid, seed_scores),
        })
    return results


# ============================================================
# 路由
# ============================================================
@app.get("/health")
def health():
    kg_ok = KG_GRAPH is not None
    return {
        "status": "ok",
        "collection_size": col.count(),
        "kg_loaded": kg_ok,
        "kg_questions": (len(KG_QUESTIONS) if kg_ok else 0),
    }


@app.post("/rag/search")
def rag_search(req: SearchReq):
    """检索：★ 失败返回空结果 + error（1 号改进点 P2-7），调用方可以降级，不 500"""
    try:
        # 1) 向量化查询
        qv = emb_model.encode([req.query], normalize_embeddings=True)[0].tolist()

        # ============================================================
        # expand 深挖模式：先选 Top-1 题，再按原题ID 取全层级
        # ============================================================
        if req.mode == "expand":
            top1 = kg_select(req.query, qv,
                             job=req.job, level=req.level, top=1)
            if not top1:
                return {"mode": "expand", "原题ID": None,
                        "命中题目": [], "全层级片段": [], "片段数": 0}
            pid = top1[0]["原题ID"]
            full = col.get(where={"原题ID": pid})
            order = {"原题": 0, "L1": 1, "L2": 2, "L3": 3,
                     "基础得分点": 4, "进阶得分点": 5, "语义变体": 6,
                     "场景化": 7, "答案变体": 8, "基础铺垫": 9}
            expand = []
            for iid, doc, m in zip(full["ids"], full["documents"], full["metadatas"]):
                _parts = doc.split("\n", 1)
                expand.append({
                    "层级": m.get("对应层级"),
                    "考点优先级": m.get("考点优先级"),
                    "难度": m.get("难度等级"),
                    "题目": _parts[0],
                    "内容": _parts[1] if len(_parts) > 1 else "",
                })
            expand.sort(key=lambda x: order.get(x["层级"], 99))
            return {"mode": "expand", "原题ID": pid,
                    "命中题目": top1,
                    "全层级片段": expand, "片段数": len(expand)}

        # ============================================================
        # 出题模式：kg_select 优先，KG 缺失自动降级为经典 Top-N
        # ============================================================
        results = kg_select(req.query, qv,
                            job=req.job, level=req.level, top=req.top)
        return {
            "mode": "kg_select" if KG_GRAPH is not None else "select",
            "results": results,
        }

    except Exception as e:
        return {"mode": req.mode, "results": [],
                "error": f"{type(e).__name__}: {e}"}


@app.get("/question/{qid}")
def question_detail(qid: str):
    """按原题ID 查主库 18 字段完整素材。
    ★ 未命中返回 404（1 号改进点 P2-8）"""
    rec = MAIN_INDEX.get(qid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"原题ID {qid} 不在主库中")
    return {"原题ID": qid, "记录": rec}


if __name__ == "__main__":
    # 端口约定：8001 主后端、8002 P3 评估、8003 本 RAG 检索服务
    # ★ 环境变量可覆盖（1 号修复点 P0-1）
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("RAG_PORT", "8003")))
