# -*- coding: utf-8 -*-
"""
============================================================
memory_retriever · 内存向量检索模块（替代 ChromaDB HNSW）
============================================================
背景：ChromaDB 的 HNSW 索引与 SQLite 元数据存在不同步 bug
      （305 条记录只进 SQLite、未进 HNSW，导致检索缺失/报错）。
      本模块用「全量内存精确余弦」替代 HNSW 近似检索：
        · 无异步索引构建层 → 从机制上根除不同步问题
        · 精确余弦比 HNSW 近似更准
        · 76222 × 1024 维 float32 ≈ 303MB，单次查询 <100ms

数据文件（由 rebuild_index.py 生成）：
  all_records.pkl  : list[{"id": str, "document": str, "metadata": dict}]  (76222 条)
  memory_index.npz : {"embeddings": float32 [N, dim]（已归一化）, "ids": list[str]}

接口与 ChromaDB collection 兼容：
  retriever.count()                      -> int
  retriever.get(where=None, limit=None)  -> {"ids", "documents", "metadatas"}
  retriever.query(query_embeddings, n_results, where=None)
                                         -> {"ids", "documents", "metadatas", "distances"}

路径自适应：环境变量 RAG_MEM_DIR → 交付包内「数据」目录 → 脚本同目录 → 开发机目录
============================================================
"""
import os
import pickle
import numpy as np

# ---- 路径自适应 ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pick(*candidates):
    """按存在性选择：交付包结构优先，开发机构建目录回退。
    ★ 全部未命中 → 明确抛错"""
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("内存索引数据目录不存在，已尝试: " + " | ".join(candidates))


RECORDS_NAME = "all_records.pkl"
INDEX_NAME = "memory_index.npz"
EXPECTED_N = 76222  # ★ 主库 RAG v2 总条数（硬断言）


def _where_matches(meta, where):
    """单条 metadata 是否命中 where 条件。
    支持：{key: value} 多键 AND、{"$and": [cond...]}、value 为 list 时视为 $in。"""
    if not where:
        return True
    conds = where.get("$and") if isinstance(where, dict) else None
    if conds is not None:
        return all(_where_matches(meta, c) for c in conds)
    for k, v in where.items():
        mv = meta.get(k)
        if isinstance(v, list):
            if mv not in v:
                return False
        elif isinstance(v, dict) and "$in" in v:
            if mv not in v["$in"]:
                return False
        elif mv != v:
            return False
    return True


class MemoryRetriever:
    """全量内存检索器：加载一次，之后 query/get/count 全部在内存完成。"""

    def __init__(self, records_path=None, index_path=None):
        if records_path is None or index_path is None:
            base = os.environ.get("RAG_MEM_DIR") or _pick(
                os.path.join(_PKG_ROOT, "向量库"),            # 交付包结构（primary）
                os.path.join(_PKG_ROOT, "memory_index"),     # 独立索引目录
                os.path.dirname(os.path.abspath(__file__)),  # 脚本同目录（kg_review/kg-enhanced 等）
                os.path.join(_PKG_ROOT, "数据"),             # 兼容旧结构
                r"E:\GitHubRepos\rag-db-v5",
                r"E:\GitHubRepos\rag-db-v5\handoff\交付包-1号后端\数据",
            )
            records_path = records_path or os.path.join(base, RECORDS_NAME)
            index_path = index_path or os.path.join(base, INDEX_NAME)
        self.records_path = records_path
        self.index_path = index_path

        with open(records_path, "rb") as f:
            self.records = pickle.load(f)          # list[dict]
        z = np.load(index_path, allow_pickle=True)
        self.embeddings = z["embeddings"]           # float32 [N, dim] 已归一化
        self.ids = list(z["ids"])

        n = len(self.records)
        assert n == len(self.ids) == self.embeddings.shape[0], \
            f"内存索引内部不一致: records={n} ids={len(self.ids)} emb={self.embeddings.shape[0]}"
        # ★ 条数硬断言：必须是 76222，否则说明导出/编码不完整，宁可不启动
        if n != EXPECTED_N:
            raise ValueError(
                f"[memory_retriever] 条数断言失败：期望 {EXPECTED_N}，实际 {n}。"
                f"请重新运行 rebuild_index.py 生成完整索引。")
        # id -> 序号 映射
        self._pos = {iid: i for i, iid in enumerate(self.ids)}
        self._meta = [r["metadata"] for r in self.records]
        print(f"[memory] 内存索引已加载：{n} 条 × {self.embeddings.shape[1]} 维"
              f"（精确余弦，无 HNSW）", flush=True)

    # ----------------------------------------------------------
    def count(self):
        return len(self.records)

    # ----------------------------------------------------------
    def get(self, where=None, limit=None, include=None):
        """按元数据条件取记录。include 兼容 ChromaDB 语义，仅支持 documents/metadatas。"""
        out_ids, out_docs, out_metas = [], [], []
        for i, r in enumerate(self.records):
            if _where_matches(r["metadata"], where):
                out_ids.append(self.ids[i])
                out_docs.append(r["document"])
                out_metas.append(r["metadata"])
                if limit and len(out_ids) >= limit:
                    break
        return {"ids": out_ids, "documents": out_docs, "metadatas": out_metas}

    # ----------------------------------------------------------
    def query(self, query_embeddings, n_results=10, where=None):
        """精确余弦 Top-K（带可选元数据过滤）。返回结构与 ChromaDB query 兼容。
        query_embeddings: [vec] 其中 vec 为已归一化列表/数组（与 bge-m3 normalize 一致）。"""
        qv = np.asarray(query_embeddings[0], dtype=np.float32)
        qn = np.linalg.norm(qv)
        if qn > 0:
            qv = qv / qn  # 保险：再归一化一次（已是单位向量则无影响）

        scores = self.embeddings @ qv  # [N] 余弦相似度

        # 过滤
        if where:
            keep = [i for i, m in enumerate(self._meta) if _where_matches(m, where)]
            if not keep:
                return {"ids": [], "documents": [], "metadatas": [], "distances": []}
            scores = scores[keep]
            pos = keep
        else:
            pos = np.arange(len(scores))

        k = min(n_results, len(scores))
        # 相似度从高到低（distances 用 1 - score 表示距离，与 ChromaDB cosine 一致）
        top = np.argsort(-scores)[:k]
        out_ids, out_docs, out_metas, out_dists = [], [], [], []
        for t in top:
            i = int(pos[t])
            out_ids.append(self.ids[i])
            out_docs.append(self.records[i]["document"])
            out_metas.append(self.records[i]["metadata"])
            out_dists.append(float(1.0 - scores[t]))
        return {"ids": out_ids, "documents": out_docs,
                "metadatas": out_metas, "distances": out_dists}


if __name__ == "__main__":
    import sys
    m = MemoryRetriever()
    print("count =", m.count())
    q = "Redis 缓存穿透怎么办"
    from sentence_transformers import SentenceTransformer
    emb = SentenceTransformer("BAAI/bge-m3")
    emb.max_seq_length = 512
    qv = emb.encode([q], normalize_embeddings=True)[0].tolist()
    r = m.query([qv], n_results=3, where={"所属岗位": "Java 后端开发工程师"})
    for d, mm in zip(r["documents"], r["metadatas"]):
        print("-", mm.get("原题ID"), d.split("\n")[0][:40])
