import { arenaApi } from '@Services/ArenaApi'
import { Badge, Button, Group, SimpleGrid, Stack, Text, TextInput, ThemeIcon, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  mdiAccountSearch,
  mdiArrowLeft,
  mdiChartTimelineVariantShimmer,
  mdiCheckDecagram,
  mdiDoorOpen,
  mdiHomePlusOutline,
  mdiLightningBolt,
  mdiNumeric,
  mdiShieldCheckOutline,
  mdiSwordCross,
  mdiTimerSand,
  mdiTrophyOutline,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import { FC, FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { WithNavBar } from '@Components/WithNavbar'
import { PixelStat, SegmentedBar, VoxelAvatar, VoxelPanel } from '@Components/arena/VoxelUI'
import { usePageTitle } from '@Hooks/usePageTitle'
import { useUser } from '@Hooks/useUser'
import classes from '@Styles/PkArena.module.css'

type ArenaPublicData = Awaited<ReturnType<typeof arenaApi.public.getActive>>
type PkRuntimeState = Awaited<ReturnType<typeof arenaApi.public.getPkState>>

const roomErrorMessage = (error: unknown) => {
  const response = (
    error as {
      response?: { status?: number; data?: { detail?: string; title?: string; message?: string } }
      message?: string
    }
  )?.response

  if (response?.status === 401) return '请先登录 GZCTF，再创建或加入 Solo 房间。'
  return response?.data?.detail ?? response?.data?.message ?? response?.data?.title ?? '房间服务暂不可用，请稍后重试。'
}

const PkLobby: FC = () => {
  const navigate = useNavigate()
  const { user } = useUser()
  const [arena, setArena] = useState<ArenaPublicData | null>(null)
  const [runtime, setRuntime] = useState<PkRuntimeState | null>(null)
  const [configurationUnavailable, setConfigurationUnavailable] = useState(false)
  const [configurationError, setConfigurationError] = useState(false)
  const [roomCode, setRoomCode] = useState('')
  const [roomError, setRoomError] = useState('')
  const [roomAction, setRoomAction] = useState<'create' | 'join' | null>(null)

  usePageTitle('PK 大厅')

  useEffect(() => {
    let active = true

    const load = async () => {
      try {
        const config = await arenaApi.public.getActive()
        if (!active) return
        setArena(config)
        setConfigurationUnavailable(config.mode !== 'solo_pk' && config.mode !== 'hybrid')
        if (config.mode === 'solo_pk' || config.mode === 'hybrid') {
          try {
            const state = await arenaApi.public.getPkState(config.gameId)
            if (active) setRuntime(state)
          } catch {
            // Public rules remain visible when the visitor has not logged in yet.
          }
        }
      } catch {
        if (active) setConfigurationError(true)
      }
    }

    void load()
    return () => {
      active = false
    }
  }, [])

  const challengeCount =
    arena?.challenges.filter((challenge) => challenge.modes.includes('pk') && challenge.pk).length ?? 3
  const matchSeconds = arena?.pkConfig.matchSeconds ?? 15 * 60
  const matchMinutes = Math.max(1, Math.ceil(matchSeconds / 60))
  const maxLeaderboardScore = Math.max(1, ...(runtime?.leaderboard.map((entry) => entry.score) ?? [1]))
  const rules = [
    {
      id: 'first-blood',
      name: '首解奖励',
      description: `本题首位解出者额外获得 ${arena?.pkConfig.firstBloodBonus ?? 100} 分`,
      icon: mdiCheckDecagram,
    },
    {
      id: 'wrong-penalty',
      name: '错误惩罚',
      description: `错误 Flag 最多扣除 ${arena?.pkConfig.wrongPenalty ?? 0} 分`,
      icon: mdiShieldCheckOutline,
    },
    {
      id: 'streak',
      name: '连胜加成',
      description: `连续解题每层增加 ${arena?.pkConfig.streakBonus ?? 25} 分`,
      icon: mdiLightningBolt,
    },
  ]

  const leaderboard = useMemo(() => runtime?.leaderboard.slice(0, 4) ?? [], [runtime])

  const openRoom = (code: string) => {
    navigate(`/arena/pk/match?room=${encodeURIComponent(code)}`)
  }

  const createRoom = async () => {
    if (!arena || configurationUnavailable || roomAction) return
    setRoomAction('create')
    setRoomError('')
    try {
      const room = await arenaApi.public.createPkRoom(arena.gameId)
      openRoom(room.code)
    } catch (error) {
      const message = roomErrorMessage(error)
      setRoomError(message)
      notifications.show({ title: '创建房间失败', message, color: 'red' })
    } finally {
      setRoomAction(null)
    }
  }

  const joinRoom = async (event: FormEvent) => {
    event.preventDefault()
    if (!arena || configurationUnavailable || roomAction) return

    if (!/^\d{6}$/.test(roomCode)) {
      const message = '请输入完整的 6 位数字房间号。'
      setRoomError(message)
      notifications.show({ title: '房间号无效', message, color: 'yellow' })
      return
    }

    setRoomAction('join')
    setRoomError('')
    try {
      const room = await arenaApi.public.joinPkRoom(roomCode, arena.gameId)
      openRoom(room.code)
    } catch (error) {
      const message = roomErrorMessage(error)
      setRoomError(message)
      notifications.show({ title: '加入房间失败', message, color: 'red' })
    } finally {
      setRoomAction(null)
    }
  }

  const roomControlsDisabled = configurationUnavailable || configurationError || !arena

  return (
    <WithNavBar width="min(1240px, 95%)" minWidth={0}>
      <main className={classes.pkWorld}>
        <Group justify="space-between" align="flex-end" mb="lg">
          <div>
            <Button
              component={Link}
              to="/arena"
              variant="subtle"
              color="gray"
              px={0}
              leftSection={<Icon path={mdiArrowLeft} size={0.8} />}
            >
              返回模式大厅
            </Button>
            <Title className={classes.pageTitle}>矿坑决斗</Title>
            <Text className={classes.pageSubtitle}>
              {arena ? `SOLO RANKED ARENA #${arena.gameId} · REV ${arena.revision}` : 'SOLO RANKED ARENA'}
            </Text>
          </div>
          <Badge className={classes.onlineBadge}>
            {configurationUnavailable ? '当前赛事未开启 PK' : `${challengeCount} 道挑战已发布`}
          </Badge>
        </Group>

        <div className={classes.lobbyGrid}>
          <Stack gap="lg">
            <VoxelPanel tone="obsidian" title="矿工档案" eyebrow="YOUR SCORE">
              <Group align="center" wrap="nowrap">
                <VoxelAvatar color="cyan" size="lg" label="玩家头像" />
                <div className={classes.playerInfo}>
                  <Text fw={900} size="lg">
                    {user?.userName ?? '未登录玩家'}
                  </Text>
                  <Text c="yellow.4" fw={800}>
                    {runtime ? `${runtime.score.toLocaleString()} PK POINTS` : '登录后同步积分'}
                  </Text>
                  <Text size="xs" c="dimmed" mt={4}>
                    {runtime ? `${runtime.solves} 道已解 · 当前 ${runtime.streak} 连胜` : '个人数据由服务器实时结算'}
                  </Text>
                </div>
              </Group>
              <SegmentedBar
                value={runtime?.solves ?? 0}
                max={Math.max(1, challengeCount)}
                tone="energy"
                segments={10}
                label="题池进度"
                detail={`${runtime?.solves ?? 0} / ${challengeCount}`}
                size="sm"
              />
              <SimpleGrid cols={2} spacing="xs" mt="md">
                <PixelStat label="当前积分" value={runtime?.score.toLocaleString() ?? '--'} accent="#45d2c2" />
                <PixelStat label="连续攻克" value={runtime?.streak ?? '--'} accent="#f3c74f" />
              </SimpleGrid>
            </VoxelPanel>

            <VoxelPanel tone="stone" title="实时排行榜" eyebrow="LEADERBOARD">
              <Stack gap="sm">
                {leaderboard.length ? (
                  leaderboard.map((entry) => (
                    <div key={entry.userId} className={classes.skillRow}>
                      <Text fw={800} size="sm">
                        #{entry.rank} {entry.userName}
                      </Text>
                      <div>
                        <span
                          style={{
                            width: `${Math.max(4, (entry.score / maxLeaderboardScore) * 100)}%`,
                            background: '#45d2c2',
                          }}
                        />
                      </div>
                      <Text ff="monospace" fw={900} size="xs">
                        {entry.score}
                      </Text>
                    </div>
                  ))
                ) : (
                  <Text size="sm" c="dimmed">
                    登录后显示实时 PK 排行榜。
                  </Text>
                )}
              </Stack>
            </VoxelPanel>
          </Stack>

          <VoxelPanel tone="grass" className={classes.matchCore}>
            <Stack align="center" gap="lg">
              <div className={classes.duelMark} data-searching={roomAction || undefined}>
                <VoxelAvatar color="cyan" size="lg" />
                <span>
                  <Icon path={roomAction ? mdiAccountSearch : mdiSwordCross} size={1.35} />
                </span>
                <VoxelAvatar color="orange" size="lg" />
              </div>

              <div className={classes.matchHeading}>
                <Text className={classes.modeLabel}>{roomAction ? 'CONNECTING ROOM' : 'PRIVATE SOLO ROOM'}</Text>
                <Title order={2}>{roomAction ? '正在连接方块房间' : '创建或加入 Solo 房间'}</Title>
                <Text c="dimmed" mt={6}>
                  {roomAction
                    ? '正在验证房间与玩家身份…'
                    : `${challengeCount} 道挑战 · 每回合 ${matchMinutes} 分钟 · ${arena?.pkConfig.sameQuestionsForBoth === false ? '独立变体题池' : '同题竞技'}`}
                </Text>
              </div>

              <Group justify="center" gap="xs">
                <Badge color="cyan">{arena?.pkConfig.scoreMode === 'dynamic' ? '动态分值' : '固定分值'}</Badge>
                <Badge color="yellow">冷却 {arena?.pkConfig.cooldownSeconds ?? 3}s</Badge>
                <Badge color="gray">{arena?.pkConfig.winRule ?? 'highest_score'}</Badge>
              </Group>

              <SimpleGrid cols={3} spacing="xs" w="100%">
                <PixelStat
                  label="回合时长"
                  value={`${matchMinutes}m`}
                  accent="#45d2c2"
                  icon={<Icon path={mdiTimerSand} size={0.8} />}
                />
                <PixelStat
                  label="题池数量"
                  value={challengeCount}
                  accent="#f3c74f"
                  icon={<Icon path={mdiChartTimelineVariantShimmer} size={0.8} />}
                />
                <PixelStat
                  label="首解奖励"
                  value={`+${arena?.pkConfig.firstBloodBonus ?? 100}`}
                  accent="#67af50"
                  icon={<Icon path={mdiTrophyOutline} size={0.8} />}
                />
              </SimpleGrid>

              <Stack className={classes.roomActions} gap="sm">
                <Button
                  fullWidth
                  size="lg"
                  className={classes.matchButton}
                  loading={roomAction === 'create'}
                  disabled={roomControlsDisabled || roomAction !== null}
                  leftSection={<Icon path={mdiHomePlusOutline} size={1} />}
                  onClick={() => void createRoom()}
                >
                  {configurationUnavailable
                    ? '当前赛事未开启 PK'
                    : configurationError
                      ? '竞技场服务暂不可用'
                      : arena
                        ? '创建 6 位房间'
                        : '正在读取赛事配置'}
                </Button>

                <div className={classes.roomDivider}>
                  <span>或输入好友的 6 位房间号</span>
                </div>

                <form className={classes.roomJoinForm} onSubmit={(event) => void joinRoom(event)}>
                  <TextInput
                    className={classes.roomCodeInput}
                    aria-label="6 位 Solo 房间号"
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={6}
                    placeholder="000000"
                    size="lg"
                    leftSection={<Icon path={mdiNumeric} size={0.9} />}
                    value={roomCode}
                    error={roomError || undefined}
                    disabled={roomControlsDisabled || roomAction !== null}
                    onChange={(event) => {
                      setRoomCode(event.currentTarget.value.replace(/\D/g, '').slice(0, 6))
                      setRoomError('')
                    }}
                  />
                  <Button
                    type="submit"
                    size="lg"
                    className={classes.cancelButton}
                    loading={roomAction === 'join'}
                    disabled={roomControlsDisabled || roomAction !== null || roomCode.length !== 6}
                    leftSection={<Icon path={mdiDoorOpen} size={1} />}
                  >
                    加入房间
                  </Button>
                </form>
              </Stack>

              <Text className={classes.roomHint} size="xs" c="dimmed" ta="center">
                房主不会提前计时；第二位玩家成功进入后，双方按服务器时间同步开始 5 秒倒计时。
              </Text>

              <Text size="xs" c="dimmed" ta="center">
                Flag 由服务器验证，积分、首解、连胜和错误惩罚均以服务端结算为准。
              </Text>
            </Stack>
          </VoxelPanel>

          <Stack gap="lg">
            <VoxelPanel tone="wood" title="计分规则" eyebrow="SERVER RULES" action={<Badge>LIVE</Badge>}>
              <Stack gap="sm">
                {rules.map((rule) => (
                  <div key={rule.id} className={classes.tacticCard} data-selected>
                    <ThemeIcon size={42} className={classes.tacticIcon}>
                      <Icon path={rule.icon} size={1} />
                    </ThemeIcon>
                    <span>
                      <strong>{rule.name}</strong>
                      <small>{rule.description}</small>
                    </span>
                    <Icon path={mdiCheckDecagram} size={0.85} />
                  </div>
                ))}
              </Stack>
            </VoxelPanel>

            <VoxelPanel tone="stone" title="题池规则" eyebrow="CHALLENGE POOL">
              <Text size="sm" c="dimmed" mb="sm">
                当前规则由管理员后台发布，玩家端只读取真实配置。
              </Text>
              <Group gap="xs">
                <Badge className={classes.banTag}>
                  {arena?.pkConfig.sameQuestionsForBoth === false ? '独立变体' : '双方同题'}
                </Badge>
                <Badge className={classes.banTagMuted}>{challengeCount} 题</Badge>
              </Group>
            </VoxelPanel>
          </Stack>
        </div>
      </main>
    </WithNavBar>
  )
}

export default PkLobby
