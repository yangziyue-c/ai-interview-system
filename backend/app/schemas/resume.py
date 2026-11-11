"""简历导入 schema"""
from datetime import datetime

from pydantic import BaseModel


class SuggestedFields(BaseModel):
    """从简历文本推测出的可回填字段（全部可为 null：抽不到就不猜）

    只覆盖 users 表已有的三个字段——头像无法从文本中得到，故不在此列。
    """
    nickname: str | None = None
    student_id: str | None = None
    target_position: str | None = None


class SuggestedNotes(BaseModel):
    """每个建议字段的来源说明，直接展示给用户（如「据文档首行推测：张三（请核对）」）

    抽不到时写着原因（「未找到学号」），前端原样展示即可，不必自己编文案。
    """
    nickname: str = ""
    student_id: str = ""
    target_position: str = ""


class ResumeOut(BaseModel):
    """一份简历的读取视图（POST / latest / {id} 三处共用同一形状，前端一套渲染代码通吃）"""

    id: int
    # 原始文件名会回显给用户，下载接口也用它做文件名。**前端渲染时勿用 innerHTML**
    # （它是用户可控字符串，虽已在入库前洗过路径成分与控制字符）。
    original_filename: str
    file_ext: str
    file_size: int
    parse_status: str
    parse_message: str
    # 提取到的全文（已按 MAX_RESUME_TEXT_CHARS 截断）。图片与解析失败时为 null。
    # 面试出题若要「结合简历提问」，取的就是这个字段。
    text: str | None
    # 前 300 字，供前端折叠态直接渲染，省得它对长字符串再切一刀
    text_preview: str
    text_length: int
    text_truncated: bool
    suggested: SuggestedFields
    suggested_notes: SuggestedNotes
    created_at: datetime
