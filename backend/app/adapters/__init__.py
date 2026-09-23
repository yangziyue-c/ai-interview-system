"""适配器包

- ai_interviewer: P2 AI 面试官（生成问题与追问）
- ai_evaluator  : P3 AI 评估（评分与报告）
- ai_dialogue   : AI 对话层引擎（A11，整场委托：出题 / 追问 / 评分）

前两者支持内置 Mock 与外部 HTTP 服务，15 秒超时自动降级；
ai_dialogue 是会话式的，且**刻意不做 Mock 兜底**（见该模块 docstring）。
"""
from app.adapters.ai_dialogue import get_dialogue_adapter
from app.adapters.ai_evaluator import get_evaluator_adapter
from app.adapters.ai_interviewer import get_interviewer_adapter

__all__ = ["get_dialogue_adapter", "get_interviewer_adapter", "get_evaluator_adapter"]
