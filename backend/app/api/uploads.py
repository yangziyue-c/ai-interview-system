"""上传接口：语音录音文件（P3 语音识别/评估使用）、用户头像"""
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile

from app.adapters import get_dialogue_adapter
from app.adapters.ai_dialogue import EngineError
from app.api.deps import CurrentUser
from app.config import settings
from app.core.exceptions import BadRequestError, ServiceUnavailableError
from app.core.upload_rules import (
    ALLOWED_AVATAR_EXT,
    AVATAR_SUBDIR,
    AVATAR_URL_PREFIX,
    looks_like_image,
)
from app.utils.response import ok

router = APIRouter()

_ALLOWED_EXT = {".mp3", ".wav", ".webm", ".m4a", ".ogg", ".aac", ".flac"}
_MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
_MAX_AVATAR_BYTES = settings.MAX_AVATAR_SIZE_MB * 1024 * 1024


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


@router.post("/audio/asr", response_model=dict, summary="语音转写（音频进，文字 + 表达指标 + 地址出）")
async def transcribe_audio(user: CurrentUser, file: UploadFile) -> dict:
    """转写录音，并把它存下来（省掉第二次上传）

    与 `/audio` 的分工：那个只管存（返回 url），这个把「转写」和「存」一次做完——
    录音最终要作为 `audio_url` 随答案提交，所以文案与地址一起返回，
    前端一个文件只传一次。

    引擎不可用时明确报 503，不静默返回空文本——空文本会被当成「考生没说话」，
    这种静默失败比一次报错难查得多。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise BadRequestError(
            f"不支持的音频格式 {ext or '(无扩展名)'}，支持: {', '.join(sorted(_ALLOWED_EXT))}"
        )

    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise BadRequestError(f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制")

    try:
        data = await get_dialogue_adapter().transcribe(
            file.filename or "", content, file.content_type or ""
        )
    except EngineError as exc:
        raise ServiceUnavailableError(f"语音转写不可用：{exc}") from exc

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_name = f"{user.id}_{uuid.uuid4().hex[:12]}{ext}"
    (upload_dir / saved_name).write_bytes(content)

    payload = {
        key: data.get(key)
        for key in (
            "text", "duration_ms", "audio_ms", "segments", "pauses", "pause_total_ms",
            "asr_model", "elapsed_ms", "loudness", "loudness_cv", "tail_ratio",
            "emotion", "emotion_score", "emotion_dist",
        )
    }
    payload["url"] = f"/uploads/{saved_name}"
    return ok(payload, "转写完成")


@router.post("/avatar", response_model=dict, summary="上传头像图片（jpg/png/webp，≤2MB）")
async def upload_avatar(user: CurrentUser, file: UploadFile) -> dict:
    """只落盘并返回地址，不改用户资料。

    换头像是「上传拿地址 → 调 PUT /auth/me 提交」两步：旧图的清理放在提交那一步，
    这样「传了图但没提交」只会留下一个无引用文件，不会让用户资料指向已删的图。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AVATAR_EXT:
        raise BadRequestError(
            f"不支持的图片格式 {ext or '(无扩展名)'}，支持: {', '.join(sorted(ALLOWED_AVATAR_EXT))}"
        )

    content = await file.read()
    if len(content) > _MAX_AVATAR_BYTES:
        raise BadRequestError(f"图片超过 {settings.MAX_AVATAR_SIZE_MB}MB 限制")
    if not looks_like_image(content, ext):
        raise BadRequestError("文件内容不是有效图片，请确认文件格式与扩展名一致")

    avatar_dir = Path(settings.UPLOAD_DIR) / AVATAR_SUBDIR
    avatar_dir.mkdir(parents=True, exist_ok=True)
    saved_name = f"{user.id}_{uuid.uuid4().hex[:12]}{ext}"
    (avatar_dir / saved_name).write_bytes(content)

    return ok({"url": f"{AVATAR_URL_PREFIX}{saved_name}"}, "头像上传成功")
