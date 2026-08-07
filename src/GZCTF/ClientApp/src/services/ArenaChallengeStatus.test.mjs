import assert from 'node:assert/strict'
import test from 'node:test'
import {
  arenaModeSupportsPk,
  defaultSyncedChallengeStatus,
  findEnabledDraftPkChallengeIndexes,
  hasOpenPkChallenge,
  isReadyOneWayChallenge,
  isArenaChallengeOpen,
  oneWayDirectionIssues,
  oneWaySourceExposureIssues,
  openChallengesAtIndexes,
} from './ArenaChallengeStatus.ts'

const challenge = (patch = {}) => ({
  id: 1,
  sourceChallengeId: 10,
  title: 'test',
  description: '',
  target: null,
  attachmentUrl: null,
  status: 'draft',
  category: 'Web',
  difficulty: 'easy',
  enabled: true,
  sortOrder: 1,
  modes: ['pk'],
  pk: { variantGroup: null, baseScore: 100, timeLimitSeconds: null },
  boss: null,
  flagCaseSensitive: true,
  hasFlag: true,
  ...patch,
})

test('newly synced challenges open only when both source and imported Flag are ready', () => {
  assert.equal(defaultSyncedChallengeStatus(true, true), 'active')
  assert.equal(defaultSyncedChallengeStatus(true, false), 'draft')
  assert.equal(defaultSyncedChallengeStatus(false, true), 'draft')
  assert.equal(defaultSyncedChallengeStatus(false, false), 'draft')
})

test('open status and published PK validation accept active/open only', () => {
  assert.equal(isArenaChallengeOpen(' ACTIVE '), true)
  assert.equal(isArenaChallengeOpen('open'), true)
  assert.equal(isArenaChallengeOpen('draft'), false)
  assert.equal(hasOpenPkChallenge([challenge()]), false)
  assert.equal(hasOpenPkChallenge([challenge({ status: 'active' })]), true)
  assert.equal(hasOpenPkChallenge([challenge({ status: 'open' })]), true)
  assert.equal(hasOpenPkChallenge([challenge({ status: 'active', enabled: false })]), false)
  assert.equal(hasOpenPkChallenge([challenge({ status: 'active', modes: ['boss'] })]), false)
  assert.equal(hasOpenPkChallenge([challenge({ status: 'active', hasFlag: false })]), false)
  assert.equal(hasOpenPkChallenge([challenge({ status: 'active', clearFlag: true })]), false)
  assert.equal(hasOpenPkChallenge([challenge({ status: 'active', hasFlag: false, flag: 'flag{pending_save}' })]), true)
  assert.equal(arenaModeSupportsPk('solo_pk'), true)
  assert.equal(arenaModeSupportsPk('hybrid'), true)
  assert.equal(arenaModeSupportsPk('boss_raid'), false)
})

test('legacy repair only offers enabled draft PK mappings whose GZCTF source is enabled', () => {
  const challenges = [
    challenge({ sourceChallengeId: 10 }),
    challenge({ sourceChallengeId: 11 }),
    challenge({ sourceChallengeId: 12, enabled: false }),
    challenge({ sourceChallengeId: 13, modes: ['boss'] }),
    challenge({ sourceChallengeId: 14, status: 'locked' }),
    challenge({ sourceChallengeId: null }),
    challenge({ sourceChallengeId: 15, hasFlag: false }),
  ]
  const sources = [
    { id: 10, isEnabled: true },
    { id: 11, isEnabled: false },
    { id: 12, isEnabled: true },
    { id: 13, isEnabled: true },
    { id: 14, isEnabled: true },
    { id: 15, isEnabled: true },
  ]

  assert.deepEqual(findEnabledDraftPkChallengeIndexes(challenges, sources), [0])
})

test('legacy repair is explicit, immutable, and leaves unselected drafts untouched', () => {
  const original = [challenge({ sourceChallengeId: 10 }), challenge({ sourceChallengeId: 11 })]
  const repaired = openChallengesAtIndexes(original, [0])

  assert.equal(repaired[0].status, 'active')
  assert.equal(repaired[1].status, 'draft')
  assert.equal(original[0].status, 'draft')
  assert.notEqual(repaired[0], original[0])
  assert.equal(repaired[1], original[1])
})

test('one-way directions require saved, open, flagged one-way challenges and enough unique questions', () => {
  const oneWay = challenge({ id: 21, status: 'active', modes: ['one_way'] })
  assert.equal(isReadyOneWayChallenge(oneWay), true)
  assert.equal(isReadyOneWayChallenge({ ...oneWay, id: null }), false)
  assert.equal(isReadyOneWayChallenge({ ...oneWay, status: 'draft' }), false)
  assert.equal(isReadyOneWayChallenge({ ...oneWay, modes: ['pk'] }), false)

  const pool = [
    oneWay,
    challenge({ id: 22, status: 'open', modes: ['one_way'] }),
    challenge({ id: 23, status: 'active', modes: ['one_way'] }),
  ]
  assert.deepEqual(oneWayDirectionIssues(pool, [{ name: 'Web', challengeIds: [21, 22, 23] }], 3), [])
  assert.match(oneWayDirectionIssues(pool, [{ name: 'Web', challengeIds: [21, 21, 22] }], 3)[0], /至少需要 3 道/)
  assert.match(oneWayDirectionIssues(pool, [{ name: 'Web', challengeIds: [21, 22, 999] }], 3)[0], /未就绪/)
  assert.match(oneWayDirectionIssues(pool, [], 3)[0], /至少需要配置一个/)
})

test('one-way publication blocks selected mappings whose native GZCTF source is still enabled', () => {
  const mapped = challenge({ id: 31, sourceChallengeId: 301, status: 'active', modes: ['one_way'] })
  const detached = challenge({ id: 32, sourceChallengeId: null, status: 'active', modes: ['one_way'] })
  const directions = [{ challengeIds: [31, 32] }]

  assert.deepEqual(oneWaySourceExposureIssues([mapped, detached], directions, [{ id: 301, isEnabled: false }]), [])
  assert.deepEqual(
    oneWaySourceExposureIssues([mapped, detached], [{ challengeIds: [32] }], [{ id: 301, isEnabled: true }]),
    []
  )

  const issues = oneWaySourceExposureIssues([mapped, detached], directions, [{ id: 301, isEnabled: true }])
  assert.equal(issues.length, 1)
  assert.match(issues[0], /原生 GZCTF 题 #301 仍处于启用状态/)
})
