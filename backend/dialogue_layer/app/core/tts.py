# -*- coding: utf-8 -*-
"""Interviewer text-to-speech via DashScope CosyVoice."""
from __future__ import annotations

import base64
import json
import uuid
from typing import Generator

import httpx
from websockets.sync.client import connect

from app import config
from app.logging_conf import get_logger

logger = get_logger(__name__)


class TTSError(RuntimeError):
    pass


def ready() -> bool:
    return bool(config.TTS_ENABLED and config.TTS_API_KEY
                and config.TTS_ENDPOINT and config.TTS_MODEL
                and config.TTS_VOICE)


def synthesize_url(text: str, voice: str = "") -> tuple[str, str]:
    """Return DashScope's temporary audio URL without downloading the WAV."""
    text = str(text or "").strip()
    if not text:
        raise TTSError("待朗读文本为空")
    if len(text) > config.TTS_MAX_CHARS:
        text = text[:config.TTS_MAX_CHARS]
    if not ready():
        raise TTSError("在线 TTS 未配置")

    selected_voice = (voice or config.TTS_VOICE).strip()
    try:
        resp = httpx.post(
            config.TTS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {config.TTS_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.TTS_MODEL,
                "input": {"text": text},
                "parameters": {"voice": selected_voice},
            },
            timeout=config.TTS_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        audio = (((body.get("output") or {}).get("audio")) or {})
        url = str(audio.get("url") or "").strip()
        if not url:
            raise TTSError(f"TTS 未返回音频 URL：{str(body)[:200]}")
        content_type = str(audio.get("content_type") or "audio/wav")
        return url, content_type
    except TTSError:
        raise
    except Exception as e:
        logger.exception("CosyVoice TTS 调用失败")
        raise TTSError(f"{type(e).__name__}: {e}") from e


def synthesize(text: str, voice: str = "") -> tuple[bytes, str]:
    url, content_type = synthesize_url(text, voice)
    try:
        audio_resp = httpx.get(url, timeout=config.TTS_TIMEOUT)
        audio_resp.raise_for_status()
        return audio_resp.content, audio_resp.headers.get("content-type") or content_type
    except Exception as e:
        logger.exception("CosyVoice 音频下载失败")
        raise TTSError(f"{type(e).__name__}: {e}") from e


def stream_pcm(text: str, voice: str = "") -> Generator[dict, None, None]:
    """
    Stream one sentence as PCM plus word timestamps.

    Yields:
        {"type": "start", "sample_rate": 16000}
        {"type": "sentence", "text": ..., "audio": <base64>, "words": [...]}
        {"type": "done"}
        {"type": "error", "err": ...}
    """
    text = str(text or "").strip()
    if not text:
        yield {"type": "error", "err": "待朗读文本为空"}
        return
    if len(text) > config.TTS_MAX_CHARS:
        text = text[:config.TTS_MAX_CHARS]
    if not ready() or not config.TTS_WS_ENDPOINT:
        yield {"type": "error", "err": "在线流式 TTS 未配置"}
        return

    task_id = str(uuid.uuid4())
    selected_voice = (voice or config.TTS_STREAM_VOICE).strip()
    sample_rate = config.TTS_STREAM_SAMPLE_RATE
    headers = {
        "Authorization": f"Bearer {config.TTS_API_KEY}",
        "user-agent": "A11-Interviewer/1.0",
    }
    run_task = {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "tts",
            "function": "SpeechSynthesizer",
            "model": config.TTS_STREAM_MODEL,
            "parameters": {
                "text_type": "PlainText",
                "voice": selected_voice,
                "format": "pcm",
                "sample_rate": sample_rate,
                "word_timestamp_enabled": True,
            },
            "input": {},
        },
    }

    try:
        with connect(
            config.TTS_WS_ENDPOINT,
            additional_headers=headers,
            open_timeout=min(config.TTS_TIMEOUT, 20),
            close_timeout=5,
            max_size=None,
        ) as ws:
            yield {"type": "start", "sample_rate": sample_rate}
            ws.send(json.dumps(run_task, ensure_ascii=False))
            started = False
            current_text = ""
            current_audio = bytearray()
            current_index = 0

            while True:
                msg = ws.recv()
                if isinstance(msg, (bytes, bytearray)):
                    current_audio.extend(msg)
                    continue

                event = json.loads(msg)
                header = event.get("header") or {}
                name = str(header.get("event") or "")
                if name == "task-started" and not started:
                    started = True
                    ws.send(json.dumps({
                        "header": {
                            "action": "continue-task",
                            "task_id": task_id,
                            "streaming": "duplex",
                        },
                        "payload": {"input": {"text": text}},
                    }, ensure_ascii=False))
                    ws.send(json.dumps({
                        "header": {
                            "action": "finish-task",
                            "task_id": task_id,
                            "streaming": "duplex",
                        },
                        "payload": {"input": {}},
                    }, ensure_ascii=False))
                    continue
                if name == "task-failed":
                    err = header.get("error_message") or "流式 TTS 任务失败"
                    raise TTSError(str(err))
                if name == "task-finished":
                    yield {"type": "done"}
                    return

                output = ((event.get("payload") or {}).get("output") or {})
                kind = str(output.get("type") or "")
                sentence = output.get("sentence") or {}
                if kind == "sentence-begin":
                    current_index = int(sentence.get("index") or 0)
                    current_text = str(output.get("original_text") or "")
                    current_audio = bytearray()
                    continue
                if kind == "sentence-end":
                    words = sentence.get("words") or []
                    if current_audio:
                        yield {
                            "type": "sentence",
                            "index": current_index,
                            "text": str(output.get("original_text") or current_text),
                            "audio": base64.b64encode(bytes(current_audio)).decode("ascii"),
                            "words": words,
                            "sample_rate": sample_rate,
                        }
                    current_audio = bytearray()
    except TTSError as e:
        yield {"type": "error", "err": str(e)}
    except Exception as e:
        logger.exception("CosyVoice 流式 TTS 调用失败")
        yield {"type": "error", "err": f"{type(e).__name__}: {e}"}


def status() -> dict:
    return {
        "tts_enabled": config.TTS_ENABLED,
        "tts_ready": ready(),
        "tts_provider": "dashscope_cosyvoice" if config.TTS_ENABLED else "",
        "tts_model": config.TTS_MODEL,
        "tts_voice": config.TTS_VOICE,
        "tts_stream_model": config.TTS_STREAM_MODEL,
        "tts_stream_voice": config.TTS_STREAM_VOICE,
        "tts_stream_ready": bool(ready() and config.TTS_WS_ENDPOINT),
        "tts_stream_sample_rate": config.TTS_STREAM_SAMPLE_RATE,
    }
