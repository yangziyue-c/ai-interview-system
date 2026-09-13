# -*- coding: utf-8 -*-
"""
============================================================
02 · 向量数据库构建脚本（RAG jsonl → ChromaDB）
============================================================
功能：把 01 生成的 5 个 {岗位}-rag-v2.jsonl（共 7.4 万条）
      用 bge-m3 向量化后写入 ChromaDB（持久化本地库）。

技术选型（为什么这么选）：
  - 向量模型：BAAI/bge-m3 —— 中文语义检索标杆，1024 维，
    max_seq 512 token；纯 CPU 可跑（7.4 万条约 3 小时）。
  - 向量库：ChromaDB（PersistentClient）—— 轻量、本地持久化、
    自带 cosine 距离（hnsw:space=cosine），适合单机项目。
  - 相似度：cosine（normalize_embeddings=True 后点积即余弦）。

★ 断点续跑机制：
  - build_v2_done.json 记录已完成文件；重跑时已完成的文件
    直接跳过（重复启动不会重复向量化）。
  - ★ 注意：务必避免同时跑多个构建进程（col.add 对重复 id
    会崩/写库冲突）。

★ 性能优化：
  - 按「估计文本长度」排序分桶处理：短文本快、长文本慢，
    长度相近的放同一批减少 padding 浪费。
  - torch 线程数默认取 CPU 核心数（RAG_THREADS 环境变量可覆盖）开启多线程编码。
  - 批量 64 条编码，进度日志每 2000 条打一次。
============================================================
"""
import os, json, re, sys, time, argparse
# 模型下载源：默认走 huggingface.co（本机实测可直连；hf-mirror 反而超时）。
# 网络受限的环境请自行设置 HF_ENDPOINT=https://hf-mirror.com 走镜像。
# 默认允许联网下载模型（交付包不含 4.5GB 模型文件）；模型就位后可设 HF_HUB_OFFLINE=1
os.environ.setdefault("HF_HUB_OFFLINE", "0")
import torch
torch.set_num_threads(int(os.environ.get("RAG_THREADS", os.cpu_count() or 8)))
import chromadb
from sentence_transformers import SentenceTransformer

# ---- 路径自适应：优先使用交付包内的相对路径（成员机器解压即用） ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 交付包根目录
def _pick(*candidates):
    """按存在性选择：交付包结构优先，开发机构建目录回退。

    全部候选都不存在时快速失败（原先返回 candidates[0] 会让下游
    静默使用无效路径，问题被推迟到运行时且难以定位）。
    """
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        "路径不存在，已尝试：\n  " + "\n  ".join(candidates)
        + "\n请确认交付包结构完整（向量库/、数据/ 与本脚本所在目录同级）。"
    )
BASE = _pick(os.path.join(_PKG_ROOT, "数据"),
             r"C:\Users\litao\WorkBuddy\2026-09-10-21-25-17\ai-interview-data\v5")
FILES = ["java-rag-v2.jsonl", "web-rag-v2.jsonl", "test-rag-v2.jsonl",
         "algorithm-rag-v2.jsonl", "system-design-rag-v2.jsonl"]
OUT_DIR = _pick(os.path.join(_PKG_ROOT, "向量库"), _PKG_ROOT)   # 写断点文件的位置（向量库目录优先）
# 向量库**输出目录**：构建/重建时它本就不存在，故不走 _pick 的存在性校验
# （chromadb.PersistentClient 会自动创建；父目录「向量库/」由下方 makedirs 保证）
CHROMA_DIR = os.path.join(_PKG_ROOT, "向量库", "chroma_db_v2")
COLLECTION = "a11_interview_kb_v5v2"                 # collection 名
EMBED_MODEL = "BAAI/bge-m3"
MAX_SEQ = 512
BATCH = 64
DONE_MARK = os.path.join(OUT_DIR, "build_v2_done.json")  # 断点标记文件


def est_len(t):
    """估算 embedding 序列长度：中文按 1.5 字/token，英文按 4 字符/token"""
    cn = sum(1 for ch in t if '\u4e00' <= ch <= '\u9fff')
    return int(cn / 1.5 + (len(t) - cn) / 4.0)


