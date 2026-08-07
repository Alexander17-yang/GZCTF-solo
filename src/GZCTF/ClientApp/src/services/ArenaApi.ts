import api, { ContentType } from '@Api'

export type ArenaMode = 'classic' | 'solo_pk' | 'one_way_onebyone' | 'boss_raid' | 'hybrid'
export type ArenaChallengeMode = 'pk' | 'one_way' | 'boss'
export type PkScoreMode = 'fixed' | 'dynamic'
export type PkWinRule = 'highest_score' | 'first_to_target' | 'most_solves'
export type ArenaDifficulty = string
export type BossAffinity = string

export interface PkModeConfig {
  teamSize: number
  matchSeconds: number
  questionCount: number
  scoreMode: PkScoreMode
  winRule: PkWinRule
  targetScore: number | null
  allowDraw: boolean
  wrongPenalty: number
  cooldownSeconds: number
  firstBloodBonus: number
  streakBonus: number
  sameQuestionsForBoth: boolean
}

export interface BossModeConfig {
  name: string
  maxHp: number
  phaseCount: number
  phaseThresholds: number[]
  enrageSeconds: number
  enrageDamageMultiplier: number
  minTeamContribution: number
  shieldEnabled: boolean
}

export interface OneWayDirection {
  id: string
  name: string
  description?: string | null
}

export interface OneWayDirectionConfig extends OneWayDirection {
  challengeIds: number[]
}

export interface OneWayModeConfig {
  countdownSeconds: number
  roundCount: number
  roundSeconds: number
  intervalSeconds: number
  directions: OneWayDirectionConfig[]
}

export interface OneWayPublicModeConfig extends Omit<OneWayModeConfig, 'directions'> {
  directions: OneWayDirection[]
}

export interface ArenaPkChallengeConfig {
  variantGroup: string | null
  baseScore: number
  timeLimitSeconds: number | null
}

export interface ArenaBossChallengeConfig {
  baseDamage: number
  phase: number
  affinity: BossAffinity
  isShieldChallenge: boolean
  isCoreChallenge: boolean
}

export interface ArenaChallengeConfig {
  id?: number | null
  sourceChallengeId: number | null
  title: string
  description: string
  target: string | null
  attachmentUrl: string | null
  status: string
  category: string
  difficulty: ArenaDifficulty
  enabled: boolean
  sortOrder: number
  modes: ArenaChallengeMode[]
  pk: ArenaPkChallengeConfig | null
  boss: ArenaBossChallengeConfig | null
  flagCaseSensitive: boolean
  /** Admin GET only: whether a write-only flag is stored. */
  hasFlag?: boolean
  /** Admin PUT only: omit/null to preserve the existing flag. */
  flag?: string | null
  /** Admin PUT only: explicitly delete the existing flag. */
  clearFlag?: boolean
}

export interface ArenaGameConfig {
  gameId: number
  exists?: boolean
  enabled: boolean
  published: boolean
  mode: ArenaMode
  revision: number
  pkConfig: PkModeConfig
  oneWayConfig: OneWayModeConfig
  bossConfig: BossModeConfig
  challenges: ArenaChallengeConfig[]
  updatedAt?: string | null
}

export interface ArenaGameConfigUpdate {
  gameId?: number | null
  enabled: boolean
  published: boolean
  mode: ArenaMode
  pkConfig: PkModeConfig
  oneWayConfig: OneWayModeConfig
  bossConfig: BossModeConfig
  challenges: ArenaChallengeConfig[]
  revision?: number | null
}

export interface BossPublicState {
  status: 'active' | 'defeated'
  hp: number
  maxHp: number
  phase: number
  shieldActive: boolean
  enraged: boolean
  version: number
  startedAt: string
  defeatedAt: string | null
}

export interface ArenaPublicChallenge {
  id: number
  sourceChallengeId: number | null
  title: string
  category: string
  difficulty: string
  description: string
  target: string | null
  attachmentUrl: string | null
  status: string
  enabled: boolean
  sortOrder: number
  modes: ArenaChallengeMode[]
  pk: ArenaPkChallengeConfig | null
  boss: ArenaBossChallengeConfig | null
  flagCaseSensitive: boolean
  locked: boolean
  solved: boolean
}

export interface ArenaPublicGame {
  gameId: number
  enabled: boolean
  mode: ArenaMode
  pkConfig: PkModeConfig
  oneWayConfig: OneWayPublicModeConfig
  bossConfig: BossModeConfig
  challenges: ArenaPublicChallenge[]
  revision: number
  updatedAt: string
  bossState: BossPublicState | null
}

