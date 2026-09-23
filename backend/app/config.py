"""全局配置：从 .env 文件读取，未提供时使用默认值"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 基础 ----
    APP_NAME: str = "AI 模拟面试系统"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"   # 监听所有网卡，内网穿透/局域网演示必须
    PORT: int = 8001

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

    # ---- RAG 语义检索（V5 知识库，backend/rag/，题库策略未命中时的兜底源）----
    # 默认指向 start.py 拉起的本地服务（8003）；置空字符串可完全禁用该数据源
    RAG_API_URL: str = "http://localhost:8003"
    # 单次检索超时：CPU 上 bge-m3 编码 + Top-20 候选 reranker 精排，**实测约 20~30 秒**
    # （瓶颈是 reranker：20 个 (query, doc) 对逐条打分；向量召回本身仅需 0.1 秒）。
    # 取 60 秒留 2 倍余量——宁可等，也不要误判「RAG 不可用」而白白降级到下一级数据源。
    RAG_TIMEOUT_SECONDS: float = 60.0
    # 健康探测结果缓存秒数（RAG 未启用时避免每轮白等超时；取值偏大以摊薄探测开销）
    RAG_HEALTH_CACHE_SECONDS: float = 120.0

    # ---- 大模型直连（题库策略未命中时的兜底源，OpenAI 兼容接口）----
    # 面试官出题优先级：题库策略（interviewer_new/）> RAG 检索 > AI_INTERVIEWER_URL > LLM_API_KEY > Mock
    # 仅保存在本地 .env，切勿提交到 git
    LLM_BASE_URL: str = ""   # 如 https://api.deepseek.com/v1
    LLM_API_KEY: str = ""    # API Key
    LLM_MODEL: str = "deepseek-chat"

    # ---- 上传 ----
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 20
    # 头像单独设上限：它比录音小得多，且会随用户信息接口反复传输
    MAX_AVATAR_SIZE_MB: int = 2

    # ---- 简历导入 ----
    # 简历原件私有目录：**绝不能**改成 UPLOAD_DIR 或 STATIC_DIR 的子目录。
    # main.py 把这两个目录整棵挂成了静态资源（/uploads 无鉴权、/ 兜底前端），
    # 放进去等于把简历（姓名/手机/学历）公开到公网。只有鉴权接口能读到它。
    # 该目录已进 .gitignore——简历原件永远不该进版本库。
    RESUME_DIR: str = "private/resumes"
    MAX_RESUME_SIZE_MB: int = 10
    # 全文存储与接口返回的上限。同时受 MySQL TEXT 64KB 字节约束
    # （utf8mb4 最坏 4 字节/字符，10000 字符 ≈ 40KB，留足余量）；
    # 将来若要放宽到 5 万字符，得换 MEDIUMTEXT，不是改这个常量的事。
    MAX_RESUME_TEXT_CHARS: int = 10000
    # PDF 解析预算（秒）：解析阻塞，丢到线程里跑并设超时。
    # 注意超时只让请求返回，杀不掉那个线程（原因与安全性见 adapters/resume_parser.py）
    RESUME_PARSE_TIMEOUT_SECONDS: float = 15.0

    # ---- 报告分享 ----
    # 分享链接有效期（天）：过期后凭分享码访问返回 404，报告本身不受影响
    SHARE_EXPIRE_DAYS: int = 7

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
