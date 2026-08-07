from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

import app.repository as repository
from app.auth import current_admin, current_user
from app.database import Database
from app.main import create_app
from app.models import UserIdentity
from app.repository import ArenaRepositoryError, join_pk_room, submit_one_way


@pytest.fixture()
def client(tmp_path: Path):
    database = Database(tmp_path / "arena.db")
    application = create_app(database)
    identity = {
        "value": UserIdentity(user_id="user-1", user_name="Alice", role="Admin")
    }

    async def fake_user() -> UserIdentity:
        return identity["value"]

    application.dependency_overrides[current_user] = fake_user
    application.dependency_overrides[current_admin] = fake_user
    with TestClient(application) as test_client:
        test_client.identity = identity  # type: ignore[attr-defined]
        test_client.database = database  # type: ignore[attr-defined]
        yield test_client


def use_identity(client: TestClient, user_id: str, user_name: str) -> UserIdentity:
    identity = UserIdentity(user_id=user_id, user_name=user_name, role="User")
    client.identity["value"] = identity  # type: ignore[attr-defined]
    return identity


def config_payload(*, revision: int | None = 0, published: bool = True) -> dict:
    return {
        "gameId": 7,
        "enabled": True,
        "published": published,
        "mode": "hybrid",
        "revision": revision,
        "pkConfig": {
            "teamSize": 1,
            "matchSeconds": 900,
            "questionCount": 4,
            "scoreMode": "fixed",
            "winRule": "highest_score",
            "allowDraw": False,
            "wrongPenalty": 10,
            "cooldownSeconds": 0,
            "firstBloodBonus": 100,
            "streakBonus": 25,
            "sameQuestionsForBoth": True,
        },
        "bossConfig": {
            "name": "岩浆核心",
            "maxHp": 10000,
            "phaseCount": 3,
            "phaseThresholds": [0.66, 0.33],
            "enrageSeconds": 7200,
            "enrageDamageMultiplier": 0.75,
            "minTeamContribution": 100,
            "shieldEnabled": True,
        },
        "challenges": [
            {
                "title": "熔炉入口",
                "category": "Web",
                "difficulty": "easy",
                "description": "找到入口 Flag",
                "target": "http://challenge.local",
                "attachmentUrl": None,
                "status": "active",
                "enabled": True,
                "sortOrder": 1,
                "modes": ["pk", "boss"],
                "pk": {
                    "variantGroup": "web-a",
                    "baseScore": 500,
                    "timeLimitSeconds": 600,
                },
                "boss": {
                    "baseDamage": 1000,
                    "phase": 1,
                    "affinity": "weak",
                    "isShieldChallenge": True,
                    "isCoreChallenge": False,
                },
                "flagCaseSensitive": True,
                "flag": "flag{voxel_arena}",
            }
        ],
    }


def create_one_way_game(
    client: TestClient,
    *,
    round_count: int = 3,
    pool_size: int | None = None,
    countdown_seconds: int = 2,
    round_seconds: int = 30,
    interval_seconds: int = 3,
) -> tuple[dict, dict[int, str]]:
    actual_pool_size = pool_size if pool_size is not None else round_count
    challenges = [
        {
            "title": f"单向题 {index}",
            "category": "Web",
            "difficulty": "normal",
            "description": f"仅在第 {index} 个抽中轮次公开",
            "target": f"http://one-way-{index}.internal",
            "attachmentUrl": f"/attachments/one-way-{index}.zip",
            "status": "active",
            "enabled": True,
            "sortOrder": index,
            "modes": ["one_way"],
            "flagCaseSensitive": True,
            "flag": f"flag{{one_way_{index}}}",
        }
        for index in range(1, actual_pool_size + 1)
    ]
    draft_payload = {
        "gameId": 7,
        "enabled": True,
        "published": False,
        "mode": "one_way_onebyone",
        "revision": 0,
        "oneWayConfig": {
            "countdownSeconds": countdown_seconds,
            "roundCount": round_count,
            "roundSeconds": round_seconds,
            "intervalSeconds": interval_seconds,
            "directions": [],
        },
        "challenges": challenges,
    }
    draft = client.put("/api/arena/admin/games/7", json=draft_payload)
    assert draft.status_code == 200, draft.text
    draft_body = draft.json()
    challenge_ids = [item["id"] for item in draft_body["challenges"]]
    flags = {
        challenge_id: f"flag{{one_way_{index}}}"
        for index, challenge_id in enumerate(challenge_ids, 1)
    }
    update_payload = admin_view_to_write(draft_body)
    update_payload["published"] = True
    update_payload["oneWayConfig"] = {
        "countdownSeconds": countdown_seconds,
        "roundCount": round_count,
        "roundSeconds": round_seconds,
        "intervalSeconds": interval_seconds,
        "directions": [
            {
                "id": "web",
                "name": "Web 安全",
                "description": "单方向 Web 对决",
                "challengeIds": challenge_ids,
            }
        ],
    }
    published = client.put("/api/arena/admin/games/7", json=update_payload)
    assert published.status_code == 200, published.text
    return published.json(), flags


def admin_view_to_write(body: dict) -> dict:
    payload = {
        key: value for key, value in body.items() if key not in {"exists", "updatedAt"}
    }
    payload["challenges"] = [
        {key: value for key, value in challenge.items() if key != "hasFlag"}
        for challenge in body["challenges"]
    ]
    return payload


def parse_api_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_config_lifecycle_and_public_flag_redaction(client: TestClient):
    initial = client.get("/api/arena/admin/games/7")
    assert initial.status_code == 200
    assert initial.json()["exists"] is False
    assert initial.json()["revision"] == 0
    assert client.get("/api/arena/public/active").status_code == 404

    saved = client.put("/api/arena/admin/games/7", json=config_payload())
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["exists"] is True
    assert body["revision"] == 1
    assert body["challenges"][0]["hasFlag"] is True
    assert "flag" not in body["challenges"][0]

    public = client.get("/api/arena/public/active")
    assert public.status_code == 200, public.text
    public_body = public.json()
    assert public_body["gameId"] == 7
    assert public_body["bossState"]["hp"] == 10000
    challenge = public_body["challenges"][0]
    assert challenge["title"] == "熔炉入口"
    assert "flag" not in challenge
    assert "hasFlag" not in challenge

    stale = config_payload(revision=0)
    response = client.put("/api/arena/admin/games/7", json=stale)
    assert response.status_code == 409


def test_published_pk_config_rejects_when_all_pk_challenges_are_draft(
    client: TestClient,
):
    payload = config_payload()
    payload["challenges"][0]["status"] = "draft"

    rejected = client.put("/api/arena/admin/games/7", json=payload)
    assert rejected.status_code == 422
    assert "至少需要一道已开放" in rejected.json()["detail"]

    rolled_back = client.get("/api/arena/admin/games/7").json()
    assert rolled_back["exists"] is False
    assert rolled_back["revision"] == 0
    assert rolled_back["challenges"] == []


def test_published_pk_config_rejects_active_challenge_without_flag(
    client: TestClient,
):
    payload = config_payload()
    payload["challenges"][0].pop("flag")

    rejected = client.put("/api/arena/admin/games/7", json=payload)
    assert rejected.status_code == 422
    assert "已配置 Flag" in rejected.json()["detail"]

    rolled_back = client.get("/api/arena/admin/games/7").json()
    assert rolled_back["exists"] is False
    assert rolled_back["revision"] == 0
    assert rolled_back["challenges"] == []


