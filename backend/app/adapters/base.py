"""适配器基类：HTTP 调用 + 15 秒超时降级兜底

P2/P3 适配器统一继承本类：
- URL 未配置（.env 留空）   → 直接返回内置 Mock 数据
- URL 已配置但超时/异常/失败 → 记录警告并降级为 Mock（保证面试流程永不中断）
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AdapterTimeoutError(Exception):
    """适配器调用超过 settings.ADAPTER_TIMEOUT_SECONDS"""


class HTTPAdapterBase:
    """带超时降级的 HTTP 适配器基类"""

    def __init__(self, base_url: str, name: str) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.name = name

    async def call(
        self, path: str, payload: dict, timeout: float | None = None
    ) -> dict | None:
        """调用外部服务并返回 JSON；未配置 URL 时返回 None（表示走 Mock）

        timeout: 单次调用预算，默认取 settings.ADAPTER_TIMEOUT_SECONDS；
        评估报告生成较慢，评估适配器可单独传入更长的预算。
        """
        if not self.base_url:
            return None
        t = timeout if timeout is not None else settings.ADAPTER_TIMEOUT_SECONDS
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                resp = await asyncio.wait_for(
                    client.post(f"{self.base_url}{path}", json=payload),
                    timeout=t,
                )
                resp.raise_for_status()
                return resp.json()
        except asyncio.TimeoutError:
            raise AdapterTimeoutError(
                f"{self.name} 调用超时（>{t:.0f}s）"
            ) from None
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"{self.name} 返回异常状态码 {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{self.name} 网络错误: {exc}") from exc
        except ValueError as exc:
            # resp.json() 解析失败（返回了非 JSON 内容）也走 Mock 兜底，保证流程不中断
            raise RuntimeError(f"{self.name} 返回非 JSON 内容: {exc}") from exc

    async def call_or_fallback(
        self,
        path: str,
        payload: dict,
        mock_func: Callable[[], Awaitable[Any] | Any],
        timeout: float | None = None,
    ) -> Any:
        """调用外部服务，失败/超时自动降级为 Mock 并记录日志"""
        try:
            result = await self.call(path, payload, timeout)
            if result is not None:
                return result
            logger.debug("%s 未配置 URL，使用 Mock 数据", self.name)
        except (AdapterTimeoutError, RuntimeError) as exc:
            logger.warning("%s 调用失败(%s)，已降级为 Mock 兜底", self.name, exc)
        return await mock_func() if asyncio.iscoroutinefunction(mock_func) else mock_func()
