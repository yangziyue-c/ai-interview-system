"""简历接口：上传并解析 / 读取最近一份 / 读取指定一份 / 下载原文件

简历原件存私有目录（`settings.RESUME_DIR`），**不经过 `/uploads` 静态挂载**——
那个目录是公开的（无鉴权、无子目录白名单），而简历含姓名/学号/联系方式，
只能由本模块的鉴权接口下发。

解析结果不自动写用户资料：格式千差万别的简历靠规则抽取必然出错，自动覆盖会把用户
已经填对的信息改坏。流程是「解析 → 返回建议 → 用户确认 → 走既有的 PUT /auth/me」，
与头像的「上传拿地址 → 提交」同构。
"""
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.resume_parser import parse_resume_file
from app.api.deps import CurrentUser, DbSession
from app.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.resume_fields import FieldGuess, FieldGuesses, extract_fields
from app.core.resume_files import (
    ALLOWED_RESUME_EXT,
    RESUME_MEDIA_TYPES,
    resume_file_path,
    sanitize_filename,
    save_resume_bytes,
)
from app.core.upload_rules import looks_like_resume
from app.models import Position, Resume, User
from app.schemas.resume import ResumeOut, SuggestedFields, SuggestedNotes
from app.utils.response import ok

logger = logging.getLogger(__name__)
router = APIRouter()

_PREVIEW_CHARS = 300


async def _get_owned_resume(resume_id: int, user: User, db: AsyncSession) -> Resume:
    """取本人的简历：非本人一律 404，**不返回 403**——那等于承认这个 id 存在"""
    resume = await db.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    if resume is None:
        raise NotFoundError("简历不存在")
    return resume


async def _resolve_position(guesses: FieldGuesses, db: AsyncSession) -> FieldGuesses:
    """收口岗位 code：抽到的方向必须是当前已开放的岗位

    `core/resume_fields` 是纯函数、不查库，所以这道校验放在 API 层——否则前端会拿到
    一个 `PUT /auth/me` 必然 400 的值去预填，用户点了确认才发现存不进去。
    """
    code = guesses.target_position.value
    if not code:
        return guesses
    enabled = await db.scalar(
        select(Position.id).where(Position.code == code, Position.enabled.is_(True))
    )
    if enabled is None:
        guesses.target_position = FieldGuess(
            None, f"识别到的岗位方向（{code}）当前未开放，请手动选择"
        )
    return guesses


def _resume_out(resume: Resume, guesses: FieldGuesses) -> dict:
    """简历 + 当前的建议字段 → 统一响应形状"""
    text = resume.text_content
    return ResumeOut(
        id=resume.id,
        original_filename=resume.original_filename,
        file_ext=resume.file_ext,
        file_size=resume.file_size,
        parse_status=resume.parse_status,
        parse_message=resume.parse_message,
        text=text,
        text_preview=(text or "")[:_PREVIEW_CHARS],
        text_length=resume.text_length,
        # 存下来的比抽到的短，就说明被截断了；没有文本时不算截断
        text_truncated=bool(text) and resume.text_length > len(text),
        suggested=SuggestedFields(
            nickname=guesses.nickname.value,
            student_id=guesses.student_id.value,
            target_position=guesses.target_position.value,
        ),
        suggested_notes=SuggestedNotes(
            nickname=guesses.nickname.note,
            student_id=guesses.student_id.note,
            target_position=guesses.target_position.note,
        ),
        created_at=resume.created_at,
    ).model_dump()


@router.post("", response_model=dict, summary="上传简历并解析（PDF / 图片）")
async def upload_resume(user: CurrentUser, file: UploadFile, db: DbSession) -> dict:
    """接收简历 → 落私有目录 → 解析 → 返回建议字段供用户确认

    解析不出来**不算请求失败**：文件已安全保存，返回 200 并在 parse_status 里说明原因，
    用户仍可手动填写资料。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_RESUME_EXT:
        raise BadRequestError(
            f"不支持的简历格式 {ext or '(无扩展名)'}，支持: {', '.join(sorted(ALLOWED_RESUME_EXT))}"
        )

    max_bytes = settings.MAX_RESUME_SIZE_MB * 1024 * 1024
    # 先看声明体积：UploadFile.size 在 multipart 解析阶段就已知，能挡掉大文件，
    # 不必把它整个读进内存再判（既有上传接口是后判的，这里不沿用那个顺序）
    if file.size is not None and file.size > max_bytes:
        raise BadRequestError(f"文件超过 {settings.MAX_RESUME_SIZE_MB}MB 限制")

    content = await file.read()
    if len(content) > max_bytes:  # 兜底：分块上传时 size 可能为 None
        raise BadRequestError(f"文件超过 {settings.MAX_RESUME_SIZE_MB}MB 限制")
    if not looks_like_resume(content, ext):
        raise BadRequestError("文件内容不是有效的 PDF / 图片，请确认格式与扩展名一致")

    stored_name = save_resume_bytes(user.id, ext, content)
    parsed = await parse_resume_file(content, ext)

    text = parsed.text[: settings.MAX_RESUME_TEXT_CHARS]
    guesses = await _resolve_position(extract_fields(text), db)

    resume = Resume(
        user_id=user.id,
        original_filename=sanitize_filename(file.filename),
        stored_name=stored_name,
        file_ext=ext,
        file_size=len(content),
        parse_status=parsed.status,
        parse_message=parsed.message,
        parser=parsed.parser,
        text_content=text or None,
        text_length=len(parsed.text),  # 截断前的长度，前端据此提示「已截断」
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    return ok(_resume_out(resume, guesses), parsed.message or "简历已保存")


@router.get("/latest", response_model=dict, summary="获取最近一次上传的简历")
async def get_latest_resume(user: CurrentUser, db: DbSession) -> dict:
    """从未上传过时返回 `data: null`（空态查询而非缺资源，故不返回 404）"""
    resume = await db.scalar(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.id.desc()).limit(1)
    )
    if resume is None:
        return ok(None)
    guesses = await _resolve_position(extract_fields(resume.text_content or ""), db)
    return ok(_resume_out(resume, guesses))


@router.get("/{resume_id}", response_model=dict, summary="获取指定简历")
async def get_resume(resume_id: int, user: CurrentUser, db: DbSession) -> dict:
    resume = await _get_owned_resume(resume_id, user, db)
    guesses = await _resolve_position(extract_fields(resume.text_content or ""), db)
    return ok(_resume_out(resume, guesses))


@router.get("/{resume_id}/file", summary="下载简历原文件（仅本人）")
async def download_resume_file(resume_id: int, user: CurrentUser, db: DbSession):
    """鉴权下载。**非本人一律 404**。

    不写 `response_model=dict`——返回值不是统一响应体而是文件流。
    `media_type` 显式查表而非让 Starlette 调 `mimetypes`（Windows 会查注册表，跨机结果可能不同）；
    `filename` 交给 Starlette 处理，非 ASCII 名会自动按 RFC 5987 编码，不自己拼响应头。
    """
    resume = await _get_owned_resume(resume_id, user, db)
    try:
        path = resume_file_path(resume.stored_name)
    except ValueError:
        logger.error("简历文件名非法: id=%s", resume.id)  # 只记 id，不记文件名与正文
        raise NotFoundError("简历文件不存在")
    if not path.exists():
        logger.warning("简历文件缺失: id=%s", resume.id)
        raise NotFoundError("简历文件不存在")

    return FileResponse(
        path,
        media_type=RESUME_MEDIA_TYPES.get(resume.file_ext, "application/octet-stream"),
        filename=resume.original_filename,
        content_disposition_type="attachment",
    )