def test_published_pk_config_update_reuses_existing_flag(client: TestClient):
    saved = client.put("/api/arena/admin/games/7", json=config_payload()).json()
    challenge_id = saved["challenges"][0]["id"]
    payload = config_payload(revision=saved["revision"])
    payload["challenges"][0]["id"] = challenge_id
    payload["challenges"][0].pop("flag")
    payload["challenges"][0]["title"] = "保留已有 Flag"

    updated = client.put("/api/arena/admin/games/7", json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["challenges"][0]["hasFlag"] is True

    clear_payload = config_payload(revision=updated.json()["revision"])
    clear_payload["challenges"][0]["id"] = challenge_id
    clear_payload["challenges"][0].pop("flag")
    clear_payload["challenges"][0]["clearFlag"] = True
    rejected_clear = client.put("/api/arena/admin/games/7", json=clear_payload)
    assert rejected_clear.status_code == 422

    rolled_back = client.get("/api/arena/admin/games/7").json()
    assert rolled_back["revision"] == updated.json()["revision"]
    assert rolled_back["challenges"][0]["hasFlag"] is True

    solved = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
        },
    )
    assert solved.status_code == 200, solved.text
    assert solved.json()["correct"] is True


def test_enabled_draft_challenge_stays_locked_until_admin_explicitly_opens_it(
    client: TestClient,
):
    payload = config_payload()
    payload["challenges"][0]["status"] = "draft"
    playable_challenge = dict(payload["challenges"][0])
    playable_challenge.update(
        {
            "title": "后端防线题",
            "status": "active",
            "sortOrder": 2,
            "flag": "flag{playable_guard}",
        }
    )
    payload["challenges"].append(playable_challenge)
    saved = client.put("/api/arena/admin/games/7", json=payload)
    assert saved.status_code == 200, saved.text
    challenge = saved.json()["challenges"][0]
    challenge_id = challenge["id"]

    public_draft = client.get("/api/arena/public/active")
    assert public_draft.status_code == 200
    assert public_draft.json()["challenges"][0]["status"] == "draft"
    assert public_draft.json()["challenges"][0]["locked"] is True

    blocked = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
        },
    )
    assert blocked.status_code == 423
    assert blocked.json()["detail"] == "题目尚未开放"

    challenge.pop("hasFlag")
    challenge["status"] = "active"
    opened = client.put(
        f"/api/arena/admin/games/7/challenges/{challenge_id}", json=challenge
    )
    assert opened.status_code == 200, opened.text

    public_open = client.get("/api/arena/public/active")
    assert public_open.json()["challenges"][0]["locked"] is False
    solved = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
        },
    )
    assert solved.status_code == 200, solved.text
    assert solved.json()["correct"] is True


def test_pk_and_boss_atomic_scoring_and_reset(client: TestClient):
    saved = client.put("/api/arena/admin/games/7", json=config_payload())
    challenge_id = saved.json()["challenges"][0]["id"]

    wrong = client.post(
        "/api/arena/pk/submit",
        json={"gameId": 7, "challengeId": challenge_id, "flag": "wrong"},
    )
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["correct"] is False
    assert wrong.json()["score"] == 0

    correct = client.post(
        "/api/arena/pk/submit",
        json={"gameId": 7, "challengeId": challenge_id, "flag": "flag{voxel_arena}"},
    )
    assert correct.status_code == 200, correct.text
    assert correct.json()["correct"] is True
    assert correct.json()["firstBlood"] is True
    assert correct.json()["scoreDelta"] == 600

    duplicate = client.post(
        "/api/arena/pk/submit",
        json={"gameId": 7, "challengeId": challenge_id, "flag": "flag{voxel_arena}"},
    )
    assert duplicate.json()["alreadySolved"] is True
    assert duplicate.json()["score"] == 600

    pk_state = client.get("/api/arena/pk/state?gameId=7")
    assert pk_state.status_code == 200
    assert pk_state.json()["solvedChallengeIds"] == [challenge_id]
    assert pk_state.json()["leaderboard"][0]["userName"] == "Alice"

    boss = client.post(
        "/api/arena/boss/submit",
        json={"gameId": 7, "challengeId": challenge_id, "flag": "flag{voxel_arena}"},
    )
    assert boss.status_code == 200, boss.text
    assert boss.json()["damage"] == 1500
    assert boss.json()["bossState"]["hp"] == 8500
    assert boss.json()["bossState"]["shieldActive"] is False

    boss_state = client.get("/api/arena/boss/state?gameId=7")
    assert boss_state.status_code == 200
    assert boss_state.json()["contribution"] == 1500
    assert boss_state.json()["leaderboard"][0]["contribution"] == 1500

    reset = client.post(
        "/api/arena/admin/games/7/reset",
        json={"modes": ["pk", "boss"]},
    )
    assert reset.status_code == 204
    assert client.get("/api/arena/pk/state?gameId=7").json()["score"] == 0
    reset_boss = client.get("/api/arena/boss/state?gameId=7").json()["bossState"]
    assert reset_boss["hp"] == 10000
    assert reset_boss["shieldActive"] is True


def test_granular_challenge_crud_preserves_existing_flag(client: TestClient):
    saved = client.put("/api/arena/admin/games/7", json=config_payload()).json()
    challenge_id = saved["challenges"][0]["id"]
    challenge = saved["challenges"][0]
    challenge.pop("hasFlag")
    challenge["title"] = "新标题"

    updated = client.put(
        f"/api/arena/admin/games/7/challenges/{challenge_id}", json=challenge
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "新标题"
    assert updated.json()["hasFlag"] is True

    solve = client.post(
        "/api/arena/pk/submit",
        json={"gameId": 7, "challengeId": challenge_id, "flag": "flag{voxel_arena}"},
    )
    assert solve.status_code == 200
    assert solve.json()["correct"] is True

    current = client.get("/api/arena/admin/games/7").json()
    unpublished = config_payload(revision=current["revision"], published=False)
    unpublished["challenges"][0]["id"] = challenge_id
    unpublished["challenges"][0]["title"] = "新标题"
    unpublished["challenges"][0].pop("flag")
    disabled_guard = client.put("/api/arena/admin/games/7", json=unpublished)
    assert disabled_guard.status_code == 200, disabled_guard.text

    deleted = client.delete(f"/api/arena/admin/games/7/challenges/{challenge_id}")
    assert deleted.status_code == 204
    assert client.get("/api/arena/admin/games/7").json()["challenges"] == []


def test_public_active_ignores_draft_game(client: TestClient):
    response = client.put(
        "/api/arena/admin/games/7", json=config_payload(published=False)
    )
    assert response.status_code == 200
    assert client.get("/api/arena/public/active").status_code == 404


def test_identity_proxy_forwards_chunked_cookie(monkeypatch):
    from starlette.requests import Request

    import app.auth as auth_module

    captured: dict = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"userId": "abc", "userName": "Chunked", "role": "Admin"}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def get(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", FakeClient)
    auth_module._identity_cache.clear()
    auth_module._identity_inflight.clear()
    auth_module._identity_client = None
    cookie = b"GZCTF_Token=chunks-2; GZCTF_TokenC1=part-one; GZCTF_TokenC2=part-two"
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/arena/pk/state",
            "headers": [(b"cookie", cookie)],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("127.0.0.1", 1),
            "scheme": "http",
        }
    )
    identity = asyncio.run(auth_module.current_user(request))
    assert identity.user_name == "Chunked"
    assert captured["headers"]["Cookie"] == cookie.decode()
    asyncio.run(auth_module.close_identity_client())


