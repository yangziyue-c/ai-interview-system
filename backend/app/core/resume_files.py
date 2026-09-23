"""简历原件的私有存储：目录、文件名、防路径穿越、下载用的 Content-Type

**为什么不放 `UPLOAD_DIR`**：`main.py` 把该目录整棵挂成了 `/uploads` 静态资源——
无鉴权、无子目录白名单，放进去等于把简历（姓名/学号/联系方式）公开到公网。
本模块的目录同样不能在 `STATIC_DIR` 树下：那条挂在 `/` 的静态资源兜底了所有未匹配路径。
"""
import uuid
from pathlib import Path

from app.config import settings

# 扩展名 → 下载时用的 Content-Type。**显式查表，不用 mimetypes.guess_type**：
# 后者在 Windows 上会去查注册表，同一份代码在不同机器上对 .webp 可能给出不同结果，
# 而这个扩展名是我们自己白名单校验过的，查表最确定。
RESUME_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
ALLOWED_RESUME_EXT = frozenset(RESUME_MEDIA_TYPES)

# 原始文件名会进 Content-Disposition 响应头与前端 DOM，属用户可控字符串
_MAX_FILENAME_CHARS = 100


def new_stored_name(user_id: int, ext: str) -> str:
    """生成落盘文件名（沿用 uploads 的规则：用户号前缀 + 12 位随机十六进制）"""
    return f"{user_id}_{uuid.uuid4().hex[:12]}{ext}"


def resume_file_path(stored_name: str) -> Path:
    """由库里的文件名还原磁盘路径

    库里只存文件名、不存路径（没有路径成分就没有可穿越的东西），这里再校验一次作为双保险：
    即便有人改了库，`Path(...).name` 也会把 `../../` 之类的成分剥掉
    （同 `upload_rules.remove_avatar_file` 的写法）。
    """
    if not stored_name or "/" in stored_name or "\\" in stored_name:
        raise ValueError(f"非法简历文件名: {stored_name!r}")
    safe = Path(stored_name).name
    if safe != stored_name or safe in {".", ".."}:
        raise ValueError(f"非法简历文件名: {stored_name!r}")
    return Path(settings.RESUME_DIR) / safe


def save_resume_bytes(user_id: int, ext: str, content: bytes) -> str:
    """把简历原件写进私有目录，返回落盘文件名（目录懒创建，按用户号前缀便于人工排查）"""
    directory = Path(settings.RESUME_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    name = new_stored_name(user_id, ext)
    (directory / name).write_bytes(content)
    return name


def sanitize_filename(name: str | None) -> str:
    """清洗用户上传的原始文件名：去路径成分、去控制字符、限长

    先统一分隔符再取末段——只用 `Path(name).name` 的话，在 Linux 上
    `..\\..\\x.pdf` 会被整串保留（反斜杠在 POSIX 不是分隔符），跨平台表现不一致。
    """
    base = (name or "").replace("\\", "/").split("/")[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable())
    return cleaned[:_MAX_FILENAME_CHARS] or "resume"
