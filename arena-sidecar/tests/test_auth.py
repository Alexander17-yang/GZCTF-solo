from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import replace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.auth as auth_module
from app.config import Settings


def make_request(cookie: str | list[str]) -> Request:
    cookie_headers = [cookie] if isinstance(cookie, str) else cookie
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/arena/pk/state",
            "headers": [
                (b"cookie", value.encode("latin-1")) for value in cookie_headers
            ],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("127.0.0.1", 1),
            "scheme": "http",
        }
    )


class FakeResponse:
    def __init__(self, status_code: int = 200, role: str | int = "User"):
        self.status_code = status_code
        self.role = role

    def json(self):
        return {"userId": "user-1", "userName": "Alice", "role": self.role}


@pytest.fixture(autouse=True)
def isolated_identity_state(monkeypatch):
    monkeypatch.setattr(auth_module, "_identity_client", None)
    monkeypatch.setattr(auth_module, "_identity_cache", OrderedDict())
    monkeypatch.setattr(auth_module, "_identity_inflight", {})


def test_reuses_client_and_invalidates_cache_when_any_cookie_chunk_changes(monkeypatch):
    instances = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.cookies = []
            self.closed = False
            instances.append(self)

        async def get(self, _url, **kwargs):
            self.cookies.append(kwargs["headers"]["Cookie"])
            return FakeResponse(role=3)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    first_cookie = "GZCTF_Token=chunks-2; GZCTF_TokenC1=part-one; theme=dark"
    changed_cookie = "GZCTF_Token=chunks-2; GZCTF_TokenC1=part-two; theme=dark"

    async def scenario():
        first = await auth_module.current_user(make_request(first_cookie))
        cached = await auth_module.current_user(make_request(first_cookie))
        changed = await auth_module.current_user(make_request(changed_cookie))
        assert await auth_module.current_admin(cached) is cached
        await auth_module.close_identity_client()
        return first, cached, changed

    first, cached, changed = asyncio.run(scenario())

    assert len(instances) == 1
    assert instances[0].cookies == [first_cookie, changed_cookie]
    assert instances[0].closed is True
    assert first.role == cached.role == changed.role == "3"


def test_multiple_cookie_headers_are_merged_before_profile_lookup(monkeypatch):
    forwarded = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, _url, **kwargs):
            forwarded.append(kwargs["headers"]["Cookie"])
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)

    async def scenario():
        identity = await auth_module.current_user(
            make_request(
                [
                    "theme=dark; GZCTF_Token=chunks-2",
                    "GZCTF_TokenC1=part-one; GZCTF_TokenC2=part-two",
                ]
            )
        )
        await auth_module.close_identity_client()
        return identity

    identity = asyncio.run(scenario())
    assert identity.user_name == "Alice"
    assert forwarded == [
        "theme=dark; GZCTF_Token=chunks-2; GZCTF_TokenC1=part-one; GZCTF_TokenC2=part-two"
    ]


def test_same_cookie_concurrent_requests_use_single_profile_lookup(monkeypatch):
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, _url, **_kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return FakeResponse(role="Admin")

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    cookie = "GZCTF_Token=session; GZCTF_TokenC1=one; GZCTF_TokenC2=two"

    async def scenario():
        requests = [
            asyncio.create_task(auth_module.current_user(make_request(cookie)))
            for _ in range(25)
        ]
        await started.wait()
        await asyncio.sleep(0)
        assert calls == 1
        release.set()
        identities = await asyncio.gather(*requests)
        await auth_module.close_identity_client()
        return identities

    identities = asyncio.run(scenario())

    assert calls == 1
    assert {identity.user_id for identity in identities} == {"user-1"}
    assert {identity.role for identity in identities} == {"Admin"}


def test_success_cache_expires_after_configured_short_ttl(monkeypatch):
    calls = 0

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, _url, **_kwargs):
            nonlocal calls
            calls += 1
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(auth_module.settings, identity_cache_ttl_seconds=0.01),
    )
    request = make_request("GZCTF_Token=short-lived")

    async def scenario():
        await auth_module.current_user(request)
        await auth_module.current_user(request)
        await asyncio.sleep(0.02)
        await auth_module.current_user(request)
        await auth_module.close_identity_client()

    asyncio.run(scenario())
    assert calls == 2


