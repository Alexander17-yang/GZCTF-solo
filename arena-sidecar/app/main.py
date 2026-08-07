from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .auth import close_identity_client, current_admin, current_user
from .config import settings
from .database import Database
from .models import (
    ArenaAdminView,
    ArenaConfigWrite,
    ArenaPublicView,
    BossStateView,
    BossSubmitResponse,
    ChallengeAdminView,
    ChallengeWrite,
    LoginRequest,
    LoginResponse,
    OneWayMatchAdminView,
    OneWayMatchStatus,
    OneWayRoomCreateRequest,
    OneWayRoomJoinRequest,
    OneWayRoomRequest,
    OneWayRoomView,
    OneWaySubmitRequest,
    OneWaySubmitResponse,
    PkMatchAdminView,
    PkMatchStatus,
    PkRoomRequest,
    PkRoomView,
    PkStateView,
    PkSubmitRequest,
    PkSubmitResponse,
    ResetRequest,
    SubmitRequest,
    UserIdentity,
)
from .repository import (
    ArenaRepositoryError,
    create_pk_room,
    create_one_way_room,
    delete_admin_config,
    delete_pk_match,
    delete_pk_match_room,
    delete_one_way_match,
    delete_one_way_match_room,
    get_pk_room,
    get_one_way_room,
    get_admin_config,
    get_boss_state,
    get_pk_state,
    get_public_config,
    join_pk_room,
    join_one_way_room,
    leave_pk_room,
    leave_one_way_room,
    list_pk_matches,
    list_one_way_matches,
    reset_runtime,
    save_admin_config,
    submit_boss,
    submit_pk,
    submit_one_way,
)
from .security import issue_token, verify_secret


def _write_from_admin(config: ArenaAdminView) -> ArenaConfigWrite:
    challenges = [
        ChallengeWrite.model_validate(challenge.model_dump(exclude={"has_flag"}))
        for challenge in config.challenges
    ]
    return ArenaConfigWrite(
        game_id=config.game_id,
        enabled=config.enabled,
        published=config.published,
        mode=config.mode,
        pk_config=config.pk_config,
        boss_config=config.boss_config,
        one_way_config=config.one_way_config,
        challenges=challenges,
        revision=config.revision,
    )


