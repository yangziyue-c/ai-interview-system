# -*- coding: utf-8 -*-
"""
04 · 向量库完整性验证（ChromaDB 版）
功能：验证 collection 计数、按岗位/层级/题型分布、抽查内容非空。
"""
import os
import chromadb

# ---- 路径自适应：优先使用交付包内的相对路径（成员机器解压即用） ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 交付包根目录
def _pick(*candidates):
    """按存在性选择：交付包结构优先，开发机构建目录回退。
    ★ 全部未命中 → 明确抛错"""
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("RAG 向量库目录不存在，已尝试: " + " | ".join(candidates))


def _ensure_ascii_chroma(src_dir):
    """chromadb 1.5.9 的 HNSW 段 reader 不支持非 ASCII 路径（Windows 中文路径会报
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

CHROMA_DIR = os.environ.get("RAG_CHROMA_DIR") or _pick(
    os.path.join(_PKG_ROOT, "向量库", "chroma_db_v2"),
    os.path.join(_PKG_ROOT, "chroma_db_v2"),
    r"E:\GitHubRepos\rag-db-v5\chroma_db_v2",
)
CHROMA_DIR = _ensure_ascii_chroma(CHROMA_DIR)
COLLECTION = "a11_interview_kb_v5v2"

client = chromadb.PersistentClient(path=CHROMA_DIR)
col = client.get_collection(COLLECTION)

total = col.count()
print(f"[chroma] collection 总条数={total}  向量库目录={CHROMA_DIR}")

# 分批拉取元数据（每批 5000，避免 too many SQL variables）
by_job, by_level, by_type, empty_docs = {}, {}, {}, 0
B = 5000
offset = 0
while offset < total:
    r = col.get(limit=B, offset=offset, include=["metadatas", "documents"])
    for doc, m in zip(r["documents"], r["metadatas"]):
        by_job[m["所属岗位"]] = by_job.get(m["所属岗位"], 0) + 1
        by_level[m["对应层级"]] = by_level.get(m["对应层级"], 0) + 1
        by_type[m["题型分类"]] = by_type.get(m["题型分类"], 0) + 1
        if not (doc or "").strip():
            empty_docs += 1
    offset += len(r["documents"])

print("\n=== 按岗位分布 ===")
for k, v in sorted(by_job.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
print("\n=== 按层级分布 ===")
for k, v in sorted(by_level.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
print("\n=== 按题型分布 ===")
for k, v in sorted(by_type.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
print(f"\n空文档条数: {empty_docs}")
print(f"验证结果: {'通过 ✓（计数与数据一致）' if offset == total and empty_docs == 0 else '异常 ✗'}")
