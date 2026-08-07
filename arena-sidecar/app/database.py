from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 4


DEFAULT_ONE_WAY_CONFIG_JSON = (
    '{"countdownSeconds":5,"roundCount":3,"roundSeconds":600,'
    '"intervalSeconds":5,"directions":[]}'
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS arena_games (
    game_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1)),
    mode TEXT NOT NULL,
    pk_config_json TEXT NOT NULL,
    boss_config_json TEXT NOT NULL,
    one_way_config_json TEXT NOT NULL DEFAULT
        '{"countdownSeconds":5,"roundCount":3,"roundSeconds":600,"intervalSeconds":5,"directions":[]}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS arena_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES arena_games(game_id) ON DELETE CASCADE,
    source_challenge_id INTEGER,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    target TEXT,
    attachment_url TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    modes_json TEXT NOT NULL,
    pk_json TEXT,
    boss_json TEXT,
    flag_hash TEXT,
    flag_case_sensitive INTEGER NOT NULL DEFAULT 1 CHECK (flag_case_sensitive IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_arena_challenges_game_order
ON arena_challenges(game_id, sort_order, id);

CREATE TABLE IF NOT EXISTS pk_players (
    game_id INTEGER NOT NULL REFERENCES arena_games(game_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    solves INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    last_submission_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (game_id, user_id)
);

CREATE TABLE IF NOT EXISTS boss_states (
    game_id INTEGER PRIMARY KEY REFERENCES arena_games(game_id) ON DELETE CASCADE,
    hp INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    phase INTEGER NOT NULL DEFAULT 1,
    shield_active INTEGER NOT NULL DEFAULT 0 CHECK (shield_active IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    defeated_at TEXT
);

CREATE TABLE IF NOT EXISTS boss_contributions (
    game_id INTEGER NOT NULL REFERENCES arena_games(game_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    contribution INTEGER NOT NULL DEFAULT 0,
    solves INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (game_id, user_id)
);

CREATE TABLE IF NOT EXISTS arena_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL CHECK (mode IN ('pk', 'boss')),
    game_id INTEGER NOT NULL REFERENCES arena_games(game_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    challenge_id INTEGER NOT NULL REFERENCES arena_challenges(id) ON DELETE CASCADE,
    correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
    points INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_arena_submissions_lookup
ON arena_submissions(game_id, mode, user_id, challenge_id, submitted_at);

CREATE UNIQUE INDEX IF NOT EXISTS ux_arena_correct_solve
ON arena_submissions(game_id, mode, user_id, challenge_id)
WHERE correct = 1;

CREATE TABLE IF NOT EXISTS pk_rooms (
    code TEXT PRIMARY KEY
        CHECK (length(code) = 6 AND code NOT GLOB '*[^0-9]*'),
    game_id INTEGER NOT NULL REFERENCES arena_games(game_id) ON DELETE CASCADE,
    host_user_id TEXT NOT NULL,
    host_user_name TEXT NOT NULL,
    guest_user_id TEXT,
    guest_user_name TEXT,
    created_at TEXT NOT NULL,
    starts_at TEXT,
    updated_at TEXT NOT NULL,
    CHECK (
        (guest_user_id IS NULL AND guest_user_name IS NULL AND starts_at IS NULL)
        OR
        (guest_user_id IS NOT NULL AND guest_user_name IS NOT NULL
            AND guest_user_id <> host_user_id AND starts_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_pk_rooms_game_created
ON pk_rooms(game_id, created_at);

CREATE TABLE IF NOT EXISTS pk_room_players (
    room_code TEXT NOT NULL REFERENCES pk_rooms(code) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    solves INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    last_submission_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (room_code, user_id)
);

CREATE TABLE IF NOT EXISTS pk_room_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code TEXT NOT NULL REFERENCES pk_rooms(code) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    challenge_id INTEGER NOT NULL REFERENCES arena_challenges(id) ON DELETE CASCADE,
    correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
    points INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_pk_room_submissions_lookup
ON pk_room_submissions(room_code, user_id, challenge_id, submitted_at);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pk_room_correct_solve
ON pk_room_submissions(room_code, user_id, challenge_id)
WHERE correct = 1;

CREATE TABLE IF NOT EXISTS pk_match_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    room_code TEXT NOT NULL
        CHECK (length(room_code) = 6 AND room_code NOT GLOB '*[^0-9]*'),
    host_user_id TEXT NOT NULL,
    host_user_name TEXT NOT NULL,
    guest_user_id TEXT,
    guest_user_name TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('waiting', 'countdown', 'active', 'finished', 'cancelled', 'reset')),
    host_score INTEGER NOT NULL DEFAULT 0,
    host_solves INTEGER NOT NULL DEFAULT 0,
    guest_score INTEGER NOT NULL DEFAULT 0,
    guest_solves INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    joined_at TEXT,
    starts_at TEXT,
    ends_at TEXT,
    finished_at TEXT,
    finish_reason TEXT
        CHECK (finish_reason IS NULL OR finish_reason IN ('timeout', 'player_left', 'admin_reset')),
    winner_user_id TEXT,
    winner_user_name TEXT,
    is_draw INTEGER NOT NULL DEFAULT 0 CHECK (is_draw IN (0, 1)),
    updated_at TEXT NOT NULL,
    CHECK (
        (guest_user_id IS NULL AND guest_user_name IS NULL)
        OR (guest_user_id IS NOT NULL AND guest_user_name IS NOT NULL)
    ),
    CHECK (
        (winner_user_id IS NULL AND winner_user_name IS NULL)
        OR (winner_user_id IS NOT NULL AND winner_user_name IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_pk_match_audits_game_created
ON pk_match_audits(game_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_pk_match_audits_game_status_created
ON pk_match_audits(game_id, status, created_at DESC, id DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pk_match_audits_live_room
ON pk_match_audits(room_code)
WHERE status IN ('waiting', 'countdown', 'active');

CREATE TABLE IF NOT EXISTS one_way_match_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    room_code TEXT NOT NULL
        CHECK (length(room_code) = 6 AND room_code NOT GLOB '*[^0-9]*'),
    direction_id TEXT NOT NULL,
    direction_name TEXT NOT NULL,
    direction_description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL,
    host_user_id TEXT NOT NULL,
    host_user_name TEXT NOT NULL,
    guest_user_id TEXT,
    guest_user_name TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('waiting', 'countdown', 'active', 'interval',
                   'finished', 'cancelled', 'reset')
    ),
    current_round INTEGER NOT NULL DEFAULT 0,
    total_rounds INTEGER NOT NULL,
    host_round_wins INTEGER NOT NULL DEFAULT 0,
    guest_round_wins INTEGER NOT NULL DEFAULT 0,
    round_draws INTEGER NOT NULL DEFAULT 0,
    rounds_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    joined_at TEXT,
    starts_at TEXT,
    finished_at TEXT,
    finish_reason TEXT CHECK (
        finish_reason IS NULL OR
        finish_reason IN ('completed', 'player_left', 'admin_reset')
    ),
    winner_user_id TEXT,
    winner_user_name TEXT,
    is_draw INTEGER NOT NULL DEFAULT 0 CHECK (is_draw IN (0, 1)),
    updated_at TEXT NOT NULL,
    CHECK (
        (guest_user_id IS NULL AND guest_user_name IS NULL)
        OR (guest_user_id IS NOT NULL AND guest_user_name IS NOT NULL)
    ),
    CHECK (
        (winner_user_id IS NULL AND winner_user_name IS NULL)
        OR (winner_user_id IS NOT NULL AND winner_user_name IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_one_way_match_audits_game_created
ON one_way_match_audits(game_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_one_way_match_audits_game_status_created
ON one_way_match_audits(game_id, status, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS one_way_rooms (
    code TEXT PRIMARY KEY
        CHECK (length(code) = 6 AND code NOT GLOB '*[^0-9]*'),
    game_id INTEGER NOT NULL REFERENCES arena_games(game_id) ON DELETE CASCADE,
    audit_id INTEGER NOT NULL UNIQUE REFERENCES one_way_match_audits(id),
    direction_id TEXT NOT NULL,
    direction_name TEXT NOT NULL,
    direction_description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL,
    host_user_id TEXT NOT NULL,
    host_user_name TEXT NOT NULL,
    guest_user_id TEXT,
    guest_user_name TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('waiting', 'countdown', 'active', 'interval', 'finished')
    ),
    current_round INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    joined_at TEXT,
    starts_at TEXT,
    finished_at TEXT,
    winner_user_id TEXT,
    winner_user_name TEXT,
    is_draw INTEGER NOT NULL DEFAULT 0 CHECK (is_draw IN (0, 1)),
    updated_at TEXT NOT NULL,
    CHECK (
        (guest_user_id IS NULL AND guest_user_name IS NULL
             AND joined_at IS NULL AND starts_at IS NULL)
        OR
        (guest_user_id IS NOT NULL AND guest_user_name IS NOT NULL
             AND guest_user_id <> host_user_id
             AND joined_at IS NOT NULL AND starts_at IS NOT NULL)
    ),
    CHECK (
        (winner_user_id IS NULL AND winner_user_name IS NULL)
        OR (winner_user_id IS NOT NULL AND winner_user_name IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_one_way_rooms_game_created
ON one_way_rooms(game_id, created_at DESC, code);

CREATE TABLE IF NOT EXISTS one_way_rounds (
    room_code TEXT NOT NULL REFERENCES one_way_rooms(code) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    challenge_id INTEGER NOT NULL,
    challenge_title TEXT NOT NULL,
    challenge_snapshot_json TEXT NOT NULL,
    flag_hash TEXT NOT NULL,
    flag_case_sensitive INTEGER NOT NULL DEFAULT 1 CHECK (flag_case_sensitive IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'finished')),
    starts_at TEXT,
    ends_at TEXT,
    finished_at TEXT,
    winner_user_id TEXT,
    winner_user_name TEXT,
    is_draw INTEGER NOT NULL DEFAULT 0 CHECK (is_draw IN (0, 1)),
    PRIMARY KEY (room_code, round_number),
    CHECK (round_number >= 1),
    CHECK (
        (winner_user_id IS NULL AND winner_user_name IS NULL)
        OR (winner_user_id IS NOT NULL AND winner_user_name IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS one_way_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code TEXT NOT NULL REFERENCES one_way_rooms(code) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    challenge_id INTEGER NOT NULL,
    correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
    submitted_at TEXT NOT NULL,
    FOREIGN KEY (room_code, round_number)
        REFERENCES one_way_rounds(room_code, round_number) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_one_way_submissions_lookup
ON one_way_submissions(room_code, round_number, user_id, submitted_at);

CREATE UNIQUE INDEX IF NOT EXISTS ux_one_way_round_correct_submission
ON one_way_submissions(room_code, round_number)
WHERE correct = 1;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            row = connection.execute(
                "SELECT version FROM schema_info LIMIT 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,)
                )
            elif int(row["version"]) in {1, 2}:
                # SCHEMA is the idempotent structural migration. Version 3 also
                # backfills every live v2 room into the durable PK match audit
                # table before advancing the version, without rewriting or
                # deleting any existing arena/runtime row.
                self._backfill_pk_match_audits(connection)
                self._migrate_to_v4(connection)
                connection.execute(
                    "UPDATE schema_info SET version = ?", (SCHEMA_VERSION,)
                )
            elif int(row["version"]) == 3:
                self._migrate_to_v4(connection)
                connection.execute(
                    "UPDATE schema_info SET version = ?", (SCHEMA_VERSION,)
                )
            elif int(row["version"]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported arena database schema {row['version']}; expected {SCHEMA_VERSION}"
                )

    @staticmethod
    def _migrate_to_v4(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(arena_games)")
        }
        if "one_way_config_json" not in columns:
            escaped_default = DEFAULT_ONE_WAY_CONFIG_JSON.replace("'", "''")
            connection.execute(
                "ALTER TABLE arena_games "
                "ADD COLUMN one_way_config_json TEXT NOT NULL "
                f"DEFAULT '{escaped_default}'"
            )

    @staticmethod
    def _backfill_pk_match_audits(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT
                room.*,
                game.pk_config_json,
                COALESCE(host.score, 0) AS host_score,
                COALESCE(host.solves, 0) AS host_solves,
                COALESCE(guest.score, 0) AS guest_score,
                COALESCE(guest.solves, 0) AS guest_solves
            FROM pk_rooms AS room
            JOIN arena_games AS game ON game.game_id = room.game_id
            LEFT JOIN pk_room_players AS host
              ON host.room_code = room.code AND host.user_id = room.host_user_id
            LEFT JOIN pk_room_players AS guest
              ON guest.room_code = room.code AND guest.user_id = room.guest_user_id
            WHERE NOT EXISTS (
                SELECT 1 FROM pk_match_audits AS audit
                WHERE audit.room_code = room.code
            )
            ORDER BY room.created_at, room.code
            """
        ).fetchall()
        now = datetime.now(UTC)
        for row in rows:
            config = json.loads(row["pk_config_json"] or "{}")
            match_seconds = int(config.get("matchSeconds", 1800))
            starts_at = Database._parse_timestamp(row["starts_at"])
            ends_at = (
                starts_at + timedelta(seconds=match_seconds) if starts_at else None
            )
            if row["guest_user_id"] is None or starts_at is None:
                match_status = "waiting"
            elif now < starts_at:
                match_status = "countdown"
            elif ends_at is not None and now < ends_at:
                match_status = "active"
            else:
                match_status = "finished"

            joined_at = starts_at - timedelta(seconds=5) if starts_at else None
            finished_at = ends_at if match_status == "finished" else None
            finish_reason = "timeout" if match_status == "finished" else None
            winner_id: str | None = None
            winner_name: str | None = None
            is_draw = False
            if match_status == "finished" and row["guest_user_id"] is not None:
                if config.get("winRule") == "most_solves":
                    host_primary = int(row["host_solves"])
                    guest_primary = int(row["guest_solves"])
                    host_secondary = int(row["host_score"])
                    guest_secondary = int(row["guest_score"])
                else:
                    host_primary = int(row["host_score"])
                    guest_primary = int(row["guest_score"])
                    host_secondary = int(row["host_solves"])
                    guest_secondary = int(row["guest_solves"])
                if host_primary > guest_primary:
                    winner_id = row["host_user_id"]
                    winner_name = row["host_user_name"]
                elif guest_primary > host_primary:
                    winner_id = row["guest_user_id"]
                    winner_name = row["guest_user_name"]
                elif not bool(config.get("allowDraw", False)) and (
                    host_secondary != guest_secondary
                ):
                    if host_secondary > guest_secondary:
                        winner_id = row["host_user_id"]
                        winner_name = row["host_user_name"]
                    else:
                        winner_id = row["guest_user_id"]
                        winner_name = row["guest_user_name"]
                else:
                    is_draw = True

            connection.execute(
                """
                INSERT INTO pk_match_audits(
                    game_id, room_code, host_user_id, host_user_name,
                    guest_user_id, guest_user_name, status,
                    host_score, host_solves, guest_score, guest_solves,
                    created_at, joined_at, starts_at, ends_at, finished_at,
                    finish_reason, winner_user_id, winner_user_name, is_draw, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["game_id"]),
                    row["code"],
                    row["host_user_id"],
                    row["host_user_name"],
                    row["guest_user_id"],
                    row["guest_user_name"],
                    match_status,
                    int(row["host_score"]),
                    int(row["host_solves"]),
                    int(row["guest_score"]),
                    int(row["guest_solves"]),
                    row["created_at"],
                    joined_at.isoformat() if joined_at else None,
                    starts_at.isoformat() if starts_at else None,
                    ends_at.isoformat() if ends_at else None,
                    finished_at.isoformat() if finished_at else None,
                    finish_reason,
                    winner_id,
                    winner_name,
                    int(is_draw),
                    row["updated_at"],
                ),
            )

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=15,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
