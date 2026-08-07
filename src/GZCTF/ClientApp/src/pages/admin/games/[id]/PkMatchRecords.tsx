import { AdminPkMatchRecord, AdminPkMatchStatus, arenaApi } from '@Services/ArenaApi'
import {
  Alert,
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
  mdiAlertCircleOutline,
  mdiDeleteForeverOutline,
  mdiHomeRemoveOutline,
  mdiRefresh,
  mdiSwordCross,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import axios from 'axios'
import { FC, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import classes from '@Styles/ArenaAdmin.module.css'

interface PkMatchRecordsProps {
  gameId: number
}

type MatchStatusFilter = 'all' | AdminPkMatchStatus
type DeleteAction = 'room' | 'record'

interface DeleteTarget {
  action: DeleteAction
  match: AdminPkMatchRecord
}

const STATUS_META: Record<AdminPkMatchStatus, { label: string; color: string }> = {
  waiting: { label: '等待挑战者', color: 'gray' },
  countdown: { label: '开局倒计时', color: 'yellow' },
  active: { label: '对局中', color: 'cyan' },
  finished: { label: '已结束', color: 'green' },
  cancelled: { label: '已取消', color: 'orange' },
  reset: { label: '已重置', color: 'red' },
}

const FINISH_REASON_LABELS = {
  timeout: '比赛到时',
  player_left: '玩家离开',
  admin_reset: '管理员终止 / 重置',
}

const STATUS_OPTIONS = [
  { value: 'all', label: '全部状态' },
  ...Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.label })),
]

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

const formatDateTime = (value: string | null) => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateTimeFormatter.format(date)
}

const errorMessage = (error: unknown) => {
  if (!axios.isAxiosError(error)) return error instanceof Error ? error.message : String(error)
  const data = error.response?.data as { detail?: string | { msg?: string }[]; message?: string } | undefined
  if (data?.message) return data.message
  if (typeof data?.detail === 'string') return data.detail
  if (Array.isArray(data?.detail))
    return data.detail
      .map((item) => item.msg)
      .filter(Boolean)
      .join('；')
  return error.message
}

const deleteErrorMessage = (error: unknown, action: DeleteAction) => {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 404)
      return action === 'room' ? '该 PK 房间已经不存在，列表将自动刷新。' : '该对局记录已经不存在，列表将自动刷新。'
    if (error.response?.status === 409)
      return action === 'record'
        ? '该记录仍关联实际房间，请先删除房间，再永久删除对局记录。'
        : '房间状态已经变化，暂时无法删除。请刷新后重试。'
  }
  return errorMessage(error)
}

const MatchStatusBadge: FC<{ status: AdminPkMatchStatus }> = ({ status }) => {
  const meta = STATUS_META[status]
  return (
    <Badge color={meta.color} variant="light" size="sm">
      {meta.label}
    </Badge>
  )
}

const Player: FC<{
  label: string
  player: AdminPkMatchRecord['host'] | null
  winnerUserId: string | null
}> = ({ label, player, winnerUserId }) => {
  if (!player) {
    return (
      <div className={classes.matchPlayer} data-empty>
        <Text size="xs" c="dimmed" fw={800}>
          {label}
        </Text>
        <Text size="sm" c="dimmed">
          等待加入…
        </Text>
      </div>
    )
  }

  const winner = winnerUserId === player.userId
  return (
    <div className={classes.matchPlayer} data-winner={winner || undefined}>
      <Group gap={6} wrap="nowrap">
        <Text size="xs" c="dimmed" fw={800}>
          {label}
        </Text>
        {winner && (
          <Badge size="xs" color="yellow" variant="filled">
            WIN
          </Badge>
        )}
      </Group>
      <Text size="sm" fw={900} truncate title={player.userName}>
        {player.userName}
      </Text>
      <Text size="xs" c="dimmed" className={classes.matchUserId} title={player.userId}>
        {player.userId}
      </Text>
    </div>
  )
}

const Score: FC<{ match: AdminPkMatchRecord }> = ({ match }) => (
  <div className={classes.matchScore}>
    <Text fw={900}>
      {match.host.score.toLocaleString()} <span>:</span> {match.guest?.score.toLocaleString() ?? '—'}
    </Text>
    <Text size="xs" c="dimmed">
      解题 {match.host.solves} : {match.guest?.solves ?? '—'}
    </Text>
  </div>
)

