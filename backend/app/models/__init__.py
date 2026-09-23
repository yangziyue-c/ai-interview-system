"""ORM 模型统一出口：导入本包即可注册全部表"""
from app.models.qa_record import QARecord
from app.models.report import Report
from app.models.report_share import ReportShare
from app.models.resume import Resume
from app.models.user import User
from app.models.interview import Interview
from app.models.position import Position
from app.models.question import Question

__all__ = [
    "User",
    "Interview",
    "QARecord",
    "Report",
    "ReportShare",
    "Resume",
    "Position",
    "Question",
]
