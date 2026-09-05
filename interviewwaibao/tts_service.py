# tts_service.py
import edge_tts
import uuid
import os
import asyncio
import threading

AUDIO_DIR = "audio_files"
os.makedirs(AUDIO_DIR, exist_ok=True)


def _run_async_in_thread(coro):
    """在新线程中运行异步任务"""
    result = None
    exception = None

    def _run():
        nonlocal result, exception
        try:
            # 在新线程中创建全新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(coro)
            finally:
                loop.close()
        except Exception as e:
            exception = e

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join()

    if exception:
        raise exception
    return result


def text_to_speech(text: str):
    """同步版本：在独立线程中运行异步代码"""
    try:
        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)

        communicate = edge_tts.Communicate(text, "zh-CN-YunxiNeural")
        _run_async_in_thread(communicate.save(filepath))

        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return f"/audio/{filename}"
        else:
            print(f"⚠️ 语音文件生成失败: {filepath}")
            return None
    except Exception as e:
        print(f"❌ text_to_speech 错误: {e}")
        return None