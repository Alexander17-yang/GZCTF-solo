import { arenaApi } from '@Services/ArenaApi'
import { Badge, Button, Code, Group, Loader, SimpleGrid, Stack, Text, TextInput, ThemeIcon } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  mdiAlertCircleOutline,
  mdiArrowLeft,
  mdiCheckBold,
  mdiClockOutline,
  mdiContentCopy,
  mdiDownload,
  mdiFlagCheckered,
  mdiHumanGreeting,
  mdiOpenInNew,
  mdiRefresh,
  mdiSwordCross,
  mdiTrophyOutline,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import { FC, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { WithNavBar } from '@Components/WithNavbar'
import { SegmentedBar, VoxelAvatar, VoxelPanel } from '@Components/arena/VoxelUI'
import { usePageTitle } from '@Hooks/usePageTitle'
import { useUser } from '@Hooks/useUser'
import classes from '@Styles/PkMatch.module.css'

type ArenaPublicData = Awaited<ReturnType<typeof arenaApi.public.getActive>>
type PkRuntimeState = Awaited<ReturnType<typeof arenaApi.public.getPkState>>
type PkRoomData = Awaited<ReturnType<typeof arenaApi.public.getPkRoom>>

type PageStatus = 'loading' | 'ready' | 'empty' | 'unavailable' | 'error'

// `locked` in the shared public payload also includes Boss phase gating for
// dual-mode challenges. PK availability is controlled only by the challenge
// publish status; otherwise a phase-2 Boss challenge would incorrectly be
// hidden from the Solo mirror pool.
const isPkLocked = (challenge: ArenaPublicData['challenges'][number]) =>
  !['active', 'open'].includes(challenge.status.toLowerCase())

const formatTime = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`

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

const supportsPk = (arena: ArenaPublicData) => arena.mode === 'solo_pk' || arena.mode === 'hybrid'
const TERMINAL_ROOM_STATUSES = new Set([403, 404, 409, 410])

const PkMatch: FC = () => {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const roomCode = searchParams.get('room')?.trim() ?? ''
  const { user } = useUser()
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [pageMessage, setPageMessage] = useState('正在连接方块竞技场…')
  const [arena, setArena] = useState<ArenaPublicData | null>(null)
  const [room, setRoom] = useState<PkRoomData | null>(null)
  const [runtime, setRuntime] = useState<PkRuntimeState | null>(null)
  const [authRequired, setAuthRequired] = useState(false)
  const [clockNow, setClockNow] = useState(() => Date.now())
  const [serverOffset, setServerOffset] = useState(0)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [flag, setFlag] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [wrongAttempts, setWrongAttempts] = useState(0)
  const [events, setEvents] = useState<string[]>([])
  const [leaving, setLeaving] = useState(false)
  const previousRoomStatus = useRef<string | null>(null)
  const roomRequestVersion = useRef(0)
  const stateRequestVersion = useRef(0)

  usePageTitle('PK 对局')

  const stopStaleMatch = useCallback(() => {
    // Invalidate any in-flight success before clearing the local snapshot. This
    // prevents a delayed response from resurrecting a room that was reset or left.
    roomRequestVersion.current += 1
    stateRequestVersion.current += 1
    setRoom(null)
    setRuntime(null)
    setPageStatus('error')
    setPageMessage('该 PK 房间已结束、已重置或你已不在房间中，请返回 Solo 大厅重新加入。')
  }, [])

  const refreshPkState = useCallback(async (gameId: number, code: string, quiet = true) => {
    const requestVersion = ++stateRequestVersion.current
    try {
      const nextState = await arenaApi.public.getPkState(gameId, code)
      if (requestVersion !== stateRequestVersion.current) return nextState
      setRuntime(nextState)
      setAuthRequired(false)
      return nextState
    } catch (error) {
      if (requestVersion !== stateRequestVersion.current) return null
      const status = errorStatus(error)
      if (status === 401) {
        setAuthRequired(true)
        setRuntime(null)
        return null
      }
      if (quiet && status !== undefined && TERMINAL_ROOM_STATUSES.has(status)) {
        stopStaleMatch()
        return null
      }
      if (!quiet) throw error
      return null
    }
  }, [stopStaleMatch])

  const refreshRoom = useCallback(async (gameId: number, code: string, quiet = true) => {
    const requestVersion = ++roomRequestVersion.current
    try {
      const nextRoom = await arenaApi.public.getPkRoom(code, gameId)
      if (requestVersion !== roomRequestVersion.current) return nextRoom
      setRoom(nextRoom)
      setServerOffset(Date.parse(nextRoom.serverTime) - Date.now())
      setAuthRequired(false)
      return nextRoom
    } catch (error) {
      if (requestVersion !== roomRequestVersion.current) return null
      const status = errorStatus(error)
      if (status === 401) {
        setAuthRequired(true)
        setRoom(null)
        return null
      }
      if (quiet && status !== undefined && TERMINAL_ROOM_STATUSES.has(status)) {
        stopStaleMatch()
        return null
      }
      if (!quiet) throw error
      return null
    }
  }, [stopStaleMatch])

  const loadArena = useCallback(async () => {
    setPageStatus('loading')
    setPageMessage('正在连接方块竞技场…')

    if (!/^\d{6}$/.test(roomCode)) {
      setPageStatus('error')
      setPageMessage('缺少有效的 6 位 Solo 房间号，请返回 PK 大厅创建或加入房间。')
      return
    }

    let arenaLoaded = false
    try {
      const config = await arenaApi.public.getActive()
      arenaLoaded = true
      if (!supportsPk(config)) {
        setPageStatus('unavailable')
        setPageMessage('当前已发布的竞技场没有开启 Solo PK 模式。')
        return
      }

      const pkChallenges = config.challenges.filter((challenge) => challenge.modes.includes('pk') && challenge.pk)
      setArena(config)
      setActiveId((current) =>
        current && pkChallenges.some((challenge) => challenge.id === current)
          ? current
          : (pkChallenges.find((challenge) => !isPkLocked(challenge))?.id ?? pkChallenges[0]?.id ?? null)
      )
      setEvents([
        `房间 ${roomCode} 正在等待双方就位`,
        `竞技场 #${config.gameId} 已载入，共 ${pkChallenges.length} 道 PK 挑战`,
        `系统：首解奖励 ${config.pkConfig.firstBloodBonus} 分，连胜奖励每层 ${config.pkConfig.streakBonus} 分`,
      ])

      await refreshRoom(config.gameId, roomCode, false)
      await refreshPkState(config.gameId, roomCode, false)
      setPageStatus('ready')
    } catch (error) {
      const status = errorStatus(error)
      if (status === 404 && !arenaLoaded) {
        setPageStatus('empty')
        setPageMessage('暂无已发布的方块竞技场，请等待管理员启用并发布赛事。')
        return
      }
      if (status !== undefined && TERMINAL_ROOM_STATUSES.has(status)) {
        stopStaleMatch()
        return
      }
      setPageStatus('error')
      setPageMessage(errorMessage(error))
    }
  }, [refreshPkState, refreshRoom, roomCode, stopStaleMatch])

  useEffect(() => {
    void loadArena()
  }, [loadArena])

  useEffect(() => {
    if (pageStatus !== 'ready') return
    // All visible timers are second-based; a 250 ms full-page render offered no
    // extra precision and made lower-end clients noticeably less responsive.
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [pageStatus])

  useEffect(() => {
    if (!arena || pageStatus !== 'ready' || authRequired || submitting) return
    let cancelled = false
    let timer: number | undefined
    let pollCount = 0

    // Do not use setInterval here. When the identity service is slow an interval
    // starts another pair of requests before the previous pair has completed,
    // which quickly creates a retry storm for both players. Room data already
    // contains both scores, so only refresh the private solved/streak state every
    // fifth cycle and always schedule the next cycle after this one finishes.
    const poll = async () => {
      if (cancelled) return

      await refreshRoom(arena.gameId, roomCode)
      if (cancelled) return
      pollCount += 1
      if (pollCount % 5 === 0) await refreshPkState(arena.gameId, roomCode)

      if (!cancelled) {
        timer = window.setTimeout(poll, document.visibilityState === 'hidden' ? 5000 : 1500)
      }
    }

    timer = window.setTimeout(poll, 1000)
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [arena, authRequired, pageStatus, refreshPkState, refreshRoom, roomCode, submitting])

  useEffect(() => {
    if (!room) return
    const previous = previousRoomStatus.current
    previousRoomStatus.current = room.status
    if (!previous || previous === room.status) return

    if (room.status === 'countdown') {
      setEvents((current) => [`${room.guest?.userName ?? '对手'} 已进入房间，双方同步准备倒计时开始`, ...current])
    } else if (room.status === 'active') {
      setEvents((current) => ['双方已就位，Solo PK 正式开始', ...current])
    } else if (room.status === 'finished') {
      setEvents((current) => ['比赛时间结束，本局成绩已锁定', ...current])
    }
  }, [room])

  const challenges = useMemo(() => {
    const solved = new Set(runtime?.solvedChallengeIds ?? [])
    return (arena?.challenges ?? [])
      .filter((challenge) => challenge.modes.includes('pk') && challenge.pk)
      .map((challenge) => ({ ...challenge, solved: solved.has(challenge.id) }))
  }, [arena, runtime])

  const active = useMemo(
    () => challenges.find((challenge) => challenge.id === activeId) ?? challenges[0] ?? null,
    [activeId, challenges]
  )

  const selfPlayer = room?.currentUserRole === 'guest' ? room.guest : room?.host
  const roomOpponent = room?.currentUserRole === 'guest' ? room.host : room?.guest
  const opponent = roomOpponent ?? {
    userId: '',
    userName: '等待挑战者',
    score: 0,
    solves: 0,
  }

  const serverNow = clockNow + serverOffset
  const startsAt = room?.startsAt ? Date.parse(room.startsAt) : null
  const endsAt = room?.endsAt ? Date.parse(room.endsAt) : null
  const roomWaiting = !room?.guest || room?.status === 'waiting'
  const readyCountdown = startsAt ? Math.max(0, Math.ceil((startsAt - serverNow) / 1000)) : 0
  const roomFinished = room?.status === 'finished' || (!!endsAt && serverNow >= endsAt)
  const matchStarted = !!room?.guest && !!startsAt && serverNow >= startsAt && !roomFinished
  const remaining = endsAt
    ? Math.max(0, Math.ceil((endsAt - serverNow) / 1000))
    : (arena?.pkConfig.matchSeconds ?? 0)

  const score = selfPlayer?.score ?? runtime?.score ?? 0
  const maxScore = Math.max(
    1,
    arena?.pkConfig.targetScore ?? challenges.reduce((total, challenge) => total + (challenge.pk?.baseScore ?? 0), 0),
    score,
    opponent.score
  )

  const copyRoomCode = async () => {
    try {
      await navigator.clipboard.writeText(roomCode)
      notifications.show({ title: '房间号已复制', message: roomCode, color: 'green' })
    } catch {
      notifications.show({ title: '房间号', message: roomCode, color: 'blue' })
    }
  }

  const leaveRoom = async () => {
    if (!arena || leaving) return
    roomRequestVersion.current += 1
    stateRequestVersion.current += 1
    setLeaving(true)
    try {
      await arenaApi.public.leavePkRoom(roomCode, arena.gameId)
    } catch {
      // Navigation should still be available if the room already expired.
    } finally {
      navigate('/arena/pk')
      setLeaving(false)
    }
  }

  const submitFlag = async (event: FormEvent) => {
    event.preventDefault()
    if (
      !arena ||
      !active ||
      active.solved ||
      isPkLocked(active) ||
      submitting ||
      !flag.trim() ||
      !matchStarted
    )
      return

    // Pause polling and make any already-running poll response obsolete before
    // submitting, so it cannot overwrite the authoritative post-submit refresh.
    roomRequestVersion.current += 1
    stateRequestVersion.current += 1
    setSubmitting(true)
    try {
      const result = await arenaApi.public.submitPk({
        gameId: arena.gameId,
        challengeId: active.id,
        flag: flag.trim(),
        roomCode,
      })

      setRuntime((current) =>
        current
          ? {
              ...current,
              score: result.score,
              solves: result.solves,
              streak: result.streak,
              solvedChallengeIds:
                result.correct && !current.solvedChallengeIds.includes(result.challengeId)
                  ? [...current.solvedChallengeIds, result.challengeId]
                  : current.solvedChallengeIds,
            }
          : current
      )

      if (result.correct) {
        setFlag('')
        const bonus = result.firstBlood ? '，并夺得首解' : ''
        setEvents((current) => [
          result.alreadySolved
            ? `「${active.title}」已经计分，本次没有重复加分`
            : `你攻克了「${active.title}」，积分 ${result.scoreDelta >= 0 ? '+' : ''}${result.scoreDelta}${bonus}`,
          ...current,
        ])
        notifications.show({
          title: result.alreadySolved ? '已经攻克' : '矿脉已突破',
          message: result.message,
          color: result.alreadySolved ? 'blue' : 'green',
        })
      } else {
        setWrongAttempts((value) => value + 1)
        setEvents((current) => [
          `「${active.title}」提交错误${result.scoreDelta < 0 ? `，扣除 ${Math.abs(result.scoreDelta)} 分` : ''}`,
          ...current,
        ])
        notifications.show({ title: 'Flag 错误', message: result.message, color: 'red' })
      }

      await Promise.all([refreshPkState(arena.gameId, roomCode), refreshRoom(arena.gameId, roomCode)])
    } catch (error) {
      if (errorStatus(error) === 401) setAuthRequired(true)
      notifications.show({
        title: errorStatus(error) === 429 ? '提交冷却中' : '提交失败',
        message: errorMessage(error),
        color: errorStatus(error) === 429 ? 'yellow' : 'red',
      })
    } finally {
      setSubmitting(false)
    }
  }

  if (pageStatus !== 'ready' || !arena) {
    return (
      <WithNavBar width="min(1100px, 94%)" minWidth={0}>
        <main className={classes.battlefield}>
          <VoxelPanel
            tone={pageStatus === 'error' ? 'danger' : 'obsidian'}
            title={pageStatus === 'loading' ? '正在加载 PK 战场' : 'PK 战场暂未开放'}
            eyebrow="SOLO PK"
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

  return (
    <WithNavBar width="min(1500px, 98%)" minWidth={0}>
      <main className={classes.battlefield}>
        <header className={classes.matchHeader}>
          <Button
            variant="subtle"
            color="gray"
            loading={leaving}
            onClick={() => void leaveRoom()}
            leftSection={<Icon path={mdiArrowLeft} size={0.8} />}
          >
            退出战场
          </Button>
          <div className={classes.roundScore}>
            <span data-won>{selfPlayer?.solves ?? runtime?.solves ?? 0}</span>
            <Text>ROOM {roomCode} · {arena.pkConfig.scoreMode.toUpperCase()}</Text>
            <span>{opponent.solves}</span>
          </div>
          <div
            className={classes.timer}
            data-warning={(matchStarted && remaining < 120) || (room?.status === 'countdown' && readyCountdown <= 3) || undefined}
          >
            <Icon path={mdiClockOutline} size={1} />
            {roomWaiting
              ? '--:--'
              : !matchStarted && !roomFinished
                ? `00:${String(readyCountdown).padStart(2, '0')}`
                : formatTime(remaining)}
          </div>
        </header>

        <VoxelPanel
          tone={roomWaiting ? 'wood' : roomFinished ? 'danger' : matchStarted ? 'grass' : 'obsidian'}
          compact
          title={
            roomWaiting
              ? `等待对手加入 · 房间 ${roomCode}`
              : roomFinished
                ? '本局比赛已结束'
                : matchStarted
                  ? `Solo PK 进行中 · 房间 ${roomCode}`
                  : `双方已到齐 · ${readyCountdown} 秒后开始`
          }
          eyebrow="PRIVATE SOLO ROOM"
        >
          <Group justify="space-between" align="center">
            <Group gap="sm">
              <ThemeIcon size={42} color={roomWaiting ? 'yellow' : matchStarted ? 'green' : 'cyan'} variant="light">
                <Icon path={roomWaiting ? mdiHumanGreeting : mdiSwordCross} size={1} />
              </ThemeIcon>
              <div>
                <Text fw={900} ff="monospace" size="xl">
                  {roomCode}
                </Text>
                <Text size="xs" c="dimmed">
                  {roomWaiting
                    ? '让另一名玩家在 PK 大厅输入此 6 位房间号；等待期间不会消耗比赛时间。'
                    : roomFinished
                      ? '双方成绩已锁定，可以退出房间重新创建对局。'
                      : matchStarted
                        ? `比赛计时已由服务器同步启动，剩余 ${formatTime(remaining)}。`
                        : '服务器已确认两名玩家，双方将在同一时刻开始比赛。'}
                </Text>
              </div>
            </Group>
            {roomWaiting && (
              <Button
                size="xs"
                variant="light"
                leftSection={<Icon path={mdiContentCopy} size={0.75} />}
                onClick={() => void copyRoomCode()}
              >
                复制房间号
              </Button>
            )}
          </Group>
        </VoxelPanel>

        {authRequired && (
          <VoxelPanel tone="wood" compact title="登录后才能计分" eyebrow="AUTH REQUIRED">
            <Group justify="space-between">
              <Text size="sm">题目配置已载入；登录 GZCTF 后即可读取个人积分并提交 Flag。</Text>
              <Button component={Link} to="/account/login" size="xs">
                前往登录
              </Button>
            </Group>
          </VoxelPanel>
        )}

        <section className={classes.playerStrip}>
          <div className={classes.playerSide}>
            <VoxelAvatar color="cyan" />
            <div>
              <Text fw={950}>{selfPlayer?.userName ?? user?.userName ?? '未登录玩家'}</Text>
              <Text size="xs" c="cyan.3">
                {room?.currentUserRole === 'host' ? '房主' : room?.currentUserRole === 'guest' ? '挑战者' : '连接中'} ·{' '}
                {runtime ? `${runtime.streak} 连胜` : '等待同步战绩'}
              </Text>
            </div>
            <strong>{score}</strong>
          </div>
          <div className={classes.vsMark}>
            <Icon path={mdiSwordCross} size={1.05} />
          </div>
          <div className={`${classes.playerSide} ${classes.opponent}`}>
            <strong>{opponent.score}</strong>
            <div>
              <Text fw={950} ta="right">
                {opponent.userName}
              </Text>
              <Text size="xs" c="orange.3" ta="right">
                {roomOpponent ? `${room?.currentUserRole === 'host' ? '挑战者' : '房主'} · ${opponent.solves} 解` : '等待输入房间号加入'}
              </Text>
            </div>
            <VoxelAvatar color="orange" />
          </div>
        </section>

        <div className={classes.battleGrid}>
          <Stack gap="md">
            <VoxelPanel tone="obsidian" title="战场情报" eyebrow="DUEL STATUS" compact>
              <Stack gap="md">
                <SegmentedBar
                  value={score}
                  max={maxScore}
                  segments={10}
                  tone="success"
                  label="我的题池进度"
                  detail={`${score} 分`}
                />
                <SegmentedBar
                  value={opponent.score}
                  max={maxScore}
                  segments={10}
                  tone="energy"
                  label="领先对手进度"
                  detail={`${opponent.score} 分`}
                />
                <SimpleGrid cols={2} spacing="xs">
                  <div className={classes.smallMetric}>
                    <strong>
                      {selfPlayer?.solves ?? runtime?.solves ?? 0}/{challenges.length}
                    </strong>
                    <span>已攻克</span>
                  </div>
                  <div className={classes.smallMetric}>
                    <strong>{wrongAttempts}</strong>
                    <span>本次错误提交</span>
                  </div>
                </SimpleGrid>
              </Stack>
            </VoxelPanel>

            <VoxelPanel tone="wood" title="真实计分规则" eyebrow="SCORING" compact>
              <Stack gap="xs">
                <Group justify="space-between">
                  <Text size="xs">错误提交</Text>
                  <Badge color="red">-{arena.pkConfig.wrongPenalty} 分</Badge>
                </Group>
                <Group justify="space-between">
                  <Text size="xs">首解奖励</Text>
                  <Badge color="yellow">+{arena.pkConfig.firstBloodBonus}</Badge>
                </Group>
                <Group justify="space-between">
                  <Text size="xs">连胜加成</Text>
                  <Badge color="cyan">+{arena.pkConfig.streakBonus}/层</Badge>
                </Group>
                <Group justify="space-between">
                  <Text size="xs">提交冷却</Text>
                  <Badge color="gray">{arena.pkConfig.cooldownSeconds}s</Badge>
                </Group>
              </Stack>
            </VoxelPanel>
          </Stack>

          <Stack gap="md">
            {challenges.length > 0 ? (
              <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
                {challenges.map((challenge, index) => (
                  <button
                    type="button"
                    key={challenge.id}
                    className={classes.challengeBlock}
                    data-active={challenge.id === active?.id || undefined}
                    data-solved={challenge.solved || undefined}
                    disabled={isPkLocked(challenge)}
                    onClick={() => setActiveId(challenge.id)}
                  >
                    <span>{isPkLocked(challenge) ? '尚未开放' : challenge.status}</span>
                    <strong>{challenge.title}</strong>
                    <small>
                      {challenge.category} · {challenge.difficulty} · {challenge.pk?.baseScore ?? 0} 分
                    </small>
                    <i>
                      {challenge.solved ? (
                        <Icon path={mdiCheckBold} size={0.75} />
                      ) : (
                        `#${String(index + 1).padStart(2, '0')}`
                      )}
                    </i>
                  </button>
                ))}
              </SimpleGrid>
            ) : (
              <VoxelPanel tone="stone" title="暂无 PK 题目" eyebrow="EMPTY POOL">
                <Text c="dimmed">管理员已经发布竞技场，但尚未配置可用的 PK 题目。</Text>
              </VoxelPanel>
            )}

            {active && (
              <VoxelPanel
                tone="stone"
                className={classes.challengeDetail}
                eyebrow={`${active.category} / ${active.difficulty}`}
                title={active.title}
                action={
                  active.solved ? (
                    <Badge color="green">已攻克</Badge>
                  ) : isPkLocked(active) ? (
                    <Badge color="gray">尚未开放</Badge>
                  ) : !matchStarted ? (
                    <Badge color={roomFinished ? 'red' : 'yellow'}>{roomFinished ? '比赛已结束' : '等待双方开赛'}</Badge>
                  ) : (
                    <Badge>{active.pk?.baseScore ?? 0} 基础分</Badge>
                  )
                }
              >
                <Stack gap="lg">
                  <Text className={classes.challengeCopy}>{active.description || '管理员暂未填写题目说明。'}</Text>

                  <Code block className={classes.codeBlock}>
                    {active.target ? `目标：${active.target}` : '目标：请根据题目描述与附件完成挑战'}
                  </Code>

                  <Group gap="sm">
                    {active.attachmentUrl && (
                      <Button
                        component="a"
                        href={active.attachmentUrl}
                        target="_blank"
                        rel="noreferrer"
                        className={classes.resourceButton}
                        leftSection={<Icon path={mdiDownload} size={0.8} />}
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
                        className={classes.resourceButton}
                        leftSection={<Icon path={mdiOpenInNew} size={0.8} />}
                      >
                        打开目标
                      </Button>
                    )}
                    {!active.attachmentUrl && !active.target && (
                      <Text size="xs" c="dimmed">
                        本题没有外部资源。
                      </Text>
                    )}
                  </Group>

                  <form className={classes.flagForm} onSubmit={(event) => void submitFlag(event)}>
                    <TextInput
                      aria-label="Flag"
                      value={flag}
                      onChange={(event) => setFlag(event.currentTarget.value)}
                      disabled={active.solved || isPkLocked(active) || authRequired || submitting || !matchStarted}
                      placeholder={
                        active.solved
                          ? '本题已完成'
                          : isPkLocked(active)
                            ? '题目尚未开放'
                            : roomFinished
                              ? '比赛已结束'
                              : !matchStarted
                                ? roomWaiting
                                  ? '等待另一名玩家进入房间'
                                  : `双方将在 ${readyCountdown} 秒后开始`
                                : 'flag{your_answer_here}'
                      }
                      leftSection={<Icon path={mdiFlagCheckered} size={0.8} />}
                    />
                    <Button
                      type="submit"
                      loading={submitting}
                      disabled={active.solved || isPkLocked(active) || authRequired || !flag.trim() || !matchStarted}
                      className={classes.submitButton}
                    >
                      {roomFinished ? '比赛已结束' : matchStarted ? '提交 Flag' : '等待开赛'}
                    </Button>
                  </form>

                  <Group gap={7} className={classes.ruleHint}>
                    <Icon path={mdiAlertCircleOutline} size={0.7} />
                    <Text size="xs">
                      服务端按 {arena.pkConfig.scoreMode === 'dynamic' ? '动态分值' : '固定分值'} 结算；提交间隔限制为{' '}
                      {arena.pkConfig.cooldownSeconds} 秒。
                    </Text>
                  </Group>
                </Stack>
              </VoxelPanel>
            )}
          </Stack>

          <VoxelPanel tone="obsidian" title="实时战报" eyebrow="EVENT FEED" className={classes.eventPanel} compact>
            <Stack gap="xs">
              {events.length ? (
                events.slice(0, 10).map((event, index) => (
                  <div key={`${event}-${index}`} className={classes.eventItem} data-fresh={index === 0 || undefined}>
                    <span>
                      {roomWaiting
                        ? roomCode
                        : !matchStarted && !roomFinished
                          ? `00:${String(readyCountdown).padStart(2, '0')}`
                          : formatTime(Math.max(0, remaining + index * 7))}
                    </span>
                    <Text size="xs">{event}</Text>
                  </div>
                ))
              ) : (
                <Text size="xs" c="dimmed">
                  等待真实对局事件…
                </Text>
              )}
            </Stack>
            <div className={classes.privacyHint}>
              <Icon path={mdiTrophyOutline} size={0.6} />
              房间状态与双方分数每秒同步
            </div>
          </VoxelPanel>
        </div>
      </main>
    </WithNavBar>
  )
}

export default PkMatch
