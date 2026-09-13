# -*- coding: utf-8 -*-
"""
04 · 向量库完整性验证（分批 get，规避 SQLite 变量上限）
功能：验证 collection 计数、按岗位/层级分布、抽查内容非空。
"""
import os
# 模型下载源：默认走 huggingface.co（本机实测可直连；hf-mirror 反而超时）。
# 网络受限的环境请自行设置 HF_ENDPOINT=https://hf-mirror.com 走镜像。
# 本脚本只读向量库、不加载模型，但仍保持与其他脚本一致（避免将来扩展时踩坑）
os.environ.setdefault("HF_HUB_OFFLINE", "0")
import chromadb

# ---- 路径自适应：优先使用交付包内的相对路径（成员机器解压即用） ----
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 交付包根目录
def _pick(*candidates):
    """按存在性选择：交付包结构优先，开发机构建目录回退。

    全部候选都不存在时快速失败（原先返回 candidates[0] 会让 chromadb
    静默创建空库，表现为「验证结果全空」而非「路径配错」）。
    """
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        "路径不存在，已尝试：\n  " + "\n  ".join(candidates)
        + "\n请确认交付包结构完整（向量库/ 与本脚本所在目录同级）。"
    )
CHROMA_DIR = _pick(os.path.join(_PKG_ROOT, "向量库", "chroma_db_v2"),
                   os.path.join(_PKG_ROOT, "chroma_db_v2"))     # 向量库目录
COLLECTION = "a11_interview_kb_v5v2"

client = chromadb.PersistentClient(path=CHROMA_DIR)
col = client.get_collection(COLLECTION)
total = col.count()
print(f"[chroma] collection={COLLECTION} 总条数={total}")

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
    print(f"  已读取 {offset}/{total}")

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
