from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import settings
from .database import Database
from .models import (
    ArenaAdminView,
    ArenaConfigWrite,
    ArenaMode,
    ArenaPublicView,
    BossChallengeConfig,
    BossConfig,
    BossPublicState,
    BossStateView,
    BossSubmitResponse,
    ChallengeAdminView,
    ChallengeMode,
    ChallengePublicView,
    LeaderboardEntry,
    OneWayConfig,
    OneWayDirectionPublicView,
    OneWayMatchAdminView,
    OneWayMatchFinishReason,
    OneWayMatchRoundAdminView,
    OneWayMatchStatus,
    OneWayPublicConfig,
    OneWayRoomPlayerView,
    OneWayRoomView,
    OneWayRoundStatus,
    OneWayRoundView,
    OneWaySubmitResponse,
    PkChallengeConfig,
    PkConfig,
    PkMatchAdminPlayerView,
    PkMatchAdminView,
    PkMatchFinishReason,
    PkMatchStatus,
    PkRoomPlayerView,
    PkRoomView,
    PkStateView,
    PkSubmitResponse,
    ScoreMode,
    RuntimeMode,
    UserIdentity,
    WinRule,
)
from .security import hash_secret, verify_secret


class ArenaRepositoryError(Exception):
    def __init__(
        self, status_code: int, detail: str, headers: dict[str, str] | None = None
    ):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}


PK_ROOM_START_DELAY_SECONDS = 5


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _json_model(model: Any) -> str:
    return model.model_dump_json(by_alias=True)


def _mode_allows(mode: str, challenge_mode: ChallengeMode) -> bool:
    if mode == ArenaMode.HYBRID.value:
        return challenge_mode in {ChallengeMode.PK, ChallengeMode.BOSS}
    if challenge_mode == ChallengeMode.PK:
        return mode == ArenaMode.SOLO_PK.value
    if challenge_mode == ChallengeMode.BOSS:
        return mode == ArenaMode.BOSS_RAID.value
    return mode == ArenaMode.ONE_WAY_ONEBYONE.value


def _challenge_admin_from_row(row: sqlite3.Row) -> ChallengeAdminView:
    return ChallengeAdminView(
        id=row["id"],
        source_challenge_id=row["source_challenge_id"],
        title=row["title"],
        category=row["category"],
        difficulty=row["difficulty"],
        description=row["description"],
        target=row["target"],
        attachment_url=row["attachment_url"],
        status=row["status"],
        enabled=bool(row["enabled"]),
        sort_order=row["sort_order"],
        modes=json.loads(row["modes_json"]),
        pk=PkChallengeConfig.model_validate_json(row["pk_json"])
        if row["pk_json"]
        else None,
        boss=(
            BossChallengeConfig.model_validate_json(row["boss_json"])
            if row["boss_json"]
            else None
        ),
        flag_case_sensitive=bool(row["flag_case_sensitive"]),
        has_flag=bool(row["flag_hash"]),
    )


def _default_admin_view(game_id: int) -> ArenaAdminView:
    return ArenaAdminView(
        game_id=game_id,
        exists=False,
        enabled=False,
        published=False,
        mode=ArenaMode.HYBRID,
        pk_config=PkConfig(),
        boss_config=BossConfig(),
        one_way_config=OneWayConfig(),
        challenges=[],
        revision=0,
        updated_at=None,
    )


def get_admin_config(database: Database, game_id: int) -> ArenaAdminView:
    with database.connection() as connection:
        game = connection.execute(
            "SELECT * FROM arena_games WHERE game_id = ?", (game_id,)
        ).fetchone()
        if game is None:
            return _default_admin_view(game_id)
        challenges = connection.execute(
            "SELECT * FROM arena_challenges WHERE game_id = ? ORDER BY sort_order, id",
            (game_id,),
        ).fetchall()
    return ArenaAdminView(
        game_id=game_id,
        exists=True,
        enabled=bool(game["enabled"]),
        published=bool(game["published"]),
        mode=game["mode"],
        pk_config=PkConfig.model_validate_json(game["pk_config_json"]),
        boss_config=BossConfig.model_validate_json(game["boss_config_json"]),
        one_way_config=OneWayConfig.model_validate_json(game["one_way_config_json"]),
        challenges=[_challenge_admin_from_row(row) for row in challenges],
        revision=game["revision"],
        updated_at=_parse_time(game["updated_at"]),
    )


def save_admin_config(
    database: Database, game_id: int, payload: ArenaConfigWrite
) -> ArenaAdminView:
    if payload.game_id is not None and payload.game_id != game_id:
        raise ArenaRepositoryError(400, "URL 中的 gameId 与请求体不一致")
    timestamp = _iso()
    with database.transaction(immediate=True) as connection:
        current = connection.execute(
            "SELECT revision, boss_config_json, one_way_config_json "
            "FROM arena_games WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        previous_boss_config_json = (
            current["boss_config_json"] if current is not None else None
        )
        one_way_config = (
            payload.one_way_config
            if payload.one_way_config is not None
            else OneWayConfig.model_validate_json(current["one_way_config_json"])
            if current is not None
            else OneWayConfig()
        )
        if current is None:
            if payload.revision not in {None, 0}:
                raise ArenaRepositoryError(409, "配置不存在，revision 必须为 0 或省略")
            revision = 1
            connection.execute(
                """
                INSERT INTO arena_games(
                    game_id, enabled, published, mode, pk_config_json, boss_config_json,
                    one_way_config_json, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    int(payload.enabled),
                    int(payload.published),
                    payload.mode.value,
                    _json_model(payload.pk_config),
                    _json_model(payload.boss_config),
                    _json_model(one_way_config),
                    revision,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            current_revision = int(current["revision"])
            if payload.revision is not None and payload.revision != current_revision:
                raise ArenaRepositoryError(
                    409,
                    f"配置已被其他管理员更新（当前 revision={current_revision}）",
                )
            revision = current_revision + 1
            connection.execute(
                """
                UPDATE arena_games
                SET enabled = ?, published = ?, mode = ?, pk_config_json = ?,
                    boss_config_json = ?, one_way_config_json = ?, revision = ?, updated_at = ?
                WHERE game_id = ?
                """,
                (
                    int(payload.enabled),
                    int(payload.published),
                    payload.mode.value,
                    _json_model(payload.pk_config),
                    _json_model(payload.boss_config),
                    _json_model(one_way_config),
                    revision,
                    timestamp,
                    game_id,
                ),
            )

        existing_rows = connection.execute(
            "SELECT id, flag_hash, flag_case_sensitive FROM arena_challenges WHERE game_id = ?",
            (game_id,),
        ).fetchall()
        existing = {int(row["id"]): row for row in existing_rows}
        retained_ids: list[int] = []
        request_ids = [item.id for item in payload.challenges if item.id is not None]
        if len(request_ids) != len(set(request_ids)):
            raise ArenaRepositoryError(422, "challenges 中存在重复 id")

        requires_playable_pk_challenge = (
            payload.enabled
            and payload.published
            and payload.mode in {ArenaMode.SOLO_PK, ArenaMode.HYBRID}
        )
        requires_playable_one_way_directions = (
            payload.enabled
            and payload.published
            and payload.mode == ArenaMode.ONE_WAY_ONEBYONE
        )
        has_playable_pk_challenge = False

        for challenge in payload.challenges:
            stored = existing.get(challenge.id) if challenge.id is not None else None
            if challenge.id is not None and stored is None:
                raise ArenaRepositoryError(422, f"题目 {challenge.id} 不属于当前赛事")
            if (
                stored is not None
                and bool(stored["flag_case_sensitive"]) != challenge.flag_case_sensitive
                and challenge.flag is None
                and stored["flag_hash"]
            ):
                raise ArenaRepositoryError(
                    422, f"题目 {challenge.id} 修改大小写规则时必须重新填写 flag"
                )

            if challenge.clear_flag:
                flag_hash = None
            elif challenge.flag is not None:
                normalized_flag = (
                    challenge.flag
                    if challenge.flag_case_sensitive
                    else challenge.flag.casefold()
                )
                flag_hash = hash_secret(normalized_flag, pepper=settings.flag_pepper)
            else:
                flag_hash = stored["flag_hash"] if stored is not None else None

            if (
                challenge.enabled
                and ChallengeMode.PK in challenge.modes
                and challenge.status.lower() in {"active", "open"}
                and bool(flag_hash)
            ):
                has_playable_pk_challenge = True

            values = (
                challenge.source_challenge_id,
                challenge.title,
                challenge.category,
                challenge.difficulty,
                challenge.description,
                challenge.target,
                challenge.attachment_url,
                challenge.status,
                int(challenge.enabled),
                challenge.sort_order,
                json.dumps(
                    [mode.value for mode in challenge.modes], separators=(",", ":")
                ),
                _json_model(challenge.pk) if challenge.pk is not None else None,
                _json_model(challenge.boss) if challenge.boss is not None else None,
                flag_hash,
                int(challenge.flag_case_sensitive),
                timestamp,
            )
            if stored is None:
                cursor = connection.execute(
                    """
                    INSERT INTO arena_challenges(
                        game_id, source_challenge_id, title, category, difficulty, description,
                        target, attachment_url, status, enabled, sort_order, modes_json, pk_json,
                        boss_json, flag_hash, flag_case_sensitive, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (game_id, *values[:-1], timestamp, timestamp),
                )
                retained_ids.append(int(cursor.lastrowid))
            else:
                connection.execute(
                    """
                    UPDATE arena_challenges
                    SET source_challenge_id = ?, title = ?, category = ?, difficulty = ?,
                        description = ?, target = ?, attachment_url = ?, status = ?, enabled = ?,
                        sort_order = ?, modes_json = ?, pk_json = ?, boss_json = ?, flag_hash = ?,
                        flag_case_sensitive = ?, updated_at = ?
                    WHERE id = ? AND game_id = ?
                    """,
                    (*values, challenge.id, game_id),
                )
                retained_ids.append(challenge.id)

        if requires_playable_pk_challenge and not has_playable_pk_challenge:
            raise ArenaRepositoryError(
                422,
                "启用并发布 PK 竞技场时，至少需要一道已开放且已配置 Flag 的 PK 题目",
            )

        retained_id_set = set(retained_ids)
        configured_one_way_ids = {
            challenge_id
            for direction in one_way_config.directions
            for challenge_id in direction.challenge_ids
        }
        unknown_one_way_ids = configured_one_way_ids - retained_id_set
        if unknown_one_way_ids:
            formatted = ", ".join(str(value) for value in sorted(unknown_one_way_ids))
            raise ArenaRepositoryError(
                422, f"单方向单挑方向题池包含不属于当前赛事的题目：{formatted}"
            )

        if requires_playable_one_way_directions:
            if not one_way_config.directions:
                raise ArenaRepositoryError(
                    422, "发布单方向单挑前至少需要配置一个挑战方向"
                )
            challenge_rows = connection.execute(
                "SELECT id, enabled, status, modes_json, flag_hash "
                "FROM arena_challenges WHERE game_id = ?",
                (game_id,),
            ).fetchall()
            playable_one_way_ids = {
                int(row["id"])
                for row in challenge_rows
                if bool(row["enabled"])
                and row["status"].lower() in {"active", "open"}
                and bool(row["flag_hash"])
                and ChallengeMode.ONE_WAY.value in json.loads(row["modes_json"])
            }
            for direction in one_way_config.directions:
                playable_count = len(
                    playable_one_way_ids.intersection(direction.challenge_ids)
                )
                if playable_count < one_way_config.round_count:
                    raise ArenaRepositoryError(
                        422,
                        f"挑战方向“{direction.name}”至少需要 "
                        f"{one_way_config.round_count} 道已启用、已开放、"
                        "已配置 Flag 且属于 one_way 的唯一题目",
                    )

        if retained_ids:
            placeholders = ",".join("?" for _ in retained_ids)
            connection.execute(
                f"DELETE FROM arena_challenges WHERE game_id = ? AND id NOT IN ({placeholders})",
                (game_id, *retained_ids),
            )
        else:
            connection.execute(
                "DELETE FROM arena_challenges WHERE game_id = ?", (game_id,)
            )

        state = connection.execute(
            "SELECT game_id FROM boss_states WHERE game_id = ?", (game_id,)
        ).fetchone()
        if state is None:
            _insert_boss_state(connection, game_id, payload.boss_config, timestamp)
        elif previous_boss_config_json != _json_model(payload.boss_config):
            contribution = int(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(contribution), 0) AS total
                    FROM boss_contributions WHERE game_id = ?
                    """,
                    (game_id,),
                ).fetchone()["total"]
            )
            # It is safe to rebuild an untouched encounter. Once damage exists, preserving
            # state avoids silently restoring HP; the explicit admin reset endpoint applies
            # new HP/phase/shield settings when the administrator is ready.
            if contribution == 0:
                connection.execute(
                    "DELETE FROM boss_states WHERE game_id = ?", (game_id,)
                )
                _insert_boss_state(connection, game_id, payload.boss_config, timestamp)

    return get_admin_config(database, game_id)


def delete_admin_config(database: Database, game_id: int) -> bool:
    with database.transaction(immediate=True) as connection:
        game = connection.execute(
            "SELECT * FROM arena_games WHERE game_id = ?", (game_id,)
        ).fetchone()
        if game is not None:
            now = _now()
            rooms = connection.execute(
                "SELECT * FROM pk_rooms WHERE game_id = ?", (game_id,)
            ).fetchall()
            for room in rooms:
                audit = _sync_pk_match_audit(connection, room, game, now)
                if audit["status"] in {
                    PkMatchStatus.WAITING.value,
                    PkMatchStatus.COUNTDOWN.value,
                    PkMatchStatus.ACTIVE.value,
                }:
                    _sync_pk_match_audit(
                        connection,
                        room,
                        game,
                        now,
                        forced_status=PkMatchStatus.RESET,
                        finish_reason=PkMatchFinishReason.ADMIN_RESET,
                    )
            one_way_rooms = connection.execute(
                "SELECT * FROM one_way_rooms WHERE game_id = ?", (game_id,)
            ).fetchall()
            for room in one_way_rooms:
                room = _advance_one_way_room(connection, room, now)
                if room["status"] != OneWayMatchStatus.FINISHED.value:
                    _sync_one_way_match_audit(
                        connection,
                        room,
                        now,
                        forced_status=OneWayMatchStatus.RESET,
                        finish_reason=OneWayMatchFinishReason.ADMIN_RESET,
                    )
        result = connection.execute(
            "DELETE FROM arena_games WHERE game_id = ?", (game_id,)
        )
        return result.rowcount > 0


def _insert_boss_state(
    connection: sqlite3.Connection,
    game_id: int,
    config: BossConfig,
    timestamp: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO boss_states(
            game_id, hp, max_hp, phase, shield_active, status, version, started_at, defeated_at
        ) VALUES (?, ?, ?, 1, ?, 'active', 1, ?, NULL)
        """,
        (
            game_id,
            config.max_hp,
            config.max_hp,
            int(config.shield_enabled),
            timestamp or _iso(),
        ),
    )


