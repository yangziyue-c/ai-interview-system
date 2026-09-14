# -*- coding: utf-8 -*-
"""
05 · RAG 检索 HTTP 服务（FastAPI 封装）
============================================================
给 1 号（后端主程）用的现成服务：把 03_search_rag.py 的检索逻辑
封装成 POST /rag/search HTTP 接口，供 2 号（AI 对话）调用。

启动方式（在本文件所在目录下）：
    pip install -r ../requirements-rag.txt   # 约 2.5GB，torch 走 CPU 索引
    python 05_rag_api_server.py

服务启动后（端口 8003，可用环境变量 RAG_PORT 覆盖）：
    POST http://localhost:8003/rag/search
    Body: {"query": "Redis 缓存穿透怎么办",
           "job": "Java 后端开发工程师",      # 可空
           "mode": "select",                  # select=出题 | expand=深挖
           "top": 3, "level": null}           # level 可空（按层级过滤）

    GET  http://localhost:8003/health   → 健康检查

环境变量（均可选）：
    RAG_PORT         监听端口，默认 8003（8000 被本机 Godot AI MCP 占用，不可用）
    RAG_CHROMA_DIR   向量库目录，默认按交付包结构自动定位
    RAG_MAIN_DIR     主库 json 目录，默认按交付包结构自动定位
    RAG_THREADS      torch 线程数，默认取 CPU 核心数
    HF_HUB_OFFLINE   置 1 则离线加载模型（模型下载完成后可开启以加快启动）

说明：
  - 模型在服务启动时加载一次（bge-m3 + reranker）：首次约需下载 4.5GB，
    默认走 huggingface.co；网络受限时设 HF_ENDPOINT=https://hf-mirror.com 走镜像。
    下载完成后约 10-30 秒加载。
  - CORS 已放开，前端（4 号）也可直接调用。
  - 深挖模式（expand）返回命中题的全部层级片段，供追问/评分。
  - GET /question/{原题ID} 返回主库 18 字段完整素材（降级策略/建议用时/单题校准锚点等
    RAG 条目中不存在的字段，均通过该接口按原题ID 从主库获取）。
"""
import os
# 模型下载源：默认走 huggingface.co（本机实测可直连；hf-mirror 反而超时）。
# 网络受限的环境请自行设置 HF_ENDPOINT=https://hf-mirror.com 走镜像。
# 默认允许联网下载模型：交付包不含 4.5GB 模型文件，成员机器通常也无 HF 缓存，
# 写死 OFFLINE=1 会在首次启动时直接抛 OSError。模型就位后可设 HF_HUB_OFFLINE=1 加快启动。
os.environ.setdefault("HF_HUB_OFFLINE", "0")
import torch
torch.set_num_threads(int(os.environ.get("RAG_THREADS", os.cpu_count() or 8)))
import chromadb
import json
import logging
from sentence_transformers import SentenceTransformer, CrossEncoder
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

logger = logging.getLogger("rag_api_server")

# ---- 路径自适应：优先使用交付包内的相对路径（成员机器解压即用） ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 交付包根目录
def _pick(*candidates):
    """按存在性选择路径：交付包结构优先，开发机构建目录回退。

    全部候选都不存在时**快速失败**。原先返回 candidates[0] 会让
    chromadb.PersistentClient 静默创建一个空库（表现为「检索永远无结果」
    而非「路径配错」），排查成本极高。
    """
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        "路径不存在，已尝试：\n  " + "\n  ".join(candidates)
        + "\n请确认交付包结构完整（vector_db/、数据/ 与本脚本所在目录同级）。"
    )

# ★ 向量库目录名必须是纯 ASCII：chromadb 无法打开「含非 ASCII 字符的绝对路径」
#   （实测 100% 失败，报 Error loading hnsw index，极易误判为索引损坏）。
#   旧交付包目录名为「向量库/」，此处自动升级，避免按旧文档操作时踩坑。
VECTOR_DIR = os.path.join(_PKG_ROOT, "vector_db")
_LEGACY_VECTOR_DIR = os.path.join(_PKG_ROOT, "向量库")
if not os.path.exists(VECTOR_DIR) and os.path.exists(_LEGACY_VECTOR_DIR):
    print("[init] 旧目录名「向量库」→ vector_db（chromadb 不支持含中文的绝对路径）",
          flush=True)
    os.rename(_LEGACY_VECTOR_DIR, VECTOR_DIR)


def _assert_ascii_path(path: str) -> str:
    """守卫：chromadb 打不开非 ASCII 绝对路径，提前报错而非表现为「索引损坏」"""
    if not os.path.abspath(path).isascii():
        raise RuntimeError(
            f"向量库路径含非 ASCII 字符，chromadb 无法打开：{path}\n"
            f"  请移动到纯 ASCII 路径（推荐 {VECTOR_DIR}）。")
    return path


# 环境变量可覆盖（部署时目录结构可能不同）
CHROMA_DIR = _assert_ascii_path(
    os.environ.get("RAG_CHROMA_DIR") or _pick(
        os.path.join(VECTOR_DIR, "chroma_db_v2"),
        os.path.join(_PKG_ROOT, "chroma_db_v2")))               # 向量库目录
COLLECTION = "a11_interview_kb_v5v2"
EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
MAIN_DIR = os.environ.get("RAG_MAIN_DIR") or _pick(
    os.path.join(_PKG_ROOT, "数据"),
    r"C:\Users\litao\WorkBuddy\2026-09-10-21-25-17\ai-interview-data\v5")

app = FastAPI(title="A11 RAG 检索服务", version="1.0")

