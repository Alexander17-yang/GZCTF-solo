import { arenaApi, OneWayRoomView, OneWayRoundView } from '@Services/ArenaApi'
import {
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from '@mantine/core'
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
  mdiMapMarkerPath,
  mdiOpenInNew,
  mdiRefresh,
  mdiSwordCross,
  mdiTimerSand,
  mdiTrophyOutline,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import { FC, FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { WithNavBar } from '@Components/WithNavbar'
import { SegmentedBar, VoxelAvatar, VoxelPanel } from '@Components/arena/VoxelUI'
import { usePageTitle } from '@Hooks/usePageTitle'
import { useUser } from '@Hooks/useUser'
import classes from '@Styles/PkMatch.module.css'

type ArenaPublicData = Awaited<ReturnType<typeof arenaApi.public.getActive>>
type PageStatus = 'loading' | 'ready' | 'empty' | 'unavailable' | 'error'

interface ResultAnnouncement {
  key: string
  eyebrow: string
  title: string
  message: string
  color: 'green' | 'yellow' | 'cyan'
  final?: boolean
}

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

const TERMINAL_ROOM_STATUSES = new Set([403, 404, 409, 410])

const roundAnnouncement = (round: OneWayRoundView): ResultAnnouncement =>
  round.isDraw || !round.winner
    ? {
        key: `round-${round.roundNumber}`,
        eyebrow: `ROUND ${round.roundNumber} RESULT`,
        title: '时间结束 · 平局',
        message: `第 ${round.roundNumber} 轮无人解出，双方均不获得轮次胜场。`,
        color: 'yellow',
      }
    : {
        key: `round-${round.roundNumber}`,
        eyebrow: `ROUND ${round.roundNumber} RESULT`,
        title: `${round.winner.userName} 获胜`,
        message: `${round.winner.userName} 最先解出本轮题目，赢得第 ${round.roundNumber} 轮。`,
        color: 'green',
      }

const finalAnnouncement = (room: OneWayRoomView): ResultAnnouncement =>
  room.isDraw || !room.winner
    ? {
        key: 'final',
        eyebrow: 'MATCH RESULT',
        title: '最终平局',
        message: `双方以 ${room.hostRoundWins} : ${room.guestRoundWins} 完成全部 ${room.totalRounds} 轮挑战。`,
        color: 'yellow',
        final: true,
      }
    : {
        key: 'final',
        eyebrow: 'MATCH RESULT',
        title: `${room.winner.userName} 获胜`,
        message: `最终比分 ${room.hostRoundWins} : ${room.guestRoundWins}，${room.winner.userName} 赢得本场单方向单挑。`,
        color: 'cyan',
        final: true,
      }

const OneWayMatch: FC = () => {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const roomCode = searchParams.get('room')?.trim() ?? ''
  const requestedGameId = Number(searchParams.get('gameId'))
  const hasValidGameId = Number.isInteger(requestedGameId) && requestedGameId > 0
  const { user } = useUser()
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [pageMessage, setPageMessage] = useState('正在连接单方向单挑战场…')
  const [arena, setArena] = useState<ArenaPublicData | null>(null)
  const [room, setRoom] = useState<OneWayRoomView | null>(null)
  const [authRequired, setAuthRequired] = useState(false)
  const [clockNow, setClockNow] = useState(() => Date.now())
  const [serverOffset, setServerOffset] = useState(0)
  const [flag, setFlag] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [events, setEvents] = useState<string[]>([])
  const [announcements, setAnnouncements] = useState<ResultAnnouncement[]>([])
  const enqueuedKeys = useRef(new Set<string>())
  const acknowledgedKeys = useRef(new Set<string>())
  const requestVersion = useRef(0)
  const submittingRef = useRef(false)
  const previousStatus = useRef<string | null>(null)

  usePageTitle('单方向单挑对局')

  const wasResultSeen = useCallback((key: string) => {
    if (acknowledgedKeys.current.has(key)) return true
    try {
      return window.localStorage.getItem(key) === '1'
    } catch {
      return false
    }
  }, [])

  const persistResultSeen = useCallback((key: string) => {
    acknowledgedKeys.current.add(key)
    try {
      window.localStorage.setItem(key, '1')
    } catch {
      // The acknowledged in-memory set still prevents repeats for this page lifetime.
    }
  }, [])

  const enqueueResults = useCallback(
    (nextRoom: OneWayRoomView) => {
      const next: ResultAnnouncement[] = []
      for (const round of nextRoom.rounds ?? []) {
        const key = `arena-one-way-result:${nextRoom.code}:${round.roundNumber}:${round.finishedAt ?? 'finished'}`
        if (round.status !== 'finished' || enqueuedKeys.current.has(key) || wasResultSeen(key)) continue
        enqueuedKeys.current.add(key)
        next.push({ ...roundAnnouncement(round), key })
      }
      const finalKey = `arena-one-way-result:${nextRoom.code}:final:${nextRoom.finishedAt ?? 'finished'}`
      if (nextRoom.status === 'finished' && !enqueuedKeys.current.has(finalKey) && !wasResultSeen(finalKey)) {
        enqueuedKeys.current.add(finalKey)
        next.push({ ...finalAnnouncement(nextRoom), key: finalKey })
      }
      if (next.length) setAnnouncements((current) => [...current, ...next])
    },
    [wasResultSeen]
  )

  const stopStaleMatch = useCallback(() => {
    requestVersion.current += 1
    setRoom(null)
    setPageStatus('error')
    setPageMessage('该单挑房间已结束、已重置或你已不在房间中，请返回大厅重新加入。')
  }, [])

  const refreshRoom = useCallback(
    async (gameId: number, code: string, quiet = true) => {
      const version = ++requestVersion.current
      try {
        const nextRoom = await arenaApi.public.getOneWayRoom(code, gameId)
        if (version !== requestVersion.current) return nextRoom
        setRoom(nextRoom)
        setServerOffset(Date.parse(nextRoom.serverTime) - Date.now())
        setAuthRequired(false)
        enqueueResults(nextRoom)
        return nextRoom
      } catch (error) {
        if (version !== requestVersion.current) return null
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
    },
    [enqueueResults, stopStaleMatch]
  )

  const loadMatch = useCallback(async () => {
    setPageStatus('loading')
    setPageMessage('正在连接单方向单挑战场…')
    if (!/^\d{6}$/.test(roomCode)) {
      setPageStatus('error')
      setPageMessage('缺少有效的 6 位房间号，请返回单方向单挑大厅创建或加入房间。')
      return
    }
    if (!hasValidGameId) {
      setPageStatus('error')
      setPageMessage('缺少有效的赛事 gameId，请返回单方向单挑大厅重新进入房间。')
      return
    }

    try {
      // The room is the frozen source of truth. Do not gate an in-progress match
      // on whichever arena mode an administrator happens to publish afterwards.
      const nextRoom = await refreshRoom(requestedGameId, roomCode, false)
      setEvents([
        `房间 ${roomCode} 已连接`,
        nextRoom ? `挑战方向：${nextRoom.direction.name}` : '正在同步挑战方向',
        nextRoom ? `赛制：${nextRoom.totalRounds} 轮，每轮一题` : '正在同步冻结赛制',
      ])
      setPageStatus('ready')

      // Public configuration is optional decoration only. The room remains usable
      // if the game was unpublished or its active mode changed after creation.
      try {
        setArena(await arenaApi.public.getGame(nextRoom?.gameId ?? requestedGameId))
      } catch {
        setArena(null)
      }
    } catch (error) {
      const status = errorStatus(error)
      if (status !== undefined && TERMINAL_ROOM_STATUSES.has(status)) {
        stopStaleMatch()
        return
      }
      setPageStatus('error')
      setPageMessage(errorMessage(error))
    }
  }, [hasValidGameId, refreshRoom, requestedGameId, roomCode, stopStaleMatch])

  useEffect(() => {
    void loadMatch()
  }, [loadMatch])

  useEffect(() => {
    if (pageStatus !== 'ready') return
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [pageStatus])

  useEffect(() => {
    if (!hasValidGameId || pageStatus !== 'ready' || authRequired || submitting) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      if (cancelled || submittingRef.current) return
      await refreshRoom(room?.gameId ?? requestedGameId, roomCode)
      if (!cancelled) timer = window.setTimeout(poll, document.visibilityState === 'hidden' ? 5000 : 1200)
    }
    timer = window.setTimeout(poll, 800)
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [authRequired, hasValidGameId, pageStatus, refreshRoom, requestedGameId, room?.gameId, roomCode, submitting])

  useEffect(() => {
    if (!room) return
    const previous = previousStatus.current
    previousStatus.current = room.status
    if (!previous || previous === room.status) return
    if (room.status === 'countdown') {
      setEvents((current) => [`${room.guest?.userName ?? '挑战者'} 已进入，双方开始同步倒计时`, ...current])
    } else if (room.status === 'active') {
      setEvents((current) => [`第 ${room.currentRound} 轮开始：最先解出者获胜`, ...current])
    } else if (room.status === 'interval') {
      setEvents((current) => [`第 ${room.currentRound} 轮已结算，等待下一轮`, ...current])
    } else if (room.status === 'finished') {
      setEvents((current) => ['全部轮次已结束，最终结果已锁定', ...current])
    }
  }, [room])

  const activeChallenge = room?.currentChallenge ?? null
  const selfPlayer = room?.currentUserRole === 'guest' ? room.guest : room?.host
  const opponent = room?.currentUserRole === 'guest' ? room.host : room?.guest
  const selfWins = room?.currentUserRole === 'guest' ? (room?.guestRoundWins ?? 0) : (room?.hostRoundWins ?? 0)
  const opponentWins = room?.currentUserRole === 'guest' ? (room?.hostRoundWins ?? 0) : (room?.guestRoundWins ?? 0)
  const serverNow = clockNow + serverOffset
  const countdownTarget = room?.startsAt ? Date.parse(room.startsAt) : null
  const roundEnd = room?.roundEndsAt ? Date.parse(room.roundEndsAt) : null
  const nextRound = room?.nextRoundStartsAt ? Date.parse(room.nextRoundStartsAt) : null
  const waiting = room?.status === 'waiting' || !room?.guest
  const countdown = room?.status === 'countdown'
  const active = room?.status === 'active'
  const interval = room?.status === 'interval'
  const finished = room?.status === 'finished'
  const remaining =
    active && roundEnd
      ? Math.max(0, Math.ceil((roundEnd - serverNow) / 1000))
      : countdown && countdownTarget
        ? Math.max(0, Math.ceil((countdownTarget - serverNow) / 1000))
        : interval && nextRound
          ? Math.max(0, Math.ceil((nextRound - serverNow) / 1000))
          : 0

  const copyRoomCode = async () => {
    try {
      await navigator.clipboard.writeText(roomCode)
      notifications.show({ title: '房间号已复制', message: roomCode, color: 'green' })
    } catch {
      notifications.show({ title: '房间号', message: roomCode, color: 'blue' })
    }
  }

  const leaveRoom = async () => {
    const gameId = room?.gameId ?? requestedGameId
    if (!Number.isInteger(gameId) || gameId <= 0 || leaving) return
    requestVersion.current += 1
    setLeaving(true)
    try {
      await arenaApi.public.leaveOneWayRoom(roomCode, gameId)
    } catch {
      // The room may already have expired; always allow the user to leave the page.
    } finally {
      navigate('/arena/one-way')
      setLeaving(false)
    }
  }

  const submitFlag = async (event: FormEvent) => {
    event.preventDefault()
    if (!room || !activeChallenge || !active || submittingRef.current || !flag.trim() || remaining <= 0) return
    submittingRef.current = true
    requestVersion.current += 1
    setSubmitting(true)
    try {
      const result = await arenaApi.public.submitOneWay({
        gameId: room.gameId,
        roomCode,
        challengeId: activeChallenge.id,
        flag: flag.trim(),
      })
      // Invalidate any GET that could have slipped through during React's
      // submit-state cleanup window before applying the authoritative response.
      requestVersion.current += 1
      setRoom(result.room)
      setServerOffset(Date.parse(result.room.serverTime) - Date.now())
      enqueueResults(result.room)
      if (result.alreadyResolved) {
        setEvents((current) => ['你的提交到达前，本轮已经由服务器结算', ...current])
        notifications.show({ title: '本轮已结算', message: result.message, color: 'blue' })
      } else if (result.correct) {
        setFlag('')
        setEvents((current) => [`你最先攻克了「${activeChallenge.title}」`, ...current])
        notifications.show({
          title: '提交正确',
          message: result.message,
          color: 'green',
        })
      } else {
        setEvents((current) => [`「${activeChallenge.title}」Flag 错误`, ...current])
        notifications.show({ title: 'Flag 错误', message: result.message, color: 'red' })
      }
    } catch (error) {
      if (errorStatus(error) === 401) setAuthRequired(true)
      notifications.show({ title: '提交失败', message: errorMessage(error), color: 'red' })
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  if (pageStatus !== 'ready') {
    return (
      <WithNavBar width="min(1100px, 94%)" minWidth={0}>
        <main className={classes.battlefield}>
          <VoxelPanel
            tone={pageStatus === 'error' ? 'danger' : 'obsidian'}
            title={pageStatus === 'loading' ? '正在加载单挑战场' : '单挑战场暂未开放'}
            eyebrow="ONE-WAY ONE-BY-ONE"
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
                  <Button leftSection={<Icon path={mdiRefresh} size={0.8} />} onClick={() => void loadMatch()}>
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

  const announcement = announcements[0]
  const acknowledgeAnnouncement = () => {
    if (!announcement) return
    persistResultSeen(announcement.key)
    enqueuedKeys.current.delete(announcement.key)
    setAnnouncements((current) =>
      current[0]?.key === announcement.key ? current.slice(1) : current.filter((item) => item.key !== announcement.key)
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
            <span data-won>{selfWins}</span>
            <Text>
              ROUND {Math.max(1, room?.currentRound ?? 1)} / {room?.totalRounds ?? arena?.oneWayConfig.roundCount ?? 1}
            </Text>
            <span>{opponentWins}</span>
          </div>
          <div className={classes.timer} data-warning={(active && remaining <= 60) || undefined}>
            <Icon path={mdiClockOutline} size={1} />
            {waiting ? '--:--' : finished ? '00:00' : formatTime(remaining)}
          </div>
        </header>

        <VoxelPanel
          tone={waiting ? 'wood' : finished ? 'danger' : active ? 'grass' : 'obsidian'}
          compact
          title={
            waiting
              ? `等待对手加入 · 房间 ${roomCode}`
              : countdown
                ? `双方已到齐 · ${remaining} 秒后开始`
                : active
                  ? `第 ${room?.currentRound} 轮进行中`
                  : interval
                    ? `本轮已结算 · ${remaining} 秒后进入下一轮`
                    : '全部轮次已结束'
          }
          eyebrow={`ONE-WAY · ${room?.direction.name ?? 'LOADING'}`}
        >
          <Group justify="space-between" align="center">
            <Group gap="sm">
              <ThemeIcon size={42} color={waiting ? 'yellow' : active ? 'green' : 'cyan'} variant="light">
                <Icon path={waiting ? mdiHumanGreeting : active ? mdiSwordCross : mdiTimerSand} size={1} />
              </ThemeIcon>
              <div>
                <Group gap="xs">
                  <Text fw={900} ff="monospace" size="xl">
                    {roomCode}
                  </Text>
                  <Badge color="violet" leftSection={<Icon path={mdiMapMarkerPath} size={0.6} />}>
                    {room?.direction.name}
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed">
                  {waiting
                    ? '让另一名玩家在大厅输入此 6 位房间号；等待期间不会消耗比赛时间。'
                    : active
                      ? '当前只开放这一道题，最先提交正确 Flag 的玩家立即赢得本轮。'
                      : interval
                        ? '双方正在查看本轮结果，下一轮题目将在倒计时结束后同时开放。'
                        : finished
                          ? '比分和每轮结果已锁定，可以退出房间重新创建对局。'
                          : '服务器已确认双方就位，将在同一时刻开放第一轮题目。'}
                </Text>
              </div>
            </Group>
            {waiting && (
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
          <VoxelPanel tone="wood" compact title="登录后才能参赛" eyebrow="AUTH REQUIRED">
            <Group justify="space-between">
              <Text size="sm">登录 GZCTF 后才能读取房间状态并提交 Flag。</Text>
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
                {room?.currentUserRole === 'host' ? '房主' : '挑战者'} · {selfWins} 轮胜利
              </Text>
            </div>
            <strong>{selfWins}</strong>
          </div>
          <div className={classes.vsMark}>
            <Icon path={mdiSwordCross} size={1.05} />
          </div>
          <div className={`${classes.playerSide} ${classes.opponent}`}>
            <strong>{opponentWins}</strong>
            <div>
              <Text fw={950} ta="right">
                {opponent?.userName ?? '等待挑战者'}
              </Text>
              <Text size="xs" c="orange.3" ta="right">
                {opponent
                  ? `${room?.currentUserRole === 'host' ? '挑战者' : '房主'} · ${opponentWins} 轮胜利`
                  : '等待输入房间号加入'}
              </Text>
            </div>
            <VoxelAvatar color="orange" />
          </div>
        </section>

        <div className={classes.battleGrid}>
          <Stack gap="md">
            <VoxelPanel tone="obsidian" title="轮次进度" eyebrow="ROUND SCORE" compact>
              <Stack gap="md">
                <SegmentedBar
                  value={(room?.rounds ?? []).filter((round) => round.status === 'finished').length}
                  max={room?.totalRounds ?? arena?.oneWayConfig.roundCount ?? 1}
                  segments={Math.min(10, room?.totalRounds ?? arena?.oneWayConfig.roundCount ?? 1)}
                  tone="success"
                  label="已完成轮次"
                  detail={`${(room?.rounds ?? []).filter((round) => round.status === 'finished').length} / ${room?.totalRounds ?? arena?.oneWayConfig.roundCount ?? 1}`}
                />
                <SimpleGrid cols={2} spacing="xs">
                  <div className={classes.smallMetric}>
                    <strong>{selfWins}</strong>
                    <span>我的胜场</span>
                  </div>
                  <div className={classes.smallMetric}>
                    <strong>{opponentWins}</strong>
                    <span>对手胜场</span>
                  </div>
                </SimpleGrid>
              </Stack>
            </VoxelPanel>

            <VoxelPanel tone="wood" title="逐轮战绩" eyebrow="ROUND HISTORY" compact>
              <Stack gap="xs">
                {(room?.rounds ?? []).length ? (
                  room?.rounds.map((round) => (
                    <Group key={round.roundNumber} justify="space-between" wrap="nowrap">
                      <Text size="xs">第 {round.roundNumber} 轮</Text>
                      <Badge
                        color={
                          round.status !== 'finished' ? 'gray' : round.isDraw || !round.winner ? 'yellow' : 'green'
                        }
                      >
                        {round.status !== 'finished'
                          ? round.status === 'active'
                            ? '进行中'
                            : '等待'
                          : round.isDraw || !round.winner
                            ? '平局'
                            : `${round.winner.userName} 获胜`}
                      </Badge>
                    </Group>
                  ))
                ) : (
                  <Text size="xs" c="dimmed">
                    第一轮开始后显示战绩。
                  </Text>
                )}
              </Stack>
            </VoxelPanel>
          </Stack>

          <Stack gap="md">
            {active && activeChallenge ? (
              <VoxelPanel
                tone="stone"
                className={classes.challengeDetail}
                eyebrow={`ROUND ${room?.currentRound} · ${activeChallenge.category} / ${activeChallenge.difficulty}`}
                title={activeChallenge.title}
                action={<Badge color="green">本轮唯一题目</Badge>}
              >
                <Stack gap="lg">
                  <Text className={classes.challengeCopy}>
                    {activeChallenge.description || '管理员暂未填写题目说明。'}
                  </Text>
                  <Code block className={classes.codeBlock}>
                    {activeChallenge.target ? `目标：${activeChallenge.target}` : '目标：请根据题目描述与附件完成挑战'}
                  </Code>
                  <Group gap="sm">
                    {activeChallenge.attachmentUrl && (
                      <Button
                        component="a"
                        href={activeChallenge.attachmentUrl}
                        target="_blank"
                        rel="noreferrer"
                        className={classes.resourceButton}
                        leftSection={<Icon path={mdiDownload} size={0.8} />}
                      >
                        下载附件
                      </Button>
                    )}
                    {activeChallenge.target?.match(/^https?:\/\//i) && (
                      <Button
                        component="a"
                        href={activeChallenge.target}
                        target="_blank"
                        rel="noreferrer"
                        className={classes.resourceButton}
                        leftSection={<Icon path={mdiOpenInNew} size={0.8} />}
                      >
                        打开目标
                      </Button>
                    )}
                  </Group>
                  <form className={classes.flagForm} onSubmit={(event) => void submitFlag(event)}>
                    <TextInput
                      aria-label="Flag"
                      value={flag}
                      onChange={(event) => setFlag(event.currentTarget.value)}
                      disabled={authRequired || submitting || remaining <= 0}
                      placeholder="flag{your_answer_here}"
                      leftSection={<Icon path={mdiFlagCheckered} size={0.8} />}
                    />
                    <Button
                      type="submit"
                      loading={submitting}
                      disabled={authRequired || !flag.trim() || remaining <= 0}
                      className={classes.submitButton}
                    >
                      提交 Flag
                    </Button>
                  </form>
                  <Group gap={7} className={classes.ruleHint}>
                    <Icon path={mdiAlertCircleOutline} size={0.7} />
                    <Text size="xs">正确提交由服务器原子结算；若双方同时提交，以服务端最先成功写入者为本轮赢家。</Text>
                  </Group>
                </Stack>
              </VoxelPanel>
            ) : (
              <VoxelPanel
                tone={finished ? 'danger' : interval ? 'wood' : 'obsidian'}
                title={
                  finished ? '对局已经结束' : interval ? '准备下一轮' : waiting ? '等待另一位玩家' : '题目尚未开放'
                }
                eyebrow="ONE CHALLENGE PER ROUND"
              >
                <Stack align="center" gap="md" py="xl">
                  <ThemeIcon size={58} color={finished ? 'red' : interval ? 'yellow' : 'cyan'} variant="light">
                    <Icon path={finished ? mdiTrophyOutline : interval ? mdiTimerSand : mdiSwordCross} size={1.25} />
                  </ThemeIcon>
                  <Title order={3} ta="center">
                    {finished
                      ? room?.isDraw || !room?.winner
                        ? '最终平局'
                        : `${room.winner.userName} 获胜`
                      : interval
                        ? `${remaining} 秒后同时开放下一题`
                        : waiting
                          ? `分享房间号 ${roomCode}`
                          : `${remaining} 秒后开始第一轮`}
                  </Title>
                  <Text ta="center" c="dimmed" maw={560}>
                    {interval
                      ? '轮间阶段不会提前显示下一题，确保双方在同一时间看到题面。'
                      : '每轮只开放一题，题目和计时均由服务器统一下发。'}
                  </Text>
                </Stack>
              </VoxelPanel>
            )}
          </Stack>

          <VoxelPanel tone="obsidian" title="实时战报" eyebrow="EVENT FEED" className={classes.eventPanel} compact>
            <Stack gap="xs">
              {events.slice(0, 10).map((event, index) => (
                <div key={`${event}-${index}`} className={classes.eventItem} data-fresh={index === 0 || undefined}>
                  <span>{active || countdown || interval ? formatTime(remaining) : roomCode}</span>
                  <Text size="xs">{event}</Text>
                </div>
              ))}
            </Stack>
            <div className={classes.privacyHint}>
              <Icon path={mdiCheckBold} size={0.6} />
              房间、计时与轮次结果由服务端同步
            </div>
          </VoxelPanel>
        </div>
      </main>

      <Modal
        opened={!!announcement}
        onClose={acknowledgeAnnouncement}
        centered
        closeOnClickOutside={false}
        closeOnEscape={false}
        title={announcement?.eyebrow}
      >
        {announcement && (
          <Stack align="center" gap="md" py="md">
            <ThemeIcon size={72} color={announcement.color} variant="light">
              <Icon
                path={
                  announcement.final ? mdiTrophyOutline : announcement.color === 'yellow' ? mdiTimerSand : mdiSwordCross
                }
                size={1.55}
              />
            </ThemeIcon>
            <Title order={2} ta="center">
              {announcement.title}
            </Title>
            <Text ta="center" c="dimmed">
              {announcement.message}
            </Text>
            <Button fullWidth color={announcement.color} onClick={acknowledgeAnnouncement}>
              {announcements.length > 1 ? '查看下一项结果' : announcement.final ? '确认最终结果' : '继续下一轮'}
            </Button>
          </Stack>
        )}
      </Modal>
    </WithNavBar>
  )
}

export default OneWayMatch
