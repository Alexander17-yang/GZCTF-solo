import { arenaApi } from '@Services/ArenaApi'
import { Badge, Button, Group, SimpleGrid, Stack, Text, TextInput, ThemeIcon, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  mdiArrowLeft,
  mdiArrowRightBold,
  mdiCheckDecagram,
  mdiDoorOpen,
  mdiHomePlusOutline,
  mdiMapMarkerPath,
  mdiNumeric,
  mdiShuffleDisabled,
  mdiSwordCross,
  mdiTimerSand,
  mdiTrophyOutline,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import { FC, FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { WithNavBar } from '@Components/WithNavbar'
import { PixelStat, VoxelAvatar, VoxelPanel } from '@Components/arena/VoxelUI'
import { usePageTitle } from '@Hooks/usePageTitle'
import { useUser } from '@Hooks/useUser'
import classes from '@Styles/PkArena.module.css'

type ArenaPublicData = Awaited<ReturnType<typeof arenaApi.public.getActive>>

const roomErrorMessage = (error: unknown) => {
  const response = (
    error as {
      response?: { status?: number; data?: { detail?: string; title?: string; message?: string } }
      message?: string
    }
  )?.response

  if (response?.status === 401) return '请先登录 GZCTF，再创建或加入单方向单挑房间。'
  return response?.data?.detail ?? response?.data?.message ?? response?.data?.title ?? '房间服务暂不可用，请稍后重试。'
}

const OneWayLobby: FC = () => {
  const navigate = useNavigate()
  const { user } = useUser()
  const [arena, setArena] = useState<ArenaPublicData | null>(null)
  const [configurationUnavailable, setConfigurationUnavailable] = useState(false)
  const [configurationError, setConfigurationError] = useState(false)
  const [directionId, setDirectionId] = useState('')
  const [roomCode, setRoomCode] = useState('')
  const [roomError, setRoomError] = useState('')
  const [roomAction, setRoomAction] = useState<'create' | 'join' | null>(null)

  usePageTitle('单方向单挑')

  useEffect(() => {
    let active = true

    const load = async () => {
      try {
        const config = await arenaApi.public.getActive()
        if (!active) return
        setArena(config)
        setConfigurationUnavailable(config.mode !== 'one_way_onebyone')
        setDirectionId((current) =>
          config.oneWayConfig.directions.some((direction) => direction.id === current)
            ? current
            : (config.oneWayConfig.directions[0]?.id ?? '')
        )
      } catch {
        if (active) setConfigurationError(true)
      }
    }

    void load()
    return () => {
      active = false
    }
  }, [])

  const directions = arena?.oneWayConfig.directions ?? []
  const selectedDirection = useMemo(
    () => directions.find((direction) => direction.id === directionId) ?? null,
    [directionId, directions]
  )
  const roundCount = arena?.oneWayConfig.roundCount ?? 3
  const roundMinutes = Math.max(1, Math.ceil((arena?.oneWayConfig.roundSeconds ?? 900) / 60))

  const openRoom = (code: string, gameId: number) => {
    navigate(`/arena/one-way/match?room=${encodeURIComponent(code)}&gameId=${gameId}`)
  }

  const createRoom = async () => {
    if (!arena || configurationUnavailable || roomAction || !selectedDirection) return
    setRoomAction('create')
    setRoomError('')
    try {
      const room = await arenaApi.public.createOneWayRoom(arena.gameId, selectedDirection.id)
      openRoom(room.code, room.gameId)
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
    if (roomAction) return
    if (!/^\d{6}$/.test(roomCode)) {
      const message = '请输入完整的 6 位数字房间号。'
      setRoomError(message)
      notifications.show({ title: '房间号无效', message, color: 'yellow' })
      return
    }

    setRoomAction('join')
    setRoomError('')
    try {
      // Joining is intentionally code-only. A waiting room is a frozen match
      // resource and remains joinable after its source game changes mode or is
      // unpublished; the authoritative gameId comes back with the room.
      const room = await arenaApi.public.joinOneWayRoom(roomCode)
      openRoom(room.code, room.gameId)
    } catch (error) {
      const message = roomErrorMessage(error)
      setRoomError(message)
      notifications.show({ title: '加入房间失败', message, color: 'red' })
    } finally {
      setRoomAction(null)
    }
  }

  const createDisabled = configurationUnavailable || configurationError || !arena || !selectedDirection
  const joinDisabled = roomAction !== null

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
            <Title className={classes.pageTitle}>单方向单挑</Title>
            <Text className={classes.pageSubtitle}>
              {arena ? `ONE-WAY ONE-BY-ONE #${arena.gameId} · REV ${arena.revision}` : 'ONE-WAY ONE-BY-ONE'}
            </Text>
          </div>
          <Badge className={classes.onlineBadge}>
            {configurationError
              ? '配置离线 · 仍可凭房间号加入'
              : configurationUnavailable
                ? '当前不可创建 · 可加入已有房间'
                : `${directions.length} 个挑战方向`}
          </Badge>
        </Group>

        <div className={classes.lobbyGrid}>
          <Stack gap="lg">
            <VoxelPanel tone="obsidian" title="决斗档案" eyebrow="DUELIST">
              <Group align="center" wrap="nowrap">
                <VoxelAvatar color="cyan" size="lg" label="玩家头像" />
                <div className={classes.playerInfo}>
                  <Text fw={900} size="lg">
                    {user?.userName ?? '未登录玩家'}
                  </Text>
                  <Text c="yellow.4" fw={800}>
                    单题竞速 · 逐轮结算
                  </Text>
                  <Text size="xs" c="dimmed" mt={4}>
                    每轮双方只会看到同一道题，第一位解出者立即赢得本轮。
                  </Text>
                </div>
              </Group>
              <SimpleGrid cols={2} spacing="xs" mt="md">
                <PixelStat label="挑战轮次" value={roundCount} accent="#45d2c2" />
                <PixelStat label="单轮时限" value={`${roundMinutes}m`} accent="#f3c74f" />
              </SimpleGrid>
            </VoxelPanel>

            <VoxelPanel tone="wood" title="胜负规则" eyebrow="FIRST SOLVE WINS">
              <Stack gap="sm">
                <Group gap="sm" wrap="nowrap">
                  <ThemeIcon size={38} color="yellow" variant="light">
                    <Icon path={mdiTrophyOutline} size={0.9} />
                  </ThemeIcon>
                  <Text size="sm">本轮第一位提交正确 Flag 的玩家立即获胜，双方同步收到结果。</Text>
                </Group>
                <Group gap="sm" wrap="nowrap">
                  <ThemeIcon size={38} color="gray" variant="light">
                    <Icon path={mdiTimerSand} size={0.9} />
                  </ThemeIcon>
                  <Text size="sm">倒计时归零仍无人解出，本轮直接判定平局，不延长时间。</Text>
                </Group>
              </Stack>
            </VoxelPanel>
          </Stack>

          <VoxelPanel tone="grass" className={classes.matchCore}>
            <Stack align="center" gap="lg">
              <div className={classes.duelMark} data-searching={roomAction || undefined}>
                <VoxelAvatar color="cyan" size="lg" />
                <span>
                  <Icon path={mdiArrowRightBold} size={1.35} />
                </span>
                <VoxelAvatar color="orange" size="lg" />
              </div>

              <div className={classes.matchHeading}>
                <Text className={classes.modeLabel}>ONE DIRECTION · ONE CHALLENGE</Text>
                <Title order={2}>先选方向，再创建房间</Title>
                <Text c="dimmed" mt={6}>
                  管理员决定方向题池与轮次；每局从所选方向无放回随机抽题，每轮只开放一题。
                </Text>
              </div>

              <Stack gap="xs" w="100%">
                {directions.length ? (
                  directions.map((direction) => (
                    <button
                      key={direction.id}
                      type="button"
                      className={classes.tacticCard}
                      data-selected={direction.id === directionId || undefined}
                      disabled={createDisabled || roomAction !== null}
                      onClick={() => setDirectionId(direction.id)}
                    >
                      <ThemeIcon size={42} className={classes.tacticIcon}>
                        <Icon path={mdiMapMarkerPath} size={1} />
                      </ThemeIcon>
                      <span>
                        <strong>{direction.name}</strong>
                        <small>{direction.description || '管理员专属题池 · 每局随机不重复'}</small>
                      </span>
                      <Icon path={direction.id === directionId ? mdiCheckDecagram : mdiArrowRightBold} size={0.85} />
                    </button>
                  ))
                ) : (
                  <Text ta="center" c="dimmed" size="sm">
                    管理员尚未配置可用的挑战方向。
                  </Text>
                )}
              </Stack>

              <SimpleGrid cols={3} spacing="xs" w="100%">
                <PixelStat
                  label="当前方向"
                  value={selectedDirection?.name ?? '--'}
                  accent="#45d2c2"
                  icon={<Icon path={mdiMapMarkerPath} size={0.8} />}
                />
                <PixelStat
                  label="挑战轮次"
                  value={roundCount}
                  accent="#f3c74f"
                  icon={<Icon path={mdiSwordCross} size={0.8} />}
                />
                <PixelStat
                  label="题目顺序"
                  value="随机"
                  accent="#67af50"
                  icon={<Icon path={mdiShuffleDisabled} size={0.8} />}
                />
              </SimpleGrid>

              <Stack className={classes.roomActions} gap="sm">
                <Button
                  fullWidth
                  size="lg"
                  className={classes.matchButton}
                  loading={roomAction === 'create'}
                  disabled={createDisabled || roomAction !== null}
                  leftSection={<Icon path={mdiHomePlusOutline} size={1} />}
                  onClick={() => void createRoom()}
                >
                  {configurationUnavailable
                    ? '当前赛事未开启单方向单挑'
                    : configurationError
                      ? '竞技场服务暂不可用'
                      : selectedDirection
                        ? `创建「${selectedDirection.name}」房间`
                        : '请先选择挑战方向'}
                </Button>

                <div className={classes.roomDivider}>
                  <span>或输入好友的 6 位房间号</span>
                </div>

                <form className={classes.roomJoinForm} onSubmit={(event) => void joinRoom(event)}>
                  <TextInput
                    className={classes.roomCodeInput}
                    aria-label="6 位单方向单挑房间号"
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={6}
                    placeholder="000000"
                    size="lg"
                    leftSection={<Icon path={mdiNumeric} size={0.9} />}
                    value={roomCode}
                    error={roomError || undefined}
                    disabled={joinDisabled}
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
                    disabled={joinDisabled || roomCode.length !== 6}
                    leftSection={<Icon path={mdiDoorOpen} size={1} />}
                  >
                    加入房间
                  </Button>
                </form>
              </Stack>

              <Text className={classes.roomHint} size="xs" c="dimmed" ta="center">
                房主等待期间不计时；即使当前赛事已切换模式或下架，已有等待房仍可凭 6 位房间号加入。
              </Text>
            </Stack>
          </VoxelPanel>

          <Stack gap="lg">
            <VoxelPanel tone="stone" title="当前赛制" eyebrow="ROUND SETTINGS" action={<Badge>LIVE</Badge>}>
              <Stack gap="sm">
                <Group justify="space-between">
                  <Text size="sm">准备倒计时</Text>
                  <Badge color="cyan">{arena?.oneWayConfig.countdownSeconds ?? 5}s</Badge>
                </Group>
                <Group justify="space-between">
                  <Text size="sm">每局轮次</Text>
                  <Badge color="yellow">{roundCount}</Badge>
                </Group>
                <Group justify="space-between">
                  <Text size="sm">每轮限时</Text>
                  <Badge color="green">{roundMinutes}m</Badge>
                </Group>
                <Group justify="space-between">
                  <Text size="sm">轮间展示</Text>
                  <Badge color="gray">{arena?.oneWayConfig.intervalSeconds ?? 5}s</Badge>
                </Group>
              </Stack>
            </VoxelPanel>

            <VoxelPanel tone="obsidian" title="方向题池" eyebrow="ADMIN POOL">
              <Text size="sm" c="dimmed" mb="sm">
                房间方向创建后不可更改。加入者自动继承房主选择的方向。
              </Text>
              <Group gap="xs">
                <Badge className={classes.banTag}>{selectedDirection?.name ?? '未选择'}</Badge>
                <Badge className={classes.banTagMuted}>无放回随机抽题</Badge>
              </Group>
            </VoxelPanel>
          </Stack>
        </div>
      </main>
    </WithNavBar>
  )
}

export default OneWayLobby
