from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic

import httpx
from fastapi import Depends, HTTPException, Request, status
from starlette.requests import cookie_parser

from .config import settings
from .models import UserIdentity
from .security import decode_token


# Arena match pages poll more than one authenticated endpoint every second. A short
# per-session cache keeps server-side revocations responsive while avoiding a profile
# lookup for every poll. Keys are digests of the complete Cookie header so chunked
# ASP.NET identity cookies participate in invalidation without retaining cookie secrets.
_IDENTITY_CACHE_MAX_ENTRIES = 2048


@dataclass(frozen=True, slots=True)
class _CachedIdentity:
    identity: UserIdentity
    fresh_until: float
    stale_until: float


class _TemporaryIdentityError(HTTPException):
    """An upstream failure for which a recent successful identity may be reused."""


_identity_client: httpx.AsyncClient | None = None
_identity_cache: OrderedDict[bytes, _CachedIdentity] = OrderedDict()
_identity_inflight: dict[bytes, asyncio.Task[UserIdentity]] = {}


def _get_identity_client() -> httpx.AsyncClient:
    global _identity_client

    if _identity_client is None:
        _identity_client = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=32,
                max_keepalive_connections=16,
                keepalive_expiry=30,
            ),
        )
    return _identity_client


def _cookie_cache_key(cookie_header: str) -> bytes:
    return sha256(cookie_header.encode("latin-1")).digest()


def _get_cached_identity(
    cache_key: bytes, *, allow_stale: bool = False
) -> UserIdentity | None:
    cached = _identity_cache.get(cache_key)
    if cached is None:
        return None
    now = monotonic()
    if cached.stale_until <= now:
        _identity_cache.pop(cache_key, None)
        return None
    if not allow_stale and cached.fresh_until <= now:
        return None
    _identity_cache.move_to_end(cache_key)
    return cached.identity


def _cache_identity(cache_key: bytes, identity: UserIdentity) -> None:
    now = monotonic()
    for expired_key in [
        key for key, cached in _identity_cache.items() if cached.stale_until <= now
    ]:
        _identity_cache.pop(expired_key, None)

    fresh_until = now + settings.identity_cache_ttl_seconds
    _identity_cache[cache_key] = _CachedIdentity(
        identity=identity,
        fresh_until=fresh_until,
        stale_until=fresh_until + settings.identity_stale_if_error_seconds,
    )
    _identity_cache.move_to_end(cache_key)
    while len(_identity_cache) > _IDENTITY_CACHE_MAX_ENTRIES:
        _identity_cache.popitem(last=False)


def _stale_identity_after_error(cache_key: bytes) -> UserIdentity | None:
    """Return stale identity and briefly suppress repeated upstream retries."""
    cached = _identity_cache.get(cache_key)
    if cached is None:
        return None
    now = monotonic()
    if cached.stale_until <= now:
        _identity_cache.pop(cache_key, None)
        return None

    # Without a retry backoff every room poll would immediately call the already
    # failing identity service again even though stale-if-error had just succeeded.
    fresh_until = min(
        cached.stale_until,
        now + settings.identity_error_backoff_seconds,
    )
    _identity_cache[cache_key] = _CachedIdentity(
        identity=cached.identity,
        fresh_until=fresh_until,
        stale_until=cached.stale_until,
    )
    _identity_cache.move_to_end(cache_key)
    return cached.identity


def _parse_identity(response: httpx.Response) -> UserIdentity:
    try:
        profile = response.json()
        user_id = str(profile.get("userId") or profile.get("UserId") or "")
        user_name = str(profile.get("userName") or profile.get("UserName") or "")
        role_value = profile.get("role", profile.get("Role", "User"))
        role = str(role_value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="无法解析 GZCTF 用户信息",
        ) from exc

    if not user_id or not user_name:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GZCTF 用户信息不完整",
        )
    if role.lower() == "banned" or role == "0":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用"
        )
    return UserIdentity(user_id=user_id, user_name=user_name, role=role)