def test_v1_database_is_migrated_without_losing_existing_config(tmp_path: Path):
    database = Database(tmp_path / "arena-v1.db")
    database.initialize()
    timestamp = datetime.now(UTC).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO arena_games(
                game_id, enabled, published, mode, pk_config_json, boss_config_json,
                revision, created_at, updated_at
            ) VALUES (99, 0, 0, 'hybrid', '{}', '{}', 1, ?, ?)
            """,
            (timestamp, timestamp),
        )
        connection.execute("DROP TABLE pk_room_submissions")
        connection.execute("DROP TABLE pk_room_players")
        connection.execute("DROP TABLE pk_rooms")
        connection.execute("UPDATE schema_info SET version = 1")

    database.initialize()

    with database.connection() as connection:
        assert (
            connection.execute("SELECT version FROM schema_info").fetchone()["version"]
            == 4
        )
        assert (
            connection.execute(
                "SELECT revision FROM arena_games WHERE game_id = 99"
            ).fetchone()["revision"]
            == 1
        )
        room_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'pk_rooms'"
        ).fetchone()
        assert room_table is not None
        audit_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'pk_match_audits'"
        ).fetchone()
        assert audit_table is not None


def test_v2_migration_backfills_live_pk_rooms_without_touching_runtime_data(
    tmp_path: Path,
):
    database = Database(tmp_path / "arena-v2.db")
    database.initialize()
    now = datetime.now(UTC)
    timestamp = now.isoformat()
    starts_at = (now - timedelta(seconds=1)).isoformat()
    pk_config = config_payload()["pkConfig"]
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO arena_games(
                game_id, enabled, published, mode, pk_config_json, boss_config_json,
                revision, created_at, updated_at
            ) VALUES (7, 1, 1, 'hybrid', ?, '{}', 1, ?, ?)
            """,
            (json.dumps(pk_config), timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO pk_rooms(
                code, game_id, host_user_id, host_user_name,
                guest_user_id, guest_user_name, created_at, starts_at, updated_at
            ) VALUES ('969710', 7, 'host-id', 'Existing Host',
                      'guest-id', 'Existing Guest', ?, ?, ?)
            """,
            (timestamp, starts_at, timestamp),
        )
        connection.executemany(
            """
            INSERT INTO pk_room_players(
                room_code, user_id, user_name, score, solves, streak,
                last_submission_at, updated_at
            ) VALUES ('969710', ?, ?, ?, ?, 0, NULL, ?)
            """,
            [
                ("host-id", "Existing Host", 600, 1, timestamp),
                ("guest-id", "Existing Guest", 100, 0, timestamp),
            ],
        )
        # Recreate the exact production upgrade boundary: v2 has the room
        # runtime tables and data, but not the v3 audit table.
        connection.execute("DROP TABLE pk_match_audits")
        connection.execute("UPDATE schema_info SET version = 2")

    database.initialize()

    with database.connection() as connection:
        assert (
            connection.execute("SELECT version FROM schema_info").fetchone()["version"]
            == 4
        )
        live_room = connection.execute(
            "SELECT * FROM pk_rooms WHERE code = '969710'"
        ).fetchone()
        assert live_room is not None
        assert live_room["guest_user_id"] == "guest-id"
        players = connection.execute(
            "SELECT COUNT(*) AS count FROM pk_room_players WHERE room_code = '969710'"
        ).fetchone()["count"]
        assert players == 2
        audit = connection.execute(
            "SELECT * FROM pk_match_audits WHERE room_code = '969710'"
        ).fetchone()
        assert audit is not None
        assert audit["status"] == "active"
        assert audit["host_user_name"] == "Existing Host"
        assert audit["guest_user_name"] == "Existing Guest"
        assert audit["host_score"] == 600
        assert audit["host_solves"] == 1
        assert audit["guest_score"] == 100

    application = create_app(database)

    async def migrated_admin() -> UserIdentity:
        return UserIdentity(user_id="admin-id", user_name="Admin", role="Admin")

    application.dependency_overrides[current_admin] = migrated_admin
    with TestClient(application) as migrated_client:
        response = migrated_client.get("/api/arena/admin/games/7/pk-matches")
    assert response.status_code == 200
    assert response.json()[0]["roomCode"] == "969710"
    assert response.json()[0]["host"]["score"] == 600
    assert response.json()[0]["guest"]["userName"] == "Existing Guest"


def test_admin_pk_match_audit_lifecycle_filters_and_reset_retention(
    client: TestClient,
):
    saved = client.put("/api/arena/admin/games/7", json=config_payload()).json()
    challenge_id = saved["challenges"][0]["id"]
    use_identity(client, "host-id", "Alice")

    first_room = client.post("/api/arena/pk/rooms", json={"gameId": 7}).json()
    waiting = client.get("/api/arena/admin/games/7/pk-matches")
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()[0] == {
        "matchId": waiting.json()[0]["matchId"],
        "gameId": 7,
        "roomCode": first_room["code"],
        "roomExists": True,
        "status": "waiting",
        "host": {
            "userId": "host-id",
            "userName": "Alice",
            "score": 0,
            "solves": 0,
        },
        "guest": None,
        "winner": None,
        "isDraw": False,
        "createdAt": waiting.json()[0]["createdAt"],
        "joinedAt": None,
        "startsAt": None,
        "endsAt": None,
        "finishedAt": None,
        "finishReason": None,
        "updatedAt": waiting.json()[0]["updatedAt"],
    }
    stable_updated_at = waiting.json()[0]["updatedAt"]
    for _ in range(3):
        assert (
            client.get(f"/api/arena/pk/rooms/{first_room['code']}?gameId=7").status_code
            == 200
        )
    waiting_again = client.get("/api/arena/admin/games/7/pk-matches").json()[0]
    assert waiting_again["updatedAt"] == stable_updated_at

    use_identity(client, "guest-id", "Bob")
    joined = client.post(
        f"/api/arena/pk/rooms/{first_room['code']}/join", json={"gameId": 7}
    )
    assert joined.status_code == 200
    countdown = client.get(
        "/api/arena/admin/games/7/pk-matches?status=countdown&limit=1"
    )
    assert countdown.status_code == 200, countdown.text
    assert len(countdown.json()) == 1
    assert countdown.json()[0]["guest"]["userName"] == "Bob"
    assert countdown.json()[0]["startsAt"] is not None
    assert countdown.json()[0]["endsAt"] is not None

    database = client.database  # type: ignore[attr-defined]
    active_start = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE pk_rooms SET starts_at = ? WHERE code = ?",
            (active_start, first_room["code"]),
        )

    use_identity(client, "host-id", "Alice")
    solve = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
            "roomCode": first_room["code"],
        },
    )
    assert solve.status_code == 200, solve.text
    assert solve.json()["score"] == 600

    expired_start = (datetime.now(UTC) - timedelta(seconds=901)).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE pk_rooms SET starts_at = ? WHERE code = ?",
            (expired_start, first_room["code"]),
        )

    finished = client.get("/api/arena/admin/games/7/pk-matches?status=finished&limit=1")
    assert finished.status_code == 200, finished.text
    result = finished.json()[0]
    assert result["roomCode"] == first_room["code"]
    assert result["status"] == "finished"
    assert result["host"]["score"] == 600
    assert result["host"]["solves"] == 1
    assert result["guest"]["score"] == 0
    assert result["winner"]["userId"] == "host-id"
    assert result["winner"]["score"] == 600
    assert result["isDraw"] is False
    assert result["finishReason"] == "timeout"
    assert result["finishedAt"] == result["endsAt"]

    # A second live room is terminated by reset, while the completed first
    # match and both audit rows survive deletion of the runtime rooms.
    second_room = client.post("/api/arena/pk/rooms", json={"gameId": 7}).json()
    reset = client.post("/api/arena/admin/games/7/reset", json={"modes": ["pk"]})
    assert reset.status_code == 204
    with database.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM pk_rooms WHERE game_id = 7"
            ).fetchone()["count"]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM pk_match_audits WHERE game_id = 7"
            ).fetchone()["count"]
            == 2
        )

    history = client.get("/api/arena/admin/games/7/pk-matches?limit=2")
    assert history.status_code == 200
    assert [item["roomCode"] for item in history.json()] == [
        second_room["code"],
        first_room["code"],
    ]
    assert history.json()[0]["status"] == "reset"
    assert history.json()[0]["finishReason"] == "admin_reset"
    assert history.json()[0]["roomExists"] is False
    assert history.json()[1]["status"] == "finished"
    assert history.json()[1]["roomExists"] is False

    assert (
        client.get("/api/arena/admin/games/7/pk-matches?status=unknown").status_code
        == 422
    )
    assert client.get("/api/arena/admin/games/7/pk-matches?limit=0").status_code == 422


def test_pk_match_audit_route_requires_admin(tmp_path: Path):
    database = Database(tmp_path / "arena-auth.db")
    application = create_app(database)

    async def regular_user() -> UserIdentity:
        return UserIdentity(user_id="user-id", user_name="Regular", role="User")

    application.dependency_overrides[current_user] = regular_user
    with TestClient(application) as unauthorized_client:
        response = unauthorized_client.get("/api/arena/admin/games/7/pk-matches")
    assert response.status_code == 403
    assert response.json()["detail"] == "需要管理员权限"


def test_admin_deletes_live_pk_room_before_permanently_deleting_audit(
    client: TestClient,
):
    saved = client.put("/api/arena/admin/games/7", json=config_payload()).json()
    challenge_id = saved["challenges"][0]["id"]
    use_identity(client, "host-id", "Alice")
    room = client.post("/api/arena/pk/rooms", json={"gameId": 7}).json()
    use_identity(client, "guest-id", "Bob")
    assert (
        client.post(
            f"/api/arena/pk/rooms/{room['code']}/join", json={"gameId": 7}
        ).status_code
        == 200
    )

    database = client.database  # type: ignore[attr-defined]
    active_start = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE pk_rooms SET starts_at = ? WHERE code = ?",
            (active_start, room["code"]),
        )

    use_identity(client, "host-id", "Alice")
    solved = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
            "roomCode": room["code"],
        },
    )
    assert solved.status_code == 200, solved.text
    match = client.get("/api/arena/admin/games/7/pk-matches").json()[0]
    match_id = match["matchId"]
    assert match["roomExists"] is True
    assert match["host"]["score"] == 600

    wrong_game_room = client.delete(
        f"/api/arena/admin/games/8/pk-matches/{match_id}/room"
    )
    wrong_game_audit = client.delete(f"/api/arena/admin/games/8/pk-matches/{match_id}")
    assert wrong_game_room.status_code == 404
    assert wrong_game_audit.status_code == 404

    audit_first = client.delete(f"/api/arena/admin/games/7/pk-matches/{match_id}")
    assert audit_first.status_code == 409
    assert "先删除" in audit_first.json()["detail"]

    deleted_room = client.delete(f"/api/arena/admin/games/7/pk-matches/{match_id}/room")
    assert deleted_room.status_code == 204, deleted_room.text
    with database.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM pk_rooms WHERE code = ?", (room["code"],)
            ).fetchone()["count"]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM pk_room_players WHERE room_code = ?",
                (room["code"],),
            ).fetchone()["count"]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM pk_room_submissions WHERE room_code = ?",
                (room["code"],),
            ).fetchone()["count"]
            == 0
        )
        audit = connection.execute(
            "SELECT * FROM pk_match_audits WHERE id = ?", (match_id,)
        ).fetchone()
        assert audit is not None
        assert audit["status"] == "cancelled"
        assert audit["finish_reason"] == "admin_reset"
        assert audit["host_score"] == 600
        assert audit["host_solves"] == 1

    retained = client.get("/api/arena/admin/games/7/pk-matches").json()[0]
    assert retained["matchId"] == match_id
    assert retained["roomExists"] is False
    assert retained["status"] == "cancelled"
    assert retained["finishReason"] == "admin_reset"
    assert retained["host"]["score"] == 600
    assert (
        client.delete(
            f"/api/arena/admin/games/7/pk-matches/{match_id}/room"
        ).status_code
        == 404
    )

    deleted_audit = client.delete(f"/api/arena/admin/games/7/pk-matches/{match_id}")
    assert deleted_audit.status_code == 204
    assert client.get("/api/arena/admin/games/7/pk-matches").json() == []
    assert (
        client.delete(f"/api/arena/admin/games/7/pk-matches/{match_id}").status_code
        == 404
    )


def test_admin_room_delete_preserves_finished_pk_result(client: TestClient):
    client.put("/api/arena/admin/games/7", json=config_payload())
    use_identity(client, "host-id", "Alice")
    room = client.post("/api/arena/pk/rooms", json={"gameId": 7}).json()
    use_identity(client, "guest-id", "Bob")
    client.post(f"/api/arena/pk/rooms/{room['code']}/join", json={"gameId": 7})

    database = client.database  # type: ignore[attr-defined]
    expired_start = (datetime.now(UTC) - timedelta(seconds=901)).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE pk_rooms SET starts_at = ? WHERE code = ?",
            (expired_start, room["code"]),
        )
        connection.execute(
            "UPDATE pk_room_players SET score = 700, solves = 2 WHERE room_code = ? AND user_id = 'host-id'",
            (room["code"],),
        )
        connection.execute(
            "UPDATE pk_room_players SET score = 100, solves = 1 WHERE room_code = ? AND user_id = 'guest-id'",
            (room["code"],),
        )

    finished = client.get("/api/arena/admin/games/7/pk-matches").json()[0]
    match_id = finished["matchId"]
    assert finished["status"] == "finished"
    assert finished["finishReason"] == "timeout"
    assert finished["winner"]["userId"] == "host-id"
    assert finished["roomExists"] is True

    response = client.delete(f"/api/arena/admin/games/7/pk-matches/{match_id}/room")
    assert response.status_code == 204
    retained = client.get("/api/arena/admin/games/7/pk-matches").json()[0]
    assert retained["roomExists"] is False
    assert retained["status"] == finished["status"]
    assert retained["finishReason"] == finished["finishReason"]
    assert retained["finishedAt"] == finished["finishedAt"]
    assert retained["winner"] == finished["winner"]
    assert retained["host"] == finished["host"]
    assert retained["guest"] == finished["guest"]


def test_old_audit_cannot_delete_a_later_room_reusing_the_same_code(
    client: TestClient,
    monkeypatch,
):
    import app.repository as repository

    client.put("/api/arena/admin/games/7", json=config_payload())
    monkeypatch.setattr(repository, "_random_pk_room_code", lambda: "123456")
    use_identity(client, "first-host", "First")
    first_room = client.post("/api/arena/pk/rooms", json={"gameId": 7})
    assert first_room.status_code == 201
    first_match_id = client.get("/api/arena/admin/games/7/pk-matches").json()[0][
        "matchId"
    ]
    assert (
        client.delete(
            f"/api/arena/admin/games/7/pk-matches/{first_match_id}/room"
        ).status_code
        == 204
    )

    use_identity(client, "second-host", "Second")
    second_room = client.post("/api/arena/pk/rooms", json={"gameId": 7})
    assert second_room.status_code == 201, second_room.text
    assert second_room.json()["code"] == "123456"
    matches = client.get("/api/arena/admin/games/7/pk-matches").json()
    second_match_id = matches[0]["matchId"]
    assert second_match_id != first_match_id
    assert matches[0]["roomExists"] is True
    assert matches[1]["roomExists"] is False

    stale_room_delete = client.delete(
        f"/api/arena/admin/games/7/pk-matches/{first_match_id}/room"
    )
    assert stale_room_delete.status_code == 409
    assert client.get("/api/arena/pk/rooms/123456?gameId=7").status_code == 200

    # An old audit is not associated with the newer runtime room and can be
    # removed without touching that room.
    assert (
        client.delete(
            f"/api/arena/admin/games/7/pk-matches/{first_match_id}"
        ).status_code
        == 204
    )
    assert client.get("/api/arena/pk/rooms/123456?gameId=7").status_code == 200
    current = client.get("/api/arena/admin/games/7/pk-matches").json()
    assert [item["matchId"] for item in current] == [second_match_id]
    assert current[0]["roomExists"] is True


def test_pk_match_delete_routes_require_admin(tmp_path: Path):
    database = Database(tmp_path / "arena-delete-auth.db")
    application = create_app(database)

    async def regular_user() -> UserIdentity:
        return UserIdentity(user_id="user-id", user_name="Regular", role="User")

    application.dependency_overrides[current_user] = regular_user
    with TestClient(application) as unauthorized_client:
        delete_room = unauthorized_client.delete(
            "/api/arena/admin/games/7/pk-matches/1/room"
        )
        delete_audit = unauthorized_client.delete(
            "/api/arena/admin/games/7/pk-matches/1"
        )
    assert delete_room.status_code == 403
    assert delete_room.json()["detail"] == "需要管理员权限"
    assert delete_audit.status_code == 403
    assert delete_audit.json()["detail"] == "需要管理员权限"


def test_pk_room_waits_for_two_distinct_players_then_uses_one_start_time(
    client: TestClient,
):
    assert (
        client.put("/api/arena/admin/games/7", json=config_payload()).status_code == 200
    )
    alice = use_identity(client, "user-1", "Alice")

    created = client.post("/api/arena/pk/rooms", json={"gameId": 7})
    assert created.status_code == 201, created.text
    room = created.json()
    assert re.fullmatch(r"\d{6}", room["code"])
    assert room["status"] == "waiting"
    assert room["host"]["userId"] == alice.user_id
    assert room["guest"] is None
    assert room["startsAt"] is None

    duplicate_host = client.post(
        f"/api/arena/pk/rooms/{room['code']}/join", json={"gameId": 7}
    )
    assert duplicate_host.status_code == 200
    assert duplicate_host.json()["status"] == "waiting"
    assert duplicate_host.json()["guest"] is None

    use_identity(client, "user-2", "Bob")
    before_join = datetime.now(UTC)
    joined = client.post(f"/api/arena/pk/rooms/{room['code']}/join", json={"gameId": 7})
    assert joined.status_code == 200, joined.text
    joined_room = joined.json()
    starts_at = datetime.fromisoformat(joined_room["startsAt"])
    assert joined_room["status"] == "countdown"
    assert joined_room["guest"]["userName"] == "Bob"
    assert 4 <= (starts_at - before_join).total_seconds() <= 6

    repeated_guest = client.post(
        f"/api/arena/pk/rooms/{room['code']}/join", json={"gameId": 7}
    )
    assert repeated_guest.status_code == 200
    assert repeated_guest.json()["startsAt"] == joined_room["startsAt"]

    use_identity(client, "user-1", "Alice")
    host_view = client.get(f"/api/arena/pk/rooms/{room['code']}?gameId=7")
    assert host_view.status_code == 200
    assert host_view.json()["startsAt"] == joined_room["startsAt"]
    assert host_view.json()["currentUserRole"] == "host"

    use_identity(client, "user-3", "Carol")
    full = client.post(f"/api/arena/pk/rooms/{room['code']}/join", json={"gameId": 7})
    assert full.status_code == 409
    assert client.get(f"/api/arena/pk/rooms/{room['code']}?gameId=7").status_code == 403


def test_pk_room_join_is_atomic_for_competing_and_duplicate_requests(
    client: TestClient,
):
    assert (
        client.put("/api/arena/admin/games/7", json=config_payload()).status_code == 200
    )
    host = use_identity(client, "host", "Host")
    created = client.post("/api/arena/pk/rooms", json={"gameId": 7}).json()
    database = client.database  # type: ignore[attr-defined]
    contenders = [
        UserIdentity(user_id="guest-a", user_name="Guest A", role="User"),
        UserIdentity(user_id="guest-b", user_name="Guest B", role="User"),
    ]
    barrier = Barrier(3)

    def compete(identity: UserIdentity):
        barrier.wait()
        try:
            return join_pk_room(database, created["code"], 7, identity)
        except ArenaRepositoryError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(compete, identity) for identity in contenders]
        barrier.wait()
        outcomes = [future.result() for future in futures]

    successes = [
        item for item in outcomes if not isinstance(item, ArenaRepositoryError)
    ]
    failures = [item for item in outcomes if isinstance(item, ArenaRepositoryError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].status_code == 409
    winner_id = successes[0].guest.user_id
    winner = next(identity for identity in contenders if identity.user_id == winner_id)
    first_start = successes[0].starts_at

    # Retrying the winning user's join is idempotent and never consumes a third seat
    # or resets the shared start timestamp.
    duplicate = join_pk_room(database, created["code"], 7, winner)
    assert duplicate.guest is not None
    assert duplicate.guest.user_id == winner_id
    assert duplicate.starts_at == first_start
    with database.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM pk_room_players WHERE room_code = ?",
            (created["code"],),
        ).fetchone()["count"]
    assert count == 2

    # The host is still recognized as the first, distinct seat.
    host_view = join_pk_room(database, created["code"], 7, host)
    assert host_view.current_user_role == "host"
    assert host_view.starts_at == first_start


def test_pk_room_countdown_and_scoring_are_isolated_per_room(client: TestClient):
    saved = client.put("/api/arena/admin/games/7", json=config_payload()).json()
    challenge_id = saved["challenges"][0]["id"]
    alice = use_identity(client, "user-1", "Alice")

    room_a = client.post("/api/arena/pk/rooms", json={"gameId": 7}).json()
    room_b = client.post("/api/arena/pk/rooms", json={"gameId": 7}).json()
    use_identity(client, "user-2", "Bob")
    for room in (room_a, room_b):
        response = client.post(
            f"/api/arena/pk/rooms/{room['code']}/join", json={"gameId": 7}
        )
        assert response.status_code == 200

    use_identity(client, alice.user_id, alice.user_name)
    too_early = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
            "roomCode": room_a["code"],
        },
    )
    assert too_early.status_code == 409
    assert 1 <= int(too_early.headers["Retry-After"]) <= 5

    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    database = client.database  # type: ignore[attr-defined]
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE pk_rooms SET starts_at = ? WHERE code IN (?, ?)",
            (past, room_a["code"], room_b["code"]),
        )

    solve_a = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
            "roomCode": room_a["code"],
        },
    )
    assert solve_a.status_code == 200, solve_a.text
    assert solve_a.json()["correct"] is True
    assert solve_a.json()["firstBlood"] is True
    assert solve_a.json()["score"] == 600
    assert solve_a.json()["roomCode"] == room_a["code"]

    state_a = client.get(
        f"/api/arena/pk/state?gameId=7&roomCode={room_a['code']}"
    ).json()
    state_b = client.get(
        f"/api/arena/pk/state?gameId=7&roomCode={room_b['code']}"
    ).json()
    legacy_state = client.get("/api/arena/pk/state?gameId=7").json()
    assert state_a["score"] == 600
    assert state_a["solvedChallengeIds"] == [challenge_id]
    assert state_b["score"] == 0
    assert state_b["solvedChallengeIds"] == []
    assert legacy_state["score"] == 0

    solve_b = client.post(
        "/api/arena/pk/submit",
        json={
            "gameId": 7,
            "challengeId": challenge_id,
            "flag": "flag{voxel_arena}",
            "roomCode": room_b["code"],
        },
    )
    assert solve_b.status_code == 200
    assert solve_b.json()["firstBlood"] is True
    assert solve_b.json()["score"] == 600


def test_one_way_config_is_redacted_and_omitted_write_preserves_it(
    client: TestClient,
):
    saved, _flags = create_one_way_game(client, round_count=2)
    public = client.get("/api/arena/public/active")
    assert public.status_code == 200, public.text
    public_body = public.json()
    assert public_body["mode"] == "one_way_onebyone"
    assert public_body["challenges"] == []
    assert public_body["oneWayConfig"]["directions"] == [
        {
            "id": "web",
            "name": "Web 安全",
            "description": "单方向 Web 对决",
        }
    ]
    assert "challengeIds" not in public_body["oneWayConfig"]["directions"][0]

    legacy_write = admin_view_to_write(saved)
    legacy_write.pop("oneWayConfig")
    updated = client.put("/api/arena/admin/games/7", json=legacy_write)
    assert updated.status_code == 200, updated.text
    assert updated.json()["oneWayConfig"] == saved["oneWayConfig"]


@pytest.mark.parametrize(
    ("arena_mode", "runtime_mode"),
    [
        ("solo_pk", "pk"),
        ("boss_raid", "boss"),
        ("hybrid", "pk"),
    ],
)
def test_pure_one_way_questions_never_leak_through_other_public_modes(
    client: TestClient,
    arena_mode: str,
    runtime_mode: str,
):
    pure_title = "绝密单向题"
    pure_description = "跨模式绝不能提前下发的完整题面"
    pure_target = "http://secret-one-way.internal"
    pure_attachment = "/attachments/secret-one-way.zip"
    mixed = {
        "title": "当前模式可用混合题",
        "category": "Web",
        "difficulty": "normal",
        "description": "同时参与当前运行模式",
        "status": "active",
        "enabled": True,
        "sortOrder": 2,
        "modes": [runtime_mode, "one_way"],
        "flag": "flag{mixed_visible}",
    }
    if runtime_mode == "pk":
        mixed["pk"] = {"baseScore": 500}
    else:
        mixed["boss"] = {"baseDamage": 1000, "phase": 1}
    saved = client.put(
        "/api/arena/admin/games/7",
        json={
            "gameId": 7,
            "enabled": True,
            "published": True,
            "mode": arena_mode,
            "revision": 0,
            "challenges": [
                {
                    "title": pure_title,
                    "category": "Reverse",
                    "difficulty": "hard",
                    "description": pure_description,
                    "target": pure_target,
                    "attachmentUrl": pure_attachment,
                    "status": "active",
                    "enabled": True,
                    "sortOrder": 1,
                    "modes": ["one_way"],
                    "flag": "flag{pure_secret}",
                },
                mixed,
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    pure_id = next(
        item["id"] for item in saved.json()["challenges"] if item["title"] == pure_title
    )

    public = client.get("/api/arena/public/active")
    assert public.status_code == 200, public.text
    public_challenges = public.json()["challenges"]
    assert {item["title"] for item in public_challenges} == {mixed["title"]}
    assert pure_id not in {item["id"] for item in public_challenges}
    serialized = json.dumps(public_challenges, ensure_ascii=False)
    for secret in (pure_title, pure_description, pure_target, pure_attachment):
        assert secret not in serialized


def test_one_way_publish_requires_enough_playable_questions(
    client: TestClient,
):
    challenges = [
        {
            "title": "混用题",
            "category": "Web",
            "difficulty": "normal",
            "description": "混合用途题也可进入方向池",
            "status": "active",
            "enabled": True,
            "sortOrder": 1,
            "modes": ["pk", "one_way"],
            "pk": {"baseScore": 500},
            "flag": "flag{mixed}",
        }
    ]
    draft = client.put(
        "/api/arena/admin/games/7",
        json={
            "gameId": 7,
            "enabled": True,
            "published": False,
            "mode": "one_way_onebyone",
            "revision": 0,
            "challenges": challenges,
        },
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    payload = admin_view_to_write(body)
    payload["published"] = True
    payload["oneWayConfig"] = {
        "countdownSeconds": 2,
        "roundCount": 2,
        "roundSeconds": 30,
        "intervalSeconds": 3,
        "directions": [
            {
                "id": "web",
                "name": "Web",
                "challengeIds": [body["challenges"][0]["id"]],
            }
        ],
    }
    rejected = client.put("/api/arena/admin/games/7", json=payload)
    assert rejected.status_code == 422
    assert "至少需要 2 道" in rejected.json()["detail"]
    assert "属于 one_way" in rejected.json()["detail"]


def test_one_way_multi_round_first_solver_and_admin_record_lifecycle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    clock = {"now": datetime(2026, 7, 14, 8, 0, tzinfo=UTC)}
    monkeypatch.setattr(repository, "_now", lambda: clock["now"])
    _saved, flags = create_one_way_game(
        client,
        round_count=3,
        countdown_seconds=2,
        round_seconds=30,
        interval_seconds=3,
    )
    host = use_identity(client, "host", "矿工甲")
    created = client.post(
        "/api/arena/one-way/rooms", json={"gameId": 7, "directionId": "web"}
    )
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    assert created.json()["currentRound"] == 0
    assert all(item["challengeId"] is None for item in created.json()["rounds"])

    guest = use_identity(client, "guest", "矿工乙")
    joined = client.post(f"/api/arena/one-way/rooms/{code}/join", json={"gameId": 7})
    assert joined.status_code == 200, joined.text
    joined_body = joined.json()
    assert joined_body["status"] == "countdown"
    assert joined_body["currentChallengeId"] is None
    assert all(item["challengeId"] is None for item in joined_body["rounds"])

    winners = [guest, host, host]
    result_body: dict | None = None
    next_start = joined_body["startsAt"]
    for round_number, winner in enumerate(winners, 1):
        assert next_start is not None
        clock["now"] = parse_api_time(next_start)
        use_identity(client, winner.user_id, winner.user_name)
        active = client.get(f"/api/arena/one-way/rooms/{code}?gameId=7")
        assert active.status_code == 200, active.text
        active_body = active.json()
        assert active_body["status"] == "active"
        assert active_body["currentRound"] == round_number
        challenge_id = active_body["currentChallengeId"]
        assert challenge_id in flags
        assert active_body["currentChallenge"]["target"].startswith("http://one-way-")
        assert all(
            item["challengeId"] is None
            for item in active_body["rounds"]
            if item["status"] == "pending"
        )

        solved = client.post(
            "/api/arena/one-way/submit",
            json={
                "gameId": 7,
                "roomCode": code,
                "challengeId": challenge_id,
                "flag": flags[challenge_id],
            },
        )
        assert solved.status_code == 200, solved.text
        result_body = solved.json()["room"]
        assert solved.json()["correct"] is True
        assert (
            result_body["rounds"][round_number - 1]["winner"]["userId"]
            == winner.user_id
        )
        if round_number < len(winners):
            assert result_body["status"] == "interval"
            assert result_body["currentChallengeId"] == challenge_id
            next_start = result_body["nextRoundStartsAt"]

    assert result_body is not None
    assert result_body["status"] == "finished"
    assert result_body["winner"]["userId"] == host.user_id
    assert result_body["hostRoundWins"] == 2
    assert result_body["guestRoundWins"] == 1
    assert result_body["isDraw"] is False

    matches = client.get("/api/arena/admin/games/7/one-way-matches")
    assert matches.status_code == 200, matches.text
    record = matches.json()[0]
    assert record["status"] == "finished"
    assert record["finishReason"] == "completed"
    assert record["roomExists"] is True
    assert record["winner"]["userId"] == host.user_id
    assert len(record["rounds"]) == 3
    match_id = record["matchId"]

    still_live = client.delete(f"/api/arena/admin/games/7/one-way-matches/{match_id}")
    assert still_live.status_code == 409
    deleted_room = client.delete(
        f"/api/arena/admin/games/7/one-way-matches/{match_id}/room"
    )
    assert deleted_room.status_code == 204
    retained = client.get("/api/arena/admin/games/7/one-way-matches").json()[0]
    assert retained["roomExists"] is False
    deleted_record = client.delete(
        f"/api/arena/admin/games/7/one-way-matches/{match_id}"
    )
    assert deleted_record.status_code == 204
    assert client.get("/api/arena/admin/games/7/one-way-matches").json() == []


def test_one_way_concurrent_correct_submissions_have_exactly_one_winner(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    clock = {"now": datetime(2026, 7, 14, 9, 0, tzinfo=UTC)}
    monkeypatch.setattr(repository, "_now", lambda: clock["now"])
    _saved, flags = create_one_way_game(client, round_count=1)
    host = use_identity(client, "host", "Host")
    room = client.post(
        "/api/arena/one-way/rooms", json={"gameId": 7, "directionId": "web"}
    ).json()
    guest = use_identity(client, "guest", "Guest")
    joined = client.post(
        f"/api/arena/one-way/rooms/{room['code']}/join", json={"gameId": 7}
    ).json()
    clock["now"] = parse_api_time(joined["startsAt"])
    active = client.get(f"/api/arena/one-way/rooms/{room['code']}?gameId=7").json()
    challenge_id = active["currentChallengeId"]
    barrier = Barrier(2)
    database = client.database  # type: ignore[attr-defined]

    def solve(identity: UserIdentity):
        barrier.wait()
        return submit_one_way(
            database,
            7,
            room["code"],
            challenge_id,
            flags[challenge_id],
            identity,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(solve, [host, guest]))

    assert sum(result.correct for result in results) == 1
    assert sum(result.already_resolved for result in results) == 1
    winner_ids = {
        result.room.winner.user_id
        for result in results
        if result.room.winner is not None
    }
    assert len(winner_ids) == 1
    with database.connection() as connection:
        correct_count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM one_way_submissions
            WHERE room_code = ? AND round_number = 1 AND correct = 1
            """,
            (room["code"],),
        ).fetchone()["count"]
    assert correct_count == 1


