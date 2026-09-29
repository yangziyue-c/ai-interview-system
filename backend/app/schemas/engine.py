"""AI 对话层引擎的扩展能力 schema：面试官朗读（TTS）与体态分析

两项都只在引擎链路（DIALOGUE_ENGINE=a11）下可用——本后端只做转发，真正的合成
与计算都在 8005。请求模型与引擎侧的 `TtsReq` / `BodyLanguageReq` 逐字段对齐
（见引擎 `app/schemas.py`），字段名与取值范围都不在这边另立一套。
"""
from pydantic import BaseModel, Field


class TtsRequest(BaseModel):
    """面试官文本转语音的入参

    上限对齐引擎侧 `A11_TTS_MAX_CHARS`（800）：超长文本引擎会自行截断，
    但那样前端拿到的是半句话，不如在这一层就明确拒掉。
    """

    text: str = Field(min_length=1, max_length=800, description="要朗读的文本")
    voice: str = Field(default="", max_length=64, description="音色名（留空用引擎默认音色）")


class BodyLanguagePoint(BaseModel):
    """一个归一化的 MediaPipe 姿态关键点

    坐标是 [0,1] 的归一化值（MediaPipe Pose 的输出口径），不是像素。
    """

    x: float
    y: float
    z: float = 0.0
    visibility: float = Field(default=1.0, ge=0.0, le=1.0)
    presence: float = Field(default=0.0, ge=0.0, le=1.0)


class BodyLanguageFrame(BaseModel):
    """浏览器在本地提取的一帧——**只有数字，没有画面**

    摄像头数据不出浏览器：MediaPipe 在本地把画面转成关键点后画面即丢，
    上传的只有这里的坐标。
    """

    timestamp_ms: float = Field(ge=0, description="该帧的时间戳（毫秒）")
    landmarks: list[BodyLanguagePoint] = Field(default_factory=list)


class BodyLanguageRequest(BaseModel):
    """体态分析入参；上限 600 帧，与引擎侧一致"""

    frames: list[BodyLanguageFrame] = Field(min_length=1, max_length=600)