def load_file(path):
    """读 jsonl，跳过空行；返回条目列表"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not (row.get("题目") or "").strip() or not (row.get("参考答案") or "").strip():
                continue
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-embed", action="store_true", help="只做数据预检，不向量化")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    # 读取断点：已完成的文件列表
    done_files = set()
    if os.path.exists(DONE_MARK):
        try:
            done_files = set(json.load(open(DONE_MARK, encoding="utf-8")))
        except Exception:
            done_files = set()

    if not args.skip_embed:
        t0 = time.time()
        print(f"[model] loading {EMBED_MODEL} (offline) ...", flush=True)
        model = SentenceTransformer(EMBED_MODEL)
        model.max_seq_length = MAX_SEQ
        print(f"[model] loaded in {time.time()-t0:.0f}s dim={model.get_embedding_dimension()}", flush=True)
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        col = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    grand_total = 0
    for fn in FILES:
        path = os.path.join(BASE, fn)
        rows = load_file(path)
        grand_total += len(rows)
        print(f"[load] {fn}: {len(rows)} 条", flush=True)

        if args.skip_embed:
            continue
        if fn in done_files:
            print(f"[skip] {fn} 已入库，跳过", flush=True)
            continue

        # 向量化内容 = 题目 + 参考答案（合起来编码，检索时用同格式）
        contents = [r["题目"].strip() + "\n" + r["参考答案"].strip() for r in rows]
        # 唯一 ID：v5v2_{岗位}_{序号}
        ids = [f"v5v2_{fn.split('-')[0]}_{i:06d}" for i in range(len(rows))]
        # 元数据：全部可过滤字段（供按岗位/层级/难度筛选）
        metadatas = [{
            "原题ID": r["原题ID"], "题目ID": r["题目ID"], "所属岗位": r["所属岗位"],
            "题型分类": r["题型分类"], "难度等级": r["难度等级"], "面试阶段": r["面试阶段"],
            "考点优先级": r["考点优先级"], "对应层级": r["对应层级"],
        } for r in rows]

        # 按长度排序：长文本放后面（它们慢），同批次长度相近省 padding
        order = sorted(range(len(contents)), key=lambda i: est_len(contents[i]))
        emb_start = time.time()
        done = 0
        for s in range(0, len(contents), BATCH):
            idx = order[s:s + BATCH]
            batch_texts = [contents[i] for i in idx]
            emb = model.encode(batch_texts, batch_size=BATCH, normalize_embeddings=True)
            col.add(ids=[ids[i] for i in idx],
                    documents=[contents[i] for i in idx],
                    embeddings=emb.tolist(),
                    metadatas=[metadatas[i] for i in idx])
            done += len(idx)
            # 每 2000 条打一次进度（注意：最后一批若不足 2000 会等完成才打印）
            if done % 2000 < BATCH or done == len(contents):
                speed = done / max(time.time() - emb_start, 0.001)
                remain = (len(contents) - done) / max(speed, 0.001)
                print(f"[embed {fn}] {done}/{len(contents)}  {speed:.1f} 条/s  预计剩 {remain/60:.0f} 分钟", flush=True)

        # 该文件完成 → 写入断点标记
        done_files.add(fn)
        with open(DONE_MARK, "w", encoding="utf-8") as f:
            json.dump(sorted(done_files), f, ensure_ascii=False, indent=2)
        print(f"[done] {fn} 完成，已标记断点", flush=True)

    if args.skip_embed:
        print(f"[precheck] 数据预检完成：{len(FILES)} 文件共 {grand_total} 条", flush=True)
        return

    # 完成：输出 collection 统计（按岗位/层级）
    # ★ 修复：col.get() 全量拉取会超 SQLite 变量上限（too many SQL variables），
    #   必须分批 get（每批 5000）再聚合
    print(f"[chroma] collection size: {col.count()}", flush=True)
    by_job, by_level = {}, {}
    offset = 0
    B = 5000
    while offset < col.count():
        r = col.get(limit=B, offset=offset, include=["metadatas"])
        for m in r["metadatas"]:
            by_job[m["所属岗位"]] = by_job.get(m["所属岗位"], 0) + 1
            by_level[m["对应层级"]] = by_level.get(m["对应层级"], 0) + 1
        offset += len(r["metadatas"])
    print("=== 按岗位 ===")
    for k, v in sorted(by_job.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print("=== 按层级 ===")
    for k, v in sorted(by_level.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"[done] build complete", flush=True)


if __name__ == "__main__":
    main()
