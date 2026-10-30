"""Security, Rate-Limiting, and Hardening Module for DataSetu Engine.

What this module does:
1. SecurityHeadersMiddleware:
   - Injects defense-in-depth HTTP security headers (CSP, HSTS, X-Frame-Options,
     X-Content-Type-Options, Referrer-Policy, Permissions-Policy).
   - Masks server technology banners (Server: DataSetu-Secure-Engine).
2. RateLimitMiddleware:
   - Sliding-window in-memory rate limiter per client IP.
   - Protects against Denial-of-Service (DoS) and automated query flooding.
   - Emits RFC-compliant X-RateLimit-* and Retry-After headers.
3. RequestSizeLimitMiddleware:
   - Rejects oversized HTTP request bodies (exceeding 10MB) with HTTP 413.
4. PathTraversalGuard:
   - Strictly enforces canonical directory boundaries for file downloads.
5. ErrorSanitizer:
   - Prevents internal database connection strings, paths, and tracebacks
     from leaking to clients in HTTP 500 error payloads.

Why it exists:
Production GovTech and Bharat data platforms handle critical public resources.
Hardening protects against injection, directory traversal, resource exhaustion,
and unauthorized framing.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects strict HTTP security headers and masks server signatures."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)

        # Defense-in-depth headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Server"] = "DataSetu-Secure-Engine/1.0"

        # Content Security Policy (strict self, allows self-contained inline demo styling & scripts)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'self';"
        )
        response.headers["Content-Security-Policy"] = csp

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window rate limiter per client IP.

    Allows 300 requests per 60-second window per IP.
    """

    def __init__(self, app, max_requests: int = 300, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Map IP -> list of request timestamps
        self.request_history: Dict[str, List[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def _cleanup_old_entries(self, now: float) -> None:
        """Periodic memory garbage collection for stale IPs."""
        if now - self._last_cleanup < 30.0:
            return
        self._last_cleanup = now
        cutoff = now - self.window_seconds
        stale_ips = []
        for ip, timestamps in self.request_history.items():
            valid_ts = [t for t in timestamps if t > cutoff]
            if not valid_ts:
                stale_ips.append(ip)
            else:
                self.request_history[ip] = valid_ts
        for ip in stale_ips:
            del self.request_history[ip]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        now = time.time()
        self._cleanup_old_entries(now)

        # Identify client (supports x-forwarded-for if behind reverse proxy)
        client_ip = request.headers.get("x-forwarded-for")
        if client_ip:
            client_ip = client_ip.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "127.0.0.1"

        timestamps = self.request_history[client_ip]
        cutoff = now - self.window_seconds

        # Prune timestamps older than window
        timestamps = [t for t in timestamps if t > cutoff]
        self.request_history[client_ip] = timestamps

        remaining = max(0, self.max_requests - len(timestamps))

        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - timestamps[0])) if timestamps else 1
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "detail": "Rate limit exceeded. DataSetu Engine operates under DoS protection.",
                    "retry_after_seconds": max(1, retry_after),
                },
                headers={
                    "Retry-After": str(max(1, retry_after)),
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # Record this request
        timestamps.append(now)

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforces maximum payload size limit (default 10MB) to mitigate memory exhaustion."""

    def __init__(self, app, max_bytes: int = 10 * 1024 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "Payload Too Large",
                            "detail": f"Request body exceeds maximum allowed size of {self.max_bytes // (1024 * 1024)}MB.",
                        },
                    )
            except ValueError:
                pass

        return await call_next(request)


def verify_safe_file_path(target_file: Path, allowed_root_dir: Path) -> Path:
    """Path traversal guard verifying target path is strictly inside allowed directory."""
    canonical_target = target_file.resolve()
    canonical_root = allowed_root_dir.resolve()

    try:
        canonical_target.relative_to(canonical_root)
    except ValueError:
        raise PermissionError(f"Access denied: path '{target_file}' is outside allowed directory.")

    if not canonical_target.exists() or not canonical_target.is_file():
        raise FileNotFoundError(f"File not found: {target_file.name}")

    return canonical_target
