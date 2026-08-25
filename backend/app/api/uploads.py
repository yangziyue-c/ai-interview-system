"""上传接口：语音录音文件（P3 语音识别/评估使用）"""
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile

from app.api.deps import CurrentUser
from app.config import settings
from app.core.exceptions import BadRequestError
from app.utils.response import ok

router = APIRouter()

_ALLOWED_EXT = {".mp3", ".wav", ".webm", ".m4a", ".ogg", ".aac", ".flac"}
_MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@router.post("/audio", response_model=dict, summary="上传面试录音")
async def upload_audio(user: CurrentUser, file: UploadFile) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise BadRequestError(f"不支持的音频格式 {ext or '(无扩展名)'}，支持: {', '.join(sorted(_ALLOWED_EXT))}")

    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise BadRequestError(f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制")

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    # 按用户分目录，避免重名；文件名随机
    saved_name = f"{user.id}_{uuid.uuid4().hex[:12]}{ext}"
    (upload_dir / saved_name).write_bytes(content)

    return ok({"url": f"/uploads/{saved_name}"}, "上传成功")