def create_app(database: Database | None = None) -> FastAPI:
    selected_database = database or Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate()
        app.state.database.initialize()
        try:
            yield
        finally:
            await close_identity_client()

    app = FastAPI(
        title="GZCTF 方块竞技场 Sidecar API",
        version="1.0.0",
        root_path=settings.root_path,
        docs_url="/api/arena/docs",
        redoc_url=None,
        openapi_url="/api/arena/openapi.json",
        lifespan=lifespan,
    )
    app.state.database = selected_database

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "If-Match"],
        )
    if settings.trusted_hosts:
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts)
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/arena/public/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        elif request.url.path.startswith("/api/arena/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(ArenaRepositoryError)
    async def repository_error_handler(_request: Request, exc: ArenaRepositoryError):
        return Response(
            content=(f'{{"detail":{_json_string(exc.detail)}}}'),
            status_code=exc.status_code,
            media_type="application/json",
            headers=exc.headers,
        )

    @app.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        with app.state.database.connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get(
        "/api/arena/public/active",
        response_model=ArenaPublicView,
        tags=["public"],
    )
    def public_active() -> ArenaPublicView:
        return get_public_config(app.state.database)

    @app.get(
        "/api/arena/public/games/{game_id}",
        response_model=ArenaPublicView,
        tags=["public"],
    )
    def public_game(game_id: int) -> ArenaPublicView:
        return get_public_config(app.state.database, game_id)

    @app.get(
        "/api/arena/config",
        response_model=ArenaPublicView,
        include_in_schema=False,
    )
    def public_config_alias(
        game_id: int | None = Query(default=None, alias="gameId"),
    ) -> ArenaPublicView:
        return get_public_config(app.state.database, game_id)

    @app.get(
        "/api/arena/admin/games/{game_id}",
        response_model=ArenaAdminView,
        tags=["admin"],
    )
    def admin_get_game(
        game_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> ArenaAdminView:
        return get_admin_config(app.state.database, game_id)

    @app.get(
        "/api/arena/admin/games/{game_id}/pk-matches",
        response_model=list[PkMatchAdminView],
        tags=["admin"],
    )
    def admin_list_pk_matches(
        game_id: int,
        match_status: PkMatchStatus | None = Query(default=None, alias="status"),
        limit: int = Query(default=100, ge=1, le=500),
        _admin: UserIdentity = Depends(current_admin),
    ) -> list[PkMatchAdminView]:
        return list_pk_matches(
            app.state.database,
            game_id,
            match_status=match_status,
            limit=limit,
        )

    @app.get(
        "/api/arena/admin/games/{game_id}/one-way-matches",
        response_model=list[OneWayMatchAdminView],
        tags=["admin"],
    )
    def admin_list_one_way_matches(
        game_id: int,
        match_status: OneWayMatchStatus | None = Query(default=None, alias="status"),
        limit: int = Query(default=100, ge=1, le=500),
        _admin: UserIdentity = Depends(current_admin),
    ) -> list[OneWayMatchAdminView]:
        return list_one_way_matches(
            app.state.database,
            game_id,
            match_status=match_status,
            limit=limit,
        )

    @app.delete(
        "/api/arena/admin/games/{game_id}/pk-matches/{match_id}/room",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["admin"],
    )
    def admin_delete_pk_match_room(
        game_id: int,
        match_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> Response:
        delete_pk_match_room(app.state.database, game_id, match_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.delete(
        "/api/arena/admin/games/{game_id}/pk-matches/{match_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["admin"],
    )
    def admin_delete_pk_match(
        game_id: int,
        match_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> Response:
        delete_pk_match(app.state.database, game_id, match_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.delete(
        "/api/arena/admin/games/{game_id}/one-way-matches/{match_id}/room",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["admin"],
    )
    def admin_delete_one_way_match_room(
        game_id: int,
        match_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> Response:
        delete_one_way_match_room(app.state.database, game_id, match_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.delete(
        "/api/arena/admin/games/{game_id}/one-way-matches/{match_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["admin"],
    )
    def admin_delete_one_way_match(
        game_id: int,
        match_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> Response:
        delete_one_way_match(app.state.database, game_id, match_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.put(
        "/api/arena/admin/games/{game_id}",
        response_model=ArenaAdminView,
        tags=["admin"],
    )
    def admin_put_game(
        game_id: int,
        payload: ArenaConfigWrite,
        _admin: UserIdentity = Depends(current_admin),
    ) -> ArenaAdminView:
        return save_admin_config(app.state.database, game_id, payload)

    @app.delete(
        "/api/arena/admin/games/{game_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["admin"],
    )
    def admin_delete_game(
        game_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> Response:
        if not delete_admin_config(app.state.database, game_id):
            raise HTTPException(status_code=404, detail="竞技场配置不存在")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/arena/admin/games/{game_id}/challenges",
        response_model=ChallengeAdminView,
        status_code=status.HTTP_201_CREATED,
        tags=["admin"],
    )
    def admin_create_challenge(
        game_id: int,
        challenge: ChallengeWrite,
        _admin: UserIdentity = Depends(current_admin),
    ) -> ChallengeAdminView:
        if challenge.id is not None:
            raise HTTPException(status_code=422, detail="新增题目时不能指定 id")
        current = get_admin_config(app.state.database, game_id)
        if not current.exists:
            raise HTTPException(status_code=404, detail="请先保存赛事竞技场配置")
        payload = _write_from_admin(current)
        old_ids = {item.id for item in current.challenges}
        payload.challenges.append(challenge)
        saved = save_admin_config(app.state.database, game_id, payload)
        return next(item for item in saved.challenges if item.id not in old_ids)

    @app.get(
        "/api/arena/admin/games/{game_id}/challenges",
        response_model=list[ChallengeAdminView],
        tags=["admin"],
    )
    def admin_list_challenges(
        game_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> list[ChallengeAdminView]:
        return get_admin_config(app.state.database, game_id).challenges

    @app.put(
        "/api/arena/admin/games/{game_id}/challenges/{challenge_id}",
        response_model=ChallengeAdminView,
        tags=["admin"],
    )
    def admin_update_challenge(
        game_id: int,
        challenge_id: int,
        challenge: ChallengeWrite,
        _admin: UserIdentity = Depends(current_admin),
    ) -> ChallengeAdminView:
        if challenge.id is not None and challenge.id != challenge_id:
            raise HTTPException(
                status_code=400, detail="URL 与请求体中的 challengeId 不一致"
            )
        current = get_admin_config(app.state.database, game_id)
        payload = _write_from_admin(current)
        for index, existing in enumerate(payload.challenges):
            if existing.id == challenge_id:
                payload.challenges[index] = challenge.model_copy(
                    update={"id": challenge_id}
                )
                break
        else:
            raise HTTPException(status_code=404, detail="题目不存在")
        saved = save_admin_config(app.state.database, game_id, payload)
        return next(item for item in saved.challenges if item.id == challenge_id)

    @app.delete(
        "/api/arena/admin/games/{game_id}/challenges/{challenge_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["admin"],
    )
    def admin_delete_challenge(
        game_id: int,
        challenge_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> Response:
        current = get_admin_config(app.state.database, game_id)
        payload = _write_from_admin(current)
        filtered = [item for item in payload.challenges if item.id != challenge_id]
        if len(filtered) == len(payload.challenges):
            raise HTTPException(status_code=404, detail="题目不存在")
        payload.challenges = filtered
        save_admin_config(app.state.database, game_id, payload)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/arena/admin/games/{game_id}/reset",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["admin"],
    )
    def admin_reset_game(
        game_id: int,
        payload: ResetRequest,
        _admin: UserIdentity = Depends(current_admin),
    ) -> Response:
        reset_runtime(app.state.database, game_id, payload.modes)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/arena/admin/config",
        response_model=ArenaAdminView,
        include_in_schema=False,
    )
    def admin_config_alias_get(
        game_id: int = Query(alias="gameId"),
        _admin: UserIdentity = Depends(current_admin),
    ) -> ArenaAdminView:
        return get_admin_config(app.state.database, game_id)

    @app.put(
        "/api/arena/admin/config",
        response_model=ArenaAdminView,
        include_in_schema=False,
    )
    def admin_config_alias_put(
        payload: ArenaConfigWrite,
        game_id: int = Query(alias="gameId"),
        _admin: UserIdentity = Depends(current_admin),
    ) -> ArenaAdminView:
        return save_admin_config(app.state.database, game_id, payload)

    @app.get(
        "/api/edit/games/{game_id}/arena",
        response_model=ArenaAdminView,
        include_in_schema=False,
    )
    def legacy_admin_get(
        game_id: int,
        _admin: UserIdentity = Depends(current_admin),
    ) -> ArenaAdminView:
        return get_admin_config(app.state.database, game_id)

    @app.put(
        "/api/edit/games/{game_id}/arena",
        response_model=ArenaAdminView,
        include_in_schema=False,
    )
    def legacy_admin_put(
        game_id: int,
        payload: ArenaConfigWrite,
        _admin: UserIdentity = Depends(current_admin),
    ) -> ArenaAdminView:
        return save_admin_config(app.state.database, game_id, payload)

    @app.post(
        "/api/arena/pk/rooms",
        response_model=PkRoomView,
        status_code=status.HTTP_201_CREATED,
        tags=["pk"],
    )
    def pk_room_create(
        payload: PkRoomRequest,
        user: UserIdentity = Depends(current_user),
    ) -> PkRoomView:
        return create_pk_room(app.state.database, payload.game_id, user)

    @app.post(
        "/api/arena/pk/rooms/{room_code}/join",
        response_model=PkRoomView,
        tags=["pk"],
    )
    def pk_room_join(
        room_code: str,
        payload: PkRoomRequest,
        user: UserIdentity = Depends(current_user),
    ) -> PkRoomView:
        return join_pk_room(app.state.database, room_code, payload.game_id, user)

    @app.get(
        "/api/arena/pk/rooms/{room_code}",
        response_model=PkRoomView,
        tags=["pk"],
    )
    def pk_room_get(
        room_code: str,
        game_id: int = Query(alias="gameId"),
        user: UserIdentity = Depends(current_user),
    ) -> PkRoomView:
        return get_pk_room(app.state.database, room_code, game_id, user)

    @app.post(
        "/api/arena/pk/rooms/{room_code}/leave",
        response_model=PkRoomView,
        tags=["pk"],
    )
    def pk_room_leave(
        room_code: str,
        payload: PkRoomRequest,
        user: UserIdentity = Depends(current_user),
    ) -> PkRoomView:
        return leave_pk_room(app.state.database, room_code, payload.game_id, user)

    @app.post(
        "/api/arena/pk/submit",
        response_model=PkSubmitResponse,
        tags=["pk"],
    )
    def pk_submit(
        payload: PkSubmitRequest,
        user: UserIdentity = Depends(current_user),
    ) -> PkSubmitResponse:
        return submit_pk(
            app.state.database,
            payload.game_id,
            payload.challenge_id,
            payload.flag,
            user,
            payload.room_code,
        )

    @app.get(
        "/api/arena/pk/state",
        response_model=PkStateView,
        tags=["pk"],
    )
    def pk_state(
        game_id: int = Query(alias="gameId"),
        room_code: str | None = Query(
            default=None, alias="roomCode", pattern=r"^\d{6}$"
        ),
        user: UserIdentity = Depends(current_user),
    ) -> PkStateView:
        return get_pk_state(app.state.database, game_id, user, room_code)

    @app.post(
        "/api/arena/one-way/rooms",
        response_model=OneWayRoomView,
        status_code=status.HTTP_201_CREATED,
        tags=["one-way"],
    )
    def one_way_room_create(
        payload: OneWayRoomCreateRequest,
        user: UserIdentity = Depends(current_user),
    ) -> OneWayRoomView:
        return create_one_way_room(
            app.state.database,
            payload.game_id,
            payload.direction_id,
            user,
        )

    @app.post(
        "/api/arena/one-way/rooms/{room_code}/join",
        response_model=OneWayRoomView,
        tags=["one-way"],
    )
    def one_way_room_join(
        room_code: str,
        payload: OneWayRoomJoinRequest | None = None,
        user: UserIdentity = Depends(current_user),
    ) -> OneWayRoomView:
        return join_one_way_room(
            app.state.database,
            room_code,
            payload.game_id if payload is not None else None,
            user,
        )

    @app.get(
        "/api/arena/one-way/rooms/{room_code}",
        response_model=OneWayRoomView,
        tags=["one-way"],
    )
    def one_way_room_get(
        room_code: str,
        game_id: int = Query(alias="gameId"),
        user: UserIdentity = Depends(current_user),
    ) -> OneWayRoomView:
        return get_one_way_room(app.state.database, room_code, game_id, user)

    @app.post(
        "/api/arena/one-way/rooms/{room_code}/leave",
        response_model=OneWayRoomView,
        tags=["one-way"],
    )
    def one_way_room_leave(
        room_code: str,
        payload: OneWayRoomRequest,
        user: UserIdentity = Depends(current_user),
    ) -> OneWayRoomView:
        return leave_one_way_room(app.state.database, room_code, payload.game_id, user)

    @app.post(
        "/api/arena/one-way/submit",
        response_model=OneWaySubmitResponse,
        tags=["one-way"],
    )
    def one_way_submit(
        payload: OneWaySubmitRequest,
        user: UserIdentity = Depends(current_user),
    ) -> OneWaySubmitResponse:
        return submit_one_way(
            app.state.database,
            payload.game_id,
            payload.room_code,
            payload.challenge_id,
            payload.flag,
            user,
        )

    @app.post(
        "/api/arena/boss/submit",
        response_model=BossSubmitResponse,
        tags=["boss"],
    )
    def boss_submit(
        payload: SubmitRequest,
        user: UserIdentity = Depends(current_user),
    ) -> BossSubmitResponse:
        return submit_boss(
            app.state.database,
            payload.game_id,
            payload.challenge_id,
            payload.flag,
            user,
        )

    @app.get(
        "/api/arena/boss/state",
        response_model=BossStateView,
        tags=["boss"],
    )
    def boss_state(
        game_id: int = Query(alias="gameId"),
        user: UserIdentity = Depends(current_user),
    ) -> BossStateView:
        return get_boss_state(app.state.database, game_id, user)

    @app.post(
        "/api/arena/admin/login",
        response_model=LoginResponse,
        include_in_schema=False,
    )
    def optional_local_login(payload: LoginRequest) -> LoginResponse:
        if not settings.local_admin_enabled:
            raise HTTPException(status_code=404, detail="本地管理员登录未启用")
        valid_user = payload.username == settings.local_admin_username
        valid_password = verify_secret(
            payload.password, settings.local_admin_password_hash
        )
        if not (valid_user and valid_password):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token, expires_at = issue_token(
            payload.username, "Admin", settings.token_secret, settings.token_ttl_seconds
        )
        return LoginResponse(
            token=token,
            expires_at=expires_at,
            expires_in=settings.token_ttl_seconds,
        )

    return app


def _json_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


app = create_app()
