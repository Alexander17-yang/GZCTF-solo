import type { ArenaChallengeConfig, ArenaMode } from './ArenaApi'

const OPEN_CHALLENGE_STATUSES = new Set(['active', 'open'])
export const hasChallengeFlag = (challenge: ArenaChallengeConfig) =>
  !challenge.clearFlag && (challenge.hasFlag === true || Boolean(challenge.flag?.trim()))

export interface GzctfChallengeStatusSource {
  id?: number | null
  isEnabled?: boolean | null
}

export const isArenaChallengeOpen = (status: string) => OPEN_CHALLENGE_STATUSES.has(status.trim().toLowerCase())

/**
 * A challenge that is enabled in GZCTF and whose Flag was imported successfully
 * should be playable immediately. Missing detail/Flag data stays a safe draft.
 */
export const defaultSyncedChallengeStatus = (sourceIsEnabled: boolean, hasImportedFlag: boolean) =>
  sourceIsEnabled && hasImportedFlag ? 'active' : 'draft'

export const arenaModeSupportsPk = (mode: ArenaMode) => mode === 'solo_pk' || mode === 'hybrid'

export const hasOpenPkChallenge = (challenges: ArenaChallengeConfig[]) =>
  challenges.some(
    (challenge) =>
      challenge.enabled &&
      challenge.modes.includes('pk') &&
      isArenaChallengeOpen(challenge.status) &&
      hasChallengeFlag(challenge)
  )

export const isReadyOneWayChallenge = (challenge: ArenaChallengeConfig) =>
  typeof challenge.id === 'number' &&
  challenge.enabled &&
  challenge.modes.includes('one_way') &&
  isArenaChallengeOpen(challenge.status) &&
  hasChallengeFlag(challenge)

export const oneWayDirectionIssues = (
  challenges: ArenaChallengeConfig[],
  directions: { name: string; challengeIds: number[] }[],
  roundCount: number
) => {
  const eligibleIds = new Set(challenges.filter(isReadyOneWayChallenge).map((challenge) => challenge.id as number))
  const minimum = Math.max(1, roundCount)
  const issues: string[] = []
  if (!directions.length) issues.push('至少需要配置一个挑战方向')

  directions.forEach((direction, index) => {
    const name = direction.name.trim() || `方向 ${index + 1}`
    const uniqueIds = new Set(direction.challengeIds)
    if (!direction.name.trim()) issues.push(`方向 ${index + 1} 缺少名称`)
    if (uniqueIds.size < minimum) issues.push(`「${name}」题池至少需要 ${minimum} 道不重复题目`)
    if ([...uniqueIds].some((id) => !eligibleIds.has(id))) issues.push(`「${name}」包含未就绪的单方向单挑题`)
  })

  return issues
}

/**
 * One-way questions must not remain visible through GZCTF's native challenge
 * endpoints. The arena keeps its own frozen copy, so administrators should
 * disable/hide the mapped source while leaving the arena copy enabled.
 */
export const oneWaySourceExposureIssues = (
  challenges: ArenaChallengeConfig[],
  directions: { challengeIds: number[] }[],
  sources: GzctfChallengeStatusSource[]
) => {
  const selectedIds = new Set(directions.flatMap((direction) => direction.challengeIds))
  const enabledSourceIds = new Set(
    sources
      .filter((source) => typeof source.id === 'number' && source.isEnabled === true)
      .map((source) => source.id as number)
  )

  return challenges.flatMap((challenge) =>
    typeof challenge.id === 'number' &&
    selectedIds.has(challenge.id) &&
    challenge.sourceChallengeId !== null &&
    enabledSourceIds.has(challenge.sourceChallengeId)
      ? [`「${challenge.title}」对应的原生 GZCTF 题 #${challenge.sourceChallengeId} 仍处于启用状态`]
      : []
  )
}

/**
 * Finds the exact legacy-sync shape without changing it automatically. Requiring
 * a currently enabled GZCTF source avoids offering to publish a source challenge
 * that the administrator has disabled in the original game.
 */
export const findEnabledDraftPkChallengeIndexes = (
  challenges: ArenaChallengeConfig[],
  sources: GzctfChallengeStatusSource[]
) => {
  const enabledSourceIds = new Set(
    sources
      .filter((source) => typeof source.id === 'number' && source.isEnabled === true)
      .map((source) => source.id as number)
  )

  return challenges.flatMap((challenge, index) =>
    challenge.enabled &&
    challenge.modes.includes('pk') &&
    challenge.status.trim().toLowerCase() === 'draft' &&
    hasChallengeFlag(challenge) &&
    challenge.sourceChallengeId !== null &&
    enabledSourceIds.has(challenge.sourceChallengeId)
      ? [index]
      : []
  )
}

/** Explicit admin action used by the legacy-draft repair prompt. */
export const openChallengesAtIndexes = (challenges: ArenaChallengeConfig[], indexes: number[]) => {
  const selected = new Set(indexes)
  return challenges.map((challenge, index) => (selected.has(index) ? { ...challenge, status: 'active' } : challenge))
}
