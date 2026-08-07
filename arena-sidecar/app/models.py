from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
OptionalShortText = Annotated[str | None, StringConstraints(max_length=200)]
RoomCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class ArenaMode(StrEnum):
    CLASSIC = "classic"
    SOLO_PK = "solo_pk"
    BOSS_RAID = "boss_raid"
    HYBRID = "hybrid"
    ONE_WAY_ONEBYONE = "one_way_onebyone"


class ChallengeMode(StrEnum):
    PK = "pk"
    BOSS = "boss"
    ONE_WAY = "one_way"


class RuntimeMode(StrEnum):
    PK = "pk"
    BOSS = "boss"
    ONE_WAY = "one_way"


class ScoreMode(StrEnum):
    FIXED = "fixed"
    DYNAMIC = "dynamic"


class WinRule(StrEnum):
    HIGHEST_SCORE = "highest_score"
    FIRST_TO_TARGET = "first_to_target"
    MOST_SOLVES = "most_solves"


class PkMatchStatus(StrEnum):
    WAITING = "waiting"
    COUNTDOWN = "countdown"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    RESET = "reset"


class PkMatchFinishReason(StrEnum):
    TIMEOUT = "timeout"
    PLAYER_LEFT = "player_left"
    ADMIN_RESET = "admin_reset"


class OneWayMatchStatus(StrEnum):
    WAITING = "waiting"
    COUNTDOWN = "countdown"
    ACTIVE = "active"
    INTERVAL = "interval"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    RESET = "reset"


class OneWayRoundStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    FINISHED = "finished"


class OneWayMatchFinishReason(StrEnum):
    COMPLETED = "completed"
    PLAYER_LEFT = "player_left"
    ADMIN_RESET = "admin_reset"


class PkConfig(ApiModel):
    team_size: int = Field(default=1, ge=1, le=5)
    match_seconds: int = Field(default=1800, ge=60, le=86_400)
    question_count: int = Field(default=8, ge=1, le=100)
    score_mode: ScoreMode = ScoreMode.FIXED
    win_rule: WinRule = WinRule.HIGHEST_SCORE
    target_score: int | None = Field(default=None, ge=1, le=10_000_000)
    allow_draw: bool = False
    wrong_penalty: int = Field(default=0, ge=0, le=100_000)
    cooldown_seconds: int = Field(default=3, ge=0, le=3600)
    first_blood_bonus: int = Field(default=100, ge=0, le=100_000)
    streak_bonus: int = Field(default=25, ge=0, le=100_000)
    same_questions_for_both: bool = True

    @model_validator(mode="after")
    def validate_target(self) -> "PkConfig":
        if self.win_rule == WinRule.FIRST_TO_TARGET and self.target_score is None:
            raise ValueError("targetScore is required when winRule is first_to_target")
        return self


class BossConfig(ApiModel):
    name: ShortText = "末影方块巨兽"
    max_hp: int = Field(default=100_000, ge=1, le=2_000_000_000)
    phase_count: int = Field(default=3, ge=1, le=10)
    phase_thresholds: list[float] = Field(
        default_factory=lambda: [0.66, 0.33], max_length=9
    )
    enrage_seconds: int = Field(default=7200, ge=60, le=2_592_000)
    enrage_damage_multiplier: float = Field(default=0.75, ge=0.05, le=5)
    min_team_contribution: int = Field(default=1000, ge=0, le=2_000_000_000)
    shield_enabled: bool = True

    @model_validator(mode="after")
    def validate_thresholds(self) -> "BossConfig":
        if len(self.phase_thresholds) != self.phase_count - 1:
            raise ValueError("phaseThresholds must contain phaseCount - 1 items")
        if any(value <= 0 or value >= 1 for value in self.phase_thresholds):
            raise ValueError("phaseThresholds values must be between 0 and 1")
        if self.phase_thresholds != sorted(self.phase_thresholds, reverse=True):
            raise ValueError("phaseThresholds must be in descending order")
        return self


DirectionId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]


