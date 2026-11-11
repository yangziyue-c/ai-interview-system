# -*- coding: utf-8 -*-
"""Local-only body-language analysis endpoint."""
from fastapi import APIRouter

from app.schemas import BodyLanguageReq
from quality.body_language import analyze_frames

router = APIRouter()


@router.post(
    "/body-language/analyze",
    summary="分析本地数字姿态关键点",
)
def analyze_body_language(req: BodyLanguageReq) -> dict:
    """
    Accept normalized numerical landmarks only.

    The browser performs MediaPipe extraction locally. This endpoint never
    accepts or stores camera frames, images, video or microphone audio.
    """
    frames = [
        frame.model_dump(exclude_none=True)
        for frame in req.frames
    ]
    return analyze_frames(frames)
