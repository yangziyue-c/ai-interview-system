"""简历导入表：原文件（私有目录）+ 提取全文 + 抽出的建议字段

命名约定：`resume` 在本项目**一律作名词（简历）**，仅用于数据实体——类 `Resume`、
表 `resumes`、模块 `app/models/resume.py`。函数名一律「动词 + 名词」以杜绝与
「恢复/续跑」的歧义（`extract_text` / `extract_fields` / `resume_file_path`）；
将来若真有「恢复面试」需求，请写 `restore_interview()`。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 解析状态受控词表（单一事实源）。前端只需判 `== parsed`，其余一律展示
# parse_message——状态细分不增加前端负担，却给排查与将来接 OCR 留了准确的原因。
PARSE_STATUS_PARSED = "parsed"                  # 文本层提取成功
PARSE_STATUS_NO_TEXT_LAYER = "no_text_layer"    # 打开成功但没有文字层（扫描件/纯图 PDF）
PARSE_STATUS_GARBLED = "garbled"                # 有文字但字体缺 ToUnicode，提取成乱码
PARSE_STATUS_IMAGE_PENDING = "image_pending"    # 图片：接受上传但本期不解析（预留多模态位）
PARSE_STATUS_FAILED = "failed"                  # 损坏 / 加密 / 超时 / 解析依赖缺失
PARSE_STATUSES = (
    PARSE_STATUS_PARSED,
    PARSE_STATUS_NO_TEXT_LAYER,
    PARSE_STATUS_GARBLED,
    PARSE_STATUS_IMAGE_PENDING,
    PARSE_STATUS_FAILED,
)


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, comment="所属用户"
    )

    # 用户上传时的原始文件名：只用于展示与下载文件名，**绝不参与拼磁盘路径**。
    # 不存它的话，用户下载到的会是 `12_a3f9c2d1.pdf` 这种名字。
    original_filename: Mapped[str] = mapped_column(
        String(255), default="", comment="原始文件名（仅展示与下载用）"
    )
    # 落盘文件名（{user_id}_{uuid12}{ext}）。**只存文件名、不存路径**：路径一律由代码拼，
    # 库里没有路径成分，就没有「改库改成 ../../ 就能读任意文件」的口子。
    stored_name: Mapped[str] = mapped_column(String(128), comment="落盘文件名（不含路径）")
    # 一个字段同时服务三件事：响应里的 file_ext、图片/PDF 的分支判断、下载的 Content-Type
    # 与文件名后缀。拆成 is_pdf 布尔会多一处可能漂移的真相。
    file_ext: Mapped[str] = mapped_column(String(8), comment="扩展名（小写含点）")
    file_size: Mapped[int] = mapped_column(Integer, default=0, comment="字节数")

    # 默认取 failed 是刻意的：万一某条插入路径漏传状态，宁可标成「解析失败」
    # （前端据此引导手动填写），也不要伪装成 parsed 让用户拿错的数据去回填资料。
    parse_status: Mapped[str] = mapped_column(
        String(24), default=PARSE_STATUS_FAILED, comment="解析状态（见 PARSE_STATUS_*）"
    )
    # 给前端直接展示的一句话。文案只维护在后端一处，前端不必为状态写分支文案。
    parse_message: Mapped[str] = mapped_column(
        String(255), default="", comment="解析结果提示（给用户看的人话）"
    )
    # 产出该文本的解析器标识（pypdf / 未来的 ocr / vlm）。接 OCR 后可据此筛出
    # 「当年用文本层解析」的旧行做重解析，也是排查数据来源的唯一依据。
    parser: Mapped[str] = mapped_column(String(32), default="", comment="解析器标识")

    # 简历全文（截断至 settings.MAX_RESUME_TEXT_CHARS）。
    # 面试出题若要「结合简历提问」，素材就是这里。
    text_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="提取的简历全文（已截断）"
    )
    # 截断前的原始字符数：text_content 比它短即说明被截断，前端据此提示
    text_length: Mapped[int] = mapped_column(Integer, default=0, comment="提取到的原始字符数")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="上传时间"
    )