async def _fetch_identity(cookie_header: str) -> UserIdentity:
    profile_url = f"{settings.gzctf_internal_url}{settings.profile_path}"
    try:
        response = await _get_identity_client().get(
            profile_url,
            headers={
                "Accept": "application/json",
                "Cookie": cookie_header,
            },
        )
    except httpx.HTTPError as exc:
        raise _TemporaryIdentityError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GZCTF 身份服务暂不可用",
        ) from exc

    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GZCTF 登录已失效",
            headers={"WWW-Authenticate": "Cookie"},
        )
    if response.status_code == 429 or response.status_code >= 500:
        raise _TemporaryIdentityError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GZCTF 身份服务返回异常",
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GZCTF 身份服务返回异常",
        )
    return _parse_identity(response)


async def _fetch_and_cache_identity(
    cache_key: bytes, cookie_header: str
) -> UserIdentity:
    try:
        identity = await _fetch_identity(cookie_header)
    except _TemporaryIdentityError:
        stale = _stale_identity_after_error(cache_key)
        if stale is None:
            raise
        return stale
    except HTTPException as exc:
        # A definitive rejection must revoke both fresh and stale local state.
        # Otherwise a later network failure could resurrect an expired/banned
        # session through stale-if-error.
        if exc.status_code in {
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        }:
            _identity_cache.pop(cache_key, None)
        raise
    _cache_identity(cache_key, identity)
    return identity


def _finish_identity_fetch(
    cache_key: bytes, completed: asyncio.Task[UserIdentity]
) -> None:
    if _identity_inflight.get(cache_key) is completed:
        _identity_inflight.pop(cache_key, None)
    # Mark failures as observed even if the originating HTTP request was cancelled.
    # Other waiters still receive the same exception when awaiting the task.
    if not completed.cancelled():
        completed.exception()


async def _identity_for_cookie(cookie_header: str) -> UserIdentity:
    cache_key = _cookie_cache_key(cookie_header)
    cached = _get_cached_identity(cache_key)
    if cached is not None:
        return cached

    task = _identity_inflight.get(cache_key)
    if task is None:
        task = asyncio.create_task(_fetch_and_cache_identity(cache_key, cookie_header))
        _identity_inflight[cache_key] = task
        task.add_done_callback(
            lambda completed, key=cache_key: _finish_identity_fetch(key, completed)
        )
    return await asyncio.shield(task)


async def close_identity_client() -> None:
    """Close the shared connection pool and clear process-local identity state."""
    global _identity_client

    tasks = list(_identity_inflight.values())
    _identity_inflight.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    _identity_cache.clear()
    client = _identity_client
    _identity_client = None
    if client is not None:
        await client.aclose()


async def current_user(request: Request) -> UserIdentity:
    authorization = request.headers.get("authorization", "")
    if settings.local_admin_enabled and authorization.lower().startswith("bearer "):
        payload = decode_token(authorization[7:].strip(), settings.token_secret)
        if payload and str(payload.get("role", "")).lower() == "admin":
            return UserIdentity(
                user_id=f"local:{payload['sub']}",
                user_name=str(payload["sub"]),
                role="Admin",
            )

    cookie_header = "; ".join(request.headers.getlist("cookie"))
    session_cookie = cookie_parser(cookie_header).get(settings.cookie_name)
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录 GZCTF",
            headers={"WWW-Authenticate": "Cookie"},
        )

    # ASP.NET Core's ChunkingCookieManager may split a large identity cookie into
    # GZCTF_TokenC1/GZCTF_TokenC2. Forward and fingerprint the original header after
    # confirming the primary GZCTF cookie exists so every chunk reaches the service.
    return await _identity_for_cookie(cookie_header)


async def current_admin(user: UserIdentity = Depends(current_user)) -> UserIdentity:
    if user.role.lower() != "admin" and user.role != "3":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )
    return user
