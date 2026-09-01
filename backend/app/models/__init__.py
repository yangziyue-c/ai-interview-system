"""ORM 模型统一出口：导入本包即可注册全部表"""
from app.models.qa_record import QARecord
from app.models.report import Report
from app.models.user import User
from app.models.interview import Interview
from app.models.position import Position

__all__ = ["User", "Interview", "QARecord", "Report", "Position"]
