import { arenaApi } from '@Services/ArenaApi'
import { Badge, Button, Code, Group, Loader, SimpleGrid, Stack, Text, TextInput, ThemeIcon, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  mdiAccountGroupOutline,
  mdiAlertCircleOutline,
  mdiArrowLeft,
  mdiCheckBold,
  mdiClockAlertOutline,
  mdiDownload,
  mdiFire,
  mdiFlashOutline,
  mdiFlagCheckered,
  mdiLockOutline,
  mdiOpenInNew,
  mdiRefresh,
  mdiShieldHalfFull,
  mdiShieldSwordOutline,
  mdiSkullCrossbonesOutline,
  mdiSwordCross,
  mdiTarget,
  mdiTrophyOutline,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import { FC, FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { WithNavBar } from '@Components/WithNavbar'
import { PixelStat, SegmentedBar, VoxelBoss, VoxelPanel } from '@Components/arena/VoxelUI'
import { usePageTitle } from '@Hooks/usePageTitle'
import { useUser } from '@Hooks/useUser'
import classes from '@Styles/BossArena.module.css'

type ArenaPublicData = Awaited<ReturnType<typeof arenaApi.public.getActive>>
type BossRuntimeState = Awaited<ReturnType<typeof arenaApi.public.getBossState>>
type ArenaPublicChallenge = ArenaPublicData['challenges'][number]
type PageStatus = 'loading' | 'ready' | 'empty' | 'unavailable' | 'error'
type DisplayAffinity = 'weak' | 'normal' | 'resistant' | 'shield' | 'locked'

const errorStatus = (error: unknown) => (error as { response?: { status?: number } })?.response?.status

const errorMessage = (error: unknown) => {
  const response = (
    error as {
      response?: { data?: { detail?: string; title?: string; message?: string } }
      message?: string
    }
  )?.response?.data

  return response?.detail ?? response?.title ?? response?.message ?? (error as Error)?.message ?? '竞技场服务暂不可用'
}

const supportsBoss = (arena: ArenaPublicData) => arena.mode === 'boss_raid' || arena.mode === 'hybrid'

const challengeAffinity = (challenge: ArenaPublicChallenge): DisplayAffinity => {
  if (challenge.locked) return 'locked'
  if (challenge.boss?.isShieldChallenge) return 'shield'
  const affinity = challenge.boss?.affinity.toLowerCase()
  if (affinity === 'weak' || affinity === 'resistant' || affinity === 'shield') return affinity
  return 'normal'
}

const affinityLabel = (affinity: DisplayAffinity) => {
  switch (affinity) {
    case 'weak':
      return '弱点加成'
    case 'resistant':
      return '伤害抗性'
    case 'shield':
      return '破盾目标'
    case 'locked':
      return '下一阶段'
    default:
      return '标准伤害'
  }
}

const formatDuration = (seconds: number) => {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = seconds % 60
  return [hours, minutes, rest].map((value) => value.toString().padStart(2, '0')).join(':')
}

const BossArena: FC = () => {
  const { user } = useUser()
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [pageMessage, setPageMessage] = useState('正在连接世界 Boss…')
  const [arena, setArena] = useState<ArenaPublicData | null>(null)
  const [runtime, setRuntime] = useState<BossRuntimeState | null>(null)
  const [authRequired, setAuthRequired] = useState(false)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [flag, setFlag] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [events, setEvents] = useState<[string, string][]>([])

  usePageTitle('Boss 讨伐')

  const refreshRuntime = useCallback(async (gameId: number, quiet = true) => {
    try {
      const nextState = await arenaApi.public.getBossState(gameId)
      setRuntime(nextState)
      setAuthRequired(false)
      return nextState
    } catch (error) {
      if (errorStatus(error) === 401) {
        setAuthRequired(true)
        setRuntime(null)
        return null
      }
      if (!quiet) throw error
      return null
    }
  }, [])

  const refreshBossData = useCallback(
    async (gameId: number, quiet = true) => {
      try {
        const config = await arenaApi.public.getGame(gameId)
        setArena(config)
        await refreshRuntime(gameId, quiet)
      } catch (error) {
        if (!quiet) throw error
      }
    },
    [refreshRuntime]
  )

  const loadArena = useCallback(async () => {
    setPageStatus('loading')
    setPageMessage('正在连接世界 Boss…')

    try {
      const config = await arenaApi.public.getActive()
      if (!supportsBoss(config)) {
        setPageStatus('unavailable')
        setPageMessage('当前已发布的竞技场没有开启 Boss 讨伐模式。')
        return
      }

      const bossChallenges = config.challenges.filter((challenge) => challenge.modes.includes('boss') && challenge.boss)
      setArena(config)
      setActiveId((current) =>
        current && bossChallenges.some((challenge) => challenge.id === current)
          ? current
          : (bossChallenges.find((challenge) => !challenge.locked)?.id ?? bossChallenges[0]?.id ?? null)
      )
      setEvents([
        ['系统', `已连接竞技场 #${config.gameId}，${bossChallenges.length} 道 Boss 挑战已同步`],
        ['系统', `最低通关贡献为 ${config.bossConfig.minTeamContribution.toLocaleString()} 伤害`],
      ])

      await refreshRuntime(config.gameId, false)
      setPageStatus('ready')
    } catch (error) {
      if (errorStatus(error) === 404) {
        setPageStatus('empty')
        setPageMessage('暂无已发布的方块竞技场，请等待管理员启用并发布赛事。')
        return
      }
      setPageStatus('error')
      setPageMessage(errorMessage(error))
    }
  }, [refreshRuntime])

  useEffect(() => {
    void loadArena()
  }, [loadArena])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!arena || pageStatus !== 'ready') return
    const timer = window.setInterval(() => void refreshBossData(arena.gameId), 5000)
    return () => window.clearInterval(timer)
  }, [arena?.gameId, pageStatus, refreshBossData])

  const challenges = useMemo(() => {
    const solved = new Set(runtime?.solvedChallengeIds ?? [])
    return (arena?.challenges ?? [])
      .filter((challenge) => challenge.modes.includes('boss') && challenge.boss)
      .map((challenge) => ({ ...challenge, solved: solved.has(challenge.id), affinity: challengeAffinity(challenge) }))
  }, [arena, runtime])

  const active = useMemo(
    () => challenges.find((challenge) => challenge.id === activeId) ?? challenges[0] ?? null,
    [activeId, challenges]
  )

  if (pageStatus !== 'ready' || !arena) {
    return (
      <WithNavBar width="min(1100px, 94%)" minWidth={0}>
        <main className={classes.raidWorld}>
          <VoxelPanel
            tone={pageStatus === 'error' ? 'danger' : 'obsidian'}
            title={pageStatus === 'loading' ? '正在加载 Boss 战场' : 'Boss 战场暂未开放'}
            eyebrow="GLOBAL RAID"
          >
            <Stack align="center" gap="lg" py="xl">
              {pageStatus === 'loading' ? (
                <Loader color="yellow" type="bars" />
              ) : (
                <ThemeIcon size={64} color={pageStatus === 'error' ? 'red' : 'yellow'} variant="light">
                  <Icon path={mdiAlertCircleOutline} size={1.35} />
                </ThemeIcon>
              )}
              <Text ta="center" c="dimmed" maw={620}>
                {pageMessage}
              </Text>
              <Group>
                <Button component={Link} to="/arena" variant="default">
                  返回模式大厅
                </Button>
                {pageStatus !== 'loading' && (
                  <Button leftSection={<Icon path={mdiRefresh} size={0.8} />} onClick={() => void loadArena()}>
                    重新加载
                  </Button>
                )}
              </Group>
            </Stack>
          </VoxelPanel>
        </main>
      </WithNavBar>
    )
  }

  const bossState = runtime?.bossState ??
    arena.bossState ?? {
      status: 'active' as const,
      hp: arena.bossConfig.maxHp,
      maxHp: arena.bossConfig.maxHp,
      phase: 1,
      shieldActive: arena.bossConfig.shieldEnabled,
      enraged: false,
      version: 0,
      startedAt: arena.updatedAt,
      defeatedAt: null,
    }
  const hpRate = bossState.maxHp > 0 ? (bossState.hp / bossState.maxHp) * 100 : 0
  const enrageDeadline = Date.parse(bossState.startedAt) + arena.bossConfig.enrageSeconds * 1000
  const enrageRemaining = Number.isFinite(enrageDeadline) ? Math.max(0, Math.floor((enrageDeadline - now) / 1000)) : 0
  const contribution = runtime?.contribution ?? 0
  const eligibilityRate =
    arena.bossConfig.minTeamContribution > 0
      ? Math.min(100, (contribution / arena.bossConfig.minTeamContribution) * 100)
      : 100
  const leaderboard = runtime?.leaderboard ?? []
  const rankedDamage = leaderboard.reduce((total, entry) => total + entry.contribution, 0)

  const submitFlag = async (event: FormEvent) => {
    event.preventDefault()
    if (!active || active.locked || active.solved || submitting || authRequired || !flag.trim()) return

    setSubmitting(true)
    try {
      const result = await arenaApi.public.submitBoss({
        gameId: arena.gameId,
        challengeId: active.id,
        flag: flag.trim(),
      })

      setRuntime((current) =>
        current
          ? {
              ...current,
              contribution: result.contribution,
              bossState: result.bossState,
              solvedChallengeIds:
                result.correct && !current.solvedChallengeIds.includes(result.challengeId)
                  ? [...current.solvedChallengeIds, result.challengeId]
                  : current.solvedChallengeIds,
            }
          : current
      )

      if (result.correct) {
        setFlag('')
        setEvents((current) => [
          [
            user?.userName ?? '你的队伍',
            result.alreadySolved
              ? `「${active.title}」已经结算过伤害`
              : `攻克「${active.title}」，对 Boss 造成 ${result.damage.toLocaleString()} 伤害`,
          ],
          ...current,
        ])
        notifications.show({
          title: result.alreadySolved ? '已经攻克' : `-${result.damage.toLocaleString()} HP`,
          message: result.message,
          color: result.alreadySolved ? 'blue' : 'green',
        })
      } else {
        setEvents((current) => [
          [user?.userName ?? '你的队伍', `「${active.title}」提交错误，没有造成伤害`],
          ...current,
        ])
        notifications.show({ title: 'Flag 错误', message: result.message, color: 'red' })
      }

      await refreshBossData(arena.gameId)
    } catch (error) {
      if (errorStatus(error) === 401) setAuthRequired(true)
      notifications.show({ title: '提交失败', message: errorMessage(error), color: 'red' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <WithNavBar width="min(1480px, 98%)" minWidth={0}>
      <main className={classes.raidWorld}>
        <header className={classes.raidHeader}>
          <Button
            component={Link}
            to="/arena"
            variant="subtle"
            color="gray"
            leftSection={<Icon path={mdiArrowLeft} size={0.8} />}
          >
            返回模式大厅
          </Button>
          <Group gap="xs">
            <Badge className={classes.phaseBadge}>
              PHASE {bossState.phase} / {arena.bossConfig.phaseCount}
            </Badge>
            <Badge className={classes.liveBadge}>{bossState.status === 'defeated' ? 'DEFEATED' : 'LIVE'}</Badge>
          </Group>
          <div className={classes.enrageClock}>
            <Icon path={bossState.enraged ? mdiFire : mdiClockAlertOutline} size={0.9} />
            {bossState.enraged ? 'Boss 已狂暴' : `狂暴 ${formatDuration(enrageRemaining)}`}
          </div>
        </header>

        {authRequired && (
          <VoxelPanel tone="wood" compact title="登录后才能贡献伤害" eyebrow="AUTH REQUIRED">
            <Group justify="space-between">
              <Text size="sm">Boss 公共血量仍会实时更新；登录 GZCTF 后可读取个人贡献并提交 Flag。</Text>
              <Button component={Link} to="/account/login" size="xs">
                前往登录
              </Button>
            </Group>
          </VoxelPanel>
        )}

        <section className={classes.bossStage}>
          <div className={classes.bossIdentity}>
            <Text className={classes.raidKicker}>ANCIENT DATA GUARDIAN</Text>
            <Title className={classes.bossName}>{arena.bossConfig.name}</Title>
            <Group gap="xs" mt="sm">
              <Badge color={bossState.shieldActive ? 'blue' : 'green'}>
                {bossState.shieldActive ? '护盾激活' : '护盾已破'}
              </Badge>
              <Badge color={bossState.enraged ? 'red' : 'yellow'}>
                {bossState.enraged ? '狂暴状态' : `阶段 ${bossState.phase}`}
              </Badge>
              {bossState.status === 'defeated' && <Badge color="green">讨伐完成</Badge>}
            </Group>
          </div>
          <div className={classes.bossVisual}>
            <VoxelBoss />
          </div>
          <div className={classes.worldStats}>
            <PixelStat
              label="参战玩家"
              value={leaderboard.length}
              accent="#76bde8"
              icon={<Icon path={mdiAccountGroupOutline} size={0.85} />}
            />
            <PixelStat
              label="榜单累计伤害"
              value={rankedDamage.toLocaleString()}
              accent="#ed5145"
              icon={<Icon path={mdiFlashOutline} size={0.85} />}
            />
          </div>
          <div className={classes.healthArea}>
            <SegmentedBar
              value={bossState.hp}
              max={bossState.maxHp}
              segments={30}
              tone="health"
              size="lg"
              label="BOSS HP"
              detail={`${bossState.hp.toLocaleString()} / ${bossState.maxHp.toLocaleString()} · ${hpRate.toFixed(1)}%`}
            />
            <SegmentedBar
              value={bossState.shieldActive ? 1 : 0}
              max={1}
              segments={20}
              tone="shield"
              size="sm"
              label="阶段护盾"
              detail={bossState.shieldActive ? 'ACTIVE' : 'BROKEN'}
            />
          </div>
        </section>

        <div className={classes.raidGrid}>
          <Stack gap="lg">
            <VoxelPanel tone="stone" title="遗迹挑战地图" eyebrow="CHALLENGE MAP">
              {challenges.length ? (
                <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }} spacing="sm">
                  {challenges.map((challenge) => (
                    <button
                      type="button"
                      key={challenge.id}
                      className={classes.raidChallenge}
                      data-active={challenge.id === active?.id || undefined}
                      data-affinity={challenge.affinity}
                      data-solved={challenge.solved || undefined}
                      onClick={() => setActiveId(challenge.id)}
                    >
                      <div className={classes.challengeIcon}>
                        <Icon
                          path={
                            challenge.solved
                              ? mdiCheckBold
                              : challenge.affinity === 'locked'
                                ? mdiLockOutline
                                : challenge.affinity === 'shield'
                                  ? mdiShieldHalfFull
                                  : mdiSwordCross
                          }
                          size={0.85}
                        />
                      </div>
                      <span>{challenge.category}</span>
                      <strong>{challenge.title}</strong>
                      <small>{challenge.difficulty}</small>
                      <b>{(challenge.boss?.baseDamage ?? 0).toLocaleString()} DMG</b>
                      <i>{affinityLabel(challenge.affinity)}</i>
                    </button>
                  ))}
                </SimpleGrid>
              ) : (
                <Text c="dimmed">管理员已经发布竞技场，但尚未配置可用的 Boss 题目。</Text>
              )}
            </VoxelPanel>

            {active && (
              <VoxelPanel
                tone={active.affinity === 'weak' ? 'wood' : 'obsidian'}
                title={active.title}
                eyebrow={`${active.category} / ${active.difficulty}`}
                action={<Badge>{(active.boss?.baseDamage ?? 0).toLocaleString()} 基础伤害</Badge>}
              >
                <div className={classes.challengeDetailGrid}>
                  <Stack gap="sm">
                    <Text className={classes.challengeText}>{active.description || '管理员暂未填写题目说明。'}</Text>
                    {active.target && <Code block>目标：{active.target}</Code>}
                    <Group gap="xs">
                      <Badge
                        color={active.affinity === 'weak' ? 'yellow' : active.affinity === 'resistant' ? 'red' : 'gray'}
                      >
                        {affinityLabel(active.affinity)}
                      </Badge>
                      {active.boss?.isCoreChallenge && <Badge color="grape">核心挑战</Badge>}
                      <Badge color="gray">第 {active.boss?.phase ?? 1} 阶段</Badge>
                    </Group>
                    <Group gap="xs">
                      {active.attachmentUrl && (
                        <Button
                          component="a"
                          href={active.attachmentUrl}
                          target="_blank"
                          rel="noreferrer"
                          size="xs"
                          leftSection={<Icon path={mdiDownload} size={0.75} />}
                        >
                          下载附件
                        </Button>
                      )}
                      {active.target?.match(/^https?:\/\//i) && (
                        <Button
                          component="a"
                          href={active.target}
                          target="_blank"
                          rel="noreferrer"
                          size="xs"
                          variant="light"
                          leftSection={<Icon path={mdiOpenInNew} size={0.75} />}
                        >
                          打开目标
                        </Button>
                      )}
                    </Group>
                  </Stack>
                  <form className={classes.bossFlagForm} onSubmit={(event) => void submitFlag(event)}>
                    <TextInput
                      aria-label="Boss Flag"
                      value={flag}
                      onChange={(event) => setFlag(event.currentTarget.value)}
                      disabled={
                        active.locked || active.solved || authRequired || submitting || bossState.status === 'defeated'
                      }
                      placeholder={
                        active.solved ? '本题已攻克' : active.locked ? '下一阶段开放' : 'flag{your_answer_here}'
                      }
                      leftSection={<Icon path={mdiFlagCheckered} size={0.8} />}
                    />
                    <Button
                      type="submit"
                      className={classes.attackButton}
                      loading={submitting}
                      disabled={
                        active.locked ||
                        active.solved ||
                        authRequired ||
                        !flag.trim() ||
                        bossState.status === 'defeated'
                      }
                      leftSection={<Icon path={active.solved ? mdiCheckBold : mdiTarget} size={0.95} />}
                    >
                      {active.solved
                        ? '已攻克'
                        : bossState.status === 'defeated'
                          ? 'Boss 已击败'
                          : active.locked
                            ? '尚未开放'
                            : '提交 Flag 攻击'}
                    </Button>
                  </form>
                </div>
              </VoxelPanel>
            )}
          </Stack>

          <Stack gap="lg">
            <VoxelPanel tone="grass" title="个人贡献" eyebrow="YOUR DAMAGE">
              <div className={classes.partyName}>
                <ThemeIcon className={classes.partyIcon} size={48}>
                  <Icon path={mdiShieldSwordOutline} size={1.05} />
                </ThemeIcon>
                <div>
                  <Text fw={950}>{user?.userName ?? '未登录玩家'}</Text>
                  <Text size="xs" c="dimmed">
                    {runtime ? `${runtime.solvedChallengeIds.length} 道题已造成伤害` : '登录后同步贡献'}
                  </Text>
                </div>
              </div>
              <Text className={classes.damageNumber}>{contribution.toLocaleString()}</Text>
              <Text size="xs" c="dimmed" ta="center">
                个人累计伤害
              </Text>
              <SegmentedBar
                value={eligibilityRate}
                tone="success"
                segments={10}
                label="通关资格"
                detail={`${eligibilityRate.toFixed(0)}%`}
              />
              <Text size="xs" c="dimmed" mt="sm">
                {eligibilityRate >= 100
                  ? '已满足最低贡献要求，Boss 被击败后具备通关资格。'
                  : `还需 ${Math.max(0, arena.bossConfig.minTeamContribution - contribution).toLocaleString()} 伤害达到最低贡献。`}
              </Text>
            </VoxelPanel>

            <VoxelPanel tone="wood" title="阶段推进" eyebrow="PHASE CONTROL">
              <Stack gap="md">
                {Array.from({ length: arena.bossConfig.phaseCount }, (_, index) => {
                  const phase = index + 1
                  const reached = bossState.phase >= phase
                  const completed = bossState.phase > phase || bossState.status === 'defeated'
                  return (
                    <SegmentedBar
                      key={phase}
                      value={reached ? 1 : 0}
                      max={1}
                      segments={6}
                      tone={completed ? 'success' : 'shield'}
                      size="sm"
                      label={`PHASE ${phase}`}
                      detail={completed ? '已突破' : bossState.phase === phase ? '作战中' : '未开放'}
                    />
                  )
                })}
              </Stack>
            </VoxelPanel>

            <VoxelPanel tone="obsidian" title="实时战报" eyebrow="RAID FEED" compact>
              <Stack gap={7}>
                {events.slice(0, 8).map(([name, event], index) => (
                  <div
                    key={`${name}-${event}-${index}`}
                    className={classes.raidEvent}
                    data-fresh={index === 0 || undefined}
                  >
                    <strong>{name}</strong>
                    <Text size="xs">{event}</Text>
                  </div>
                ))}
              </Stack>
            </VoxelPanel>

            <VoxelPanel tone="danger" title="全服伤害榜" eyebrow="TOP DAMAGE" compact>
              <Stack gap={6}>
                {leaderboard.length ? (
                  leaderboard.slice(0, 10).map((entry) => (
                    <div
                      key={entry.userId}
                      className={classes.rankRow}
                      data-self={entry.userId === user?.userId || undefined}
                    >
                      <span>{String(entry.rank).padStart(2, '0')}</span>
                      <strong>{entry.userName}</strong>
                      <b>{entry.contribution.toLocaleString()}</b>
                    </div>
                  ))
                ) : (
                  <Text size="xs" c="dimmed">
                    尚无玩家造成伤害。
                  </Text>
                )}
              </Stack>
            </VoxelPanel>
          </Stack>
        </div>

        <div className={classes.worldTicker}>
          <Icon path={bossState.status === 'defeated' ? mdiSkullCrossbonesOutline : mdiFire} size={0.8} />
          <strong>世界事件：</strong>
          {bossState.status === 'defeated'
            ? `${arena.bossConfig.name} 已被击败，讨伐结算完成。`
            : bossState.enraged
              ? `${arena.bossConfig.name} 已进入狂暴状态，伤害倍率发生变化。`
              : bossState.shieldActive
                ? `阶段护盾仍然激活，优先攻克带有「破盾目标」标记的题目。`
                : `护盾已经破除，集中火力攻击 Boss 核心。`}
          <Icon path={mdiTrophyOutline} size={0.8} />
        </div>
      </main>
    </WithNavBar>
  )
}

export default BossArena
