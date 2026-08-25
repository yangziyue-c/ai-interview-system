"""FastAPI 应用入口

启动：
    conda activate ai_interview
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
（或直接双击 start.bat）
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import settings
from app.core.exceptions import AppException
from app.database import init_db
from app.redis_client import get_cache

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await get_cache()  # 预热缓存（Redis 不可用时自动降级）
    logger.info("%s 启动完成，监听 %s:%s", settings.APP_NAME, settings.HOST, settings.PORT)
    yield


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

# CORS 通配符：内网穿透/局域网演示时允许任意来源访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 全局异常处理：统一错误返回格式 ----------
@app.exception_handler(AppException)
async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(loc) for loc in first.get("loc", []) if loc != "body")
    message = first.get("msg", "参数校验失败")
    detail = f"参数校验失败: {field} {message}" if field else f"参数校验失败: {message}"
    return JSONResponse(
        status_code=422, content={"code": 40000, "message": detail, "data": None}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("未捕获异常: %s", exc)
    return JSONResponse(
        status_code=500, content={"code": 50000, "message": "服务器内部错误", "data": None}
    )


# ---------- 健康检查（内网穿透演示时用于快速验证连通性） ----------
@app.get("/api/v1/health", tags=["系统"])
async def health() -> dict:
    return {"code": 0, "message": "ok", "data": {"status": "healthy"}}


# ---------- 业务路由 ----------
app.include_router(api_router, prefix="/api/v1")

# ---------- 静态资源 ----------
# 1) 录音文件
upload_dir = Path(settings.UPLOAD_DIR)
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")

# 2) 前端构建产物（P4 的 dist 内容放入 backend/static/，统一端口避免跨域）
static_dir = Path(settings.STATIC_DIR)
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