def _boss_state_from_row(row: sqlite3.Row, config: BossConfig) -> BossPublicState:
    started_at = _parse_time(row["started_at"]) or _now()
    return BossPublicState(
        status=row["status"],
        hp=row["hp"],
        max_hp=row["max_hp"],
        phase=row["phase"],
        shield_active=bool(row["shield_active"]),
        enraged=(
            row["status"] == "active"
            and _now() >= started_at + timedelta(seconds=config.enrage_seconds)
        ),
        version=row["version"],
        started_at=started_at,
        defeated_at=_parse_time(row["defeated_at"]),
    )


def _ensure_boss_state(
    connection: sqlite3.Connection, game_id: int, config: BossConfig
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM boss_states WHERE game_id = ?", (game_id,)
    ).fetchone()
    if row is None:
        _insert_boss_state(connection, game_id, config)
        row = connection.execute(
            "SELECT * FROM boss_states WHERE game_id = ?", (game_id,)
        ).fetchone()
    assert row is not None
    return row


def _load_public_game(
    connection: sqlite3.Connection, game_id: int | None
) -> sqlite3.Row | None:
    if game_id is not None:
        return connection.execute(
            """
            SELECT * FROM arena_games
            WHERE game_id = ? AND enabled = 1 AND published = 1
            """,
            (game_id,),
        ).fetchone()
    return connection.execute(
        """
        SELECT * FROM arena_games
        WHERE enabled = 1 AND published = 1
        ORDER BY updated_at DESC, game_id DESC
        LIMIT 1
        """
    ).fetchone()


def get_public_config(
    database: Database, game_id: int | None = None
) -> ArenaPublicView:
    with database.transaction(immediate=True) as connection:
        game = _load_public_game(connection, game_id)
        if game is None:
            raise ArenaRepositoryError(404, "暂无已发布的方块竞技场")
        actual_game_id = int(game["game_id"])
        boss_config = BossConfig.model_validate_json(game["boss_config_json"])
        one_way_config = OneWayConfig.model_validate_json(game["one_way_config_json"])
        boss_row = _ensure_boss_state(connection, actual_game_id, boss_config)
        rows = connection.execute(
            """
            SELECT * FROM arena_challenges
            WHERE game_id = ? AND enabled = 1
            ORDER BY sort_order, id
            """,
            (actual_game_id,),
        ).fetchall()
        boss_state = _boss_state_from_row(boss_row, boss_config)

    challenges: list[ChallengePublicView] = []
    for row in rows:
        modes = [ChallengeMode(value) for value in json.loads(row["modes_json"])]
        # One-way questions are intentionally absent from the public arena payload.
        # Their frozen content is revealed only to the two room members while that
        # round is active (and during its result interval).
        if ChallengeMode.ONE_WAY in modes:
            arena_mode = ArenaMode(game["mode"])
            if arena_mode == ArenaMode.ONE_WAY_ONEBYONE:
                continue
            allowed_runtime_modes: set[ChallengeMode]
            if arena_mode == ArenaMode.SOLO_PK:
                allowed_runtime_modes = {ChallengeMode.PK}
            elif arena_mode == ArenaMode.BOSS_RAID:
                allowed_runtime_modes = {ChallengeMode.BOSS}
            elif arena_mode == ArenaMode.HYBRID:
                allowed_runtime_modes = {ChallengeMode.PK, ChallengeMode.BOSS}
            else:
                allowed_runtime_modes = set()
            if not allowed_runtime_modes.intersection(modes):
                continue
        boss = (
            BossChallengeConfig.model_validate_json(row["boss_json"])
            if row["boss_json"]
            else None
        )
        locked = row["status"].lower() not in {"active", "open"}
        if (
            boss is not None
            and ChallengeMode.BOSS in modes
            and boss.phase > boss_state.phase
        ):
            locked = True
        challenges.append(
            ChallengePublicView(
                id=row["id"],
                source_challenge_id=row["source_challenge_id"],
                title=row["title"],
                category=row["category"],
                difficulty=row["difficulty"],
                description=row["description"],
                target=row["target"],
                attachment_url=row["attachment_url"],
                status=row["status"],
                enabled=True,
                sort_order=row["sort_order"],
                modes=modes,
                pk=PkChallengeConfig.model_validate_json(row["pk_json"])
                if row["pk_json"]
                else None,
                boss=boss,
                flag_case_sensitive=bool(row["flag_case_sensitive"]),
                locked=locked,
                solved=False,
            )
        )
    return ArenaPublicView(
        game_id=actual_game_id,
        enabled=True,
        published=True,
        mode=game["mode"],
        pk_config=PkConfig.model_validate_json(game["pk_config_json"]),
        boss_config=boss_config,
        one_way_config=OneWayPublicConfig(
            countdown_seconds=one_way_config.countdown_seconds,
            round_count=one_way_config.round_count,
            round_seconds=one_way_config.round_seconds,
            interval_seconds=one_way_config.interval_seconds,
            directions=[
                OneWayDirectionPublicView(
                    id=direction.id,
                    name=direction.name,
                    description=direction.description,
                )
                for direction in one_way_config.directions
            ],
        ),
        challenges=challenges,
        revision=game["revision"],
        updated_at=_parse_time(game["updated_at"]) or _now(),
        boss_state=boss_state,
    )


def _load_runtime_context(
    connection: sqlite3.Connection,
    game_id: int,
    challenge_id: int,
    required_mode: ChallengeMode,
) -> tuple[sqlite3.Row, sqlite3.Row]:
    game = connection.execute(
        """
        SELECT * FROM arena_games
        WHERE game_id = ? AND enabled = 1 AND published = 1
        """,
        (game_id,),
    ).fetchone()
    if game is None:
        raise ArenaRepositoryError(404, "竞技场不存在、未启用或尚未发布")
    if not _mode_allows(game["mode"], required_mode):
        raise ArenaRepositoryError(409, f"当前赛事未开启 {required_mode.value} 模式")
    challenge = connection.execute(
        """
        SELECT * FROM arena_challenges
        WHERE id = ? AND game_id = ? AND enabled = 1
        """,
        (challenge_id, game_id),
    ).fetchone()
    if challenge is None:
        raise ArenaRepositoryError(404, "题目不存在或未启用")
    modes = json.loads(challenge["modes_json"])
    if required_mode.value not in modes:
        raise ArenaRepositoryError(409, "该题不属于当前模式")
    if challenge["status"].lower() not in {"active", "open"}:
        raise ArenaRepositoryError(423, "题目尚未开放")
    if not challenge["flag_hash"]:
        raise ArenaRepositoryError(409, "管理员尚未为该题配置 Flag")
    return game, challenge


def _flag_is_correct(challenge: sqlite3.Row, submitted_flag: str) -> bool:
    normalized = (
        submitted_flag
        if bool(challenge["flag_case_sensitive"])
        else submitted_flag.casefold()
    )
    return verify_secret(
        normalized, challenge["flag_hash"], pepper=settings.flag_pepper
    )


def _pk_leaderboard(
    connection: sqlite3.Connection, game_id: int
) -> list[LeaderboardEntry]:
    rows = connection.execute(
        """
        SELECT user_id, user_name, score, solves
        FROM pk_players WHERE game_id = ?
        ORDER BY score DESC, solves DESC, updated_at ASC, user_id ASC
        LIMIT 100
        """,
        (game_id,),
    ).fetchall()
    return [
        LeaderboardEntry(
            rank=index,
            user_id=row["user_id"],
            user_name=row["user_name"],
            score=row["score"],
            solves=row["solves"],
            contribution=0,
        )
        for index, row in enumerate(rows, 1)
    ]


def _validate_room_code(room_code: str) -> None:
    if len(room_code) != 6 or any(
        character < "0" or character > "9" for character in room_code
    ):
        raise ArenaRepositoryError(422, "房间号必须是 6 位数字")