const MatchResult: FC<{ match: AdminPkMatchRecord }> = ({ match }) => {
  const pending = ['waiting', 'countdown', 'active'].includes(match.status)
  const winnerRole =
    match.winner?.userId === match.host.userId
      ? '房主获胜'
      : match.winner?.userId === match.guest?.userId
        ? '挑战者获胜'
        : '胜者'
  const meta = pending
    ? { label: '待结算', color: 'gray' }
    : match.isDraw
      ? { label: '平局', color: 'yellow' }
      : match.winner
        ? { label: winnerRole, color: match.winner.userId === match.host.userId ? 'cyan' : 'violet' }
        : match.status === 'cancelled'
          ? { label: '对局取消', color: 'orange' }
          : match.status === 'reset'
            ? { label: '已重置', color: 'red' }
            : { label: '无有效结果', color: 'gray' }
  return (
    <Stack gap={4} align="flex-start">
      <Badge color={meta.color} variant="dot" size="sm">
        {meta.label}
      </Badge>
      {match.winner && (
        <Text size="xs" fw={800}>
          {match.winner.userName}
        </Text>
      )}
      {match.finishReason && (
        <Text size="xs" c="dimmed">
          {FINISH_REASON_LABELS[match.finishReason]}
        </Text>
      )}
    </Stack>
  )
}

const MatchTimes: FC<{ match: AdminPkMatchRecord }> = ({ match }) => (
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
      <span>截止</span> {formatDateTime(match.endsAt)}
    </Text>
    {match.finishedAt && (
      <Text size="xs">
        <span>完成</span> {formatDateTime(match.finishedAt)}
      </Text>
    )}
  </div>
)

const MatchActions: FC<{
  match: AdminPkMatchRecord
  deleting: DeleteTarget | undefined
  onDelete: (match: AdminPkMatchRecord, action: DeleteAction) => void
}> = ({ match, deleting, onDelete }) => {
  // Missing roomExists is treated conservatively while old responses are being upgraded.
  const roomExists = match.roomExists !== false
  const deleteRoomInProgress = deleting?.match.matchId === match.matchId && deleting.action === 'room'
  const deleteRecordInProgress = deleting?.match.matchId === match.matchId && deleting.action === 'record'
  const mutationInProgress = Boolean(deleting)

  return (
    <Group className={classes.matchActions} gap={6} align="stretch">
      {roomExists && (
        <Button
          size="xs"
          color="orange"
          variant="outline"
          loading={deleteRoomInProgress}
          disabled={mutationInProgress && !deleteRoomInProgress}
          leftSection={<Icon path={mdiHomeRemoveOutline} size={0.72} />}
          onClick={() => onDelete(match, 'room')}
        >
          删除房间
        </Button>
      )}
      <Tooltip
        label={roomExists ? '请先删除实际房间，再永久删除对局记录' : '永久删除该条对局历史'}
        withArrow
        position="top"
      >
        <span className={classes.matchActionTooltipTarget}>
          <Button
            size="xs"
            color="red"
            variant="outline"
            loading={deleteRecordInProgress}
            disabled={roomExists || (mutationInProgress && !deleteRecordInProgress)}
            leftSection={<Icon path={mdiDeleteForeverOutline} size={0.72} />}
            onClick={() => onDelete(match, 'record')}
          >
            删除记录
          </Button>
        </span>
      </Tooltip>
    </Group>
  )
}

