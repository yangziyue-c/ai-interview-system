"""统一业务异常与错误码

错误码约定（响应体 code 字段）：
    0       成功
    400xx   请求参数/业务规则错误
    401xx   未认证 / token 失效
    403xx   无权限访问
    404xx   资源不存在
    409xx   状态冲突（如非法状态转换）
    500xx   服务器内部错误
"""
from fastapi import HTTPException


class AppException(HTTPException):
    """业务异常：抛出处只需关心 code 与 message，HTTP 状态码附带默认值"""

    def __init__(self, code: int, message: str, http_status: int = 400) -> None:
        self.code = code
        super().__init__(status_code=http_status, detail={"code": code, "message": message, "data": None})


# ---- 常用异常快捷定义 ----
class BadRequestError(AppException):
    def __init__(self, message: str = "请求参数错误") -> None:
        super().__init__(40000, message, 400)


class UnauthorizedError(AppException):
    def __init__(self, message: str = "未登录或登录已过期") -> None:
        super().__init__(40100, message, 401)


class ForbiddenError(AppException):
    def __init__(self, message: str = "无权限执行此操作") -> None:
        super().__init__(40300, message, 403)


class NotFoundError(AppException):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(40400, message, 404)


class ConflictError(AppException):
    def __init__(self, message: str = "当前状态不允许此操作") -> None:
        super().__init__(40900, message, 409)


class InternalError(AppException):
    def __init__(self, message: str = "服务器内部错误") -> None:
        super().__init__(50000, message, 500)