class OneWayDirectionConfig(ApiModel):
    id: DirectionId
    name: ShortText
    description: Annotated[str, StringConstraints(max_length=1000)] = ""
    challenge_ids: list[int] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_challenge_ids(self) -> "OneWayDirectionConfig":
        if any(challenge_id < 1 for challenge_id in self.challenge_ids):
            raise ValueError("challengeIds must contain positive integers")
        if len(self.challenge_ids) != len(set(self.challenge_ids)):
            raise ValueError("challengeIds must be unique within a direction")
        return self


class OneWayDirectionPublicView(ApiModel):
    id: DirectionId
    name: str
    description: str = ""


class OneWayConfig(ApiModel):
    countdown_seconds: int = Field(default=5, ge=1, le=300)
    round_count: int = Field(default=3, ge=1, le=50)
    round_seconds: int = Field(default=600, ge=10, le=86_400)
    interval_seconds: int = Field(default=5, ge=1, le=3600)
    directions: list[OneWayDirectionConfig] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def validate_directions(self) -> "OneWayConfig":
        direction_ids = [direction.id for direction in self.directions]
        if len(direction_ids) != len(set(direction_ids)):
            raise ValueError("direction ids must be unique")
        return self


class OneWayPublicConfig(ApiModel):
    countdown_seconds: int
    round_count: int
    round_seconds: int
    interval_seconds: int
    directions: list[OneWayDirectionPublicView]


class PkChallengeConfig(ApiModel):
    variant_group: OptionalShortText = None
    base_score: int = Field(default=500, ge=0, le=10_000_000)
    time_limit_seconds: int | None = Field(default=None, ge=10, le=86_400)


class BossChallengeConfig(ApiModel):
    base_damage: int = Field(default=1000, ge=0, le=2_000_000_000)
    phase: int = Field(default=1, ge=1, le=10)
    affinity: Annotated[str, StringConstraints(min_length=1, max_length=64)] = "normal"
    is_shield_challenge: bool = False
    is_core_challenge: bool = False


class ChallengeBase(ApiModel):
    source_challenge_id: int | None = Field(default=None, ge=1)
    title: ShortText
    category: Annotated[str, StringConstraints(min_length=1, max_length=100)] = "Misc"
    difficulty: Annotated[str, StringConstraints(min_length=1, max_length=64)] = (
        "normal"
    )
    description: Annotated[str, StringConstraints(max_length=50_000)] = ""
    target: OptionalShortText = None
    attachment_url: Annotated[str | None, StringConstraints(max_length=2048)] = None
    status: Annotated[str, StringConstraints(min_length=1, max_length=64)] = "active"
    enabled: bool = True
    sort_order: int = Field(default=0, ge=-1_000_000, le=1_000_000)
    modes: list[ChallengeMode] = Field(default_factory=lambda: [ChallengeMode.PK])
    pk: PkChallengeConfig | None = None
    boss: BossChallengeConfig | None = None
    flag_case_sensitive: bool = True

    @model_validator(mode="after")
    def validate_mode_configs(self) -> "ChallengeBase":
        if not self.modes or len(set(self.modes)) != len(self.modes):
            raise ValueError("modes must contain one or more unique values")
        if ChallengeMode.PK in self.modes and self.pk is None:
            raise ValueError("pk config is required when modes contains pk")
        if ChallengeMode.BOSS in self.modes and self.boss is None:
            raise ValueError("boss config is required when modes contains boss")
        return self


class ChallengeWrite(ChallengeBase):
    id: int | None = Field(default=None, ge=1)
    flag: Annotated[str | None, StringConstraints(min_length=1, max_length=1024)] = (
        Field(
            default=None,
            description="Write-only flag. Omit it on updates to preserve the stored flag.",
        )
    )
    clear_flag: bool = False

    @model_validator(mode="after")
    def validate_flag_operation(self) -> "ChallengeWrite":
        if self.flag is not None and self.clear_flag:
            raise ValueError("flag and clearFlag cannot be supplied together")
        return self


