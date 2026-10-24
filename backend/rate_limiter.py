# rate_limiter.py - 轻量级内存速率限制器
import time
from collections import defaultdict
from fastapi import HTTPException


class RateLimiter:
    """简单的滑动窗口速率限制器"""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.time()
        window_start = now - self.window_seconds

        # 清理过期记录
        self._requests[key] = [
            t for t in self._requests[key] if t > window_start
        ]

        if len(self._requests[key]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请 {self.window_seconds} 秒后再试",
            )

        self._requests[key].append(now)


# 登录/注册限流：每分钟 5 次
auth_limiter = RateLimiter(max_requests=5, window_seconds=60)

# API 全局限流：每分钟 30 次
api_limiter = RateLimiter(max_requests=30, window_seconds=60)
