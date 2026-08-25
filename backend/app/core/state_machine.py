"""面试状态机

状态流转：idle → in_progress → finished
- idle        ：会话已创建，尚未开始
- in_progress ：面试进行中，可提交答案
- finished    ：面试结束，报告已生成（终态）

任何非法转换统一抛出 409 冲突错误。
"""
from enum import Enum

from app.core.exceptions import ConflictError


class InterviewStatus(str, Enum):
    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class StateMachine:
    _TRANSITIONS: dict[InterviewStatus, set[InterviewStatus]] = {
        InterviewStatus.IDLE: {InterviewStatus.IN_PROGRESS},
        InterviewStatus.IN_PROGRESS: {InterviewStatus.FINISHED},
        InterviewStatus.FINISHED: set(),  # 终态不可再转
    }

    @classmethod
    def can_transition(cls, current: InterviewStatus, target: InterviewStatus) -> bool:
        return target in cls._TRANSITIONS.get(current, set())

    @classmethod
    def transition(cls, interview, target: InterviewStatus) -> None:
        """校验并执行状态转换；非法转换抛 409"""
        current = InterviewStatus(interview.status)
        if not cls.can_transition(current, target):
            raise ConflictError(f"面试状态不允许从 {current.value} 变更为 {target.value}")
        interview.status = target.value

    @classmethod
    def require(cls, interview, expected: InterviewStatus) -> None:
        """断言当前处于某状态，否则抛 409"""
        current = InterviewStatus(interview.status)
        if current is not expected:
            raise ConflictError(f"面试当前状态为 {current.value}，此操作要求 {expected.value}")
