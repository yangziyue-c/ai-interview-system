"""P2/P3 适配器包

- ai_interviewer: P2 AI 面试官（生成问题与追问）
- ai_evaluator  : P3 AI 评估（评分与报告）
均支持内置 Mock 与外部 HTTP 服务，15 秒超时自动降级。
"""
from app.adapters.ai_evaluator import get_evaluator_adapter
from app.adapters.ai_interviewer import get_interviewer_adapter

__all__ = ["get_interviewer_adapter", "get_evaluator_adapter"]
