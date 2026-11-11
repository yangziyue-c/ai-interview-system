"""ORM 模型统一出口：导入本包即可注册全部表"""
from app.models.qa_record import QARecord
from app.models.report import Report
from app.models.report_share import ReportShare
from app.models.resume import Resume
from app.models.sample_answer import SampleAnswer
from app.models.user import User
from app.models.user_setting import UserSetting
from app.models.interview import Interview
from app.models.position import Position
from app.models.question import Question

__all__ = [
    "User",
    "UserSetting",
    "Interview",
    "QARecord",
    "Report",
    "ReportShare",
    "Resume",
    "SampleAnswer",
    "Position",
    "Question",
]