export interface ArenaLeaderboardEntry {
  rank: number
  userId: string
  userName: string
  score: number
  solves: number
  contribution: number
}

export interface ArenaSubmitRequest {
  gameId: number
  challengeId: number
  flag: string
}

export interface PkSubmitRequest extends ArenaSubmitRequest {
  roomCode?: string
}

export type PkRoomStatus = 'waiting' | 'countdown' | 'active' | 'finished'
export type PkRoomRole = 'host' | 'guest'

export type AdminPkMatchStatus = PkRoomStatus | 'cancelled' | 'reset'
export type AdminPkMatchFinishReason = 'timeout' | 'player_left' | 'admin_reset'

export interface AdminPkMatchPlayer {
  userId: string
  userName: string
  score: number
  solves: number
}

export interface AdminPkMatchRecord {
  matchId: number
  gameId: number
  roomCode: string
  roomExists: boolean
  status: AdminPkMatchStatus
  host: AdminPkMatchPlayer
  guest: AdminPkMatchPlayer | null
  winner: AdminPkMatchPlayer | null
  isDraw: boolean
  createdAt: string
  joinedAt: string | null
  startsAt: string | null
  endsAt: string | null
  finishedAt: string | null
  finishReason: AdminPkMatchFinishReason | null
  updatedAt: string
}

export interface PkRoomPlayer {
  userId: string
  userName: string
  score: number
  solves: number
}

export interface PkRoomView {
  code: string
  gameId: number
  status: PkRoomStatus
  host: PkRoomPlayer
  guest: PkRoomPlayer | null
  currentUserRole: PkRoomRole
  createdAt: string
  startsAt: string | null
  endsAt: string | null
  serverTime: string
}

export interface PkStateView {
  gameId: number
  score: number
  solves: number
  streak: number
  solvedChallengeIds: number[]
  leaderboard: ArenaLeaderboardEntry[]
}

export interface PkSubmitResponse {
  correct: boolean
  alreadySolved: boolean
  challengeId: number
  scoreDelta: number
  score: number
  solves: number
  firstBlood: boolean
  streak: number
  message: string
}

export type OneWayRoomStatus = 'waiting' | 'countdown' | 'active' | 'interval' | 'finished'
export type OneWayRoomRole = 'host' | 'guest'

export interface OneWayRoomPlayer {
  userId: string
  userName: string
  roundWins: number
}

export interface OneWayRoundView {
  roundNumber: number
  status: 'pending' | 'active' | 'finished'
  challengeId: number | null
  challengeTitle: string | null
  startsAt: string | null
  endsAt: string | null
  finishedAt: string | null
  winner: OneWayRoomPlayer | null
  isDraw: boolean
}

export interface OneWayRoomView {
  code: string
  gameId: number
  status: OneWayRoomStatus
  direction: OneWayDirection
  host: OneWayRoomPlayer
  guest: OneWayRoomPlayer | null
  currentUserRole: OneWayRoomRole
  createdAt: string
  startsAt: string | null
  currentRound: number
  totalRounds: number
  currentChallengeId: number | null
  currentChallenge: ArenaPublicChallenge | null
  roundStartsAt: string | null
  roundEndsAt: string | null
  nextRoundStartsAt: string | null
  rounds: OneWayRoundView[]
  hostRoundWins: number
  guestRoundWins: number
  winner: OneWayRoomPlayer | null
  isDraw: boolean
  finishedAt: string | null
  serverTime: string
}

export interface OneWaySubmitRequest {
  gameId: number
  roomCode: string
  challengeId: number
  flag: string
}

export interface OneWaySubmitResponse {
  correct: boolean
  alreadyResolved: boolean
  challengeId: number
  roundNumber: number
  message: string
  room: OneWayRoomView
}

export type AdminOneWayMatchStatus = OneWayRoomStatus | 'cancelled' | 'reset'

export interface AdminOneWayMatchRecord {
  matchId: number
  gameId: number
  roomCode: string
  roomExists: boolean
  status: AdminOneWayMatchStatus
  direction: OneWayDirection
  host: OneWayRoomPlayer
  guest: OneWayRoomPlayer | null
  winner: OneWayRoomPlayer | null
  isDraw: boolean
  currentRound: number
  totalRounds: number
  hostRoundWins: number
  guestRoundWins: number
  roundDraws: number
  rounds: AdminOneWayRoundRecord[]
  createdAt: string
  joinedAt: string | null
  startsAt: string | null
  finishedAt: string | null
  finishReason: string | null
  updatedAt: string
}