def test_recent_success_is_used_only_for_temporary_upstream_failure(monkeypatch):
    calls = 0

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, _url, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeResponse(role="Admin")
            raise httpx.ConnectTimeout("identity timeout")

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(
            auth_module.settings,
            identity_cache_ttl_seconds=0.01,
            identity_stale_if_error_seconds=1,
            identity_error_backoff_seconds=0.2,
        ),
    )
    cookie = "GZCTF_Token=stale-session; GZCTF_TokenC1=chunk"

    async def scenario():
        original = await auth_module.current_user(make_request(cookie))
        await asyncio.sleep(0.02)
        fallback = await auth_module.current_user(make_request(cookie))
        with pytest.raises(HTTPException) as changed_cookie_error:
            await auth_module.current_user(
                make_request("GZCTF_Token=stale-session; GZCTF_TokenC1=changed")
            )
        await auth_module.close_identity_client()
        return original, fallback, changed_cookie_error.value

    original, fallback, changed_cookie_error = asyncio.run(scenario())
    assert calls == 3
    assert fallback == original
    assert changed_cookie_error.status_code == 503


def test_stale_fallback_sets_short_retry_backoff(monkeypatch):
    calls = 0

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, _url, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeResponse(role="Admin")
            raise httpx.ConnectTimeout("identity timeout")

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(
            auth_module.settings,
            identity_cache_ttl_seconds=0.01,
            identity_stale_if_error_seconds=1,
            identity_error_backoff_seconds=0.2,
        ),
    )
    request = make_request("GZCTF_Token=backoff-session")

    async def scenario():
        await auth_module.current_user(request)
        await asyncio.sleep(0.02)
        fallback = await auth_module.current_user(request)
        cached_fallback = await auth_module.current_user(request)
        await auth_module.close_identity_client()
        return fallback, cached_fallback

    fallback, cached_fallback = asyncio.run(scenario())
    assert calls == 2
    assert fallback == cached_fallback


def test_expired_success_is_not_used_after_identity_service_rejects_cookie(monkeypatch):
    calls = 0

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, _url, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeResponse(role="Admin")
            if calls == 2:
                return FakeResponse(status_code=401)
            raise httpx.ConnectTimeout("identity timeout after rejection")

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(
            auth_module.settings,
            identity_cache_ttl_seconds=0.01,
            identity_stale_if_error_seconds=1,
        ),
    )
    request = make_request("GZCTF_Token=rejected-session")

    async def scenario():
        await auth_module.current_user(request)
        await asyncio.sleep(0.02)
        with pytest.raises(HTTPException) as rejected:
            await auth_module.current_user(request)
        with pytest.raises(HTTPException) as network_failure:
            await auth_module.current_user(request)
        await auth_module.close_identity_client()
        return rejected.value, network_failure.value

    rejected, network_failure = asyncio.run(scenario())
    assert calls == 3
    assert rejected.status_code == 401
    assert network_failure.status_code == 503


def test_identity_cache_windows_are_configurable(monkeypatch):
    monkeypatch.setenv("GZCTF_IDENTITY_CACHE_TTL_SECONDS", "12.5")
    monkeypatch.setenv("GZCTF_IDENTITY_STALE_IF_ERROR_SECONDS", "90")
    monkeypatch.setenv("GZCTF_IDENTITY_ERROR_BACKOFF_SECONDS", "4")
    configured = Settings.from_env()
    assert configured.identity_cache_ttl_seconds == 12.5
    assert configured.identity_stale_if_error_seconds == 90
    assert configured.identity_error_backoff_seconds == 4


@pytest.mark.parametrize("failure", [401, 500, "network"])
def test_failed_identity_lookup_is_not_cached(monkeypatch, failure):
    calls = 0

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, _url, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                if failure == "network":
                    raise httpx.ConnectTimeout("identity timeout")
                return FakeResponse(status_code=failure)
            return FakeResponse(role="Admin")

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    request = make_request(f"GZCTF_Token=failure-{failure}")

    async def scenario():
        with pytest.raises(HTTPException):
            await auth_module.current_user(request)
        identity = await auth_module.current_user(request)
        await auth_module.close_identity_client()
        return identity

    identity = asyncio.run(scenario())
    assert calls == 2
    assert identity.role == "Admin"
