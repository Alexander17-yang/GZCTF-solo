import { AdminOneWayMatchRecord, AdminOneWayMatchStatus, arenaApi, OneWayRoomPlayer } from '@Services/ArenaApi'
import {
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  mdiAccountMultipleOutline,
  mdiDeleteOutline,
  mdiDoorClosedLock,
  mdiHistory,
  mdiMapMarkerPath,
  mdiRefresh,
  mdiSwordCross,
  mdiTrophyOutline,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import { FC, useCallback, useEffect, useMemo, useState } from 'react'
import classes from '@Styles/ArenaAdmin.module.css'

interface Props {
  gameId: number
}

type DeleteAction = 'room' | 'record'

const formatDateTime = (value: string | null) => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

const statusMeta: Record<AdminOneWayMatchStatus, { label: string; color: string }> = {
  waiting: { label: '等待加入', color: 'yellow' },
  countdown: { label: '准备倒计时', color: 'cyan' },
  active: { label: '进行中', color: 'green' },
  interval: { label: '轮间结算', color: 'violet' },
  finished: { label: '已完成', color: 'blue' },
  cancelled: { label: '已取消', color: 'gray' },
  reset: { label: '已重置', color: 'orange' },
}

const Player: FC<{
  label: string
  player: OneWayRoomPlayer | null
  winnerUserId: string | null
}> = ({ label, player, winnerUserId }) => (
  <div
    className={classes.matchPlayer}
    data-winner={(player && player.userId === winnerUserId) || undefined}
    data-empty={!player || undefined}
  >
    <Text size="xs" c="dimmed" fw={800}>
      {label}
    </Text>
    <Text size="sm" fw={900} truncate>
      {player?.userName ?? '尚未加入'}
    </Text>
    <Text className={classes.matchUserId} size="xs" c="dimmed">
      {player ? `${player.roundWins} 胜 · ${player.userId}` : '—'}
    </Text>
  </div>
)

const Result: FC<{ match: AdminOneWayMatchRecord }> = ({ match }) => {
  if (match.status === 'cancelled')
    return (
      <Stack gap={3}>
        <Badge color="gray">已取消</Badge>
        <Text size="xs" c="dimmed">
          对局未完成
        </Text>
      </Stack>
    )
  if (match.status === 'reset')
    return (
      <Stack gap={3}>
        <Badge color="orange">已重置</Badge>
        <Text size="xs" c="dimmed">
          管理员重置
        </Text>
      </Stack>
    )
  if (match.status !== 'finished') return <Text size="xs">等待结算</Text>
  if (match.isDraw)
    return (
      <Stack gap={3}>
        <Badge color="yellow">平局</Badge>
        <Text size="xs" c="dimmed">
          {match.hostRoundWins} : {match.guestRoundWins} · {match.roundDraws} 轮平
        </Text>
      </Stack>
    )
  if (!match.winner) return <Badge color="gray">已结束 · 无胜者</Badge>
  return (
    <Stack gap={3}>
      <Badge color="green">{match.winner.userName} 获胜</Badge>
      <Text size="xs" c="dimmed">
        {match.hostRoundWins} : {match.guestRoundWins} · {match.roundDraws} 轮平
      </Text>
    </Stack>
  )
}

const RoundHistory: FC<{ match: AdminOneWayMatchRecord }> = ({ match }) => (
  <Stack gap={4} miw="12rem">
    {match.rounds.length ? (
      match.rounds.map((round) => (
        <Group key={round.roundNumber} justify="space-between" gap="xs" wrap="nowrap">
          <Text size="xs" truncate maw="9rem">
            R{round.roundNumber} · {round.challengeTitle ?? (round.challengeId ? `#${round.challengeId}` : '待抽题')}
          </Text>
          <Badge size="xs" color={round.status !== 'finished' ? 'gray' : round.isDraw ? 'yellow' : 'green'}>
            {round.status !== 'finished'
              ? round.status === 'active'
                ? '进行中'
                : '等待'
              : round.isDraw
                ? '平局'
                : `${round.winnerUserName ?? '未知'} 胜`}
          </Badge>
        </Group>
      ))
    ) : (
      <Text size="xs" c="dimmed">
        尚无轮次记录
      </Text>
    )}
  </Stack>
)

const Times: FC<{ match: AdminOneWayMatchRecord }> = ({ match }) => (
  <div className={classes.matchTimes}>
    <Text size="xs">
      <span>创建</span> {formatDateTime(match.createdAt)}
    </Text>
    <Text size="xs">
      <span>入场</span> {formatDateTime(match.joinedAt)}
    </Text>
    <Text size="xs">
      <span>开始</span> {formatDateTime(match.startsAt)}
    </Text>
    <Text size="xs">
      <span>完成</span> {formatDateTime(match.finishedAt)}
    </Text>
  </div>
)

const OneWayMatchRecords: FC<Props> = ({ gameId }) => {
  const [matches, setMatches] = useState<AdminOneWayMatchRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<'all' | AdminOneWayMatchStatus>('all')
  const [deleteTarget, setDeleteTarget] = useState<{ match: AdminOneWayMatchRecord; action: DeleteAction } | null>(null)
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setMatches(await arenaApi.admin.listOneWayMatches(gameId, 200))
    } catch (error) {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '无法读取单方向单挑记录。'
      notifications.show({ title: '加载对局记录失败', message, color: 'red' })
    } finally {
      setLoading(false)
    }
  }, [gameId])

  useEffect(() => {
    void load()
  }, [load])

  const filteredMatches = useMemo(
    () => (statusFilter === 'all' ? matches : matches.filter((match) => match.status === statusFilter)),
    [matches, statusFilter]
  )
  const liveCount = matches.filter((match) =>
    ['waiting', 'countdown', 'active', 'interval'].includes(match.status)
  ).length
  const finishedCount = matches.filter((match) => match.status === 'finished').length
  const totalRounds = matches.reduce(
    (total, match) => total + match.rounds.filter((round) => round.status === 'finished').length,
    0
  )

  const askDelete = (match: AdminOneWayMatchRecord, action: DeleteAction) => {
    if (action === 'record' && match.roomExists !== false) {
      notifications.show({
        title: '请先关闭房间',
        message: `房间 ${match.roomCode} 仍存在，先删除房间后才能删除记录。`,
        color: 'yellow',
      })
      return
    }
    setDeleteTarget({ match, action })
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    try {
      if (deleteTarget.action === 'room') {
        await arenaApi.admin.deleteOneWayMatchRoom(gameId, deleteTarget.match.matchId)
        // Deleting a live room also transitions its audit to `reset` on the
        // server. Reload the authoritative record so status counters and the
        // finish reason do not briefly retain the pre-delete live state.
        await load()
        notifications.show({
          title: '房间已关闭',
          message: `房间 ${deleteTarget.match.roomCode} 已删除，对局人员与逐轮结果仍保留。`,
          color: 'green',
        })
      } else {
        await arenaApi.admin.deleteOneWayMatch(gameId, deleteTarget.match.matchId)
        setMatches((current) => current.filter((match) => match.matchId !== deleteTarget.match.matchId))
        notifications.show({
          title: '记录已删除',
          message: `记录 #${deleteTarget.match.matchId} 已删除。`,
          color: 'green',
        })
      }
      setDeleteTarget(null)
    } catch (error) {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '删除操作失败。'
      notifications.show({ title: '删除失败', message, color: 'red' })
    } finally {
      setDeleting(false)
    }
  }

  const Actions: FC<{ match: AdminOneWayMatchRecord; mobile?: boolean }> = ({ match, mobile }) => (
    <Group className={mobile ? classes.matchCardActions : classes.matchActions} gap={6} align="stretch">
      <Tooltip label={match.roomExists === false ? '房间已经删除' : '关闭房间但保留对局记录'}>
        <span className={classes.matchActionTooltipTarget}>
          <Button
            size="xs"
            variant="light"
            color="orange"
            disabled={match.roomExists === false}
            leftSection={<Icon path={mdiDoorClosedLock} size={0.7} />}
            onClick={() => askDelete(match, 'room')}
          >
            删除房间
          </Button>
        </span>
      </Tooltip>
      <Tooltip label={match.roomExists !== false ? '需要先删除房间' : '永久删除对局与逐轮记录'}>
        <span className={classes.matchActionTooltipTarget}>
          <Button
            size="xs"
            variant="light"
            color="red"
            disabled={match.roomExists !== false}
            leftSection={<Icon path={mdiDeleteOutline} size={0.7} />}
            onClick={() => askDelete(match, 'record')}
          >
            删除记录
          </Button>
        </span>
      </Tooltip>
    </Group>
  )

  return (
    <Paper className={classes.configBlock}>
      <Group className={classes.matchToolbar} justify="space-between" align="flex-start" mb="md">
        <div>
          <Title order={4}>单方向单挑对局记录</Title>
          <Text size="xs" c="dimmed">
            查看房间方向、双方玩家、逐轮题目、每轮结果和最终胜负；房间与历史记录可分步删除。
          </Text>
        </div>
        <Group className={classes.matchToolbarActions} gap="sm">
          <Select
            className={classes.matchFilter}
            value={statusFilter}
            allowDeselect={false}
            data={[
              { value: 'all', label: '全部状态' },
              ...Object.entries(statusMeta).map(([value, meta]) => ({ value, label: meta.label })),
            ]}
            onChange={(value) => setStatusFilter((value ?? 'all') as 'all' | AdminOneWayMatchStatus)}
          />
          <Button
            variant="outline"
            loading={loading}
            leftSection={<Icon path={mdiRefresh} size={0.8} />}
            onClick={() => void load()}
          >
            刷新
          </Button>
        </Group>
      </Group>

      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm" mb="md">
        <Paper className={classes.matchStat}>
          <ThemeIcon color="cyan" variant="light">
            <Icon path={mdiAccountMultipleOutline} size={0.9} />
          </ThemeIcon>
          <div>
            <strong>{liveCount}</strong>
            <span>当前房间</span>
          </div>
        </Paper>
        <Paper className={classes.matchStat}>
          <ThemeIcon color="green" variant="light">
            <Icon path={mdiTrophyOutline} size={0.9} />
          </ThemeIcon>
          <div>
            <strong>{finishedCount}</strong>
            <span>已完成对局</span>
          </div>
        </Paper>
        <Paper className={classes.matchStat}>
          <ThemeIcon color="violet" variant="light">
            <Icon path={mdiHistory} size={0.9} />
          </ThemeIcon>
          <div>
            <strong>{totalRounds}</strong>
            <span>已结算轮次</span>
          </div>
        </Paper>
      </SimpleGrid>

      {loading && !matches.length ? (
        <Stack align="center" py="xl">
          <Loader type="bars" />
          <Text size="sm" c="dimmed">
            正在读取对局记录…
          </Text>
        </Stack>
      ) : filteredMatches.length ? (
        <>
          <ScrollArea className={classes.matchTableViewport} offsetScrollbars>
            <Table className={classes.matchTable} verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>房间</Table.Th>
                  <Table.Th>方向</Table.Th>
                  <Table.Th>玩家</Table.Th>
                  <Table.Th>状态</Table.Th>
                  <Table.Th>逐轮结果</Table.Th>
                  <Table.Th>最终结果</Table.Th>
                  <Table.Th>时间</Table.Th>
                  <Table.Th>操作</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filteredMatches.map((match) => (
                  <Table.Tr key={match.matchId}>
                    <Table.Td>
                      <Code className={classes.matchRoomCode}>{match.roomCode}</Code>
                      <Text size="xs" c="dimmed" mt={5}>
                        #{match.matchId} · {match.roomExists !== false ? '房间存在' : '仅保留记录'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge color="violet" leftSection={<Icon path={mdiMapMarkerPath} size={0.55} />}>
                        {match.direction.name}
                      </Badge>
                      <Text size="xs" c="dimmed" mt={5} maw="10rem">
                        {match.direction.description || '无方向说明'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <div className={classes.matchPlayers}>
                        <Player label="房主" player={match.host} winnerUserId={match.winner?.userId ?? null} />
                        <Player label="挑战者" player={match.guest} winnerUserId={match.winner?.userId ?? null} />
                      </div>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={statusMeta[match.status].color}>{statusMeta[match.status].label}</Badge>
                      <Text size="xs" c="dimmed" mt={5}>
                        R{match.currentRound}/{match.totalRounds}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <RoundHistory match={match} />
                    </Table.Td>
                    <Table.Td>
                      <Result match={match} />
                    </Table.Td>
                    <Table.Td>
                      <Times match={match} />
                    </Table.Td>
                    <Table.Td>
                      <Actions match={match} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>

          <Stack className={classes.matchCards} gap="sm">
            {filteredMatches.map((match) => (
              <Paper key={match.matchId} className={classes.matchCard}>
                <Group justify="space-between" align="flex-start">
                  <div>
                    <Code className={classes.matchRoomCode}>{match.roomCode}</Code>
                    <Text size="xs" c="dimmed" mt={5}>
                      #{match.matchId} · {match.direction.name}
                    </Text>
                  </div>
                  <Badge color={statusMeta[match.status].color}>{statusMeta[match.status].label}</Badge>
                </Group>
                <div className={classes.matchPlayers}>
                  <Player label="房主" player={match.host} winnerUserId={match.winner?.userId ?? null} />
                  <Player label="挑战者" player={match.guest} winnerUserId={match.winner?.userId ?? null} />
                </div>
                <Stack mt="sm" gap="xs">
                  <Result match={match} />
                  <RoundHistory match={match} />
                </Stack>
                <Times match={match} />
                <Actions match={match} mobile />
              </Paper>
            ))}
          </Stack>
        </>
      ) : (
        <Stack align="center" py="xl" gap="xs" className={classes.matchEmpty}>
          <Icon path={mdiSwordCross} size={1.8} />
          <Text fw={900}>{matches.length ? '当前筛选下没有对局' : '暂无单方向单挑记录'}</Text>
          <Text size="xs" c="dimmed">
            玩家创建此模式房间后会显示在这里。
          </Text>
        </Stack>
      )}

      <Modal
        opened={!!deleteTarget}
        onClose={() => !deleting && setDeleteTarget(null)}
        title={deleteTarget?.action === 'room' ? '确认删除房间' : '确认删除对局记录'}
        centered
        closeOnClickOutside={!deleting}
      >
        {deleteTarget && (
          <Stack gap="md">
            <SimpleGrid cols={2} spacing="xs" className={classes.matchDeleteSummary}>
              <div>
                <Text size="xs" c="dimmed">
                  房间号
                </Text>
                <Code className={classes.matchRoomCode}>{deleteTarget.match.roomCode}</Code>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  对局记录
                </Text>
                <Text fw={900}>#{deleteTarget.match.matchId}</Text>
              </div>
            </SimpleGrid>
            <Paper className={classes.matchDeleteImpact} data-action={deleteTarget.action}>
              <Text fw={900} size="sm">
                {deleteTarget.action === 'room' ? '关闭实时房间，保留所有历史数据' : '永久删除对局与逐轮结果'}
              </Text>
              <Text size="xs" c="dimmed" mt={4}>
                {deleteTarget.action === 'room'
                  ? '房间删除后玩家无法继续访问；人员、方向、题目和胜负记录仍可供管理员查看。'
                  : '此操作不可撤销。只有房间已经删除时才允许删除记录。'}
              </Text>
            </Paper>
            <Group justify="flex-end">
              <Button variant="default" disabled={deleting} onClick={() => setDeleteTarget(null)}>
                取消
              </Button>
              <Button color="red" loading={deleting} onClick={() => void confirmDelete()}>
                确认删除
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  )
}

export default OneWayMatchRecords