export interface AdminOneWayRoundRecord {
  roundNumber: number
  status: 'pending' | 'active' | 'finished'
  challengeId: number | null
  challengeTitle: string | null
  startsAt: string | null
  endsAt: string | null
  finishedAt: string | null
  winnerUserId: string | null
  winnerUserName: string | null
  isDraw: boolean
}

export interface BossStateView {
  gameId: number
  contribution: number
  solvedChallengeIds: number[]
  bossState: BossPublicState
  leaderboard: ArenaLeaderboardEntry[]
}

export interface BossSubmitResponse {
  correct: boolean
  alreadySolved: boolean
  challengeId: number
  damage: number
  contribution: number
  bossState: BossPublicState
  message: string
}

const toArenaChallengeWrite = (challenge: ArenaChallengeConfig) => ({
  id: challenge.id,
  sourceChallengeId: challenge.sourceChallengeId,
  title: challenge.title,
  category: challenge.category,
  difficulty: challenge.difficulty,
  description: challenge.description,
  target: challenge.target || null,
  attachmentUrl: challenge.attachmentUrl || null,
  status: challenge.status,
  enabled: challenge.enabled,
  sortOrder: challenge.sortOrder,
  modes: challenge.modes,
  pk: challenge.pk,
  boss: challenge.boss,
  flagCaseSensitive: challenge.flagCaseSensitive,
  ...(challenge.flag ? { flag: challenge.flag } : {}),
  ...(challenge.clearFlag ? { clearFlag: true } : {}),
})

const toArenaConfigUpdate = (config: ArenaGameConfig): ArenaGameConfigUpdate => ({
  gameId: config.gameId,
  enabled: config.enabled,
  published: config.published,
  mode: config.mode,
  pkConfig: config.pkConfig,
  oneWayConfig: config.oneWayConfig,
  bossConfig: config.bossConfig,
  revision: config.revision,
  challenges: config.challenges.map(toArenaChallengeWrite),
})