const PkMatchRecords: FC<PkMatchRecordsProps> = ({ gameId }) => {
  const [matches, setMatches] = useState<AdminPkMatchRecord[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<MatchStatusFilter>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [updatedAt, setUpdatedAt] = useState<Date>()
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>()
  const [deleting, setDeleting] = useState<DeleteTarget>()
  const mountedRef = useRef(false)
  const requestInFlightRef = useRef(false)
  const deleteInFlightRef = useRef(false)

  const loadMatches = useCallback(
    async (silent = false) => {
      if (requestInFlightRef.current) return
      requestInFlightRef.current = true
      if (!silent) setLoading(true)
      try {
        const response = await arenaApi.admin.listPkMatches(gameId, 100)
        if (!mountedRef.current) return
        setMatches(response)
        setTotal(response.length)
        setUpdatedAt(new Date())
        setError(undefined)
      } catch (requestError) {
        if (mountedRef.current) setError(errorMessage(requestError))
      } finally {
        requestInFlightRef.current = false
        if (mountedRef.current && !silent) setLoading(false)
      }
    },
    [gameId]
  )

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    void loadMatches()
  }, [loadMatches])

  useEffect(() => {
    let stopped = false
    let timer: number | undefined

    const schedule = () => {
      window.clearTimeout(timer)
      if (stopped) return
      const delay = document.visibilityState === 'visible' ? 5000 : 30000
      timer = window.setTimeout(async () => {
        if (document.visibilityState === 'visible') await loadMatches(true)
        schedule()
      }, delay)
    }

    const handleVisibilityChange = () => {
      window.clearTimeout(timer)
      if (document.visibilityState === 'visible') {
        void loadMatches(true).finally(schedule)
      } else {
        schedule()
      }
    }

    schedule()
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      stopped = true
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [loadMatches])

  const filteredMatches = useMemo(
    () => (statusFilter === 'all' ? matches : matches.filter((match) => match.status === statusFilter)),
    [matches, statusFilter]
  )

  const liveMatches = useMemo(
    () => matches.filter((match) => ['waiting', 'countdown', 'active'].includes(match.status)).length,
    [matches]
  )
  const settledMatches = useMemo(
    () => matches.filter((match) => ['finished', 'cancelled', 'reset'].includes(match.status)).length,
    [matches]
  )

  const openDeleteConfirmation = (match: AdminPkMatchRecord, action: DeleteAction) => {
    if (deleteInFlightRef.current) return
    if (action === 'record' && match.roomExists !== false) {
      notifications.show({
        color: 'orange',
        title: '请先删除房间',
        message: `房间 ${match.roomCode} 仍然存在，不能直接删除对局记录。`,
      })
      return
    }
    setDeleteTarget({ match, action })
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deleteInFlightRef.current) return
    const target = deleteTarget
    if (target.action === 'record' && target.match.roomExists !== false) return

    deleteInFlightRef.current = true
    setDeleting(target)
    try {
      if (target.action === 'room') {
        await arenaApi.admin.deletePkMatchRoom(gameId, target.match.matchId)
        if (mountedRef.current) {
          setMatches((current) =>
            current.map((match) => (match.matchId === target.match.matchId ? { ...match, roomExists: false } : match))
          )
        }
        notifications.show({
          color: 'green',
          title: 'PK 房间已删除',
          message: `房间 ${target.match.roomCode} 已关闭，对局人员、比分和结果记录仍然保留。`,
        })
      } else {
        await arenaApi.admin.deletePkMatch(gameId, target.match.matchId)
        if (mountedRef.current) {
          setMatches((current) => current.filter((match) => match.matchId !== target.match.matchId))
          setTotal((current) => Math.max(0, current - 1))
        }
        notifications.show({
          color: 'green',
          title: '对局记录已永久删除',
          message: `房间 ${target.match.roomCode} 的记录 #${target.match.matchId} 已删除。`,
        })
      }
      if (mountedRef.current) setDeleteTarget(undefined)
      await loadMatches()
    } catch (deleteError) {
      const status = axios.isAxiosError(deleteError) ? deleteError.response?.status : undefined
      notifications.show({
        color: status === 404 ? 'orange' : 'red',
        title: status === 404 ? '目标已不存在' : target.action === 'room' ? '删除 PK 房间失败' : '删除对局记录失败',
        message: deleteErrorMessage(deleteError, target.action),
      })
      if (status === 404 || status === 409) {
        if (mountedRef.current) setDeleteTarget(undefined)
        await loadMatches()
      }
    } finally {
      deleteInFlightRef.current = false
      if (mountedRef.current) setDeleting(undefined)
    }
  }

  const deletingPlayers = deleteTarget
    ? `${deleteTarget.match.host.userName} / ${deleteTarget.match.guest?.userName ?? '挑战者未加入'}`
    : ''

  return (
    <Paper className={classes.configBlock}>
      <Group className={classes.matchToolbar} justify="space-between" align="flex-start" mb="md">
        <div>
          <Title order={4}>PK 对局记录</Title>
          <Text size="xs" c="dimmed">
            查看最近 100 个房间的参赛人员、实时比分与最终结果，也可分步删除实际房间和历史记录；页面可见时每 5
            秒自动刷新。
          </Text>
          {updatedAt && (
            <Text size="xs" c="dimmed" mt={3}>
              最后刷新：{dateTimeFormatter.format(updatedAt)}
            </Text>
          )}
        </div>
        <Group className={classes.matchToolbarActions} gap="sm">
          <Select
            aria-label="筛选 PK 对局状态"
            className={classes.matchFilter}
            data={STATUS_OPTIONS}
            value={statusFilter}
            allowDeselect={false}
            onChange={(value) => setStatusFilter((value ?? 'all') as MatchStatusFilter)}
          />
          <Button
            variant="outline"
            loading={loading}
            leftSection={<Icon path={mdiRefresh} size={0.85} />}
            onClick={() => void loadMatches()}
          >
            刷新
          </Button>
        </Group>
      </Group>

      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm" mb="md">
        <Paper className={classes.matchStat}>
          <ThemeIcon color="cyan" variant="light" size="lg">
            <Icon path={mdiSwordCross} size={0.9} />
          </ThemeIcon>
          <div>
            <strong>{liveMatches}</strong>
            <span>开放 / 进行中</span>
          </div>
        </Paper>
        <Paper className={classes.matchStat}>
          <div>
            <strong>{settledMatches}</strong>
            <span>已结算对局</span>
          </div>
        </Paper>
        <Paper className={classes.matchStat}>
          <div>
            <strong>{total.toLocaleString()}</strong>
            <span>已加载记录（最多 100）</span>
          </div>
        </Paper>
      </SimpleGrid>

      {error && (
        <Alert color="red" mb="md" title="PK 对局记录加载失败" icon={<Icon path={mdiAlertCircleOutline} size={1} />}>
          <Text size="sm">{error}</Text>
          <Button mt="sm" size="xs" variant="light" onClick={() => void loadMatches()}>
            重试
          </Button>
        </Alert>
      )}

      {loading && !matches.length ? (
        <Stack align="center" py="xl" gap="sm">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            正在读取 PK 房间…
          </Text>
        </Stack>
      ) : filteredMatches.length ? (
        <>
          <ScrollArea className={classes.matchTableViewport} offsetScrollbars>
            <Table className={classes.matchTable} verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>房间</Table.Th>
                  <Table.Th>房主 / 挑战者</Table.Th>
                  <Table.Th>比分 / 解题</Table.Th>
                  <Table.Th>状态</Table.Th>
                  <Table.Th>胜者 / 结果</Table.Th>
                  <Table.Th>时间</Table.Th>
                  <Table.Th>操作</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filteredMatches.map((match) => (
                  <Table.Tr key={match.matchId}>
                    <Table.Td>
                      <Code className={classes.matchRoomCode}>{match.roomCode}</Code>
                      <Text size="xs" c="dimmed" mt={4}>
                        记录 #{match.matchId}
                      </Text>
                      <Badge size="xs" mt={5} color={match.roomExists !== false ? 'cyan' : 'gray'} variant="light">
                        {match.roomExists !== false ? '房间存在' : '仅保留记录'}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <div className={classes.matchPlayers}>
                        <Player label="房主" player={match.host} winnerUserId={match.winner?.userId ?? null} />
                        <Player label="挑战者" player={match.guest} winnerUserId={match.winner?.userId ?? null} />
                      </div>
                    </Table.Td>
                    <Table.Td>
                      <Score match={match} />
                    </Table.Td>
                    <Table.Td>
                      <MatchStatusBadge status={match.status} />
                    </Table.Td>
                    <Table.Td>
                      <MatchResult match={match} />
                    </Table.Td>
                    <Table.Td>
                      <MatchTimes match={match} />
                    </Table.Td>
                    <Table.Td>
                      <MatchActions match={match} deleting={deleting} onDelete={openDeleteConfirmation} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>

          <Stack className={classes.matchCards} gap="sm">
            {filteredMatches.map((match) => (
              <Paper key={match.matchId} className={classes.matchCard}>
                <Group justify="space-between" align="flex-start" mb="sm">
                  <div>
                    <Text size="xs" c="dimmed" fw={800}>
                      ROOM
                    </Text>
                    <Code className={classes.matchRoomCode}>{match.roomCode}</Code>
                    <Badge size="xs" mt={5} color={match.roomExists !== false ? 'cyan' : 'gray'} variant="light">
                      {match.roomExists !== false ? '房间存在' : '仅保留记录'}
                    </Badge>
                  </div>
                  <MatchStatusBadge status={match.status} />
                </Group>
                <div className={classes.matchPlayers}>
                  <Player label="房主" player={match.host} winnerUserId={match.winner?.userId ?? null} />
                  <Player label="挑战者" player={match.guest} winnerUserId={match.winner?.userId ?? null} />
                </div>
                <Group justify="space-between" align="flex-start" mt="md">
                  <Score match={match} />
                  <MatchResult match={match} />
                </Group>
                <MatchTimes match={match} />
                <div className={classes.matchCardActions}>
                  <MatchActions match={match} deleting={deleting} onDelete={openDeleteConfirmation} />
                </div>
              </Paper>
            ))}
          </Stack>
        </>
      ) : (
        <Stack align="center" py="xl" gap="xs" className={classes.matchEmpty}>
          <Icon path={mdiSwordCross} size={1.8} />
          <Text fw={900}>{matches.length ? '当前筛选下没有对局' : '暂无 PK 对局记录'}</Text>
          <Text size="xs" c="dimmed">
            {matches.length ? '切换状态筛选查看其他记录。' : '玩家创建 Solo 房间后会显示在这里。'}
          </Text>
        </Stack>
      )}

      <Modal
        opened={Boolean(deleteTarget)}
        onClose={() => !deleting && setDeleteTarget(undefined)}
        closeOnClickOutside={!deleting}
        closeOnEscape={!deleting}
        withCloseButton={!deleting}
        centered
        title={deleteTarget?.action === 'room' ? '二次确认：删除 PK 房间' : '二次确认：永久删除对局记录'}
        classNames={{ content: classes.matchDeleteModal }}
      >
        {deleteTarget && (
          <Stack gap="md">
            <Alert color={deleteTarget.action === 'room' ? 'orange' : 'red'} title="请核对删除目标">
              此操作由管理员执行，请确认房间号、参赛人员和影响范围无误。
            </Alert>
            <SimpleGrid cols={2} spacing="xs" className={classes.matchDeleteSummary}>
              <div>
                <Text size="xs" c="dimmed" fw={800}>
                  房间号
                </Text>
                <Code className={classes.matchRoomCode}>{deleteTarget.match.roomCode}</Code>
              </div>
              <div>
                <Text size="xs" c="dimmed" fw={800}>
                  对局记录
                </Text>
                <Text fw={900}>#{deleteTarget.match.matchId}</Text>
              </div>
            </SimpleGrid>
            <div>
              <Text size="xs" c="dimmed" fw={800}>
                参赛人员
              </Text>
              <Text fw={900}>{deletingPlayers}</Text>
            </div>
            <Paper className={classes.matchDeleteImpact} data-action={deleteTarget.action}>
              <Text size="xs" c="dimmed" fw={900}>
                影响范围
              </Text>
              <Text size="sm" fw={800} mt={4}>
                {deleteTarget.action === 'room'
                  ? '删除实际 PK 房间并终止该房间的继续访问；对局人员、比分、结果和时间记录仍会保留。'
                  : '永久删除该条对局历史，包括人员、比分、结果和时间数据；删除后无法恢复。'}
              </Text>
            </Paper>
            <Group justify="flex-end" gap="sm">
              <Button variant="default" disabled={Boolean(deleting)} onClick={() => setDeleteTarget(undefined)}>
                取消
              </Button>
              <Button
                color="red"
                loading={Boolean(deleting)}
                leftSection={
                  <Icon
                    path={deleteTarget.action === 'room' ? mdiHomeRemoveOutline : mdiDeleteForeverOutline}
                    size={0.8}
                  />
                }
                onClick={() => void confirmDelete()}
              >
                {deleteTarget.action === 'room' ? '确认删除房间' : '确认永久删除记录'}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  )
}

export default PkMatchRecords