class ChallengeAdminView(ChallengeBase):
    id: int
    has_flag: bool


class ChallengePublicView(ApiModel):
    id: int
    source_challenge_id: int | None = None
    title: str
    category: str
    difficulty: str
    description: str
    target: str | None = None
    attachment_url: str | None = None
    status: str
    enabled: bool = True
    sort_order: int
    modes: list[ChallengeMode]
    pk: PkChallengeConfig | None = None
    boss: BossChallengeConfig | None = None
    flag_case_sensitive: bool = True
    locked: bool = False
    solved: bool = False


class ArenaConfigWrite(ApiModel):
    game_id: int | None = Field(default=None, ge=1)
    enabled: bool = False
    published: bool = False
    mode: ArenaMode = ArenaMode.HYBRID
    pk_config: PkConfig = Field(default_factory=PkConfig)
    boss_config: BossConfig = Field(default_factory=BossConfig)
    one_way_config: OneWayConfig | None = Field(
        default=None,
        description="Omit on update to preserve the stored one-way configuration.",
    )
    challenges: list[ChallengeWrite] = Field(default_factory=list, max_length=1000)
    revision: int | None = Field(
        default=None,
        ge=0,
        description="Optional optimistic-lock revision returned by GET.",
    )


class ArenaAdminView(ApiModel):
    game_id: int
    exists: bool
    enabled: bool
    published: bool
    mode: ArenaMode
    pk_config: PkConfig
    boss_config: BossConfig
    one_way_config: OneWayConfig
    challenges: list[ChallengeAdminView]
    revision: int
    updated_at: datetime | None = None


class BossPublicState(ApiModel):
    status: Literal["active", "defeated"]
    hp: int
    max_hp: int
    phase: int
    shield_active: bool
    enraged: bool
    version: int
    started_at: datetime
    defeated_at: datetime | None = None


class LeaderboardEntry(ApiModel):
    rank: int
    user_id: str
    user_name: str
    score: int = 0
    solves: int = 0
    contribution: int = 0


class ArenaPublicView(ApiModel):
    game_id: int
    enabled: bool
    published: bool = True
    mode: ArenaMode
    pk_config: PkConfig
    boss_config: BossConfig
    one_way_config: OneWayPublicConfig
    challenges: list[ChallengePublicView]
    revision: int
    updated_at: datetime
    boss_state: BossPublicState | None = None


class SubmitRequest(ApiModel):
    game_id: int = Field(ge=1)
    challenge_id: int = Field(ge=1)
    flag: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class PkSubmitRequest(SubmitRequest):
    room_code: RoomCode | None = None


class PkSubmitResponse(ApiModel):
    correct: bool
    already_solved: bool = False
    challenge_id: int
    score_delta: int = 0
    score: int
    solves: int
    first_blood: bool = False
    streak: int = 0
    message: str
    room_code: RoomCode | None = None


class BossSubmitResponse(ApiModel):
    correct: bool
    already_solved: bool = False
    challenge_id: int
    damage: int = 0
    contribution: int
    boss_state: BossPublicState
    message: str


class PkStateView(ApiModel):
    game_id: int
    room_code: RoomCode | None = None
    score: int
    solves: int
    streak: int
    solved_challenge_ids: list[int]
    leaderboard: list[LeaderboardEntry]


class PkRoomRequest(ApiModel):
    game_id: int = Field(ge=1)


class PkRoomPlayerView(ApiModel):
    user_id: str
    user_name: str
    score: int = 0
    solves: int = 0


class PkRoomView(ApiModel):
    code: RoomCode
    game_id: int
    status: Literal["waiting", "countdown", "active", "finished"]
    host: PkRoomPlayerView
    guest: PkRoomPlayerView | None = None
    current_user_role: Literal["host", "guest"]
    created_at: datetime
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    server_time: datetime


class PkMatchAdminPlayerView(ApiModel):
    user_id: str
    user_name: str
    score: int = 0
    solves: int = 0