def _load_pk_game(connection: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    game = connection.execute(
        """
        SELECT * FROM arena_games
        WHERE game_id = ? AND enabled = 1 AND published = 1
        """,
        (game_id,),
    ).fetchone()
    if game is None:
        raise ArenaRepositoryError(404, "竞技场不存在、未启用或尚未发布")
    if not _mode_allows(game["mode"], ChallengeMode.PK):
        raise ArenaRepositoryError(409, "当前赛事未开启 PK 模式")
    return game


def _load_pk_room(
    connection: sqlite3.Connection,
    room_code: str,
    game_id: int,
) -> sqlite3.Row:
    _validate_room_code(room_code)
    room = connection.execute(
        "SELECT * FROM pk_rooms WHERE code = ?", (room_code,)
    ).fetchone()
    if room is None:
        raise ArenaRepositoryError(404, "PK 房间不存在")
    if int(room["game_id"]) != game_id:
        raise ArenaRepositoryError(409, "房间号不属于当前赛事")
    return room


def _pk_room_role(room: sqlite3.Row, user: UserIdentity) -> str | None:
    if room["host_user_id"] == user.user_id:
        return "host"
    if room["guest_user_id"] == user.user_id:
        return "guest"
    return None


def _require_pk_room_member(room: sqlite3.Row, user: UserIdentity) -> str:
    role = _pk_room_role(room, user)
    if role is None:
        raise ArenaRepositoryError(403, "你不是该 PK 房间的成员")
    return role


def _pk_room_timing(
    room: sqlite3.Row,
    pk_config: PkConfig,
    now: datetime,
) -> tuple[str, datetime | None, datetime | None]:
    starts_at = _parse_time(room["starts_at"])
    if room["guest_user_id"] is None or starts_at is None:
        return "waiting", None, None
    ends_at = starts_at + timedelta(seconds=pk_config.match_seconds)
    if now < starts_at:
        return "countdown", starts_at, ends_at
    if now >= ends_at:
        return "finished", starts_at, ends_at
    return "active", starts_at, ends_at


def _latest_pk_match_audit(
    connection: sqlite3.Connection,
    room_code: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM pk_match_audits
        WHERE room_code = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (room_code,),
    ).fetchone()


def _insert_waiting_pk_match_audit(
    connection: sqlite3.Connection,
    *,
    game_id: int,
    room_code: str,
    host_user_id: str,
    host_user_name: str,
    timestamp: str,
) -> None:
    connection.execute(
        """
        INSERT INTO pk_match_audits(
            game_id, room_code, host_user_id, host_user_name,
            guest_user_id, guest_user_name, status,
            host_score, host_solves, guest_score, guest_solves,
            created_at, joined_at, starts_at, ends_at, finished_at,
            finish_reason, winner_user_id, winner_user_name, is_draw, updated_at
        ) VALUES (?, ?, ?, ?, NULL, NULL, 'waiting', 0, 0, 0, 0,
                  ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, ?)
        """,
        (
            game_id,
            room_code,
            host_user_id,
            host_user_name,
            timestamp,
            timestamp,
        ),
    )


def _pk_match_result(
    room: sqlite3.Row,
    host_score: int,
    host_solves: int,
    guest_score: int,
    guest_solves: int,
    pk_config: PkConfig,
) -> tuple[str | None, str | None, bool]:
    if room["guest_user_id"] is None:
        return None, None, False
    if pk_config.win_rule == WinRule.MOST_SOLVES:
        host_primary = host_solves
        guest_primary = guest_solves
        host_secondary = host_score
        guest_secondary = guest_score
    else:
        host_primary = host_score
        guest_primary = guest_score
        host_secondary = host_solves
        guest_secondary = guest_solves

    if host_primary > guest_primary:
        return room["host_user_id"], room["host_user_name"], False
    if guest_primary > host_primary:
        return room["guest_user_id"], room["guest_user_name"], False
    if not pk_config.allow_draw:
        if host_secondary > guest_secondary:
            return room["host_user_id"], room["host_user_name"], False
        if guest_secondary > host_secondary:
            return room["guest_user_id"], room["guest_user_name"], False
    return None, None, True


def _sync_pk_match_audit(
    connection: sqlite3.Connection,
    room: sqlite3.Row,
    game: sqlite3.Row,
    now: datetime,
    *,
    joined_at: datetime | None = None,
    forced_status: PkMatchStatus | None = None,
    finish_reason: PkMatchFinishReason | None = None,
) -> sqlite3.Row:
    audit = _latest_pk_match_audit(connection, room["code"])
    if audit is None:
        _insert_waiting_pk_match_audit(
            connection,
            game_id=int(room["game_id"]),
            room_code=room["code"],
            host_user_id=room["host_user_id"],
            host_user_name=room["host_user_name"],
            timestamp=room["created_at"],
        )
        audit = _latest_pk_match_audit(connection, room["code"])
    assert audit is not None
    if audit["status"] in {
        PkMatchStatus.FINISHED.value,
        PkMatchStatus.CANCELLED.value,
        PkMatchStatus.RESET.value,
    }:
        return audit

    pk_config = PkConfig.model_validate_json(game["pk_config_json"])
    derived_status, starts_at, ends_at = _pk_room_timing(room, pk_config, now)
    status_value = forced_status.value if forced_status is not None else derived_status
    host = connection.execute(
        """
        SELECT score, solves, user_name FROM pk_room_players
        WHERE room_code = ? AND user_id = ?
        """,
        (room["code"], room["host_user_id"]),
    ).fetchone()
    guest = None
    if room["guest_user_id"] is not None:
        guest = connection.execute(
            """
            SELECT score, solves, user_name FROM pk_room_players
            WHERE room_code = ? AND user_id = ?
            """,
            (room["code"], room["guest_user_id"]),
        ).fetchone()
    host_score = int(host["score"]) if host else 0
    host_solves = int(host["solves"]) if host else 0
    guest_score = int(guest["score"]) if guest else 0
    guest_solves = int(guest["solves"]) if guest else 0

    resolved_joined_at = joined_at or _parse_time(audit["joined_at"])
    if resolved_joined_at is None and starts_at is not None:
        resolved_joined_at = starts_at - timedelta(seconds=PK_ROOM_START_DELAY_SECONDS)

    finished_at: datetime | None = None
    resolved_reason = finish_reason
    winner_id: str | None = None
    winner_name: str | None = None
    is_draw = False
    if status_value == PkMatchStatus.FINISHED.value:
        finished_at = ends_at or now
        resolved_reason = PkMatchFinishReason.TIMEOUT
        winner_id, winner_name, is_draw = _pk_match_result(
            room,
            host_score,
            host_solves,
            guest_score,
            guest_solves,
            pk_config,
        )
    elif status_value == PkMatchStatus.RESET.value:
        finished_at = now
        resolved_reason = PkMatchFinishReason.ADMIN_RESET
        if derived_status == PkMatchStatus.ACTIVE.value:
            winner_id, winner_name, is_draw = _pk_match_result(
                room,
                host_score,
                host_solves,
                guest_score,
                guest_solves,
                pk_config,
            )
    elif status_value == PkMatchStatus.CANCELLED.value:
        finished_at = now
        resolved_reason = resolved_reason or PkMatchFinishReason.PLAYER_LEFT

    host_name = host["user_name"] if host else room["host_user_name"]
    guest_name = guest["user_name"] if guest else room["guest_user_name"]
    joined_at_value = _iso(resolved_joined_at) if resolved_joined_at else None
    starts_at_value = _iso(starts_at) if starts_at else None
    ends_at_value = _iso(ends_at) if ends_at else None
    finished_at_value = _iso(finished_at) if finished_at else None
    finish_reason_value = resolved_reason.value if resolved_reason is not None else None
    desired_state = (
        room["host_user_id"],
        host_name,
        room["guest_user_id"],
        guest_name,
        status_value,
        host_score,
        host_solves,
        guest_score,
        guest_solves,
        joined_at_value,
        starts_at_value,
        ends_at_value,
        finished_at_value,
        finish_reason_value,
        winner_id,
        winner_name,
        int(is_draw),
    )
    current_state = (
        audit["host_user_id"],
        audit["host_user_name"],
        audit["guest_user_id"],
        audit["guest_user_name"],
        audit["status"],
        int(audit["host_score"]),
        int(audit["host_solves"]),
        int(audit["guest_score"]),
        int(audit["guest_solves"]),
        audit["joined_at"],
        audit["starts_at"],
        audit["ends_at"],
        audit["finished_at"],
        audit["finish_reason"],
        audit["winner_user_id"],
        audit["winner_user_name"],
        int(audit["is_draw"]),
    )
    if current_state == desired_state:
        return audit

    timestamp = _iso(now)
    connection.execute(
        """
        UPDATE pk_match_audits
        SET host_user_id = ?, host_user_name = ?,
            guest_user_id = ?, guest_user_name = ?, status = ?,
            host_score = ?, host_solves = ?, guest_score = ?, guest_solves = ?,
            joined_at = ?, starts_at = ?, ends_at = ?, finished_at = ?,
            finish_reason = ?, winner_user_id = ?, winner_user_name = ?,
            is_draw = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            room["host_user_id"],
            host_name,
            room["guest_user_id"],
            guest_name,
            status_value,
            host_score,
            host_solves,
            guest_score,
            guest_solves,
            joined_at_value,
            starts_at_value,
            ends_at_value,
            finished_at_value,
            finish_reason_value,
            winner_id,
            winner_name,
            int(is_draw),
            timestamp,
            int(audit["id"]),
        ),
    )
    updated = connection.execute(
        "SELECT * FROM pk_match_audits WHERE id = ?", (int(audit["id"]),)
    ).fetchone()
    assert updated is not None
    return updated


def _pk_room_player(
    connection: sqlite3.Connection,
    room_code: str,
    user_id: str,
    fallback_name: str,
) -> PkRoomPlayerView:
    player = connection.execute(
        "SELECT * FROM pk_room_players WHERE room_code = ? AND user_id = ?",
        (room_code, user_id),
    ).fetchone()
    return PkRoomPlayerView(
        user_id=user_id,
        user_name=player["user_name"] if player else fallback_name,
        score=int(player["score"]) if player else 0,
        solves=int(player["solves"]) if player else 0,
    )


def _pk_room_view(
    connection: sqlite3.Connection,
    room: sqlite3.Row,
    game: sqlite3.Row,
    user: UserIdentity,
    *,
    now: datetime | None = None,
) -> PkRoomView:
    role = _require_pk_room_member(room, user)
    current_time = now or _now()
    pk_config = PkConfig.model_validate_json(game["pk_config_json"])
    room_status, starts_at, ends_at = _pk_room_timing(room, pk_config, current_time)
    _sync_pk_match_audit(connection, room, game, current_time)
    guest = None
    if room["guest_user_id"] is not None:
        guest = _pk_room_player(
            connection,
            room["code"],
            room["guest_user_id"],
            room["guest_user_name"],
        )
    return PkRoomView(
        code=room["code"],
        game_id=int(room["game_id"]),
        status=room_status,
        host=_pk_room_player(
            connection,
            room["code"],
            room["host_user_id"],
            room["host_user_name"],
        ),
        guest=guest,
        current_user_role=role,
        created_at=_parse_time(room["created_at"]),
        starts_at=starts_at,
        ends_at=ends_at,
        server_time=current_time,
    )


def _random_pk_room_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def create_pk_room(database: Database, game_id: int, user: UserIdentity) -> PkRoomView:
    now = _now()
    timestamp = _iso(now)
    with database.transaction(immediate=True) as connection:
        game = _load_pk_game(connection, game_id)
        room_code = ""
        for _attempt in range(100):
            candidate = _random_pk_room_code()
            exists = connection.execute(
                "SELECT 1 FROM pk_rooms WHERE code = ?", (candidate,)
            ).fetchone()
            if exists is None:
                room_code = candidate
                break
        if not room_code:
            raise ArenaRepositoryError(503, "暂时无法分配 PK 房间号，请稍后重试")
        connection.execute(
            """
            INSERT INTO pk_rooms(
                code, game_id, host_user_id, host_user_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (room_code, game_id, user.user_id, user.user_name, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO pk_room_players(
                room_code, user_id, user_name, score, solves, streak,
                last_submission_at, updated_at
            ) VALUES (?, ?, ?, 0, 0, 0, NULL, ?)
            """,
            (room_code, user.user_id, user.user_name, timestamp),
        )
        _insert_waiting_pk_match_audit(
            connection,
            game_id=game_id,
            room_code=room_code,
            host_user_id=user.user_id,
            host_user_name=user.user_name,
            timestamp=timestamp,
        )
        room = _load_pk_room(connection, room_code, game_id)
        return _pk_room_view(connection, room, game, user, now=now)


def join_pk_room(
    database: Database,
    room_code: str,
    game_id: int,
    user: UserIdentity,
) -> PkRoomView:
    now = _now()
    timestamp = _iso(now)
    with database.transaction(immediate=True) as connection:
        game = _load_pk_game(connection, game_id)
        room = _load_pk_room(connection, room_code, game_id)
        role = _pk_room_role(room, user)
        if role is not None:
            column = "host_user_name" if role == "host" else "guest_user_name"
            connection.execute(
                f"UPDATE pk_rooms SET {column} = ?, updated_at = ? WHERE code = ?",
                (user.user_name, timestamp, room_code),
            )
            connection.execute(
                """
                UPDATE pk_room_players SET user_name = ?, updated_at = ?
                WHERE room_code = ? AND user_id = ?
                """,
                (user.user_name, timestamp, room_code, user.user_id),
            )
            room = _load_pk_room(connection, room_code, game_id)
            return _pk_room_view(connection, room, game, user, now=now)
        if room["guest_user_id"] is not None:
            raise ArenaRepositoryError(409, "PK 房间已满")

        starts_at = now + timedelta(seconds=PK_ROOM_START_DELAY_SECONDS)
        connection.execute(
            """
            UPDATE pk_rooms
            SET guest_user_id = ?, guest_user_name = ?, starts_at = ?, updated_at = ?
            WHERE code = ? AND guest_user_id IS NULL
            """,
            (user.user_id, user.user_name, _iso(starts_at), timestamp, room_code),
        )
        connection.execute(
            """
            INSERT INTO pk_room_players(
                room_code, user_id, user_name, score, solves, streak,
                last_submission_at, updated_at
            ) VALUES (?, ?, ?, 0, 0, 0, NULL, ?)
            """,
            (room_code, user.user_id, user.user_name, timestamp),
        )
        room = _load_pk_room(connection, room_code, game_id)
        return _pk_room_view(connection, room, game, user, now=now)


def get_pk_room(
    database: Database,
    room_code: str,
    game_id: int,
    user: UserIdentity,
) -> PkRoomView:
    now = _now()
    with database.connection() as connection:
        game = _load_pk_game(connection, game_id)
        room = _load_pk_room(connection, room_code, game_id)
        return _pk_room_view(connection, room, game, user, now=now)


def leave_pk_room(
    database: Database,
    room_code: str,
    game_id: int,
    user: UserIdentity,
) -> PkRoomView:
    now = _now()
    timestamp = _iso(now)
    with database.transaction(immediate=True) as connection:
        game = _load_pk_game(connection, game_id)
        room = _load_pk_room(connection, room_code, game_id)
        role = _require_pk_room_member(room, user)
        pk_config = PkConfig.model_validate_json(game["pk_config_json"])
        room_status, _starts_at, _ends_at = _pk_room_timing(room, pk_config, now)
        if room_status in {"active", "finished"}:
            raise ArenaRepositoryError(409, "比赛开始后不能退出房间")
        leaving_view = _pk_room_view(connection, room, game, user, now=now)
        _sync_pk_match_audit(
            connection,
            room,
            game,
            now,
            forced_status=PkMatchStatus.CANCELLED,
            finish_reason=PkMatchFinishReason.PLAYER_LEFT,
        )
        if role == "guest":
            connection.execute(
                "DELETE FROM pk_room_players WHERE room_code = ? AND user_id = ?",
                (room_code, user.user_id),
            )
            connection.execute(
                """
                UPDATE pk_rooms
                SET guest_user_id = NULL, guest_user_name = NULL, starts_at = NULL, updated_at = ?
                WHERE code = ?
                """,
                (timestamp, room_code),
            )
            waiting_room = _load_pk_room(connection, room_code, game_id)
            _insert_waiting_pk_match_audit(
                connection,
                game_id=game_id,
                room_code=room_code,
                host_user_id=waiting_room["host_user_id"],
                host_user_name=waiting_room["host_user_name"],
                timestamp=timestamp,
            )
            return leaving_view
        if room["guest_user_id"] is None:
            connection.execute("DELETE FROM pk_rooms WHERE code = ?", (room_code,))
            return leaving_view

        connection.execute(
            "DELETE FROM pk_room_players WHERE room_code = ? AND user_id = ?",
            (room_code, user.user_id),
        )
        connection.execute(
            """
            UPDATE pk_rooms
            SET host_user_id = guest_user_id, host_user_name = guest_user_name,
                guest_user_id = NULL, guest_user_name = NULL, starts_at = NULL, updated_at = ?
            WHERE code = ?
            """,
            (timestamp, room_code),
        )
        waiting_room = _load_pk_room(connection, room_code, game_id)
        _insert_waiting_pk_match_audit(
            connection,
            game_id=game_id,
            room_code=room_code,
            host_user_id=waiting_room["host_user_id"],
            host_user_name=waiting_room["host_user_name"],
            timestamp=timestamp,
        )
        return leaving_view


def _pk_room_leaderboard(
    connection: sqlite3.Connection,
    room_code: str,
) -> list[LeaderboardEntry]:
    rows = connection.execute(
        """
        SELECT user_id, user_name, score, solves
        FROM pk_room_players WHERE room_code = ?
        ORDER BY score DESC, solves DESC, updated_at ASC, user_id ASC
        """,
        (room_code,),
    ).fetchall()
    return [
        LeaderboardEntry(
            rank=index,
            user_id=row["user_id"],
            user_name=row["user_name"],
            score=row["score"],
            solves=row["solves"],
            contribution=0,
        )
        for index, row in enumerate(rows, 1)
    ]


def _pk_match_admin_from_row(
    row: sqlite3.Row,
    *,
    room_exists: bool = False,
) -> PkMatchAdminView:
    host = PkMatchAdminPlayerView(
        user_id=row["host_user_id"],
        user_name=row["host_user_name"],
        score=int(row["host_score"]),
        solves=int(row["host_solves"]),
    )
    guest = None
    if row["guest_user_id"] is not None:
        guest = PkMatchAdminPlayerView(
            user_id=row["guest_user_id"],
            user_name=row["guest_user_name"],
            score=int(row["guest_score"]),
            solves=int(row["guest_solves"]),
        )
    winner = None
    if row["winner_user_id"] is not None:
        if row["winner_user_id"] == host.user_id:
            winner = host
        elif guest is not None and row["winner_user_id"] == guest.user_id:
            winner = guest
        else:
            winner = PkMatchAdminPlayerView(
                user_id=row["winner_user_id"],
                user_name=row["winner_user_name"],
            )
    return PkMatchAdminView(
        match_id=int(row["id"]),
        game_id=int(row["game_id"]),
        room_code=row["room_code"],
        room_exists=room_exists,
        status=row["status"],
        host=host,
        guest=guest,
        winner=winner,
        is_draw=bool(row["is_draw"]),
        created_at=_parse_time(row["created_at"]),
        joined_at=_parse_time(row["joined_at"]),
        starts_at=_parse_time(row["starts_at"]),
        ends_at=_parse_time(row["ends_at"]),
        finished_at=_parse_time(row["finished_at"]),
        finish_reason=row["finish_reason"],
        updated_at=_parse_time(row["updated_at"]),
    )


def list_pk_matches(
    database: Database,
    game_id: int,
    *,
    match_status: PkMatchStatus | None = None,
    limit: int = 100,
) -> list[PkMatchAdminView]:
    with database.transaction() as connection:
        game = connection.execute(
            "SELECT * FROM arena_games WHERE game_id = ?", (game_id,)
        ).fetchone()
        if game is not None:
            rooms = connection.execute(
                "SELECT * FROM pk_rooms WHERE game_id = ?", (game_id,)
            ).fetchall()
            now = _now()
            for room in rooms:
                _sync_pk_match_audit(connection, room, game, now)

        parameters: list[Any] = [game_id]
        status_filter = ""
        if match_status is not None:
            status_filter = " AND status = ?"
            parameters.append(match_status.value)
        parameters.append(limit)
        rows = connection.execute(
            f"""
            SELECT audit.*,
                   CASE WHEN room.code IS NOT NULL
                             AND audit.id = (
                                 SELECT MAX(latest.id)
                                 FROM pk_match_audits AS latest
                                 WHERE latest.room_code = audit.room_code
                             )
                        THEN 1 ELSE 0 END AS room_exists
            FROM pk_match_audits AS audit
            LEFT JOIN pk_rooms AS room
              ON room.code = audit.room_code AND room.game_id = audit.game_id
            WHERE audit.game_id = ?{status_filter}
            ORDER BY audit.created_at DESC, audit.id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    return [
        _pk_match_admin_from_row(row, room_exists=bool(row["room_exists"]))
        for row in rows
    ]


def delete_pk_match_room(database: Database, game_id: int, match_id: int) -> None:
    """Delete the runtime room represented by the latest audit, retaining history."""
    with database.transaction(immediate=True) as connection:
        audit = connection.execute(
            "SELECT * FROM pk_match_audits WHERE id = ? AND game_id = ?",
            (match_id, game_id),
        ).fetchone()
        if audit is None:
            raise ArenaRepositoryError(404, "PK 对局记录不存在")

        latest = _latest_pk_match_audit(connection, audit["room_code"])
        if latest is None or int(latest["id"]) != match_id:
            raise ArenaRepositoryError(
                409, "该记录不是房间的最新对局，无法删除当前房间"
            )

        room = connection.execute(
            "SELECT * FROM pk_rooms WHERE code = ? AND game_id = ?",
            (audit["room_code"], game_id),
        ).fetchone()
        if room is None:
            raise ArenaRepositoryError(404, "PK 房间不存在")
        game = connection.execute(
            "SELECT * FROM arena_games WHERE game_id = ?", (game_id,)
        ).fetchone()
        if game is None:
            raise ArenaRepositoryError(404, "竞技场配置不存在")

        now = _now()
        synced = _sync_pk_match_audit(connection, room, game, now)
        if synced["status"] in {
            PkMatchStatus.WAITING.value,
            PkMatchStatus.COUNTDOWN.value,
            PkMatchStatus.ACTIVE.value,
        }:
            _sync_pk_match_audit(
                connection,
                room,
                game,
                now,
                forced_status=PkMatchStatus.CANCELLED,
                finish_reason=PkMatchFinishReason.ADMIN_RESET,
            )

        result = connection.execute(
            "DELETE FROM pk_rooms WHERE code = ? AND game_id = ?",
            (audit["room_code"], game_id),
        )
        if result.rowcount != 1:
            raise ArenaRepositoryError(409, "PK 房间已发生变化，请刷新后重试")


def delete_pk_match(database: Database, game_id: int, match_id: int) -> None:
    """Permanently delete an audit only when it is not tied to a live room."""
    with database.transaction(immediate=True) as connection:
        audit = connection.execute(
            "SELECT * FROM pk_match_audits WHERE id = ? AND game_id = ?",
            (match_id, game_id),
        ).fetchone()
        if audit is None:
            raise ArenaRepositoryError(404, "PK 对局记录不存在")

        latest = _latest_pk_match_audit(connection, audit["room_code"])
        room = connection.execute(
            "SELECT 1 FROM pk_rooms WHERE code = ? AND game_id = ?",
            (audit["room_code"], game_id),
        ).fetchone()
        if room is not None and latest is not None and int(latest["id"]) == match_id:
            raise ArenaRepositoryError(409, "请先删除该对局关联的 PK 房间")

        connection.execute(
            "DELETE FROM pk_match_audits WHERE id = ? AND game_id = ?",
            (match_id, game_id),
        )


def _load_one_way_game(connection: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    game = connection.execute(
        """
        SELECT * FROM arena_games
        WHERE game_id = ? AND enabled = 1 AND published = 1
        """,
        (game_id,),
    ).fetchone()
    if game is None:
        raise ArenaRepositoryError(404, "竞技场不存在、未启用或尚未发布")
    if game["mode"] != ArenaMode.ONE_WAY_ONEBYONE.value:
        raise ArenaRepositoryError(409, "当前赛事未开启单方向单挑模式")
    return game


def _load_one_way_room(
    connection: sqlite3.Connection, room_code: str, game_id: int | None = None
) -> sqlite3.Row:
    _validate_room_code(room_code)
    if game_id is None:
        room = connection.execute(
            "SELECT * FROM one_way_rooms WHERE code = ?", (room_code,)
        ).fetchone()
    else:
        room = connection.execute(
            "SELECT * FROM one_way_rooms WHERE code = ? AND game_id = ?",
            (room_code, game_id),
        ).fetchone()
    if room is None:
        raise ArenaRepositoryError(404, "单方向单挑房间不存在")
    return room


def _one_way_room_role(room: sqlite3.Row, user: UserIdentity) -> str | None:
    if room["host_user_id"] == user.user_id:
        return "host"
    if room["guest_user_id"] == user.user_id:
        return "guest"
    return None


def _require_one_way_room_member(room: sqlite3.Row, user: UserIdentity) -> str:
    role = _one_way_room_role(room, user)
    if role is None:
        raise ArenaRepositoryError(403, "你不是该单方向单挑房间的成员")
    return role


def _one_way_public_challenge_from_row(row: sqlite3.Row) -> ChallengePublicView:
    modes = [ChallengeMode(value) for value in json.loads(row["modes_json"])]
    boss = (
        BossChallengeConfig.model_validate_json(row["boss_json"])
        if row["boss_json"]
        else None
    )
    return ChallengePublicView(
        id=int(row["id"]),
        source_challenge_id=row["source_challenge_id"],
        title=row["title"],
        category=row["category"],
        difficulty=row["difficulty"],
        description=row["description"],
        target=row["target"],
        attachment_url=row["attachment_url"],
        status=row["status"],
        enabled=True,
        sort_order=int(row["sort_order"]),
        modes=modes,
        pk=(
            PkChallengeConfig.model_validate_json(row["pk_json"])
            if row["pk_json"]
            else None
        ),
        boss=boss,
        flag_case_sensitive=bool(row["flag_case_sensitive"]),
        locked=False,
        solved=False,
    )


def _one_way_round_admin_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "roundNumber": int(row["round_number"]),
        "status": row["status"],
        "challengeId": int(row["challenge_id"]),
        "challengeTitle": row["challenge_title"],
        "startsAt": row["starts_at"],
        "endsAt": row["ends_at"],
        "finishedAt": row["finished_at"],
        "winnerUserId": row["winner_user_id"],
        "winnerUserName": row["winner_user_name"],
        "isDraw": bool(row["is_draw"]),
    }


def _one_way_round_rows(
    connection: sqlite3.Connection, room_code: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM one_way_rounds
        WHERE room_code = ? ORDER BY round_number
        """,
        (room_code,),
    ).fetchall()


def _one_way_round_totals(
    rows: list[sqlite3.Row], host_user_id: str, guest_user_id: str | None
) -> tuple[int, int, int]:
    host_wins = sum(row["winner_user_id"] == host_user_id for row in rows)
    guest_wins = (
        sum(row["winner_user_id"] == guest_user_id for row in rows)
        if guest_user_id is not None
        else 0
    )
    draws = sum(bool(row["is_draw"]) for row in rows)
    return host_wins, guest_wins, draws


def _insert_waiting_one_way_audit(
    connection: sqlite3.Connection,
    *,
    game_id: int,
    room_code: str,
    direction_id: str,
    direction_name: str,
    direction_description: str,
    config_json: str,
    host_user_id: str,
    host_user_name: str,
    total_rounds: int,
    timestamp: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO one_way_match_audits(
            game_id, room_code, direction_id, direction_name,
            direction_description, config_json,
            host_user_id, host_user_name, status,
            current_round, total_rounds, rounds_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', 0, ?, '[]', ?, ?)
        """,
        (
            game_id,
            room_code,
            direction_id,
            direction_name,
            direction_description,
            config_json,
            host_user_id,
            host_user_name,
            total_rounds,
            timestamp,
            timestamp,
        ),
    )
    return int(cursor.lastrowid)


def _sync_one_way_match_audit(
    connection: sqlite3.Connection,
    room: sqlite3.Row,
    now: datetime,
    *,
    forced_status: OneWayMatchStatus | None = None,
    finish_reason: OneWayMatchFinishReason | None = None,
) -> sqlite3.Row:
    room = connection.execute(
        "SELECT * FROM one_way_rooms WHERE code = ?", (room["code"],)
    ).fetchone()
    if room is None:
        raise ArenaRepositoryError(404, "单方向单挑房间不存在")
    rows = _one_way_round_rows(connection, room["code"])
    host_wins, guest_wins, draws = _one_way_round_totals(
        rows, room["host_user_id"], room["guest_user_id"]
    )
    status_value = forced_status.value if forced_status is not None else room["status"]
    timestamp = _iso(now)
    finished_at = room["finished_at"]
    winner_user_id = room["winner_user_id"]
    winner_user_name = room["winner_user_name"]
    is_draw = bool(room["is_draw"])
    reason_value: str | None = None
    if status_value == OneWayMatchStatus.FINISHED.value:
        reason_value = OneWayMatchFinishReason.COMPLETED.value
    elif forced_status is not None:
        finished_at = timestamp
        winner_user_id = None
        winner_user_name = None
        is_draw = False
        reason_value = finish_reason.value if finish_reason is not None else None

    connection.execute(
        """
        UPDATE one_way_match_audits
        SET direction_id = ?, direction_name = ?, direction_description = ?,
            config_json = ?, host_user_id = ?, host_user_name = ?,
            guest_user_id = ?, guest_user_name = ?, status = ?,
            current_round = ?, total_rounds = ?,
            host_round_wins = ?, guest_round_wins = ?, round_draws = ?,
            rounds_json = ?, joined_at = ?, starts_at = ?, finished_at = ?,
            finish_reason = ?, winner_user_id = ?, winner_user_name = ?,
            is_draw = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            room["direction_id"],
            room["direction_name"],
            room["direction_description"],
            room["config_json"],
            room["host_user_id"],
            room["host_user_name"],
            room["guest_user_id"],
            room["guest_user_name"],
            status_value,
            int(room["current_round"]),
            len(rows),
            host_wins,
            guest_wins,
            draws,
            json.dumps(
                [_one_way_round_admin_payload(row) for row in rows],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            room["joined_at"],
            room["starts_at"],
            finished_at,
            reason_value,
            winner_user_id,
            winner_user_name,
            int(is_draw),
            timestamp,
            int(room["audit_id"]),
        ),
    )
    audit = connection.execute(
        "SELECT * FROM one_way_match_audits WHERE id = ?",
        (int(room["audit_id"]),),
    ).fetchone()
    assert audit is not None
    return audit


def _finish_one_way_room(
    connection: sqlite3.Connection,
    room: sqlite3.Row,
    finished_at: datetime,
) -> sqlite3.Row:
    rows = _one_way_round_rows(connection, room["code"])
    host_wins, guest_wins, _draws = _one_way_round_totals(
        rows, room["host_user_id"], room["guest_user_id"]
    )
    winner_user_id: str | None = None
    winner_user_name: str | None = None
    is_draw = host_wins == guest_wins
    if host_wins > guest_wins:
        winner_user_id = room["host_user_id"]
        winner_user_name = room["host_user_name"]
    elif guest_wins > host_wins:
        winner_user_id = room["guest_user_id"]
        winner_user_name = room["guest_user_name"]
    timestamp = _iso(finished_at)
    connection.execute(
        """
        UPDATE one_way_rooms
        SET status = 'finished', finished_at = ?, winner_user_id = ?,
            winner_user_name = ?, is_draw = ?, updated_at = ?
        WHERE code = ?
        """,
        (
            timestamp,
            winner_user_id,
            winner_user_name,
            int(is_draw),
            timestamp,
            room["code"],
        ),
    )
    updated = connection.execute(
        "SELECT * FROM one_way_rooms WHERE code = ?", (room["code"],)
    ).fetchone()
    assert updated is not None
    return updated


def _close_one_way_round(
    connection: sqlite3.Connection,
    room: sqlite3.Row,
    round_row: sqlite3.Row,
    finished_at: datetime,
) -> sqlite3.Row:
    config = OneWayConfig.model_validate_json(room["config_json"])
    if int(round_row["round_number"]) >= config.round_count:
        return _finish_one_way_room(connection, room, finished_at)
    next_round_number = int(round_row["round_number"]) + 1
    next_starts_at = finished_at + timedelta(seconds=config.interval_seconds)
    next_ends_at = next_starts_at + timedelta(seconds=config.round_seconds)
    connection.execute(
        """
        UPDATE one_way_rounds
        SET starts_at = ?, ends_at = ?
        WHERE room_code = ? AND round_number = ? AND status = 'pending'
        """,
        (
            _iso(next_starts_at),
            _iso(next_ends_at),
            room["code"],
            next_round_number,
        ),
    )
    connection.execute(
        """
        UPDATE one_way_rooms
        SET status = 'interval', updated_at = ? WHERE code = ?
        """,
        (_iso(finished_at), room["code"]),
    )
    updated = connection.execute(
        "SELECT * FROM one_way_rooms WHERE code = ?", (room["code"],)
    ).fetchone()
    assert updated is not None
    return updated


def _advance_one_way_room(
    connection: sqlite3.Connection, room: sqlite3.Row, now: datetime
) -> sqlite3.Row:
    changed = False
    while True:
        room = connection.execute(
            "SELECT * FROM one_way_rooms WHERE code = ?", (room["code"],)
        ).fetchone()
        if room is None:
            raise ArenaRepositoryError(404, "单方向单挑房间不存在")
        if room["status"] in {"waiting", "finished"}:
            break

        current_round = int(room["current_round"])
        round_row = connection.execute(
            """
            SELECT * FROM one_way_rounds
            WHERE room_code = ? AND round_number = ?
            """,
            (room["code"], current_round),
        ).fetchone()
        if round_row is None:
            raise ArenaRepositoryError(409, "单方向单挑轮次状态不完整")

        if room["status"] == "countdown":
            starts_at = _parse_time(round_row["starts_at"])
            if starts_at is None:
                raise ArenaRepositoryError(409, "单方向单挑倒计时状态不完整")
            if now < starts_at:
                break
            connection.execute(
                """
                UPDATE one_way_rounds SET status = 'active'
                WHERE room_code = ? AND round_number = ? AND status = 'pending'
                """,
                (room["code"], current_round),
            )
            connection.execute(
                "UPDATE one_way_rooms SET status = 'active', updated_at = ? WHERE code = ?",
                (_iso(starts_at), room["code"]),
            )
            changed = True
            continue

        if room["status"] == "interval":
            next_round_number = current_round + 1
            next_round = connection.execute(
                """
                SELECT * FROM one_way_rounds
                WHERE room_code = ? AND round_number = ?
                """,
                (room["code"], next_round_number),
            ).fetchone()
            if next_round is None:
                room = _finish_one_way_room(connection, room, now)
                changed = True
                continue
            next_starts_at = _parse_time(next_round["starts_at"])
            if next_starts_at is None:
                raise ArenaRepositoryError(409, "单方向单挑轮次间隔状态不完整")
            if now < next_starts_at:
                break
            connection.execute(
                """
                UPDATE one_way_rounds SET status = 'active'
                WHERE room_code = ? AND round_number = ? AND status = 'pending'
                """,
                (room["code"], next_round_number),
            )
            connection.execute(
                """
                UPDATE one_way_rooms
                SET status = 'active', current_round = ?, updated_at = ?
                WHERE code = ?
                """,
                (next_round_number, _iso(next_starts_at), room["code"]),
            )
            changed = True
            continue

        if room["status"] != "active":
            raise ArenaRepositoryError(409, "未知的单方向单挑房间状态")
        ends_at = _parse_time(round_row["ends_at"])
        if ends_at is None:
            raise ArenaRepositoryError(409, "单方向单挑轮次截止时间缺失")
        if now < ends_at:
            break
        result = connection.execute(
            """
            UPDATE one_way_rounds
            SET status = 'finished', finished_at = ?, is_draw = 1
            WHERE room_code = ? AND round_number = ? AND status = 'active'
            """,
            (_iso(ends_at), room["code"], current_round),
        )
        if result.rowcount != 1:
            continue
        room = _close_one_way_round(connection, room, round_row, ends_at)
        changed = True

    if changed:
        _sync_one_way_match_audit(connection, room, now)
    refreshed = connection.execute(
        "SELECT * FROM one_way_rooms WHERE code = ?", (room["code"],)
    ).fetchone()
    assert refreshed is not None
    return refreshed


def _one_way_room_player(
    room: sqlite3.Row,
    user_id: str,
    user_name: str,
    host_wins: int,
    guest_wins: int,
) -> OneWayRoomPlayerView:
    return OneWayRoomPlayerView(
        user_id=user_id,
        user_name=user_name,
        round_wins=host_wins if user_id == room["host_user_id"] else guest_wins,
    )


def _one_way_room_view(
    connection: sqlite3.Connection,
    room: sqlite3.Row,
    user: UserIdentity,
    now: datetime,
) -> OneWayRoomView:
    role = _require_one_way_room_member(room, user)
    rows = _one_way_round_rows(connection, room["code"])
    host_wins, guest_wins, _draws = _one_way_round_totals(
        rows, room["host_user_id"], room["guest_user_id"]
    )
    host = _one_way_room_player(
        room,
        room["host_user_id"],
        room["host_user_name"],
        host_wins,
        guest_wins,
    )
    guest = None
    if room["guest_user_id"] is not None:
        guest = _one_way_room_player(
            room,
            room["guest_user_id"],
            room["guest_user_name"],
            host_wins,
            guest_wins,
        )

    players = {host.user_id: host}
    if guest is not None:
        players[guest.user_id] = guest
    public_rounds: list[OneWayRoundView] = []
    for row in rows:
        visible = row["status"] in {
            OneWayRoundStatus.ACTIVE.value,
            OneWayRoundStatus.FINISHED.value,
        }
        public_rounds.append(
            OneWayRoundView(
                round_number=int(row["round_number"]),
                status=row["status"],
                challenge_id=int(row["challenge_id"]) if visible else None,
                challenge_title=row["challenge_title"] if visible else None,
                starts_at=_parse_time(row["starts_at"]),
                ends_at=_parse_time(row["ends_at"]),
                finished_at=_parse_time(row["finished_at"]),
                winner=players.get(row["winner_user_id"]),
                is_draw=bool(row["is_draw"]),
            )
        )

    current_row = None
    if int(room["current_round"]) > 0:
        current_row = next(
            (
                row
                for row in rows
                if int(row["round_number"]) == int(room["current_round"])
            ),
            None,
        )
    reveal_current = room["status"] in {"active", "interval"}
    current_challenge = None
    current_challenge_id = None
    if current_row is not None and reveal_current:
        current_challenge = ChallengePublicView.model_validate_json(
            current_row["challenge_snapshot_json"]
        )
        current_challenge_id = int(current_row["challenge_id"])
    next_round_starts_at = None
    if room["status"] == "interval":
        next_round = next(
            (
                row
                for row in rows
                if int(row["round_number"]) == int(room["current_round"]) + 1
            ),
            None,
        )
        if next_round is not None:
            next_round_starts_at = _parse_time(next_round["starts_at"])

    winner = players.get(room["winner_user_id"])
    return OneWayRoomView(
        code=room["code"],
        game_id=int(room["game_id"]),
        direction=OneWayDirectionPublicView(
            id=room["direction_id"],
            name=room["direction_name"],
            description=room["direction_description"],
        ),
        status=room["status"],
        host=host,
        guest=guest,
        current_user_role=role,
        created_at=_parse_time(room["created_at"]),
        starts_at=_parse_time(room["starts_at"]),
        current_round=int(room["current_round"]),
        total_rounds=len(rows),
        current_challenge_id=current_challenge_id,
        current_challenge=current_challenge,
        round_starts_at=(
            _parse_time(current_row["starts_at"]) if current_row is not None else None
        ),
        round_ends_at=(
            _parse_time(current_row["ends_at"]) if current_row is not None else None
        ),
        next_round_starts_at=next_round_starts_at,
        rounds=public_rounds,
        host_round_wins=host_wins,
        guest_round_wins=guest_wins,
        winner=winner,
        is_draw=bool(room["is_draw"]),
        finished_at=_parse_time(room["finished_at"]),
        server_time=now,
    )


def _one_way_room_needs_advance(
    connection: sqlite3.Connection, room: sqlite3.Row, now: datetime
) -> bool:
    status = room["status"]
    if status in {"waiting", "finished"}:
        return False
    round_number = int(room["current_round"])
    if status == "interval":
        round_number += 1
        time_column = "starts_at"
    elif status == "countdown":
        time_column = "starts_at"
    else:
        time_column = "ends_at"
    round_row = connection.execute(
        f"SELECT {time_column} AS boundary FROM one_way_rounds "
        "WHERE room_code = ? AND round_number = ?",
        (room["code"], round_number),
    ).fetchone()
    if round_row is None:
        return True
    boundary = _parse_time(round_row["boundary"])
    return boundary is None or now >= boundary


def create_one_way_room(
    database: Database,
    game_id: int,
    direction_id: str,
    user: UserIdentity,
) -> OneWayRoomView:
    with database.transaction(immediate=True) as connection:
        now = _now()
        timestamp = _iso(now)
        game = _load_one_way_game(connection, game_id)
        config = OneWayConfig.model_validate_json(game["one_way_config_json"])
        direction = next(
            (item for item in config.directions if item.id == direction_id), None
        )
        if direction is None:
            raise ArenaRepositoryError(404, "挑战方向不存在或未开放")
        if not direction.challenge_ids:
            raise ArenaRepositoryError(409, "该挑战方向尚未配置题目")
        placeholders = ",".join("?" for _ in direction.challenge_ids)
        candidate_rows = connection.execute(
            f"""
            SELECT * FROM arena_challenges
            WHERE game_id = ? AND id IN ({placeholders})
              AND enabled = 1 AND lower(status) IN ('active', 'open')
              AND flag_hash IS NOT NULL
            """,
            (game_id, *direction.challenge_ids),
        ).fetchall()
        playable_rows = [
            row
            for row in candidate_rows
            if ChallengeMode.ONE_WAY.value in json.loads(row["modes_json"])
        ]
        if len(playable_rows) < config.round_count:
            raise ArenaRepositoryError(
                409,
                f"该方向当前不足 {config.round_count} 道可用的单方向单挑题目",
            )
        selected_rows = secrets.SystemRandom().sample(playable_rows, config.round_count)

        room_code = ""
        for _attempt in range(100):
            candidate = _random_pk_room_code()
            exists = connection.execute(
                "SELECT 1 FROM one_way_rooms WHERE code = ?", (candidate,)
            ).fetchone()
            if exists is None:
                room_code = candidate
                break
        if not room_code:
            raise ArenaRepositoryError(503, "暂时无法分配单方向单挑房间号，请稍后重试")

        frozen_config = OneWayConfig(
            countdown_seconds=config.countdown_seconds,
            round_count=config.round_count,
            round_seconds=config.round_seconds,
            interval_seconds=config.interval_seconds,
            directions=[],
        )
        config_json = _json_model(frozen_config)
        audit_id = _insert_waiting_one_way_audit(
            connection,
            game_id=game_id,
            room_code=room_code,
            direction_id=direction.id,
            direction_name=direction.name,
            direction_description=direction.description,
            config_json=config_json,
            host_user_id=user.user_id,
            host_user_name=user.user_name,
            total_rounds=config.round_count,
            timestamp=timestamp,
        )
        connection.execute(
            """
            INSERT INTO one_way_rooms(
                code, game_id, audit_id, direction_id, direction_name,
                direction_description, config_json,
                host_user_id, host_user_name, status, current_round,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting', 0, ?, ?)
            """,
            (
                room_code,
                game_id,
                audit_id,
                direction.id,
                direction.name,
                direction.description,
                config_json,
                user.user_id,
                user.user_name,
                timestamp,
                timestamp,
            ),
        )
        for round_number, challenge in enumerate(selected_rows, 1):
            snapshot = _one_way_public_challenge_from_row(challenge)
            connection.execute(
                """
                INSERT INTO one_way_rounds(
                    room_code, round_number, challenge_id, challenge_title,
                    challenge_snapshot_json, flag_hash, flag_case_sensitive, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    room_code,
                    round_number,
                    int(challenge["id"]),
                    challenge["title"],
                    snapshot.model_dump_json(by_alias=True),
                    challenge["flag_hash"],
                    int(challenge["flag_case_sensitive"]),
                ),
            )
        room = _load_one_way_room(connection, room_code, game_id)
        _sync_one_way_match_audit(connection, room, now)
        return _one_way_room_view(connection, room, user, now)


def join_one_way_room(
    database: Database,
    room_code: str,
    game_id: int | None,
    user: UserIdentity,
) -> OneWayRoomView:
    with database.transaction(immediate=True) as connection:
        now = _now()
        timestamp = _iso(now)
        room = _load_one_way_room(connection, room_code, game_id)
        room = _advance_one_way_room(connection, room, now)
        role = _one_way_room_role(room, user)
        if role is not None:
            column = "host_user_name" if role == "host" else "guest_user_name"
            connection.execute(
                f"UPDATE one_way_rooms SET {column} = ?, updated_at = ? WHERE code = ?",
                (user.user_name, timestamp, room_code),
            )
            room = _load_one_way_room(connection, room_code, game_id)
            _sync_one_way_match_audit(connection, room, now)
            return _one_way_room_view(connection, room, user, now)
        if room["status"] == "finished":
            raise ArenaRepositoryError(409, "单方向单挑比赛已经结束")
        if room["guest_user_id"] is not None:
            raise ArenaRepositoryError(409, "单方向单挑房间已满")

        config = OneWayConfig.model_validate_json(room["config_json"])
        starts_at = now + timedelta(seconds=config.countdown_seconds)
        ends_at = starts_at + timedelta(seconds=config.round_seconds)
        result = connection.execute(
            """
            UPDATE one_way_rooms
            SET guest_user_id = ?, guest_user_name = ?, status = 'countdown',
                current_round = 1, joined_at = ?, starts_at = ?, updated_at = ?
            WHERE code = ? AND guest_user_id IS NULL AND status = 'waiting'
            """,
            (
                user.user_id,
                user.user_name,
                timestamp,
                _iso(starts_at),
                timestamp,
                room_code,
            ),
        )
        if result.rowcount != 1:
            raise ArenaRepositoryError(409, "单方向单挑房间已发生变化，请重试")
        connection.execute(
            """
            UPDATE one_way_rounds
            SET starts_at = ?, ends_at = ?
            WHERE room_code = ? AND round_number = 1 AND status = 'pending'
            """,
            (_iso(starts_at), _iso(ends_at), room_code),
        )
        room = _load_one_way_room(connection, room_code, game_id)
        _sync_one_way_match_audit(connection, room, now)
        return _one_way_room_view(connection, room, user, now)


def get_one_way_room(
    database: Database,
    room_code: str,
    game_id: int,
    user: UserIdentity,
) -> OneWayRoomView:
    with database.connection() as connection:
        now = _now()
        room = _load_one_way_room(connection, room_code, game_id)
        _require_one_way_room_member(room, user)
        if not _one_way_room_needs_advance(connection, room, now):
            return _one_way_room_view(connection, room, user, now)
    with database.transaction(immediate=True) as connection:
        now = _now()
        room = _load_one_way_room(connection, room_code, game_id)
        _require_one_way_room_member(room, user)
        room = _advance_one_way_room(connection, room, now)
        return _one_way_room_view(connection, room, user, now)


def leave_one_way_room(
    database: Database,
    room_code: str,
    game_id: int,
    user: UserIdentity,
) -> OneWayRoomView:
    with database.transaction(immediate=True) as connection:
        now = _now()
        timestamp = _iso(now)
        room = _load_one_way_room(connection, room_code, game_id)
        role = _require_one_way_room_member(room, user)
        room = _advance_one_way_room(connection, room, now)
        if room["status"] in {"active", "interval", "finished"}:
            raise ArenaRepositoryError(409, "比赛开始后不能退出房间")
        leaving_view = _one_way_room_view(connection, room, user, now)
        _sync_one_way_match_audit(
            connection,
            room,
            now,
            forced_status=OneWayMatchStatus.CANCELLED,
            finish_reason=OneWayMatchFinishReason.PLAYER_LEFT,
        )
        if role == "host" and room["guest_user_id"] is None:
            connection.execute("DELETE FROM one_way_rooms WHERE code = ?", (room_code,))
            return leaving_view

        connection.execute(
            "DELETE FROM one_way_submissions WHERE room_code = ?", (room_code,)
        )
        connection.execute(
            """
            UPDATE one_way_rounds
            SET status = 'pending', starts_at = NULL, ends_at = NULL,
                finished_at = NULL, winner_user_id = NULL,
                winner_user_name = NULL, is_draw = 0
            WHERE room_code = ?
            """,
            (room_code,),
        )
        if role == "guest":
            host_user_id = room["host_user_id"]
            host_user_name = room["host_user_name"]
        else:
            host_user_id = room["guest_user_id"]
            host_user_name = room["guest_user_name"]
        assert host_user_id is not None and host_user_name is not None
        new_audit_id = _insert_waiting_one_way_audit(
            connection,
            game_id=game_id,
            room_code=room_code,
            direction_id=room["direction_id"],
            direction_name=room["direction_name"],
            direction_description=room["direction_description"],
            config_json=room["config_json"],
            host_user_id=host_user_id,
            host_user_name=host_user_name,
            total_rounds=len(_one_way_round_rows(connection, room_code)),
            timestamp=timestamp,
        )
        connection.execute(
            """
            UPDATE one_way_rooms
            SET audit_id = ?, host_user_id = ?, host_user_name = ?,
                guest_user_id = NULL, guest_user_name = NULL,
                status = 'waiting', current_round = 0,
                joined_at = NULL, starts_at = NULL, finished_at = NULL,
                winner_user_id = NULL, winner_user_name = NULL, is_draw = 0,
                updated_at = ?
            WHERE code = ?
            """,
            (new_audit_id, host_user_id, host_user_name, timestamp, room_code),
        )
        waiting_room = _load_one_way_room(connection, room_code, game_id)
        _sync_one_way_match_audit(connection, waiting_room, now)
        return leaving_view


def submit_one_way(
    database: Database,
    game_id: int,
    room_code: str,
    challenge_id: int,
    submitted_flag: str,
    user: UserIdentity,
) -> OneWaySubmitResponse:
    prechecked_audit_id: int | None = None
    prechecked_round_number: int | None = None
    prechecked_flag_hash: str | None = None
    preverified_correct = False
    # PBKDF2 verification is deliberately performed outside the SQLite write
    # transaction. The frozen audit id/hash are compared again after acquiring
    # BEGIN IMMEDIATE, so a deleted/reused room cannot reuse this result.
    with database.connection() as connection:
        room = _load_one_way_room(connection, room_code, game_id)
        _require_one_way_room_member(room, user)
        candidate_round = connection.execute(
            """
            SELECT * FROM one_way_rounds
            WHERE room_code = ? AND challenge_id = ?
            """,
            (room_code, challenge_id),
        ).fetchone()
        prechecked_audit_id = int(room["audit_id"])
        if candidate_round is not None:
            prechecked_round_number = int(candidate_round["round_number"])
            prechecked_flag_hash = candidate_round["flag_hash"]
            normalized = (
                submitted_flag
                if bool(candidate_round["flag_case_sensitive"])
                else submitted_flag.casefold()
            )
            preverified_correct = verify_secret(
                normalized,
                candidate_round["flag_hash"],
                pepper=settings.flag_pepper,
            )

    with database.transaction(immediate=True) as connection:
        # The clock is sampled only after BEGIN IMMEDIATE acquired the write lock.
        # This makes a submission exactly at/after the deadline lose to timeout.
        now = _now()
        timestamp = _iso(now)
        room = _load_one_way_room(connection, room_code, game_id)
        _require_one_way_room_member(room, user)
        if int(room["audit_id"]) != prechecked_audit_id:
            raise ArenaRepositoryError(409, "房间对局已发生变化，请重新提交")
        room = _advance_one_way_room(connection, room, now)
        scheduled_round = connection.execute(
            """
            SELECT * FROM one_way_rounds
            WHERE room_code = ? AND challenge_id = ?
            """,
            (room_code, challenge_id),
        ).fetchone()
        if scheduled_round is not None and scheduled_round["status"] == "finished":
            return OneWaySubmitResponse(
                correct=False,
                already_resolved=True,
                challenge_id=challenge_id,
                round_number=int(scheduled_round["round_number"]),
                message="本轮已经结束，请查看轮次结果",
                room=_one_way_room_view(connection, room, user, now),
            )
        if room["status"] == "waiting":
            raise ArenaRepositoryError(409, "对手尚未进入，比赛未开始")
        if room["status"] == "countdown":
            raise ArenaRepositoryError(409, "双方已就位，比赛倒计时中")
        if room["status"] == "interval":
            raise ArenaRepositoryError(409, "本轮已结束，下一轮尚未开始")
        if room["status"] == "finished":
            raise ArenaRepositoryError(410, "单方向单挑比赛已结束")
        current_round = int(room["current_round"])
        round_row = connection.execute(
            """
            SELECT * FROM one_way_rounds
            WHERE room_code = ? AND round_number = ?
            """,
            (room_code, current_round),
        ).fetchone()
        if round_row is None or int(round_row["challenge_id"]) != challenge_id:
            raise ArenaRepositoryError(409, "提交的题目不是当前轮次题目")

        correct = (
            preverified_correct
            and prechecked_round_number == current_round
            and prechecked_flag_hash == round_row["flag_hash"]
        )
        if not correct:
            connection.execute(
                """
                INSERT INTO one_way_submissions(
                    room_code, round_number, user_id, user_name,
                    challenge_id, correct, submitted_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    room_code,
                    current_round,
                    user.user_id,
                    user.user_name,
                    challenge_id,
                    timestamp,
                ),
            )
            return OneWaySubmitResponse(
                correct=False,
                challenge_id=challenge_id,
                round_number=current_round,
                message="Flag 错误",
                room=_one_way_room_view(connection, room, user, now),
            )

        connection.execute(
            """
            INSERT INTO one_way_submissions(
                room_code, round_number, user_id, user_name,
                challenge_id, correct, submitted_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                room_code,
                current_round,
                user.user_id,
                user.user_name,
                challenge_id,
                timestamp,
            ),
        )
        result = connection.execute(
            """
            UPDATE one_way_rounds
            SET status = 'finished', finished_at = ?,
                winner_user_id = ?, winner_user_name = ?, is_draw = 0
            WHERE room_code = ? AND round_number = ?
              AND status = 'active' AND winner_user_id IS NULL
            """,
            (
                timestamp,
                user.user_id,
                user.user_name,
                room_code,
                current_round,
            ),
        )
        if result.rowcount != 1:
            raise ArenaRepositoryError(409, "本轮胜者已经产生，请刷新结果")
        finished_round = connection.execute(
            """
            SELECT * FROM one_way_rounds
            WHERE room_code = ? AND round_number = ?
            """,
            (room_code, current_round),
        ).fetchone()
        assert finished_round is not None
        room = _close_one_way_round(connection, room, finished_round, now)
        _sync_one_way_match_audit(connection, room, now)
        return OneWaySubmitResponse(
            correct=True,
            challenge_id=challenge_id,
            round_number=current_round,
            message=f"{user.user_name} 获得本轮胜利",
            room=_one_way_room_view(connection, room, user, now),
        )


def _one_way_match_admin_from_row(row: sqlite3.Row) -> OneWayMatchAdminView:
    host = OneWayRoomPlayerView(
        user_id=row["host_user_id"],
        user_name=row["host_user_name"],
        round_wins=int(row["host_round_wins"]),
    )
    guest = None
    if row["guest_user_id"] is not None:
        guest = OneWayRoomPlayerView(
            user_id=row["guest_user_id"],
            user_name=row["guest_user_name"],
            round_wins=int(row["guest_round_wins"]),
        )
    winner = None
    if row["winner_user_id"] == host.user_id:
        winner = host
    elif guest is not None and row["winner_user_id"] == guest.user_id:
        winner = guest
    rounds = [
        OneWayMatchRoundAdminView.model_validate(item)
        for item in json.loads(row["rounds_json"])
    ]
    return OneWayMatchAdminView(
        match_id=int(row["id"]),
        game_id=int(row["game_id"]),
        room_code=row["room_code"],
        room_exists=bool(row["room_exists"]),
        status=row["status"],
        direction=OneWayDirectionPublicView(
            id=row["direction_id"],
            name=row["direction_name"],
            description=row["direction_description"],
        ),
        host=host,
        guest=guest,
        current_round=int(row["current_round"]),
        total_rounds=int(row["total_rounds"]),
        host_round_wins=int(row["host_round_wins"]),
        guest_round_wins=int(row["guest_round_wins"]),
        round_draws=int(row["round_draws"]),
        rounds=rounds,
        winner=winner,
        is_draw=bool(row["is_draw"]),
        created_at=_parse_time(row["created_at"]),
        joined_at=_parse_time(row["joined_at"]),
        starts_at=_parse_time(row["starts_at"]),
        finished_at=_parse_time(row["finished_at"]),
        finish_reason=row["finish_reason"],
        updated_at=_parse_time(row["updated_at"]),
    )


def list_one_way_matches(
    database: Database,
    game_id: int,
    *,
    match_status: OneWayMatchStatus | None = None,
    limit: int = 100,
) -> list[OneWayMatchAdminView]:
    with database.transaction(immediate=True) as connection:
        now = _now()
        rooms = connection.execute(
            "SELECT * FROM one_way_rooms WHERE game_id = ?", (game_id,)
        ).fetchall()
        for room in rooms:
            _advance_one_way_room(connection, room, now)
        parameters: list[Any] = [game_id]
        status_filter = ""
        if match_status is not None:
            status_filter = " AND audit.status = ?"
            parameters.append(match_status.value)
        parameters.append(limit)
        rows = connection.execute(
            f"""
            SELECT audit.*,
                   CASE WHEN room.audit_id = audit.id THEN 1 ELSE 0 END AS room_exists
            FROM one_way_match_audits AS audit
            LEFT JOIN one_way_rooms AS room ON room.audit_id = audit.id
            WHERE audit.game_id = ?{status_filter}
            ORDER BY audit.created_at DESC, audit.id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    return [_one_way_match_admin_from_row(row) for row in rows]


def delete_one_way_match_room(database: Database, game_id: int, match_id: int) -> None:
    with database.transaction(immediate=True) as connection:
        now = _now()
        audit = connection.execute(
            "SELECT * FROM one_way_match_audits WHERE id = ? AND game_id = ?",
            (match_id, game_id),
        ).fetchone()
        if audit is None:
            raise ArenaRepositoryError(404, "单方向单挑对局记录不存在")
        room = connection.execute(
            "SELECT * FROM one_way_rooms WHERE audit_id = ? AND game_id = ?",
            (match_id, game_id),
        ).fetchone()
        if room is None:
            raise ArenaRepositoryError(404, "单方向单挑房间不存在")
        room = _advance_one_way_room(connection, room, now)
        if room["status"] != "finished":
            _sync_one_way_match_audit(
                connection,
                room,
                now,
                forced_status=OneWayMatchStatus.RESET,
                finish_reason=OneWayMatchFinishReason.ADMIN_RESET,
            )
        result = connection.execute(
            "DELETE FROM one_way_rooms WHERE code = ? AND audit_id = ?",
            (room["code"], match_id),
        )
        if result.rowcount != 1:
            raise ArenaRepositoryError(409, "单方向单挑房间已发生变化，请刷新后重试")


def delete_one_way_match(database: Database, game_id: int, match_id: int) -> None:
    with database.transaction(immediate=True) as connection:
        audit = connection.execute(
            "SELECT * FROM one_way_match_audits WHERE id = ? AND game_id = ?",
            (match_id, game_id),
        ).fetchone()
        if audit is None:
            raise ArenaRepositoryError(404, "单方向单挑对局记录不存在")
        room = connection.execute(
            "SELECT 1 FROM one_way_rooms WHERE audit_id = ? AND game_id = ?",
            (match_id, game_id),
        ).fetchone()
        if room is not None:
            raise ArenaRepositoryError(409, "请先删除该对局关联的单方向单挑房间")
        connection.execute(
            "DELETE FROM one_way_match_audits WHERE id = ? AND game_id = ?",
            (match_id, game_id),
        )


def _boss_leaderboard(
    connection: sqlite3.Connection, game_id: int
) -> list[LeaderboardEntry]:
    rows = connection.execute(
        """
        SELECT user_id, user_name, contribution, solves
        FROM boss_contributions WHERE game_id = ?
        ORDER BY contribution DESC, solves DESC, updated_at ASC, user_id ASC
        LIMIT 100
        """,
        (game_id,),
    ).fetchall()
    return [
        LeaderboardEntry(
            rank=index,
            user_id=row["user_id"],
            user_name=row["user_name"],
            score=0,
            solves=row["solves"],
            contribution=row["contribution"],
        )
        for index, row in enumerate(rows, 1)
    ]


def submit_pk(
    database: Database,
    game_id: int,
    challenge_id: int,
    submitted_flag: str,
    user: UserIdentity,
    room_code: str | None = None,
) -> PkSubmitResponse:
    if room_code is not None:
        return _submit_pk_room(
            database,
            game_id,
            challenge_id,
            submitted_flag,
            user,
            room_code,
        )
    now = _now()
    timestamp = _iso(now)
    with database.transaction(immediate=True) as connection:
        game, challenge = _load_runtime_context(
            connection, game_id, challenge_id, ChallengeMode.PK
        )
        pk_config = PkConfig.model_validate_json(game["pk_config_json"])
        pk_challenge = (
            PkChallengeConfig.model_validate_json(challenge["pk_json"])
            if challenge["pk_json"]
            else None
        )
        if pk_challenge is None:
            raise ArenaRepositoryError(409, "题目的 PK 计分配置不完整")

        player = connection.execute(
            "SELECT * FROM pk_players WHERE game_id = ? AND user_id = ?",
            (game_id, user.user_id),
        ).fetchone()
        if player is None:
            connection.execute(
                """
                INSERT INTO pk_players(
                    game_id, user_id, user_name, score, solves, streak,
                    last_submission_at, updated_at
                ) VALUES (?, ?, ?, 0, 0, 0, NULL, ?)
                """,
                (game_id, user.user_id, user.user_name, timestamp),
            )
            player = connection.execute(
                "SELECT * FROM pk_players WHERE game_id = ? AND user_id = ?",
                (game_id, user.user_id),
            ).fetchone()
        assert player is not None

        previous_submission = _parse_time(player["last_submission_at"])
        if previous_submission is not None and pk_config.cooldown_seconds:
            available_at = previous_submission + timedelta(
                seconds=pk_config.cooldown_seconds
            )
            if now < available_at:
                retry_after = max(1, int((available_at - now).total_seconds() + 0.999))
                raise ArenaRepositoryError(
                    429,
                    f"提交冷却中，请在 {retry_after} 秒后重试",
                    {"Retry-After": str(retry_after)},
                )

        solved = connection.execute(
            """
            SELECT 1 FROM arena_submissions
            WHERE game_id = ? AND mode = 'pk' AND user_id = ?
              AND challenge_id = ? AND correct = 1
            """,
            (game_id, user.user_id, challenge_id),
        ).fetchone()
        if solved is not None:
            return PkSubmitResponse(
                correct=True,
                already_solved=True,
                challenge_id=challenge_id,
                score_delta=0,
                score=player["score"],
                solves=player["solves"],
                streak=player["streak"],
                message="该题已经得分",
            )

        correct = _flag_is_correct(challenge, submitted_flag)
        if not correct:
            penalty = min(int(player["score"]), pk_config.wrong_penalty)
            score = int(player["score"]) - penalty
            connection.execute(
                """
                INSERT INTO arena_submissions(
                    mode, game_id, user_id, user_name, challenge_id, correct, points, submitted_at
                ) VALUES ('pk', ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    game_id,
                    user.user_id,
                    user.user_name,
                    challenge_id,
                    -penalty,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE pk_players
                SET user_name = ?, score = ?, streak = 0, last_submission_at = ?, updated_at = ?
                WHERE game_id = ? AND user_id = ?
                """,
                (user.user_name, score, timestamp, timestamp, game_id, user.user_id),
            )
            return PkSubmitResponse(
                correct=False,
                challenge_id=challenge_id,
                score_delta=-penalty,
                score=score,
                solves=player["solves"],
                streak=0,
                message="Flag 错误",
            )

        solver_count = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count FROM arena_submissions
                WHERE game_id = ? AND mode = 'pk' AND challenge_id = ? AND correct = 1
                """,
                (game_id, challenge_id),
            ).fetchone()["count"]
        )
        first_blood = solver_count == 0
        if pk_config.score_mode == ScoreMode.DYNAMIC:
            multiplier = max(0.30, 1.0 - solver_count * 0.03)
            base_score = round(pk_challenge.base_score * multiplier)
        else:
            base_score = pk_challenge.base_score
        new_streak = int(player["streak"]) + 1
        streak_score = min(max(new_streak - 1, 0), 10) * pk_config.streak_bonus
        score_delta = base_score + streak_score
        if first_blood:
            score_delta += pk_config.first_blood_bonus
        score = int(player["score"]) + score_delta
        solves = int(player["solves"]) + 1
        connection.execute(
            """
            INSERT INTO arena_submissions(
                mode, game_id, user_id, user_name, challenge_id, correct, points, submitted_at
            ) VALUES ('pk', ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                game_id,
                user.user_id,
                user.user_name,
                challenge_id,
                score_delta,
                timestamp,
            ),
        )
        connection.execute(
            """
            UPDATE pk_players
            SET user_name = ?, score = ?, solves = ?, streak = ?,
                last_submission_at = ?, updated_at = ?
            WHERE game_id = ? AND user_id = ?
            """,
            (
                user.user_name,
                score,
                solves,
                new_streak,
                timestamp,
                timestamp,
                game_id,
                user.user_id,
            ),
        )
        return PkSubmitResponse(
            correct=True,
            challenge_id=challenge_id,
            score_delta=score_delta,
            score=score,
            solves=solves,
            first_blood=first_blood,
            streak=new_streak,
            message="Flag 正确，得分成功",
        )


def _submit_pk_room(
    database: Database,
    game_id: int,
    challenge_id: int,
    submitted_flag: str,
    user: UserIdentity,
    room_code: str,
) -> PkSubmitResponse:
    now = _now()
    timestamp = _iso(now)
    with database.transaction(immediate=True) as connection:
        game, challenge = _load_runtime_context(
            connection, game_id, challenge_id, ChallengeMode.PK
        )
        room = _load_pk_room(connection, room_code, game_id)
        _require_pk_room_member(room, user)
        pk_config = PkConfig.model_validate_json(game["pk_config_json"])
        room_status, starts_at, ends_at = _pk_room_timing(room, pk_config, now)
        if room_status == "waiting":
            raise ArenaRepositoryError(409, "对手尚未进入，比赛未开始")
        if room_status == "countdown":
            assert starts_at is not None
            retry_after = max(1, int((starts_at - now).total_seconds() + 0.999))
            raise ArenaRepositoryError(
                409,
                f"双方已就位，比赛将在 {retry_after} 秒后开始",
                {"Retry-After": str(retry_after)},
            )
        if room_status == "finished":
            raise ArenaRepositoryError(410, "PK 比赛已结束")
        assert starts_at is not None and ends_at is not None

        pk_challenge = (
            PkChallengeConfig.model_validate_json(challenge["pk_json"])
            if challenge["pk_json"]
            else None
        )
        if pk_challenge is None:
            raise ArenaRepositoryError(409, "题目的 PK 计分配置不完整")

        player = connection.execute(
            "SELECT * FROM pk_room_players WHERE room_code = ? AND user_id = ?",
            (room_code, user.user_id),
        ).fetchone()
        if player is None:
            raise ArenaRepositoryError(409, "PK 房间玩家状态不完整")

        previous_submission = _parse_time(player["last_submission_at"])
        if previous_submission is not None and pk_config.cooldown_seconds:
            available_at = previous_submission + timedelta(
                seconds=pk_config.cooldown_seconds
            )
            if now < available_at:
                retry_after = max(1, int((available_at - now).total_seconds() + 0.999))
                raise ArenaRepositoryError(
                    429,
                    f"提交冷却中，请在 {retry_after} 秒后重试",
                    {"Retry-After": str(retry_after)},
                )

        solved = connection.execute(
            """
            SELECT 1 FROM pk_room_submissions
            WHERE room_code = ? AND user_id = ? AND challenge_id = ? AND correct = 1
            """,
            (room_code, user.user_id, challenge_id),
        ).fetchone()
        if solved is not None:
            _sync_pk_match_audit(connection, room, game, now)
            return PkSubmitResponse(
                correct=True,
                already_solved=True,
                challenge_id=challenge_id,
                score_delta=0,
                score=player["score"],
                solves=player["solves"],
                streak=player["streak"],
                message="该题已经在本局得分",
                room_code=room_code,
            )

        correct = _flag_is_correct(challenge, submitted_flag)
        if not correct:
            penalty = min(int(player["score"]), pk_config.wrong_penalty)
            score = int(player["score"]) - penalty
            connection.execute(
                """
                INSERT INTO pk_room_submissions(
                    room_code, user_id, user_name, challenge_id, correct, points, submitted_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    room_code,
                    user.user_id,
                    user.user_name,
                    challenge_id,
                    -penalty,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE pk_room_players
                SET user_name = ?, score = ?, streak = 0,
                    last_submission_at = ?, updated_at = ?
                WHERE room_code = ? AND user_id = ?
                """,
                (
                    user.user_name,
                    score,
                    timestamp,
                    timestamp,
                    room_code,
                    user.user_id,
                ),
            )
            _sync_pk_match_audit(connection, room, game, now)
            return PkSubmitResponse(
                correct=False,
                challenge_id=challenge_id,
                score_delta=-penalty,
                score=score,
                solves=player["solves"],
                streak=0,
                message="Flag 错误",
                room_code=room_code,
            )

        solver_count = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count FROM pk_room_submissions
                WHERE room_code = ? AND challenge_id = ? AND correct = 1
                """,
                (room_code, challenge_id),
            ).fetchone()["count"]
        )
        first_blood = solver_count == 0
        if pk_config.score_mode == ScoreMode.DYNAMIC:
            multiplier = max(0.30, 1.0 - solver_count * 0.03)
            base_score = round(pk_challenge.base_score * multiplier)
        else:
            base_score = pk_challenge.base_score
        new_streak = int(player["streak"]) + 1
        streak_score = min(max(new_streak - 1, 0), 10) * pk_config.streak_bonus
        score_delta = base_score + streak_score
        if first_blood:
            score_delta += pk_config.first_blood_bonus
        score = int(player["score"]) + score_delta
        solves = int(player["solves"]) + 1
        connection.execute(
            """
            INSERT INTO pk_room_submissions(
                room_code, user_id, user_name, challenge_id, correct, points, submitted_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                room_code,
                user.user_id,
                user.user_name,
                challenge_id,
                score_delta,
                timestamp,
            ),
        )
        connection.execute(
            """
            UPDATE pk_room_players
            SET user_name = ?, score = ?, solves = ?, streak = ?,
                last_submission_at = ?, updated_at = ?
            WHERE room_code = ? AND user_id = ?
            """,
            (
                user.user_name,
                score,
                solves,
                new_streak,
                timestamp,
                timestamp,
                room_code,
                user.user_id,
            ),
        )
        _sync_pk_match_audit(connection, room, game, now)
        return PkSubmitResponse(
            correct=True,
            challenge_id=challenge_id,
            score_delta=score_delta,
            score=score,
            solves=solves,
            first_blood=first_blood,
            streak=new_streak,
            message="Flag 正确，本局得分成功",
            room_code=room_code,
        )


def _boss_phase(hp: int, max_hp: int, config: BossConfig) -> int:
    if max_hp <= 0:
        return config.phase_count
    ratio = hp / max_hp
    phase = 1
    for threshold in config.phase_thresholds:
        if ratio <= threshold:
            phase += 1
    return min(phase, config.phase_count)


def submit_boss(
    database: Database,
    game_id: int,
    challenge_id: int,
    submitted_flag: str,
    user: UserIdentity,
) -> BossSubmitResponse:
    now = _now()
    timestamp = _iso(now)
    with database.transaction(immediate=True) as connection:
        game, challenge = _load_runtime_context(
            connection, game_id, challenge_id, ChallengeMode.BOSS
        )
        boss_config = BossConfig.model_validate_json(game["boss_config_json"])
        boss_challenge = (
            BossChallengeConfig.model_validate_json(challenge["boss_json"])
            if challenge["boss_json"]
            else None
        )
        if boss_challenge is None:
            raise ArenaRepositoryError(409, "题目的 Boss 伤害配置不完整")
        state = _ensure_boss_state(connection, game_id, boss_config)
        state_view = _boss_state_from_row(state, boss_config)
        if state_view.status == "defeated":
            raise ArenaRepositoryError(409, "Boss 已被击败")
        if boss_challenge.phase > state_view.phase:
            raise ArenaRepositoryError(
                423, f"该题将在 Boss 第 {boss_challenge.phase} 阶段开放"
            )

        contribution_row = connection.execute(
            "SELECT * FROM boss_contributions WHERE game_id = ? AND user_id = ?",
            (game_id, user.user_id),
        ).fetchone()
        if contribution_row is None:
            connection.execute(
                """
                INSERT INTO boss_contributions(
                    game_id, user_id, user_name, contribution, solves, updated_at
                ) VALUES (?, ?, ?, 0, 0, ?)
                """,
                (game_id, user.user_id, user.user_name, timestamp),
            )
            contribution_row = connection.execute(
                "SELECT * FROM boss_contributions WHERE game_id = ? AND user_id = ?",
                (game_id, user.user_id),
            ).fetchone()
        assert contribution_row is not None

        solved = connection.execute(
            """
            SELECT 1 FROM arena_submissions
            WHERE game_id = ? AND mode = 'boss' AND user_id = ?
              AND challenge_id = ? AND correct = 1
            """,
            (game_id, user.user_id, challenge_id),
        ).fetchone()
        if solved is not None:
            return BossSubmitResponse(
                correct=True,
                already_solved=True,
                challenge_id=challenge_id,
                contribution=contribution_row["contribution"],
                boss_state=state_view,
                message="该题已经造成过伤害",
            )

        correct = _flag_is_correct(challenge, submitted_flag)
        if not correct:
            connection.execute(
                """
                INSERT INTO arena_submissions(
                    mode, game_id, user_id, user_name, challenge_id, correct, points, submitted_at
                ) VALUES ('boss', ?, ?, ?, ?, 0, 0, ?)
                """,
                (game_id, user.user_id, user.user_name, challenge_id, timestamp),
            )
            return BossSubmitResponse(
                correct=False,
                challenge_id=challenge_id,
                contribution=contribution_row["contribution"],
                boss_state=state_view,
                message="Flag 错误",
            )

        affinity_multiplier = {
            "normal": 1.0,
            "weak": 1.5,
            "resistant": 0.6,
            "shield": 1.25 if state_view.shield_active else 0.75,
        }.get(boss_challenge.affinity.lower(), 1.0)
        multiplier = affinity_multiplier
        if state_view.shield_active and not boss_challenge.is_shield_challenge:
            multiplier *= 0.5
        if boss_challenge.is_core_challenge:
            multiplier *= 2.0 if not state_view.shield_active else 0.25
        if state_view.enraged:
            multiplier *= boss_config.enrage_damage_multiplier
        calculated_damage = max(0, round(boss_challenge.base_damage * multiplier))
        damage = min(calculated_damage, state_view.hp)
        new_hp = state_view.hp - damage
        new_status = "defeated" if new_hp <= 0 else "active"
        new_phase = _boss_phase(new_hp, state_view.max_hp, boss_config)
        shield_active = (
            state_view.shield_active and not boss_challenge.is_shield_challenge
        )
        defeated_at = timestamp if new_status == "defeated" else None
        connection.execute(
            """
            UPDATE boss_states
            SET hp = ?, phase = ?, shield_active = ?, status = ?, version = version + 1,
                defeated_at = ?
            WHERE game_id = ?
            """,
            (new_hp, new_phase, int(shield_active), new_status, defeated_at, game_id),
        )
        connection.execute(
            """
            INSERT INTO arena_submissions(
                mode, game_id, user_id, user_name, challenge_id, correct, points, submitted_at
            ) VALUES ('boss', ?, ?, ?, ?, 1, ?, ?)
            """,
            (game_id, user.user_id, user.user_name, challenge_id, damage, timestamp),
        )
        contribution = int(contribution_row["contribution"]) + damage
        solves = int(contribution_row["solves"]) + 1
        connection.execute(
            """
            UPDATE boss_contributions
            SET user_name = ?, contribution = ?, solves = ?, updated_at = ?
            WHERE game_id = ? AND user_id = ?
            """,
            (user.user_name, contribution, solves, timestamp, game_id, user.user_id),
        )
        updated_state = connection.execute(
            "SELECT * FROM boss_states WHERE game_id = ?", (game_id,)
        ).fetchone()
        assert updated_state is not None
        return BossSubmitResponse(
            correct=True,
            challenge_id=challenge_id,
            damage=damage,
            contribution=contribution,
            boss_state=_boss_state_from_row(updated_state, boss_config),
            message="Flag 正确，已对 Boss 造成伤害",
        )


def get_pk_state(
    database: Database,
    game_id: int,
    user: UserIdentity,
    room_code: str | None = None,
) -> PkStateView:
    with database.connection() as connection:
        _load_pk_game(connection, game_id)
        if room_code is not None:
            room = _load_pk_room(connection, room_code, game_id)
            _require_pk_room_member(room, user)
            player = connection.execute(
                "SELECT * FROM pk_room_players WHERE room_code = ? AND user_id = ?",
                (room_code, user.user_id),
            ).fetchone()
            solved = connection.execute(
                """
                SELECT challenge_id FROM pk_room_submissions
                WHERE room_code = ? AND user_id = ? AND correct = 1
                ORDER BY challenge_id
                """,
                (room_code, user.user_id),
            ).fetchall()
            leaderboard = _pk_room_leaderboard(connection, room_code)
            return PkStateView(
                game_id=game_id,
                room_code=room_code,
                score=int(player["score"]) if player else 0,
                solves=int(player["solves"]) if player else 0,
                streak=int(player["streak"]) if player else 0,
                solved_challenge_ids=[int(row["challenge_id"]) for row in solved],
                leaderboard=leaderboard,
            )
        player = connection.execute(
            "SELECT * FROM pk_players WHERE game_id = ? AND user_id = ?",
            (game_id, user.user_id),
        ).fetchone()
        solved = connection.execute(
            """
            SELECT challenge_id FROM arena_submissions
            WHERE game_id = ? AND mode = 'pk' AND user_id = ? AND correct = 1
            ORDER BY challenge_id
            """,
            (game_id, user.user_id),
        ).fetchall()
        leaderboard = _pk_leaderboard(connection, game_id)
    return PkStateView(
        game_id=game_id,
        score=int(player["score"]) if player else 0,
        solves=int(player["solves"]) if player else 0,
        streak=int(player["streak"]) if player else 0,
        solved_challenge_ids=[int(row["challenge_id"]) for row in solved],
        leaderboard=leaderboard,
    )


def get_boss_state(
    database: Database, game_id: int, user: UserIdentity
) -> BossStateView:
    with database.transaction(immediate=True) as connection:
        game = connection.execute(
            """
            SELECT mode, boss_config_json FROM arena_games
            WHERE game_id = ? AND enabled = 1 AND published = 1
            """,
            (game_id,),
        ).fetchone()
        if game is None:
            raise ArenaRepositoryError(404, "竞技场不存在、未启用或尚未发布")
        if not _mode_allows(game["mode"], ChallengeMode.BOSS):
            raise ArenaRepositoryError(409, "当前赛事未开启 Boss 模式")
        boss_config = BossConfig.model_validate_json(game["boss_config_json"])
        state = _ensure_boss_state(connection, game_id, boss_config)
        contribution = connection.execute(
            """
            SELECT contribution FROM boss_contributions
            WHERE game_id = ? AND user_id = ?
            """,
            (game_id, user.user_id),
        ).fetchone()
        solved = connection.execute(
            """
            SELECT challenge_id FROM arena_submissions
            WHERE game_id = ? AND mode = 'boss' AND user_id = ? AND correct = 1
            ORDER BY challenge_id
            """,
            (game_id, user.user_id),
        ).fetchall()
        leaderboard = _boss_leaderboard(connection, game_id)
        state_view = _boss_state_from_row(state, boss_config)
    return BossStateView(
        game_id=game_id,
        contribution=int(contribution["contribution"]) if contribution else 0,
        solved_challenge_ids=[int(row["challenge_id"]) for row in solved],
        boss_state=state_view,
        leaderboard=leaderboard,
    )


def reset_runtime(database: Database, game_id: int, modes: list[RuntimeMode]) -> None:
    if not modes:
        raise ArenaRepositoryError(422, "modes 不能为空")
    with database.transaction(immediate=True) as connection:
        game = connection.execute(
            "SELECT * FROM arena_games WHERE game_id = ?", (game_id,)
        ).fetchone()
        if game is None:
            raise ArenaRepositoryError(404, "竞技场配置不存在")
        if RuntimeMode.PK in modes:
            now = _now()
            rooms = connection.execute(
                "SELECT * FROM pk_rooms WHERE game_id = ?", (game_id,)
            ).fetchall()
            for room in rooms:
                audit = _sync_pk_match_audit(connection, room, game, now)
                if audit["status"] in {
                    PkMatchStatus.WAITING.value,
                    PkMatchStatus.COUNTDOWN.value,
                    PkMatchStatus.ACTIVE.value,
                }:
                    _sync_pk_match_audit(
                        connection,
                        room,
                        game,
                        now,
                        forced_status=PkMatchStatus.RESET,
                        finish_reason=PkMatchFinishReason.ADMIN_RESET,
                    )
            connection.execute("DELETE FROM pk_rooms WHERE game_id = ?", (game_id,))
            connection.execute("DELETE FROM pk_players WHERE game_id = ?", (game_id,))
            connection.execute(
                "DELETE FROM arena_submissions WHERE game_id = ? AND mode = 'pk'",
                (game_id,),
            )
        if RuntimeMode.BOSS in modes:
            connection.execute(
                "DELETE FROM boss_contributions WHERE game_id = ?", (game_id,)
            )
            connection.execute(
                "DELETE FROM arena_submissions WHERE game_id = ? AND mode = 'boss'",
                (game_id,),
            )
            connection.execute("DELETE FROM boss_states WHERE game_id = ?", (game_id,))
            boss_config = BossConfig.model_validate_json(game["boss_config_json"])
            _insert_boss_state(connection, game_id, boss_config)
        if RuntimeMode.ONE_WAY in modes:
            now = _now()
            rooms = connection.execute(
                "SELECT * FROM one_way_rooms WHERE game_id = ?", (game_id,)
            ).fetchall()
            for room in rooms:
                room = _advance_one_way_room(connection, room, now)
                if room["status"] != OneWayMatchStatus.FINISHED.value:
                    _sync_one_way_match_audit(
                        connection,
                        room,
                        now,
                        forced_status=OneWayMatchStatus.RESET,
                        finish_reason=OneWayMatchFinishReason.ADMIN_RESET,
                    )
            connection.execute(
                "DELETE FROM one_way_rooms WHERE game_id = ?", (game_id,)
            )
