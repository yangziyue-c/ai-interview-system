"""全局配置：从 .env 文件读取，未提供时使用默认值"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 基础 ----
    APP_NAME: str = "AI 模拟面试系统"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"   # 监听所有网卡，内网穿透/局域网演示必须
    PORT: int = 8000

    # ---- 数据库 ----
    # 默认 SQLite 零配置启动；正式环境在 .env 中切换 MySQL
    DATABASE_URL: str = "sqlite+aiosqlite:///./interview.db"
    SQL_ECHO: bool = False

    # ---- Redis（留空则降级为进程内缓存）----
    REDIS_URL: str = ""

    # ---- JWT ----
    JWT_SECRET_KEY: str = "change-this-secret-key-before-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 小时

    # ---- 面试规则 ----
    MAX_FOLLOW_UP_ROUNDS: int = 6  # 开场题之后最多追问 6 轮
    FIRST_QUESTION_INDEX: int = 0

    # ---- P2/P3 适配器 ----
    # 留空 = 内置 Mock；填入后调用真实 HTTP 服务，超时自动降级
    AI_INTERVIEWER_URL: str = ""
    AI_EVALUATOR_URL: str = ""
    ADAPTER_TIMEOUT_SECONDS: float = 15.0

    # ---- 上传 ----
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 20

    # ---- 前端静态文件（P4 构建产物 dist 挂载点）----
    STATIC_DIR: str = "static"

    @property
    def total_rounds(self) -> int:
        """面试总轮数 = 开场题 1 + 最大追问轮数"""
        return 1 + self.MAX_FOLLOW_UP_ROUNDS


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
