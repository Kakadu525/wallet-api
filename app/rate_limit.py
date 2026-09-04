import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.security import hash_token

_optional_bearer = HTTPBearer(auto_error=False)


class SlidingWindowRateLimiter:
    """
    Скользящее окно на клиента. Состояние in-process: при нескольких
    воркерах лимит применяется per-process. Для распределённого нужен Redis.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Возвращает (разрешено, секунд до следующего слота)."""
        now = time.monotonic() if now is None else now
        window_start = now - self.window
        hits = self._hits[key]

        while hits and hits[0] <= window_start:
            hits.popleft()

        if len(hits) >= self.max_requests:
            return False, max(hits[0] + self.window - now, 0.0)

        hits.append(now)
        return True, 0.0

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowRateLimiter(
    settings.rate_limit_requests, settings.rate_limit_window_seconds
)


def _client_key(request: Request, creds: HTTPAuthorizationCredentials | None) -> str:
    if creds and creds.credentials:
        return "tok:" + hash_token(creds.credentials)
    client = request.client
    return "ip:" + (client.host if client else "unknown")


async def rate_limit(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> None:
    if not settings.rate_limit_enabled:
        return

    allowed, retry_after = limiter.check(_client_key(request, credentials))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(1, round(retry_after)))},
        )