def test_one_way_timeout_catches_up_all_rounds_as_draws(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    clock = {"now": datetime(2026, 7, 14, 10, 0, tzinfo=UTC)}
    monkeypatch.setattr(repository, "_now", lambda: clock["now"])
    create_one_way_game(
        client,
        round_count=2,
        countdown_seconds=2,
        round_seconds=10,
        interval_seconds=2,
    )
    use_identity(client, "host", "Host")
    room = client.post(
        "/api/arena/one-way/rooms", json={"gameId": 7, "directionId": "web"}
    ).json()
    use_identity(client, "guest", "Guest")
    joined = client.post(
        f"/api/arena/one-way/rooms/{room['code']}/join", json={"gameId": 7}
    ).json()
    clock["now"] = parse_api_time(joined["startsAt"]) + timedelta(seconds=23)
    finished = client.get(f"/api/arena/one-way/rooms/{room['code']}?gameId=7")
    assert finished.status_code == 200, finished.text
    body = finished.json()
    assert body["status"] == "finished"
    assert body["winner"] is None
    assert body["isDraw"] is True
    assert body["hostRoundWins"] == body["guestRoundWins"] == 0
    assert all(item["status"] == "finished" for item in body["rounds"])
    assert all(item["isDraw"] is True for item in body["rounds"])
    record = client.get("/api/arena/admin/games/7/one-way-matches").json()[0]
    assert record["roundDraws"] == 2
    assert record["finishReason"] == "completed"


def test_reset_without_modes_resets_one_way_runtime_too(client: TestClient):
    create_one_way_game(client, round_count=1)
    use_identity(client, "host", "Host")
    room = client.post(
        "/api/arena/one-way/rooms", json={"gameId": 7, "directionId": "web"}
    )
    assert room.status_code == 201, room.text
    code = room.json()["code"]

    reset = client.post("/api/arena/admin/games/7/reset", json={})
    assert reset.status_code == 204, reset.text
    assert client.get(f"/api/arena/one-way/rooms/{code}?gameId=7").status_code == 404
    history = client.get("/api/arena/admin/games/7/one-way-matches")
    assert history.status_code == 200, history.text
    assert history.json()[0]["status"] == "reset"
    assert history.json()[0]["finishReason"] == "admin_reset"
    assert history.json()[0]["roomExists"] is False


def test_one_way_room_uses_frozen_question_and_flag_after_admin_deletes_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    clock = {"now": datetime(2026, 7, 14, 11, 0, tzinfo=UTC)}
    monkeypatch.setattr(repository, "_now", lambda: clock["now"])
    saved, flags = create_one_way_game(client, round_count=1)
    host = use_identity(client, "host", "Host")
    room = client.post(
        "/api/arena/one-way/rooms", json={"gameId": 7, "directionId": "web"}
    ).json()
    with client.database.connection() as connection:  # type: ignore[attr-defined]
        frozen_id = connection.execute(
            "SELECT challenge_id FROM one_way_rounds WHERE room_code = ?",
            (room["code"],),
        ).fetchone()["challenge_id"]

    use_identity(client, host.user_id, host.user_name)
    delete_sources = admin_view_to_write(saved)
    delete_sources["enabled"] = True
    delete_sources["published"] = False
    delete_sources["mode"] = "boss_raid"
    delete_sources["oneWayConfig"] = {
        "countdownSeconds": 2,
        "roundCount": 1,
        "roundSeconds": 30,
        "intervalSeconds": 3,
        "directions": [],
    }
    delete_sources["challenges"] = []
    removed = client.put("/api/arena/admin/games/7", json=delete_sources)
    assert removed.status_code == 200, removed.text
    assert removed.json()["challenges"] == []

    use_identity(client, "guest", "Guest")
    joined = client.post(f"/api/arena/one-way/rooms/{room['code']}/join")
    assert joined.status_code == 200, joined.text
    assert joined.json()["gameId"] == 7
    assert joined.json()["status"] == "countdown"
    clock["now"] = parse_api_time(joined.json()["startsAt"])
    active = client.get(f"/api/arena/one-way/rooms/{room['code']}?gameId=7")
    assert active.status_code == 200, active.text
    assert active.json()["currentChallengeId"] == frozen_id
    assert active.json()["currentChallenge"]["description"].startswith("仅在第")
    solved = client.post(
        "/api/arena/one-way/submit",
        json={
            "gameId": 7,
            "roomCode": room["code"],
            "challengeId": frozen_id,
            "flag": flags[frozen_id],
        },
    )
    assert solved.status_code == 200, solved.text
    assert solved.json()["correct"] is True
    assert solved.json()["room"]["status"] == "finished"


def test_v3_database_additively_migrates_one_way_schema_and_default_config(
    tmp_path: Path,
):
    database = Database(tmp_path / "arena-v3.db")
    database.initialize()
    timestamp = datetime.now(UTC).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO arena_games(
                game_id, enabled, published, mode, pk_config_json, boss_config_json,
                revision, created_at, updated_at
            ) VALUES (42, 0, 0, 'hybrid', '{}', '{}', 9, ?, ?)
            """,
            (timestamp, timestamp),
        )
        challenge_id = connection.execute(
            """
            INSERT INTO arena_challenges(
                game_id, title, category, difficulty, description,
                status, enabled, sort_order, modes_json, pk_json, boss_json,
                flag_hash, flag_case_sensitive, created_at, updated_at
            ) VALUES (
                42, 'v3 sentinel', 'Misc', 'normal', 'preserve me',
                'active', 1, 7, '["pk","boss"]', '{}', '{}',
                'sentinel-hash', 1, ?, ?
            )
            """,
            (timestamp, timestamp),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO pk_players(
                game_id, user_id, user_name, score, solves, streak,
                last_submission_at, updated_at
            ) VALUES (42, 'global-user', 'Global User', 321, 2, 1, ?, ?)
            """,
            (timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO pk_rooms(
                code, game_id, host_user_id, host_user_name, created_at, updated_at
            ) VALUES ('420042', 42, 'host-v3', 'Host V3', ?, ?)
            """,
            (timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO pk_room_players(
                room_code, user_id, user_name, score, solves, streak,
                last_submission_at, updated_at
            ) VALUES ('420042', 'host-v3', 'Host V3', 777, 3, 2, ?, ?)
            """,
            (timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO pk_room_submissions(
                room_code, user_id, user_name, challenge_id,
                correct, points, submitted_at
            ) VALUES ('420042', 'host-v3', 'Host V3', ?, 1, 555, ?)
            """,
            (challenge_id, timestamp),
        )
        connection.execute(
            """
            INSERT INTO pk_match_audits(
                game_id, room_code, host_user_id, host_user_name, status,
                host_score, host_solves, created_at, updated_at
            ) VALUES (
                42, '420042', 'host-v3', 'Host V3', 'waiting',
                777, 3, ?, ?
            )
            """,
            (timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO boss_states(
                game_id, hp, max_hp, phase, shield_active, status,
                version, started_at, defeated_at
            ) VALUES (42, 4321, 10000, 2, 0, 'active', 7, ?, NULL)
            """,
            (timestamp,),
        )
        connection.execute(
            """
            INSERT INTO boss_contributions(
                game_id, user_id, user_name, contribution, solves, updated_at
            ) VALUES (42, 'boss-user', 'Boss User', 2468, 4, ?)
            """,
            (timestamp,),
        )
        connection.execute(
            """
            INSERT INTO arena_submissions(
                mode, game_id, user_id, user_name, challenge_id,
                correct, points, submitted_at
            ) VALUES ('boss', 42, 'boss-user', 'Boss User', ?, 1, 1357, ?)
            """,
            (challenge_id, timestamp),
        )
        connection.execute("DROP TABLE one_way_submissions")
        connection.execute("DROP TABLE one_way_rounds")
        connection.execute("DROP TABLE one_way_rooms")
        connection.execute("DROP TABLE one_way_match_audits")
        connection.execute("ALTER TABLE arena_games DROP COLUMN one_way_config_json")
        connection.execute("UPDATE schema_info SET version = 3")

    database.initialize()

    with database.connection() as connection:
        assert (
            connection.execute("SELECT version FROM schema_info").fetchone()["version"]
            == 4
        )
        row = connection.execute(
            "SELECT * FROM arena_games WHERE game_id = 42"
        ).fetchone()
        assert row["revision"] == 9
        assert json.loads(row["one_way_config_json"])["directions"] == []
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM arena_challenges WHERE game_id = 42"
            ).fetchone()["count"]
            == 1
        )
        pk_room = connection.execute(
            "SELECT * FROM pk_rooms WHERE code = '420042'"
        ).fetchone()
        assert pk_room["host_user_id"] == "host-v3"
        assert pk_room["game_id"] == 42
        room_player = connection.execute(
            "SELECT * FROM pk_room_players WHERE room_code = '420042'"
        ).fetchone()
        assert (room_player["score"], room_player["solves"], room_player["streak"]) == (
            777,
            3,
            2,
        )
        room_submission = connection.execute(
            "SELECT * FROM pk_room_submissions WHERE room_code = '420042'"
        ).fetchone()
        assert (room_submission["correct"], room_submission["points"]) == (1, 555)
        audit = connection.execute(
            "SELECT * FROM pk_match_audits WHERE room_code = '420042'"
        ).fetchone()
        assert (audit["status"], audit["host_score"], audit["host_solves"]) == (
            "waiting",
            777,
            3,
        )
        global_player = connection.execute(
            "SELECT * FROM pk_players WHERE game_id = 42 AND user_id = 'global-user'"
        ).fetchone()
        assert (global_player["score"], global_player["solves"]) == (321, 2)
        boss_state = connection.execute(
            "SELECT * FROM boss_states WHERE game_id = 42"
        ).fetchone()
        assert (
            boss_state["hp"],
            boss_state["phase"],
            boss_state["version"],
        ) == (4321, 2, 7)
        boss_contribution = connection.execute(
            "SELECT * FROM boss_contributions WHERE game_id = 42"
        ).fetchone()
        assert (
            boss_contribution["contribution"],
            boss_contribution["solves"],
        ) == (2468, 4)
        boss_submission = connection.execute(
            """
            SELECT * FROM arena_submissions
            WHERE game_id = 42 AND mode = 'boss'
            """
        ).fetchone()
        assert (boss_submission["correct"], boss_submission["points"]) == (1, 1357)
        tables = {
            item["name"]
            for item in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "one_way_match_audits",
            "one_way_rooms",
            "one_way_rounds",
            "one_way_submissions",
        }.issubset(tables)
