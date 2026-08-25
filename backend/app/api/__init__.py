"""API 路由汇总"""
from fastapi import APIRouter

from app.api import auth, interviews, reports, uploads

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(interviews.router, prefix="/interviews", tags=["面试"])
api_router.include_router(reports.router, prefix="/reports", tags=["报告"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["上传"])
