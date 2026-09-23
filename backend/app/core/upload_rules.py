"""上传规则：头像与简历的格式白名单、文件头校验与地址校验

音频与头像共用 UPLOAD_DIR 这个静态挂载点，但规则不同：音频进 uploads/ 根目录、
上限 20MB；头像进 uploads/avatars/、上限 2MB，故分开定义。

头像地址会随 GET /auth/me 返回、被前端塞进 <img src>，因此写库前必须校验成
「本站上传接口产出的路径」——放开任意字符串等于允许用户互相注入外部地址。
"""
import logging
from pathlib import Path

from app.config import settings
from app.core.exceptions import BadRequestError

logger = logging.getLogger(__name__)

# 头像子目录与对外 URL 前缀：落盘路径 = UPLOAD_DIR/avatars/<文件名>
AVATAR_SUBDIR = "avatars"
AVATAR_URL_PREFIX = f"/uploads/{AVATAR_SUBDIR}/"

# 允许的头像格式：jpg/png 覆盖拍照与截图，webp 覆盖浏览器另存
ALLOWED_AVATAR_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# 各格式的文件头。仅校验扩展名挡不住把 .html/.svg 改名成 .png 传上来——
# 静态服务会照 Content-Type 提供该文件，等于给了上传者一个托管任意内容的入口。
_MAGIC = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}


def looks_like_image(content: bytes, ext: str) -> bool:
    """按文件头判断内容是否真是该扩展名对应的图片"""
    if ext == ".webp":
        # RIFF 容器：第 0-3 字节是容器标识，格式标识在第 8-11 字节
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return any(content.startswith(sig) for sig in _MAGIC.get(ext, ()))


# PDF 文件头。**不并进 _MAGIC**：那个字典的结构是「扩展名 → 图片签名集合」且被
# looks_like_image 消费，混入 PDF 会让该函数的语义变模糊。
_PDF_MAGIC = b"%PDF-"


def looks_like_pdf(content: bytes) -> bool:
    """按文件头判断内容是否真是 PDF"""
    return content.startswith(_PDF_MAGIC)


def looks_like_resume(content: bytes, ext: str) -> bool:
    """简历文件的内容真伪校验：PDF 认 `%PDF-` 魔数，图片复用 looks_like_image

    与头像同理——简历下载接口的 Content-Type 取自扩展名，若内容与扩展名不符，
    这个接口就成了托管任意内容的入口。
    """
    if ext == ".pdf":
        return looks_like_pdf(content)
    return looks_like_image(content, ext)


def validate_avatar_url(url: str | None) -> None:
    """校验头像地址指向本站头像目录（None 表示清空头像，放行）"""
    if url is None:
        return
    if not url.startswith(AVATAR_URL_PREFIX) or ".." in url or "\\" in url:
        raise BadRequestError(
            f"头像地址无效：须为 {AVATAR_URL_PREFIX}<文件名> 形式的站内路径"
        )


def remove_avatar_file(url: str | None) -> None:
    """删除头像目录下的文件（换头像时清理旧图，避免反复上传堆积垃圾）

    只取 URL 的文件名部分，构造过的地址也越不出 avatars 目录。
    删除失败只告警：文件残留不影响本次请求结果。
    """
    if not url:
        return
    path = Path(settings.UPLOAD_DIR) / AVATAR_SUBDIR / Path(url).name
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("旧头像文件删除失败: %s", path)