class PkMatchAdminView(ApiModel):
    match_id: int
    game_id: int
    room_code: RoomCode
    room_exists: bool
    status: PkMatchStatus
    host: PkMatchAdminPlayerView
    guest: PkMatchAdminPlayerView | None = None
    winner: PkMatchAdminPlayerView | None = None
    is_draw: bool = False
    created_at: datetime
    joined_at: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    finished_at: datetime | None = None
    finish_reason: PkMatchFinishReason | None = None
    updated_at: datetime


class OneWayRoomRequest(ApiModel):
    game_id: int = Field(ge=1)


class OneWayRoomJoinRequest(ApiModel):
    game_id: int | None = Field(default=None, ge=1)


class OneWayRoomCreateRequest(OneWayRoomRequest):
    direction_id: DirectionId


class OneWayRoomPlayerView(ApiModel):
    user_id: str
    user_name: str
    round_wins: int = 0


class OneWayRoundView(ApiModel):
    round_number: int
    status: OneWayRoundStatus
    challenge_id: int | None = None
    challenge_title: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    finished_at: datetime | None = None
    winner: OneWayRoomPlayerView | None = None
    is_draw: bool = False


class OneWayRoomView(ApiModel):
    code: RoomCode
    game_id: int
    direction: OneWayDirectionPublicView
    status: Literal["waiting", "countdown", "active", "interval", "finished"]
    host: OneWayRoomPlayerView
    guest: OneWayRoomPlayerView | None = None
    current_user_role: Literal["host", "guest"]
    created_at: datetime
    starts_at: datetime | None = None
    current_round: int = 0
    total_rounds: int
    current_challenge_id: int | None = None
    current_challenge: ChallengePublicView | None = None
    round_starts_at: datetime | None = None
    round_ends_at: datetime | None = None
    next_round_starts_at: datetime | None = None
    rounds: list[OneWayRoundView]
    host_round_wins: int = 0
    guest_round_wins: int = 0
    winner: OneWayRoomPlayerView | None = None
    is_draw: bool = False
    finished_at: datetime | None = None
    server_time: datetime


class OneWaySubmitRequest(SubmitRequest):
    room_code: RoomCode


class OneWaySubmitResponse(ApiModel):
    correct: bool
    already_resolved: bool = False
    challenge_id: int
    round_number: int
    message: str
    room: OneWayRoomView


class OneWayMatchRoundAdminView(ApiModel):
    round_number: int
    status: OneWayRoundStatus
    challenge_id: int
    challenge_title: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    finished_at: datetime | None = None
    winner_user_id: str | None = None
    winner_user_name: str | None = None
    is_draw: bool = False


class OneWayMatchAdminView(ApiModel):
    match_id: int
    game_id: int
    room_code: RoomCode
    room_exists: bool
    status: OneWayMatchStatus
    direction: OneWayDirectionPublicView
    host: OneWayRoomPlayerView
    guest: OneWayRoomPlayerView | None = None
    current_round: int = 0
    total_rounds: int
    host_round_wins: int = 0
    guest_round_wins: int = 0
    round_draws: int = 0
    rounds: list[OneWayMatchRoundAdminView]
    winner: OneWayRoomPlayerView | None = None
    is_draw: bool = False
    created_at: datetime
    joined_at: datetime | None = None
    starts_at: datetime | None = None
    finished_at: datetime | None = None
    finish_reason: OneWayMatchFinishReason | None = None
    updated_at: datetime


class BossStateView(ApiModel):
    game_id: int
    contribution: int
    solved_challenge_ids: list[int]
    boss_state: BossPublicState
    leaderboard: list[LeaderboardEntry]


class ResetRequest(ApiModel):
    modes: list[RuntimeMode] = Field(
        default_factory=lambda: [
            RuntimeMode.PK,
            RuntimeMode.BOSS,
            RuntimeMode.ONE_WAY,
        ]
    )


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(ApiModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    expires_in: int


class UserIdentity(ApiModel):
    user_id: str
    user_name: str
    role: str
