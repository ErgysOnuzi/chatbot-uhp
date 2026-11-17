"""Kufizim i thjeshtë i numrit të pyetjeve për IP, që të mbrohet buxheti i API-së."""

import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from .config import settings

_WINDOW_SECONDS = 60
_hits: dict[str, deque] = {}
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    # Nginx e vendos X-Forwarded-For me IP-në reale të klientit (shih frontend/nginx.conf).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(key: str) -> None:
    now = time.monotonic()
    with _lock:
        queue = _hits.setdefault(key, deque())
        while queue and now - queue[0] > _WINDOW_SECONDS:
            queue.popleft()
        if len(queue) >= settings.rate_limit_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Keni bërë shumë pyetje brenda një minute. Prisni pak dhe provoni përsëri.",
            )
        queue.append(now)