# CORS：允许前端（4 号）与演示前端直接跨域调用
# （对接说明文档承诺「CORS 已放开」，但原实现缺中间件，浏览器跨域会被拦）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 主库索引：原题ID -> 18 字段完整记录（启动时加载一次） ----
MAIN_INDEX = {}
for _p in ("java", "web", "test", "algorithm", "system-design"):
    _path = os.path.join(MAIN_DIR, f"{_p}-v5.json")
    if os.path.exists(_path):
        for _rec in json.load(open(_path, encoding="utf-8")):
            if "题目ID" in _rec:
                MAIN_INDEX[_rec["题目ID"]] = _rec
_missing = [p for p in ("java", "web", "test", "algorithm", "system-design")
            if not os.path.exists(os.path.join(MAIN_DIR, f"{p}-v5.json"))]
print(f"[init] 向量库目录: {CHROMA_DIR}", flush=True)
print(f"[init] 主库目录:   {MAIN_DIR}", flush=True)
print(f"[init] main library loaded: {len(MAIN_INDEX)} 题"
      + (f"  [警告] 缺失文件: {','.join(_missing)}" if _missing else ""), flush=True)

# ---- 请求/响应模型 ----
class SearchReq(BaseModel):
    query: str
    job: Optional[str] = None          # 岗位过滤："Java 后端开发工程师" 等
    mode: str = "select"               # select=出题（Top-N 道不同题）| expand=深挖（取一题全层级）
    top: int = 3                       # select 模式返回几道题
    level: Optional[str] = None        # 层级过滤（原题/L1/L2/L3/语义变体…）

# ---- 服务启动时加载模型（只加载一次） ----
print("[init] loading bge-m3 ...", flush=True)
emb_model = SentenceTransformer(EMBED_MODEL)
emb_model.max_seq_length = 512
print("[init] loading reranker ...", flush=True)
rerank = CrossEncoder(RERANK_MODEL, max_length=512)
client = chromadb.PersistentClient(path=CHROMA_DIR)
col = client.get_collection(COLLECTION)
print(f"[init] collection size: {col.count()}", flush=True)


@app.get("/health")
def health():
    return {"status": "ok", "collection_size": col.count()}


@app.post("/rag/search")
def rag_search(req: SearchReq):
    """出题 / 深挖双模式检索。

    检索期异常不向调用方抛 500：面试流程依赖本服务，必须可降级——
    失败时返回空 results + error 字段，由调用方决定是否落下一级数据源。
    """
    try:
        return _rag_search(req)
    except Exception as exc:  # noqa: BLE001 - 任何检索异常都降级返回
        logger.exception("rag_search 失败")
        return {"mode": req.mode, "results": [], "error": f"{type(exc).__name__}: {exc}"}


def _rag_search(req: SearchReq):
    # 1) 向量化查询
    qv = emb_model.encode([req.query], normalize_embeddings=True)[0].tolist()

    # 2) 元数据过滤
    where = {}
    if req.job:
        where["所属岗位"] = req.job
    if req.level:
        where["对应层级"] = req.level

    # 3) 向量召回 Top-20
    res = col.query(query_embeddings=[qv], n_results=20, where=where or None)
    docs, metas, ids = res["documents"][0], res["metadatas"][0], res["ids"][0]

    # 4) reranker 精排
    scores = rerank.predict([[req.query, d] for d in docs]).tolist()

    # 5) 按原题ID去重（每道题保留最高分条目）
    best = {}
    for i, m in enumerate(metas):
        pid = m["原题ID"]
        if pid not in best or scores[i] > best[pid][0]:
            best[pid] = (scores[i], docs[i], m, ids[i])
    ranked = sorted(best.values(), key=lambda x: -x[0])

    # 6) 出题模式：返回 Top-N 道不同题（参考答案去掉题目行，只含正文）
    results = []
    for sc, doc, m, i in ranked[:req.top]:
        _parts = doc.split("\n", 1)
        results.append({
            "score": round(sc, 4),
            "题目": _parts[0],
            "参考答案": _parts[1] if len(_parts) > 1 else "",
            "原题ID": m["原题ID"],
            "题目ID": m["题目ID"],
            "层级": m["对应层级"],
            "岗位": m["所属岗位"],
            "题型": m["题型分类"],
            "难度": m["难度等级"],
            "面试阶段": m["面试阶段"],
            "考点优先级": m["考点优先级"],
        })

    # 7) 深挖模式：命中最高分题后，取该题全部层级片段
    if req.mode == "expand" and ranked:
        pid = ranked[0][2]["原题ID"]
        full = col.get(where={"原题ID": pid})
        expand = []
        order = {"原题": 0, "L1": 1, "L2": 2, "L3": 3, "基础得分点": 4,
                 "进阶得分点": 5, "语义变体": 6, "场景化": 7, "答案变体": 8, "基础铺垫": 9}
        for iid, doc, m in zip(full["ids"], full["documents"], full["metadatas"]):
            _parts = doc.split("\n", 1)
            expand.append({
                "层级": m.get("对应层级"), "考点优先级": m.get("考点优先级"),
                "难度": m.get("难度等级"), "题目": _parts[0],
                "内容": _parts[1] if len(_parts) > 1 else "",
            })
        expand.sort(key=lambda x: order.get(x["层级"], 99))
        return {"mode": "expand", "原题ID": pid, "命中题目": results[:1],
                "全层级片段": expand, "片段数": len(expand)}

    return {"mode": "select", "results": results}


@app.get("/question/{qid}")
def question_detail(qid: str):
    """按原题ID 查主库 18 字段完整素材（含降级策略、建议用时、单题校准锚点等）"""
    rec = MAIN_INDEX.get(qid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"原题ID {qid} 不在主库中")
    return {"原题ID": qid, "记录": rec}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("RAG_PORT", "8003")))
