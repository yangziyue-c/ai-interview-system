from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import json
import os
import time
from typing import List, Dict, Any, Optional

from ai_service import AIService
from tts_service import text_to_speech

app = FastAPI()

# ========== CORS 跨域配置 ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ai_service = AIService()

# ========== 请求模型 ==========
class ChatRequest(BaseModel):
    session_id: str
    user_answer: str = ""
    position: str = "java"


class GenerateRequest(BaseModel):
    position: str
    round: int
    is_follow_up: bool
    history: List[Dict[str, str]]
    need_audio: Optional[bool] = False


# ========== 接口1：原有流式面试 ==========
@app.post("/interview/stream")
async def interview_stream(request: ChatRequest):
    session_id = request.session_id
    user_answer = request.user_answer
    position = request.position

    if session_id not in ai_service.sessions:
        ai_service.create_session(session_id, position)

    if ai_service.is_interview_over(session_id):
        async def end_generator():
            yield {
                "event": "end",
                "data": json.dumps({"message": "面试已结束"})
            }
        return StreamingResponse(end_generator(), media_type="text/event-stream")

    response = ai_service.ask_question(session_id, user_answer)
    if response is None:
        async def end_generator():
            yield {
                "event": "end",
                "data": json.dumps({"message": "面试结束"})
            }
        return StreamingResponse(end_generator(), media_type="text/event-stream")

    # 同步生成器（Python 3.8+ 完全兼容）
    def generate():
        full_question = ""
        print("🔍 开始读取 AI 流式响应...")

        for chunk in response.iter_lines():
            if chunk:
                chunk_str = chunk.decode('utf-8')
                print(f"📦 收到 chunk: {chunk_str}")
                if chunk_str.startswith('data: '):
                    chunk_data = chunk_str[6:]
                    if chunk_data == '[DONE]':
                        break
                    try:
                        chunk_json = json.loads(chunk_data)
                        delta = chunk_json['choices'][0]['delta']
                        if 'content' in delta:
                            content = delta['content']
                            full_question += content
                            yield f"event: text\ndata: {json.dumps({'content': content})}\n\n"
                    except:
                        pass

        if full_question:
            ai_service.save_question(session_id, full_question)
            audio_url = text_to_speech(full_question)
            yield f"event: audio\ndata: {json.dumps({'audio_url': audio_url})}\n\n"

        if ai_service.is_interview_over(session_id):
            yield f"event: end\ndata: {json.dumps({'message': '面试全部结束'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ========== 接口2：结构化出题 ==========
@app.post("/generate")
async def generate_question(request: GenerateRequest):
    try:
        question = ai_service.generate_question(
            position=request.position,
            round_num=request.round,
            is_follow_up=request.is_follow_up,
            history=request.history
        )
        audio_url = None
        if request.need_audio and question:
            audio_url = text_to_speech(question)
        return {"question": question, "audio_url": audio_url}
    except Exception as e:
        print(f"❌ /generate 接口异常: {e}")
        return {"question": "请介绍一下你的项目经历。", "audio_url": None}


# ========== 音频文件服务 ==========
@app.get("/audio/{filename}")
async def get_audio(filename: str):
    filepath = os.path.join("audio_files", filename)
    if os.path.exists(filepath):
        return FileResponse(filepath, media_type="audio/mpeg")
    return {"error": "文件不存在"}


# ========== 测试接口 ==========
@app.get("/")
async def root():
    return {"message": "AI面试官服务已启动"}


@app.get("/test-sse")
async def test_sse():
    def event_stream():
        yield f"data: {json.dumps({'content': '测试数据123'})}\n\n"
        time.sleep(0.5)
        yield f"data: {json.dumps({'content': '测试数据456'})}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")