const getAdminGame = async (gameId: number) => {
  const response = await api.request<ArenaGameConfig>({
    path: `/api/arena/admin/games/${gameId}`,
    method: 'GET',
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const updateAdminGame = async (gameId: number, config: ArenaGameConfig) => {
  const response = await api.request<ArenaGameConfig>({
    path: `/api/arena/admin/games/${gameId}`,
    method: 'PUT',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: toArenaConfigUpdate(config),
  })
  return response.data
}

const listAdminChallenges = async (gameId: number) => {
  const response = await api.request<ArenaChallengeConfig[]>({
    path: `/api/arena/admin/games/${gameId}/challenges`,
    method: 'GET',
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const createAdminChallenge = async (gameId: number, challenge: ArenaChallengeConfig) => {
  const response = await api.request<ArenaChallengeConfig>({
    path: `/api/arena/admin/games/${gameId}/challenges`,
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: toArenaChallengeWrite(challenge),
  })
  return response.data
}

const updateAdminChallenge = async (gameId: number, challengeId: number, challenge: ArenaChallengeConfig) => {
  const response = await api.request<ArenaChallengeConfig>({
    path: `/api/arena/admin/games/${gameId}/challenges/${challengeId}`,
    method: 'PUT',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: toArenaChallengeWrite(challenge),
  })
  return response.data
}

const deleteAdminChallenge = async (gameId: number, challengeId: number) => {
  await api.request<void>({
    path: `/api/arena/admin/games/${gameId}/challenges/${challengeId}`,
    method: 'DELETE',
    withCredentials: true,
  })
}

const listAdminPkMatches = async (gameId: number, limit = 100) => {
  const response = await api.request<AdminPkMatchRecord[]>({
    path: `/api/arena/admin/games/${gameId}/pk-matches`,
    method: 'GET',
    query: { limit },
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const deleteAdminPkMatchRoom = async (gameId: number, matchId: number) => {
  await api.request<void>({
    path: `/api/arena/admin/games/${gameId}/pk-matches/${matchId}/room`,
    method: 'DELETE',
    withCredentials: true,
  })
}

const deleteAdminPkMatch = async (gameId: number, matchId: number) => {
  await api.request<void>({
    path: `/api/arena/admin/games/${gameId}/pk-matches/${matchId}`,
    method: 'DELETE',
    withCredentials: true,
  })
}

const listAdminOneWayMatches = async (gameId: number, limit = 100) => {
  const response = await api.request<AdminOneWayMatchRecord[]>({
    path: `/api/arena/admin/games/${gameId}/one-way-matches`,
    method: 'GET',
    query: { limit },
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const deleteAdminOneWayMatchRoom = async (gameId: number, matchId: number) => {
  await api.request<void>({
    path: `/api/arena/admin/games/${gameId}/one-way-matches/${matchId}/room`,
    method: 'DELETE',
    withCredentials: true,
  })
}

const deleteAdminOneWayMatch = async (gameId: number, matchId: number) => {
  await api.request<void>({
    path: `/api/arena/admin/games/${gameId}/one-way-matches/${matchId}`,
    method: 'DELETE',
    withCredentials: true,
  })
}

const getActivePublicGame = async () => {
  const response = await api.request<ArenaPublicGame>({
    path: '/api/arena/public/active',
    method: 'GET',
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const getPublicGame = async (gameId: number) => {
  const response = await api.request<ArenaPublicGame>({
    path: `/api/arena/public/games/${gameId}`,
    method: 'GET',
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const createPkRoom = async (gameId: number) => {
  const response = await api.request<PkRoomView>({
    path: '/api/arena/pk/rooms',
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: { gameId },
  })
  return response.data
}

const joinPkRoom = async (roomCode: string, gameId: number) => {
  const response = await api.request<PkRoomView>({
    path: `/api/arena/pk/rooms/${encodeURIComponent(roomCode)}/join`,
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: { gameId },
  })
  return response.data
}

const getPkRoom = async (roomCode: string, gameId: number) => {
  const response = await api.request<PkRoomView>({
    path: `/api/arena/pk/rooms/${encodeURIComponent(roomCode)}`,
    method: 'GET',
    query: { gameId },
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const leavePkRoom = async (roomCode: string, gameId: number) => {
  const response = await api.request<PkRoomView>({
    path: `/api/arena/pk/rooms/${encodeURIComponent(roomCode)}/leave`,
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: { gameId },
  })
  return response.data
}

const getPkState = async (gameId: number, roomCode?: string) => {
  const response = await api.request<PkStateView>({
    path: '/api/arena/pk/state',
    method: 'GET',
    query: { gameId, roomCode },
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const submitPk = async (payload: PkSubmitRequest) => {
  const response = await api.request<PkSubmitResponse>({
    path: '/api/arena/pk/submit',
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: payload,
  })
  return response.data
}

const createOneWayRoom = async (gameId: number, directionId: string) => {
  const response = await api.request<OneWayRoomView>({
    path: '/api/arena/one-way/rooms',
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: { gameId, directionId },
  })
  return response.data
}

const joinOneWayRoom = async (roomCode: string) => {
  const response = await api.request<OneWayRoomView>({
    path: `/api/arena/one-way/rooms/${encodeURIComponent(roomCode)}/join`,
    method: 'POST',
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const getOneWayRoom = async (roomCode: string, gameId: number) => {
  const response = await api.request<OneWayRoomView>({
    path: `/api/arena/one-way/rooms/${encodeURIComponent(roomCode)}`,
    method: 'GET',
    query: { gameId },
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const leaveOneWayRoom = async (roomCode: string, gameId: number) => {
  const response = await api.request<OneWayRoomView>({
    path: `/api/arena/one-way/rooms/${encodeURIComponent(roomCode)}/leave`,
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: { gameId },
  })
  return response.data
}

const submitOneWay = async (payload: OneWaySubmitRequest) => {
  const response = await api.request<OneWaySubmitResponse>({
    path: '/api/arena/one-way/submit',
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: payload,
  })
  return response.data
}

const getBossState = async (gameId: number) => {
  const response = await api.request<BossStateView>({
    path: '/api/arena/boss/state',
    method: 'GET',
    query: { gameId },
    format: 'json',
    withCredentials: true,
  })
  return response.data
}

const submitBoss = async (payload: ArenaSubmitRequest) => {
  const response = await api.request<BossSubmitResponse>({
    path: '/api/arena/boss/submit',
    method: 'POST',
    type: ContentType.Json,
    format: 'json',
    withCredentials: true,
    body: payload,
  })
  return response.data
}

/**
 * Shared client for both the administrator and player-facing arena pages.
 * The generated GZCTF Api client supplies BASE_URL, cookies and locale headers;
 * administrator calls reuse the existing GZCTF session cookie.
 */
export const arenaApi = {
  admin: {
    getGame: getAdminGame,
    updateGame: updateAdminGame,
    listChallenges: listAdminChallenges,
    createChallenge: createAdminChallenge,
    updateChallenge: updateAdminChallenge,
    deleteChallenge: deleteAdminChallenge,
    listPkMatches: listAdminPkMatches,
    deletePkMatchRoom: deleteAdminPkMatchRoom,
    deletePkMatch: deleteAdminPkMatch,
    listOneWayMatches: listAdminOneWayMatches,
    deleteOneWayMatchRoom: deleteAdminOneWayMatchRoom,
    deleteOneWayMatch: deleteAdminOneWayMatch,
  },
  public: {
    getActive: getActivePublicGame,
    getGame: getPublicGame,
    createPkRoom,
    joinPkRoom,
    getPkRoom,
    leavePkRoom,
    getPkState,
    submitPk,
    createOneWayRoom,
    joinOneWayRoom,
    getOneWayRoom,
    leaveOneWayRoom,
    submitOneWay,
    getBossState,
    submitBoss,
  },
}

export const createDefaultArenaConfig = (gameId: number): ArenaGameConfig => ({
  gameId,
  exists: false,
  enabled: false,
  published: false,
  mode: 'hybrid',
  revision: 0,
  pkConfig: {
    teamSize: 1,
    matchSeconds: 1800,
    questionCount: 8,
    scoreMode: 'fixed',
    winRule: 'highest_score',
    targetScore: null,
    allowDraw: false,
    wrongPenalty: 0,
    cooldownSeconds: 3,
    firstBloodBonus: 100,
    streakBonus: 25,
    sameQuestionsForBoth: true,
  },
  oneWayConfig: {
    countdownSeconds: 5,
    roundCount: 3,
    roundSeconds: 900,
    intervalSeconds: 5,
    directions: [],
  },
  bossConfig: {
    name: '末影方块巨兽',
    maxHp: 100_000,
    phaseCount: 3,
    phaseThresholds: [0.66, 0.33],
    enrageSeconds: 7200,
    enrageDamageMultiplier: 0.75,
    minTeamContribution: 1000,
    shieldEnabled: true,
  },
  challenges: [],
})

export const normalizeArenaConfig = (gameId: number, config?: Partial<ArenaGameConfig> | null): ArenaGameConfig => {
  const defaults = createDefaultArenaConfig(gameId)

  return {
    ...defaults,
    ...config,
    gameId,
    pkConfig: { ...defaults.pkConfig, ...config?.pkConfig },
    oneWayConfig: {
      ...defaults.oneWayConfig,
      ...config?.oneWayConfig,
      directions: (config?.oneWayConfig?.directions ?? []).map((direction, index) => ({
        id: direction.id || `direction-${index + 1}`,
        name: direction.name || `挑战方向 ${index + 1}`,
        description: direction.description ?? '',
        challengeIds: direction.challengeIds ?? [],
      })),
    },
    bossConfig: { ...defaults.bossConfig, ...config?.bossConfig },
    challenges: (config?.challenges ?? []).map((challenge, index) => ({
      id: challenge.id,
      sourceChallengeId: challenge.sourceChallengeId,
      title: challenge.title ?? `Arena Challenge ${index + 1}`,
      description: challenge.description ?? '',
      target: challenge.target ?? null,
      attachmentUrl: challenge.attachmentUrl ?? null,
      status: challenge.status ?? 'active',
      category: challenge.category ?? 'Misc',
      difficulty: challenge.difficulty ?? 'normal',
      enabled: challenge.enabled ?? true,
      sortOrder: challenge.sortOrder ?? index + 1,
      modes: challenge.modes ?? [],
      pk:
        challenge.pk === null
          ? null
          : {
              variantGroup: challenge.pk?.variantGroup ?? null,
              baseScore: challenge.pk?.baseScore ?? 500,
              timeLimitSeconds: challenge.pk?.timeLimitSeconds ?? null,
            },
      boss:
        challenge.boss === null
          ? null
          : {
              baseDamage: challenge.boss?.baseDamage ?? 1000,
              phase: challenge.boss?.phase ?? 1,
              affinity: challenge.boss?.affinity ?? 'normal',
              isShieldChallenge: challenge.boss?.isShieldChallenge ?? false,
              isCoreChallenge: challenge.boss?.isCoreChallenge ?? false,
            },
      flagCaseSensitive: challenge.flagCaseSensitive ?? true,
      hasFlag: challenge.hasFlag ?? false,
      flag: challenge.flag ?? null,
      clearFlag: challenge.clearFlag ?? false,
    })),
  }
}
