import {
  ArenaChallengeConfig,
  ArenaChallengeMode,
  ArenaDifficulty,
  ArenaGameConfig,
  ArenaMode,
  BossAffinity,
  PkScoreMode,
  PkWinRule,
  arenaApi,
  normalizeArenaConfig,
} from '@Services/ArenaApi'
import {
  arenaModeSupportsPk,
  defaultSyncedChallengeStatus,
  findEnabledDraftPkChallengeIndexes,
  hasOpenPkChallenge,
  isReadyOneWayChallenge,
  oneWayDirectionIssues,
  oneWaySourceExposureIssues,
  openChallengesAtIndexes,
} from '@Services/ArenaChallengeStatus'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  Divider,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Paper,
  PasswordInput,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  mdiAlertCircleOutline,
  mdiCheck,
  mdiCloudSyncOutline,
  mdiContentSaveOutline,
  mdiCubeOutline,
  mdiDeleteOutline,
  mdiFire,
  mdiFlagOutline,
  mdiInformationOutline,
  mdiMapMarkerPath,
  mdiOpenInNew,
  mdiPencilOutline,
  mdiPlus,
  mdiRefresh,
  mdiShieldCrownOutline,
  mdiSwordCross,
  mdiTrophyOutline,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import axios from 'axios'
import { FC, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { WithGameEditTab } from '@Components/admin/WithGameEditTab'
import { useAdminGame } from '@Hooks/useGame'
import api, { ChallengeEditDetailModel, ChallengeInfoModel } from '@Api'
import classes from '@Styles/ArenaAdmin.module.css'
import OneWayMatchRecords from './OneWayMatchRecords'
import PkMatchRecords from './PkMatchRecords'

interface ChallengeEditorState {
  index: number | null
  value: ArenaChallengeConfig
}

const MODE_OPTIONS: { value: ArenaMode; label: string }[] = [
  { value: 'classic', label: '传统 CTF' },
  { value: 'solo_pk', label: 'Solo PK' },
  { value: 'one_way_onebyone', label: '单方向单挑' },
  { value: 'boss_raid', label: 'Boss 讨伐' },
  { value: 'hybrid', label: 'PK + Boss' },
]

const DIFFICULTY_OPTIONS: { value: ArenaDifficulty; label: string }[] = [
  { value: 'easy', label: '简单' },
  { value: 'medium', label: '中等' },
  { value: 'hard', label: '困难' },
  { value: 'nightmare', label: '噩梦' },
]

const AFFINITY_OPTIONS: { value: BossAffinity; label: string }[] = [
  { value: 'normal', label: '普通' },
  { value: 'weak', label: '弱点加成' },
  { value: 'resistant', label: '抗性减伤' },
  { value: 'shield', label: '护盾特效' },
]

const SCORE_MODE_OPTIONS: { value: PkScoreMode; label: string }[] = [
  { value: 'fixed', label: '固定得分' },
  { value: 'dynamic', label: '动态分值' },
]

const WIN_RULE_OPTIONS: { value: PkWinRule; label: string }[] = [
  { value: 'highest_score', label: '最高总分' },
  { value: 'first_to_target', label: '率先达标' },
  { value: 'most_solves', label: '解题数优先' },
]

const valueAsNumber = (value: string | number, fallback = 0) => {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : fallback
}

const DEFAULT_PK_CHALLENGE: NonNullable<ArenaChallengeConfig['pk']> = {
  variantGroup: null,
  baseScore: 500,
  timeLimitSeconds: null,
}

const DEFAULT_BOSS_CHALLENGE: NonNullable<ArenaChallengeConfig['boss']> = {
  baseDamage: 1000,
  phase: 1,
  affinity: 'normal',
  isShieldChallenge: false,
  isCoreChallenge: false,
}

const cloneConfig = (config: ArenaGameConfig) => structuredClone(config)

const arenaErrorMessage = (error: unknown) => {
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

const challengeDifficulty = (score: number): ArenaDifficulty => {
  if (score <= 150) return 'easy'
  if (score <= 300) return 'medium'
  if (score <= 500) return 'hard'
  return 'nightmare'
}

const bossDamageForDifficulty = (difficulty: ArenaDifficulty) => {
  if (difficulty === 'easy') return 1000
  if (difficulty === 'medium') return 3000
  if (difficulty === 'hard') return 7000
  return 15000
}

const phaseThresholdsFor = (phaseCount: number) =>
  Array.from({ length: Math.max(0, phaseCount - 1) }, (_, index) =>
    Number(((phaseCount - index - 1) / phaseCount).toFixed(2))
  )

const defaultModes = (mode: ArenaMode): ArenaChallengeMode[] => {
  if (mode === 'solo_pk') return ['pk']
  if (mode === 'one_way_onebyone') return ['one_way']
  if (mode === 'boss_raid') return ['boss']
  if (mode === 'hybrid') return ['pk', 'boss']
  return ['pk']
}

const createChallengeFromSource = (
  source: ChallengeInfoModel,
  detail: ChallengeEditDetailModel | undefined,
  index: number,
  mode: ArenaMode
): ArenaChallengeConfig => {
  const score = source.originalScore ?? source.score ?? 100
  const difficulty = challengeDifficulty(score)
  const importedFlag = detail?.flags.find((item) => Boolean(item.flag?.trim()))?.flag ?? ''
  const sourceEnabled = detail?.isEnabled ?? source.isEnabled ?? false

  return {
    sourceChallengeId: source.id!,
    title: source.title,
    description: detail?.content ?? '',
    target: null,
    flag: importedFlag,
    attachmentUrl: detail?.attachment?.url ?? null,
    status: defaultSyncedChallengeStatus(sourceEnabled, Boolean(importedFlag.trim())),
    category: source.category ?? 'Misc',
    difficulty,
    enabled: sourceEnabled,
    sortOrder: index + 1,
    modes: defaultModes(mode),
    pk: {
      variantGroup: `${String(source.category ?? 'misc').toLowerCase()}-${index + 1}`,
      baseScore: score,
      timeLimitSeconds: 900,
    },
    boss: {
      baseDamage: bossDamageForDifficulty(difficulty),
      phase: difficulty === 'nightmare' ? 3 : difficulty === 'hard' ? 2 : 1,
      affinity: 'normal',
      isShieldChallenge: false,
      isCoreChallenge: false,
    },
    flagCaseSensitive: true,
    hasFlag: false,
    clearFlag: false,
  }
}

const ArenaModeAdmin: FC = () => {
  const { id } = useParams()
  const gameId = Number(id)
  const navigate = useNavigate()
  const { game } = useAdminGame(gameId)

  const [sourceConfig, setSourceConfig] = useState<ArenaGameConfig>()
  const [config, setConfig] = useState<ArenaGameConfig>()
  const [sourceChallenges, setSourceChallenges] = useState<ChallengeInfoModel[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [loadError, setLoadError] = useState<string>()
  const [filter, setFilter] = useState('')
  const [modeFilter, setModeFilter] = useState<'all' | 'pk' | 'one_way' | 'boss'>('all')
  const [editor, setEditor] = useState<ChallengeEditorState>()
  const [draftRepairOpened, setDraftRepairOpened] = useState(false)

  const dirty = useMemo(
    () => !!config && !!sourceConfig && JSON.stringify(config) !== JSON.stringify(sourceConfig),
    [config, sourceConfig]
  )

  const loadData = useCallback(async () => {
    if (!Number.isInteger(gameId) || gameId <= 0) {
      navigate('/admin/games')
      return
    }

    setLoading(true)
    setLoadError(undefined)
    try {
      const [arenaConfig, challengesResponse] = await Promise.all([
        arenaApi.admin.getGame(gameId),
        api.edit.editGetGameChallenges(gameId),
      ])
      const normalized = normalizeArenaConfig(gameId, arenaConfig)
      setSourceConfig(cloneConfig(normalized))
      setConfig(cloneConfig(normalized))
      setSourceChallenges(challengesResponse.data)
    } catch (error) {
      setLoadError(arenaErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [gameId, navigate])

  useEffect(() => {
    void loadData()
  }, [loadData])

  useEffect(() => {
    const warnUnsaved = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warnUnsaved)
    return () => window.removeEventListener('beforeunload', warnUnsaved)
  }, [dirty])

  const setPkConfig = (patch: Partial<ArenaGameConfig['pkConfig']>) => {
    setConfig((current) => (current ? { ...current, pkConfig: { ...current.pkConfig, ...patch } } : current))
  }

  const setBossConfig = (patch: Partial<ArenaGameConfig['bossConfig']>) => {
    setConfig((current) => (current ? { ...current, bossConfig: { ...current.bossConfig, ...patch } } : current))
  }

  const setOneWayConfig = (patch: Partial<ArenaGameConfig['oneWayConfig']>) => {
    setConfig((current) => (current ? { ...current, oneWayConfig: { ...current.oneWayConfig, ...patch } } : current))
  }

  const saveConfig = async () => {
    if (!config) return
    if (
      config.enabled &&
      config.published &&
      arenaModeSupportsPk(config.mode) &&
      !hasOpenPkChallenge(config.challenges)
    ) {
      notifications.show({
        color: 'red',
        title: '无法发布 Solo PK',
        message: '当前没有已启用、已开放且已配置 Flag 的 PK 题目，请先准备至少一道题。',
      })
      return
    }
    if (config.enabled && config.published && config.mode === 'one_way_onebyone') {
      const issues = oneWayDirectionIssues(
        config.challenges,
        config.oneWayConfig.directions,
        config.oneWayConfig.roundCount
      )
      if (issues.length) {
        notifications.show({
          color: 'red',
          title: '无法发布单方向单挑',
          message: issues[0],
        })
        return
      }
      const exposureIssues = oneWaySourceExposureIssues(
        config.challenges,
        config.oneWayConfig.directions,
        sourceChallenges
      )
      if (exposureIssues.length) {
        notifications.show({
          color: 'red',
          title: '无法发布：原生题库会提前泄题',
          message: `${exposureIssues[0]}。请先在原生 GZCTF「题目」页将源题禁用/隐藏，再重新加载本页。`,
        })
        return
      }
    }
    setSaving(true)
    try {
      const saved = normalizeArenaConfig(gameId, await arenaApi.admin.updateGame(gameId, config))
      setSourceConfig(cloneConfig(saved))
      setConfig(cloneConfig(saved))
      notifications.show({
        color: 'green',
        title: '竞技场已保存',
        message: `配置版本 r${saved.revision}，${saved.published ? '玩家端已发布' : '当前仍为草稿'}。`,
        icon: <Icon path={mdiCheck} size={1} />,
      })
    } catch (error) {
      const conflict = axios.isAxiosError(error) && error.response?.status === 409
      notifications.show({
        color: 'red',
        title: conflict ? '配置版本冲突' : '保存失败',
        message: conflict ? '其他管理员已更新配置，请重新加载后再编辑。' : arenaErrorMessage(error),
      })
    } finally {
      setSaving(false)
    }
  }

  const syncChallenges = async () => {
    if (!config) return
    const existingIds = new Set(config.challenges.map((challenge) => challenge.sourceChallengeId))
    const missing = sourceChallenges.filter((challenge) => challenge.id && !existingIds.has(challenge.id))

    if (!missing.length) {
      notifications.show({ color: 'blue', message: 'GZCTF 题库已全部同步。' })
      return
    }

    setSyncing(true)
    try {
      const details = await Promise.all(
        missing.map(async (challenge) => {
          try {
            const response = await api.edit.editGetGameChallenge(gameId, challenge.id!)
            return response.data
          } catch {
            return undefined
          }
        })
      )
      const offset = config.challenges.length
      const imported = missing.map((challenge, index) =>
        createChallengeFromSource(challenge, details[index], offset + index, config.mode)
      )
      setConfig({ ...config, challenges: [...config.challenges, ...imported] })
      notifications.show({
        color: 'green',
        title: '题库同步完成',
        message: `已导入 ${imported.length} 道题的题面、Flag 和附件信息，请检查后保存。`,
      })
    } finally {
      setSyncing(false)
    }
  }

  const openNewChallenge = () => {
    if (!config) return
    const available = sourceChallenges.find(
      (source) => source.id && !config.challenges.some((challenge) => challenge.sourceChallengeId === source.id)
    )
    if (!available) {
      notifications.show({
        color: 'orange',
        title: '没有可映射的题目',
        message: '请先在「题目」标签新建 GZCTF 题目，或删除已有映射。',
      })
      return
    }
    setEditor({
      index: null,
      value: createChallengeFromSource(available, undefined, config.challenges.length, config.mode),
    })
  }

  const saveEditor = () => {
    if (!config || !editor) return
    if (!editor.value.title.trim() || !editor.value.modes.length) {
      notifications.show({ color: 'red', message: '题目名称不能为空，且至少选择一个参与模式。' })
      return
    }
    const duplicate = config.challenges.some(
      (challenge, index) => index !== editor.index && challenge.sourceChallengeId === editor.value.sourceChallengeId
    )
    if (duplicate) {
      notifications.show({ color: 'red', message: '该 GZCTF 题目已存在竞技场映射。' })
      return
    }
    if (
      ['active', 'open'].includes(editor.value.status) &&
      ((!editor.value.hasFlag && !editor.value.flag) || (!!editor.value.clearFlag && !editor.value.flag))
    ) {
      notifications.show({ color: 'red', message: '开放中的题目必须设置 Flag。' })
      return
    }

    const challenges = [...config.challenges]
    if (editor.index === null) challenges.push(editor.value)
    else challenges[editor.index] = editor.value
    setConfig({ ...config, challenges })
    setEditor(undefined)
  }

  const removeChallenge = (index: number) => {
    if (!config) return
    setConfig({ ...config, challenges: config.challenges.filter((_, challengeIndex) => challengeIndex !== index) })
  }

  const filteredChallenges = useMemo(() => {
    if (!config) return []
    const query = filter.trim().toLowerCase()
    return config.challenges
      .map((challenge, index) => ({ challenge, index }))
      .filter(({ challenge }) => {
        const matchesText =
          !query ||
          challenge.title.toLowerCase().includes(query) ||
          challenge.category.toLowerCase().includes(query) ||
          String(challenge.sourceChallengeId).includes(query)
        const matchesMode = modeFilter === 'all' || challenge.modes.includes(modeFilter)
        return matchesText && matchesMode
      })
      .sort((a, b) => a.challenge.sortOrder - b.challenge.sortOrder)
  }, [config, filter, modeFilter])

  const enabledDraftPkIndexes = useMemo(
    () => (config ? findEnabledDraftPkChallengeIndexes(config.challenges, sourceChallenges) : []),
    [config, sourceChallenges]
  )

  const repairEnabledDraftPkChallenges = () => {
    if (!config || !enabledDraftPkIndexes.length) return
    setConfig({
      ...config,
      challenges: openChallengesAtIndexes(config.challenges, enabledDraftPkIndexes),
    })
    setDraftRepairOpened(false)
    notifications.show({
      color: 'green',
      title: 'PK 题目已设为开放',
      message: `已更新 ${enabledDraftPkIndexes.length} 道题；点击「保存竞技场」后生效。`,
    })
  }

  const oneWayChallengeOptions = useMemo(
    () =>
      (config?.challenges ?? [])
        .filter(isReadyOneWayChallenge)
        .sort((a, b) => a.sortOrder - b.sortOrder)
        .map((challenge) => ({
          value: String(challenge.id),
          label: `#${challenge.id} · ${challenge.title} (${challenge.category})`,
        })),
    [config]
  )

  const oneWayExposureIssues = useMemo(
    () =>
      config ? oneWaySourceExposureIssues(config.challenges, config.oneWayConfig.directions, sourceChallenges) : [],
    [config, sourceChallenges]
  )

  const updateOneWayDirection = (
    directionIndex: number,
    patch: Partial<ArenaGameConfig['oneWayConfig']['directions'][number]>
  ) => {
    if (!config) return
    const directions = [...config.oneWayConfig.directions]
    directions[directionIndex] = { ...directions[directionIndex], ...patch }
    setOneWayConfig({ directions })
  }

  const addOneWayDirection = () => {
    if (!config) return
    const sequence = config.oneWayConfig.directions.length + 1
    setOneWayConfig({
      directions: [
        ...config.oneWayConfig.directions,
        {
          id: `direction-${Date.now().toString(36)}-${sequence}`,
          name: `挑战方向 ${sequence}`,
          description: '',
          challengeIds: [],
        },
      ],
    })
  }

  const removeOneWayDirection = (directionIndex: number) => {
    if (!config) return
    setOneWayConfig({
      directions: config.oneWayConfig.directions.filter((_, index) => index !== directionIndex),
    })
  }

  const sourceOptions = sourceChallenges
    .filter((challenge): challenge is ChallengeInfoModel & { id: number } => typeof challenge.id === 'number')
    .map((challenge) => ({ value: String(challenge.id), label: `#${challenge.id} · ${challenge.title}` }))

  const updateEditor = (patch: Partial<ArenaChallengeConfig>) => {
    setEditor((current) => (current ? { ...current, value: { ...current.value, ...patch } } : current))
  }

  const updateEditorModes = (modes: ArenaChallengeMode[]) => {
    if (!editor) return
    updateEditor({
      modes,
      pk: modes.includes('pk') ? (editor.value.pk ?? { ...DEFAULT_PK_CHALLENGE }) : editor.value.pk,
      boss: modes.includes('boss') ? (editor.value.boss ?? { ...DEFAULT_BOSS_CHALLENGE }) : editor.value.boss,
    })
  }

  const emptyConfig = !loading && !!config && config.exists === false

  return (
    <WithGameEditTab
      isLoading={loading || !game}
      contentPos="right"
      head={
        <>
          {dirty && <Badge color="orange">有未保存更改</Badge>}
          <Button
            variant="subtle"
            color="gray"
            disabled={loading || saving}
            leftSection={<Icon path={mdiRefresh} size={0.85} />}
            onClick={() => void loadData()}
          >
            重新加载
          </Button>
          <Button
            component={Link}
            to="/arena"
            target="_blank"
            variant="outline"
            leftSection={<Icon path={mdiOpenInNew} size={0.85} />}
          >
            预览玩家端
          </Button>
          <Button
            disabled={!config || !dirty || saving}
            loading={saving}
            leftSection={<Icon path={mdiContentSaveOutline} size={0.9} />}
            onClick={() => void saveConfig()}
          >
            保存竞技场
          </Button>
        </>
      }
    >
      <Stack gap="lg" className={classes.page}>
        {loadError && (
          <Alert color="red" title="方块竞技场服务连接失败" icon={<Icon path={mdiAlertCircleOutline} size={1} />}>
            <Text size="sm">
              当前 GZCTF 管理员会话已携带，但竞技场 API 未返回配置：<Code>{loadError}</Code>
            </Text>
            <Button mt="sm" size="xs" variant="light" onClick={() => void loadData()}>
              重试
            </Button>
          </Alert>
        )}

        {emptyConfig && (
          <Alert color="blue" title="正在初始化默认配置" icon={<Icon path={mdiInformationOutline} size={1} />}>
            该赛事还没有竞技场配置，保存后即可创建。
          </Alert>
        )}

        {config && (
          <>
            <section className={classes.hero}>
              <div>
                <Text className={classes.kicker}>VOXEL ARENA CONTROL</Text>
                <Title order={2}>{game?.title ?? `Game #${gameId}`}</Title>
                <Text size="sm" c="dimmed" mt={4}>
                  每个 GZCTF 赛事拥有独立的 PK 规则、Boss 世界状态与题目映射。
                </Text>
              </div>
              <Group gap="sm">
                <Badge color={config.exists ? 'green' : 'gray'} variant="filled">
                  {config.exists ? `REVISION ${config.revision}` : 'NEW CONFIG'}
                </Badge>
                <Badge color={config.published ? 'lime' : 'orange'} variant="filled">
                  {config.published ? '已发布' : '草稿'}
                </Badge>
              </Group>
            </section>

            <SimpleGrid cols={4} spacing="md">
              <Paper className={classes.statBlock}>
                <ThemeIcon color="cyan" variant="light">
                  <Icon path={mdiSwordCross} size={1} />
                </ThemeIcon>
                <div>
                  <strong>{config.challenges.filter((challenge) => challenge.modes.includes('pk')).length}</strong>
                  <span>PK 题目</span>
                </div>
              </Paper>
              <Paper className={classes.statBlock}>
                <ThemeIcon color="red" variant="light">
                  <Icon path={mdiFire} size={1} />
                </ThemeIcon>
                <div>
                  <strong>{config.challenges.filter((challenge) => challenge.modes.includes('boss')).length}</strong>
                  <span>Boss 题目</span>
                </div>
              </Paper>
              <Paper className={classes.statBlock}>
                <ThemeIcon color="green" variant="light">
                  <Icon path={mdiFlagOutline} size={1} />
                </ThemeIcon>
                <div>
                  <strong>
                    {config.challenges.filter((challenge) => ['active', 'open'].includes(challenge.status)).length}
                  </strong>
                  <span>就绪题目</span>
                </div>
              </Paper>
              <Paper className={classes.statBlock}>
                <ThemeIcon color="orange" variant="light">
                  <Icon path={mdiShieldCrownOutline} size={1} />
                </ThemeIcon>
                <div>
                  <strong>{config.bossConfig.maxHp.toLocaleString()}</strong>
                  <span>Boss HP</span>
                </div>
              </Paper>
            </SimpleGrid>

            <Paper className={classes.configBlock}>
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <div>
                  <Title order={4}>赛事模式</Title>
                  <Text size="xs" c="dimmed">
                    关闭「启用」会立即阻止新玩家进入；「发布」决定玩家端是否可见。
                  </Text>
                </div>
                <Group gap="xl">
                  <Switch
                    label="启用竞技场"
                    checked={config.enabled}
                    onChange={(event) => setConfig({ ...config, enabled: event.currentTarget.checked })}
                  />
                  <Switch
                    color="lime"
                    label="发布到玩家端"
                    checked={config.published}
                    onChange={(event) => setConfig({ ...config, published: event.currentTarget.checked })}
                  />
                </Group>
              </Group>
              <SegmentedControl
                mt="lg"
                fullWidth
                value={config.mode}
                data={MODE_OPTIONS}
                onChange={(value) => setConfig({ ...config, mode: value as ArenaMode })}
              />
            </Paper>

            <Tabs defaultValue="pk" variant="outline" className={classes.tabs} keepMounted={false}>
              <Tabs.List>
                <Tabs.Tab value="pk" leftSection={<Icon path={mdiSwordCross} size={0.8} />}>
                  Solo PK 规则
                </Tabs.Tab>
                <Tabs.Tab value="pk-matches" leftSection={<Icon path={mdiFlagOutline} size={0.8} />}>
                  PK 对局记录
                </Tabs.Tab>
                <Tabs.Tab value="one-way" leftSection={<Icon path={mdiMapMarkerPath} size={0.8} />}>
                  单方向单挑规则
                </Tabs.Tab>
                <Tabs.Tab value="one-way-matches" leftSection={<Icon path={mdiTrophyOutline} size={0.8} />}>
                  单挑对局记录
                </Tabs.Tab>
                <Tabs.Tab value="boss" leftSection={<Icon path={mdiShieldCrownOutline} size={0.8} />}>
                  Boss 属性
                </Tabs.Tab>
                <Tabs.Tab value="challenges" leftSection={<Icon path={mdiCubeOutline} size={0.8} />}>
                  题目与内容 ({config.challenges.length})
                </Tabs.Tab>
              </Tabs.List>

              <Tabs.Panel value="pk" pt="md">
                <Paper className={classes.configBlock}>
                  <Group justify="space-between" mb="lg">
                    <div>
                      <Title order={4}>1v1 竞技规则</Title>
                      <Text size="xs" c="dimmed">
                        默认每队 1 人、镜像题池、首血与连胜加成，体现 Solo 对决的公平性。
                      </Text>
                    </div>
                    <Badge color="cyan">SOLO COMPETITIVE</Badge>
                  </Group>
                  <SimpleGrid cols={3} spacing="lg">
                    <NumberInput
                      label="每队人数"
                      description="Solo 赛请保持为 1"
                      min={1}
                      max={4}
                      value={config.pkConfig.teamSize}
                      onChange={(value) => setPkConfig({ teamSize: valueAsNumber(value, 1) })}
                    />
                    <NumberInput
                      label="对局时长（分钟）"
                      min={1}
                      max={180}
                      value={Math.round(config.pkConfig.matchSeconds / 60)}
                      onChange={(value) => setPkConfig({ matchSeconds: valueAsNumber(value, 15) * 60 })}
                    />
                    <NumberInput
                      label="每局题目数"
                      min={1}
                      max={30}
                      value={config.pkConfig.questionCount}
                      onChange={(value) => setPkConfig({ questionCount: valueAsNumber(value, 3) })}
                    />
                    <Select
                      label="得分模型"
                      data={SCORE_MODE_OPTIONS}
                      value={config.pkConfig.scoreMode}
                      allowDeselect={false}
                      onChange={(value) => value && setPkConfig({ scoreMode: value as PkScoreMode })}
                    />
                    <Select
                      label="胜负判定"
                      data={WIN_RULE_OPTIONS}
                      value={config.pkConfig.winRule}
                      allowDeselect={false}
                      onChange={(value) => {
                        if (!value) return
                        const winRule = value as PkWinRule
                        setPkConfig({
                          winRule,
                          targetScore:
                            winRule === 'first_to_target'
                              ? (config.pkConfig.targetScore ?? 1000)
                              : config.pkConfig.targetScore,
                        })
                      }}
                    />
                    <NumberInput
                      label="错误提交扣分"
                      min={0}
                      max={100000}
                      value={config.pkConfig.wrongPenalty}
                      onChange={(value) => setPkConfig({ wrongPenalty: valueAsNumber(value) })}
                    />
                    <NumberInput
                      label="错误后冷却（秒）"
                      min={0}
                      max={600}
                      value={config.pkConfig.cooldownSeconds}
                      onChange={(value) => setPkConfig({ cooldownSeconds: valueAsNumber(value) })}
                    />
                    <NumberInput
                      label="目标分"
                      description="仅「率先达标」规则生效"
                      min={1}
                      disabled={config.pkConfig.winRule !== 'first_to_target'}
                      value={config.pkConfig.targetScore ?? ''}
                      onChange={(value) =>
                        setPkConfig({ targetScore: value === '' ? null : valueAsNumber(value, 1000) })
                      }
                    />
                    <NumberInput
                      label="首血加成"
                      min={0}
                      value={config.pkConfig.firstBloodBonus}
                      onChange={(value) => setPkConfig({ firstBloodBonus: valueAsNumber(value) })}
                    />
                    <NumberInput
                      label="连胜加成"
                      min={0}
                      value={config.pkConfig.streakBonus}
                      onChange={(value) => setPkConfig({ streakBonus: valueAsNumber(value) })}
                    />
                    <Switch
                      className={classes.fieldSwitch}
                      label="允许平局"
                      description="关闭时可由用时、错误数决胜"
                      checked={config.pkConfig.allowDraw}
                      onChange={(event) => setPkConfig({ allowDraw: event.currentTarget.checked })}
                    />
                    <Switch
                      className={classes.fieldSwitch}
                      label="双方使用相同题目"
                      description="开启后使用镜像题池，确保对局公平"
                      checked={config.pkConfig.sameQuestionsForBoth}
                      onChange={(event) => setPkConfig({ sameQuestionsForBoth: event.currentTarget.checked })}
                    />
                  </SimpleGrid>
                </Paper>
              </Tabs.Panel>

              <Tabs.Panel value="pk-matches" pt="md">
                <PkMatchRecords gameId={gameId} />
              </Tabs.Panel>

              <Tabs.Panel value="one-way" pt="md">
                <Stack gap="md">
                  <Paper className={classes.configBlock}>
                    <Group justify="space-between" mb="lg">
                      <div>
                        <Title order={4}>单方向逐题决斗规则</Title>
                        <Text size="xs" c="dimmed">
                          玩家创建房间前选择方向；每局从该方向题池无放回随机抽题，每轮只开放一题。
                        </Text>
                      </div>
                      <Badge color="violet">ONE-WAY ONE-BY-ONE</Badge>
                    </Group>
                    <SimpleGrid cols={4} spacing="lg">
                      <NumberInput
                        label="双方就位倒计时（秒）"
                        min={1}
                        max={60}
                        value={config.oneWayConfig.countdownSeconds}
                        onChange={(value) => setOneWayConfig({ countdownSeconds: valueAsNumber(value, 5) })}
                      />
                      <NumberInput
                        label="挑战轮次"
                        description="每轮恰好一题"
                        min={1}
                        max={30}
                        value={config.oneWayConfig.roundCount}
                        onChange={(value) => setOneWayConfig({ roundCount: valueAsNumber(value, 3) })}
                      />
                      <NumberInput
                        label="每轮时限（分钟）"
                        min={1}
                        max={180}
                        value={Math.round(config.oneWayConfig.roundSeconds / 60)}
                        onChange={(value) => setOneWayConfig({ roundSeconds: valueAsNumber(value, 15) * 60 })}
                      />
                      <NumberInput
                        label="轮间结果展示（秒）"
                        min={1}
                        max={120}
                        value={config.oneWayConfig.intervalSeconds}
                        onChange={(value) => setOneWayConfig({ intervalSeconds: valueAsNumber(value, 5) })}
                      />
                    </SimpleGrid>
                  </Paper>

                  <Paper className={classes.configBlock}>
                    <Group justify="space-between" mb="md" align="flex-start">
                      <div>
                        <Title order={4}>挑战方向与专属题池</Title>
                        <Text size="xs" c="dimmed">
                          这里只列出已保存 ID、已启用、已开放、已配置 Flag
                          且勾选「单方向单挑」的题目。每个方向题数必须不少于轮次。
                        </Text>
                      </div>
                      <Button leftSection={<Icon path={mdiPlus} size={0.85} />} onClick={addOneWayDirection}>
                        新增方向
                      </Button>
                    </Group>

                    <Alert
                      color={oneWayExposureIssues.length ? 'red' : 'yellow'}
                      title="公平性隔离：必须先隐藏原生 GZCTF 源题"
                      icon={<Icon path={mdiAlertCircleOutline} size={1} />}
                      mb="md"
                    >
                      <Text size="sm">
                        方向题若仍在原生 GZCTF「题目」中启用，玩家可通过原生题库 API
                        提前看到未来轮题面。请先在原生赛事中禁用/隐藏源题，再在竞技场副本中单独启用并开放；无源题映射的独立题不受影响。
                      </Text>
                      {oneWayExposureIssues.length > 0 && (
                        <Code block mt="sm">
                          {oneWayExposureIssues.join('\n')}
                        </Code>
                      )}
                    </Alert>

                    {!oneWayChallengeOptions.length && (
                      <Alert color="orange" icon={<Icon path={mdiAlertCircleOutline} size={1} />} mb="md">
                        暂无可选题目。请先在「题目与内容」中勾选「单方向单挑」，确认题目已开放且有
                        Flag，然后保存一次以取得竞技场题目 ID。
                      </Alert>
                    )}

                    <Stack gap="md">
                      {config.oneWayConfig.directions.map((direction, index) => {
                        const readyCount = new Set(direction.challengeIds).size
                        const enough = readyCount >= config.oneWayConfig.roundCount
                        return (
                          <Paper key={direction.id} className={classes.modeEditor} data-tone="pk">
                            <Group justify="space-between" mb="md">
                              <Group gap="xs">
                                <ThemeIcon color="violet" variant="light">
                                  <Icon path={mdiMapMarkerPath} size={0.9} />
                                </ThemeIcon>
                                <div>
                                  <Text fw={900}>方向 {index + 1}</Text>
                                  <Text size="xs" c={enough ? 'green.4' : 'orange.4'}>
                                    {readyCount} / {config.oneWayConfig.roundCount} 道 ·{' '}
                                    {enough ? '题池就绪' : '题目不足'}
                                  </Text>
                                </div>
                              </Group>
                              <ActionIcon
                                color="red"
                                variant="subtle"
                                aria-label={`删除方向 ${direction.name}`}
                                onClick={() => removeOneWayDirection(index)}
                              >
                                <Icon path={mdiDeleteOutline} size={0.85} />
                              </ActionIcon>
                            </Group>
                            <SimpleGrid cols={2} spacing="md" mb="md">
                              <TextInput
                                label="方向名称"
                                required
                                placeholder="例如：Web / Crypto / Pwn"
                                value={direction.name}
                                onChange={(event) => updateOneWayDirection(index, { name: event.currentTarget.value })}
                              />
                              <TextInput
                                label="方向说明"
                                placeholder="玩家在创建房间前看到的简介"
                                value={direction.description ?? ''}
                                onChange={(event) =>
                                  updateOneWayDirection(index, { description: event.currentTarget.value })
                                }
                              />
                            </SimpleGrid>
                            <MultiSelect
                              label="本方向题池"
                              description={`无放回随机抽取 ${config.oneWayConfig.roundCount} 道；未来轮题目不会提前下发到玩家端。`}
                              data={oneWayChallengeOptions}
                              searchable
                              clearable
                              hidePickedOptions
                              value={direction.challengeIds.map(String)}
                              onChange={(values) =>
                                updateOneWayDirection(index, {
                                  challengeIds: values.map(Number).filter(Number.isInteger),
                                })
                              }
                              error={enough ? undefined : `至少选择 ${config.oneWayConfig.roundCount} 道不重复题目`}
                            />
                          </Paper>
                        )
                      })}

                      {!config.oneWayConfig.directions.length && (
                        <Stack align="center" py="xl" gap="xs">
                          <Icon path={mdiMapMarkerPath} size={1.8} />
                          <Text fw={800}>尚未配置挑战方向</Text>
                          <Text size="xs" c="dimmed">
                            至少新增一个方向并为其选择足够题目，才能发布单方向单挑模式。
                          </Text>
                        </Stack>
                      )}
                    </Stack>
                  </Paper>
                </Stack>
              </Tabs.Panel>

              <Tabs.Panel value="one-way-matches" pt="md">
                <OneWayMatchRecords gameId={gameId} />
              </Tabs.Panel>

              <Tabs.Panel value="boss" pt="md">
                <Paper className={classes.configBlock}>
                  <Group justify="space-between" mb="lg">
                    <div>
                      <Title order={4}>世界 Boss 属性</Title>
                      <Text size="xs" c="dimmed">
                        题目的基础伤害、阶段和属性会在 Flag 校验成功后进入伤害结算。
                      </Text>
                    </div>
                    <Badge color="red">RAID WORLD</Badge>
                  </Group>
                  <SimpleGrid cols={3} spacing="lg">
                    <TextInput
                      label="Boss 名称"
                      value={config.bossConfig.name}
                      onChange={(event) => setBossConfig({ name: event.currentTarget.value })}
                    />
                    <NumberInput
                      label="总血量 HP"
                      min={1}
                      value={config.bossConfig.maxHp}
                      thousandSeparator=","
                      onChange={(value) => setBossConfig({ maxHp: valueAsNumber(value, 1) })}
                    />
                    <NumberInput
                      label="难度阶段数"
                      min={1}
                      max={10}
                      value={config.bossConfig.phaseCount}
                      onChange={(value) => {
                        const phaseCount = valueAsNumber(value, 1)
                        setBossConfig({ phaseCount, phaseThresholds: phaseThresholdsFor(phaseCount) })
                      }}
                    />
                    <NumberInput
                      label="狂暴时间（分钟）"
                      min={1}
                      value={Math.round(config.bossConfig.enrageSeconds / 60)}
                      onChange={(value) => setBossConfig({ enrageSeconds: valueAsNumber(value, 120) * 60 })}
                    />
                    <NumberInput
                      label="狂暴后伤害系数"
                      description="0.75 表示狂暴后玩家伤害为 75%"
                      min={0.05}
                      max={5}
                      step={0.05}
                      decimalScale={2}
                      value={config.bossConfig.enrageDamageMultiplier}
                      onChange={(value) => setBossConfig({ enrageDamageMultiplier: valueAsNumber(value, 0.75) })}
                    />
                    <NumberInput
                      label="队伍最低通关贡献"
                      min={0}
                      value={config.bossConfig.minTeamContribution}
                      thousandSeparator=","
                      onChange={(value) => setBossConfig({ minTeamContribution: valueAsNumber(value) })}
                    />
                    <Switch
                      className={classes.fieldSwitch}
                      label="启用阶段护盾"
                      description="需要破盾题才能解锁后续阶段"
                      checked={config.bossConfig.shieldEnabled}
                      onChange={(event) => setBossConfig({ shieldEnabled: event.currentTarget.checked })}
                    />
                    <TagsInput
                      label="阶段切换血量（%）"
                      description={`必须为 ${Math.max(0, config.bossConfig.phaseCount - 1)} 个降序数值`}
                      value={config.bossConfig.phaseThresholds.map((threshold) => String(Math.round(threshold * 100)))}
                      onChange={(values) =>
                        setBossConfig({
                          phaseThresholds: values
                            .map((value) => Number(value.replace('%', '')))
                            .filter(Number.isFinite)
                            .map((value) => (value >= 1 ? value / 100 : value))
                            .sort((a, b) => b - a),
                        })
                      }
                    />
                  </SimpleGrid>
                </Paper>
              </Tabs.Panel>

              <Tabs.Panel value="challenges" pt="md">
                <Paper className={classes.configBlock}>
                  <Group justify="space-between" mb="md" wrap="nowrap">
                    <div>
                      <Title order={4}>竞技场题目映射</Title>
                      <Text size="xs" c="dimmed">
                        题目来源于当前 GZCTF 赛事；竞技场另外保存题面、目标、Flag、PK 分值与 Boss 伤害。
                      </Text>
                    </div>
                    <Group gap="sm" wrap="nowrap">
                      <Button
                        variant="outline"
                        loading={syncing}
                        leftSection={<Icon path={mdiCloudSyncOutline} size={0.85} />}
                        onClick={() => void syncChallenges()}
                      >
                        同步 GZCTF 题库
                      </Button>
                      <Button leftSection={<Icon path={mdiPlus} size={0.85} />} onClick={openNewChallenge}>
                        新增映射
                      </Button>
                    </Group>
                  </Group>

                  {enabledDraftPkIndexes.length > 0 && (
                    <Alert
                      mb="md"
                      color="orange"
                      title="检测到旧版同步的 PK 草稿题"
                      icon={<Icon path={mdiAlertCircleOutline} size={1} />}
                    >
                      <Group justify="space-between" align="center" wrap="nowrap">
                        <Text size="sm">
                          当前有 {enabledDraftPkIndexes.length} 道已在 GZCTF 启用、但竞技场状态仍为「草稿」的 PK
                          题。系统不会自动修改已有草稿，你可以确认后一次性设为开放。
                        </Text>
                        <Button size="xs" color="orange" variant="filled" onClick={() => setDraftRepairOpened(true)}>
                          一键开放
                        </Button>
                      </Group>
                    </Alert>
                  )}

                  <Group gap="sm" mb="md" wrap="nowrap">
                    <TextInput
                      className={classes.search}
                      placeholder="搜索题名、分类或源题 ID"
                      value={filter}
                      onChange={(event) => setFilter(event.currentTarget.value)}
                    />
                    <SegmentedControl
                      value={modeFilter}
                      data={[
                        { value: 'all', label: '全部' },
                        { value: 'pk', label: 'PK' },
                        { value: 'one_way', label: '单挑' },
                        { value: 'boss', label: 'Boss' },
                      ]}
                      onChange={(value) => setModeFilter(value as 'all' | 'pk' | 'one_way' | 'boss')}
                    />
                  </Group>

                  <ScrollArea offsetScrollbars h="min(48vh, 560px)">
                    <Table className={classes.challengeTable} verticalSpacing="sm" highlightOnHover>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>#</Table.Th>
                          <Table.Th>题目</Table.Th>
                          <Table.Th>状态</Table.Th>
                          <Table.Th>模式</Table.Th>
                          <Table.Th>PK 分值</Table.Th>
                          <Table.Th>Boss 伤害</Table.Th>
                          <Table.Th>启用</Table.Th>
                          <Table.Th />
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {filteredChallenges.map(({ challenge, index }) => (
                          <Table.Tr key={challenge.id ?? `source-${challenge.sourceChallengeId}`}>
                            <Table.Td>
                              <Code>{challenge.sortOrder}</Code>
                            </Table.Td>
                            <Table.Td>
                              <Text fw={800} size="sm">
                                {challenge.title}
                              </Text>
                              <Text size="xs" c="dimmed">
                                GZCTF #{challenge.sourceChallengeId} · {challenge.category} · {challenge.difficulty}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <Badge
                                size="sm"
                                color={
                                  ['active', 'open'].includes(challenge.status)
                                    ? 'green'
                                    : challenge.status === 'locked'
                                      ? 'gray'
                                      : 'orange'
                                }
                              >
                                {['active', 'open'].includes(challenge.status)
                                  ? '已开放'
                                  : challenge.status === 'locked'
                                    ? '锁定'
                                    : '草稿'}
                              </Badge>
                            </Table.Td>
                            <Table.Td>
                              <Group gap={4} wrap="nowrap">
                                {challenge.modes.includes('pk') && <Badge color="cyan">PK</Badge>}
                                {challenge.modes.includes('one_way') && <Badge color="violet">单挑</Badge>}
                                {challenge.modes.includes('boss') && <Badge color="red">BOSS</Badge>}
                              </Group>
                            </Table.Td>
                            <Table.Td>
                              {challenge.modes.includes('pk') ? (challenge.pk?.baseScore ?? '—') : '—'}
                            </Table.Td>
                            <Table.Td>
                              {challenge.modes.includes('boss')
                                ? (challenge.boss?.baseDamage.toLocaleString() ?? '—')
                                : '—'}
                            </Table.Td>
                            <Table.Td>
                              <Switch
                                size="sm"
                                checked={challenge.enabled}
                                onChange={(event) => {
                                  const challenges = [...config.challenges]
                                  challenges[index] = { ...challenge, enabled: event.currentTarget.checked }
                                  setConfig({ ...config, challenges })
                                }}
                              />
                            </Table.Td>
                            <Table.Td>
                              <Group gap={4} wrap="nowrap" justify="right">
                                <Tooltip label="编辑题目与结算参数">
                                  <ActionIcon
                                    variant="subtle"
                                    onClick={() => setEditor({ index, value: structuredClone(challenge) })}
                                  >
                                    <Icon path={mdiPencilOutline} size={0.85} />
                                  </ActionIcon>
                                </Tooltip>
                                <Tooltip label="从竞技场移除">
                                  <ActionIcon color="red" variant="subtle" onClick={() => removeChallenge(index)}>
                                    <Icon path={mdiDeleteOutline} size={0.85} />
                                  </ActionIcon>
                                </Tooltip>
                              </Group>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                        {!filteredChallenges.length && (
                          <Table.Tr>
                            <Table.Td colSpan={8}>
                              <Stack align="center" py="xl" gap="xs">
                                <Icon path={mdiCubeOutline} size={1.8} />
                                <Text fw={800}>还没有竞技场题目</Text>
                                <Text size="xs" c="dimmed">
                                  点击「同步 GZCTF 题库」快速创建映射。
                                </Text>
                              </Stack>
                            </Table.Td>
                          </Table.Tr>
                        )}
                      </Table.Tbody>
                    </Table>
                  </ScrollArea>
                </Paper>
              </Tabs.Panel>
            </Tabs>
          </>
        )}
      </Stack>

      <Modal
        opened={draftRepairOpened}
        onClose={() => setDraftRepairOpened(false)}
        title="确认开放旧版同步题目"
        centered
      >
        <Stack gap="md">
          <Text size="sm">将以下 {enabledDraftPkIndexes.length} 道题的竞技场状态由「草稿」改为「已开放」：</Text>
          <Code block>
            {enabledDraftPkIndexes
              .map((index) => config?.challenges[index]?.title)
              .filter(Boolean)
              .join('\n')}
          </Code>
          <Alert color="yellow" icon={<Icon path={mdiInformationOutline} size={1} />}>
            此操作只更新当前编辑内容，仍需点击「保存竞技场」才会生效。若其中有刻意保留的草稿题，请取消并逐题编辑。
          </Alert>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDraftRepairOpened(false)}>
              取消
            </Button>
            <Button color="orange" disabled={!enabledDraftPkIndexes.length} onClick={repairEnabledDraftPkChallenges}>
              确认全部开放
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={!!editor}
        onClose={() => setEditor(undefined)}
        title={editor?.index === null ? '新增竞技场题目' : '编辑竞技场题目'}
        size="72rem"
        centered
        scrollAreaComponent={ScrollArea.Autosize}
        classNames={{ content: classes.editorModal }}
      >
        {editor && config && (
          <Stack gap="lg">
            <SimpleGrid cols={4} spacing="md">
              <Select
                label="GZCTF 源题目"
                data={sourceOptions}
                searchable
                value={editor.value.sourceChallengeId ? String(editor.value.sourceChallengeId) : null}
                allowDeselect={false}
                onChange={(value) => {
                  if (!value) return
                  const source = sourceChallenges.find((challenge) => challenge.id === Number(value))
                  updateEditor({
                    sourceChallengeId: Number(value),
                    ...(source ? { title: source.title, category: source.category ?? 'Misc' } : {}),
                  })
                }}
              />
              <TextInput
                label="竞技场题名"
                required
                value={editor.value.title}
                onChange={(event) => updateEditor({ title: event.currentTarget.value })}
              />
              <TextInput
                label="分类"
                value={editor.value.category}
                onChange={(event) => updateEditor({ category: event.currentTarget.value })}
              />
              <Select
                label="发布状态"
                data={[
                  { value: 'draft', label: '草稿' },
                  { value: 'active', label: '已开放' },
                  { value: 'open', label: '已开放（兼容）' },
                  { value: 'locked', label: '锁定' },
                ]}
                value={editor.value.status ?? 'draft'}
                allowDeselect={false}
                onChange={(value) => value && updateEditor({ status: value as ArenaChallengeConfig['status'] })}
              />
            </SimpleGrid>

            <Textarea
              label="题目描述"
              description="玩家在 PK、单方向单挑或 Boss 题目详情中看到的题面，支持 Markdown 文本。"
              minRows={5}
              autosize
              value={editor.value.description ?? ''}
              onChange={(event) => updateEditor({ description: event.currentTarget.value })}
            />

            <SimpleGrid cols={4} spacing="md">
              <TextInput
                label="挑战目标 / 容器地址"
                placeholder="http://challenge:3000"
                value={editor.value.target ?? ''}
                onChange={(event) => updateEditor({ target: event.currentTarget.value })}
              />
              <TextInput
                label="附件 URL"
                placeholder="/assets/arena/challenge.zip"
                value={editor.value.attachmentUrl ?? ''}
                onChange={(event) => updateEditor({ attachmentUrl: event.currentTarget.value })}
              />
              <PasswordInput
                label="Flag"
                description={
                  editor.value.hasFlag ? '已存储 Flag；留空表示保持不变' : '新 Flag 仅会写入，不会从 API 读回'
                }
                value={editor.value.flag ?? ''}
                onChange={(event) => updateEditor({ flag: event.currentTarget.value || null, clearFlag: false })}
              />
              <Stack gap="xs" justify="flex-end" pb={4}>
                <Switch
                  label="Flag 区分大小写"
                  checked={editor.value.flagCaseSensitive}
                  onChange={(event) => updateEditor({ flagCaseSensitive: event.currentTarget.checked })}
                />
                <Switch
                  color="red"
                  label="清除已存 Flag"
                  disabled={!editor.value.hasFlag}
                  checked={editor.value.clearFlag ?? false}
                  onChange={(event) => updateEditor({ clearFlag: event.currentTarget.checked, flag: null })}
                />
              </Stack>
            </SimpleGrid>

            <Group justify="space-between" align="flex-end">
              <div>
                <Text size="sm" fw={700} mb={6}>
                  难度
                </Text>
                <SegmentedControl
                  value={editor.value.difficulty}
                  data={DIFFICULTY_OPTIONS}
                  onChange={(value) => updateEditor({ difficulty: value as ArenaDifficulty })}
                />
              </div>
              <Checkbox.Group
                label="参与模式"
                value={editor.value.modes}
                onChange={(value) => updateEditorModes(value as ArenaChallengeMode[])}
              >
                <Group mt={8}>
                  <Checkbox value="pk" label="Solo PK" />
                  <Checkbox value="one_way" label="单方向单挑" />
                  <Checkbox value="boss" label="Boss 讨伐" />
                </Group>
              </Checkbox.Group>
              <NumberInput
                label="排序"
                min={1}
                w="8rem"
                value={editor.value.sortOrder}
                onChange={(value) => updateEditor({ sortOrder: valueAsNumber(value, 1) })}
              />
              <Switch
                className={classes.fieldSwitch}
                label="启用此题"
                checked={editor.value.enabled}
                onChange={(event) => updateEditor({ enabled: event.currentTarget.checked })}
              />
            </Group>

            {editor.value.modes.includes('pk') && (
              <Paper className={classes.modeEditor} data-tone="pk">
                <Group mb="md">
                  <Icon path={mdiSwordCross} size={0.9} />
                  <Text fw={900}>PK 结算</Text>
                </Group>
                <SimpleGrid cols={3} spacing="md">
                  <TextInput
                    label="镜像题组"
                    description="同组变体会分配给对战双方"
                    value={editor.value.pk!.variantGroup ?? ''}
                    onChange={(event) =>
                      updateEditor({ pk: { ...editor.value.pk!, variantGroup: event.currentTarget.value || null } })
                    }
                  />
                  <NumberInput
                    label="基础分"
                    min={0}
                    value={editor.value.pk!.baseScore}
                    onChange={(value) => updateEditor({ pk: { ...editor.value.pk!, baseScore: valueAsNumber(value) } })}
                  />
                  <NumberInput
                    label="本题限时（分钟）"
                    min={1}
                    value={editor.value.pk!.timeLimitSeconds ? Math.round(editor.value.pk!.timeLimitSeconds / 60) : ''}
                    onChange={(value) =>
                      updateEditor({ pk: { ...editor.value.pk!, timeLimitSeconds: valueAsNumber(value, 15) * 60 } })
                    }
                  />
                </SimpleGrid>
              </Paper>
            )}

            {editor.value.modes.includes('boss') && (
              <Paper className={classes.modeEditor} data-tone="boss">
                <Group mb="md">
                  <Icon path={mdiShieldCrownOutline} size={0.9} />
                  <Text fw={900}>Boss 结算</Text>
                </Group>
                <SimpleGrid cols={3} spacing="md">
                  <NumberInput
                    label="基础伤害"
                    min={0}
                    thousandSeparator=","
                    value={editor.value.boss!.baseDamage}
                    onChange={(value) =>
                      updateEditor({ boss: { ...editor.value.boss!, baseDamage: valueAsNumber(value) } })
                    }
                  />
                  <NumberInput
                    label="开放阶段"
                    min={1}
                    max={config.bossConfig.phaseCount}
                    value={editor.value.boss!.phase}
                    onChange={(value) =>
                      updateEditor({ boss: { ...editor.value.boss!, phase: valueAsNumber(value, 1) } })
                    }
                  />
                  <Select
                    label="Boss 属性关系"
                    data={AFFINITY_OPTIONS}
                    value={editor.value.boss!.affinity}
                    allowDeselect={false}
                    onChange={(value) =>
                      value && updateEditor({ boss: { ...editor.value.boss!, affinity: value as BossAffinity } })
                    }
                  />
                  <Switch
                    className={classes.fieldSwitch}
                    label="破盾题"
                    description="完成时额外扣减阶段护盾"
                    checked={editor.value.boss!.isShieldChallenge}
                    onChange={(event) =>
                      updateEditor({ boss: { ...editor.value.boss!, isShieldChallenge: event.currentTarget.checked } })
                    }
                  />
                  <Switch
                    className={classes.fieldSwitch}
                    label="核心处决题"
                    description="只在最终阶段开放"
                    checked={editor.value.boss!.isCoreChallenge}
                    onChange={(event) =>
                      updateEditor({ boss: { ...editor.value.boss!, isCoreChallenge: event.currentTarget.checked } })
                    }
                  />
                </SimpleGrid>
              </Paper>
            )}

            <Divider />
            <Group justify="space-between">
              <Text size="xs" c="dimmed">
                编辑后还需点击页面右上角「保存竞技场」才会写入服务器。
              </Text>
              <Group>
                <Button variant="default" onClick={() => setEditor(undefined)}>
                  取消
                </Button>
                <Button leftSection={<Icon path={mdiCheck} size={0.85} />} onClick={saveEditor}>
                  应用题目设置
                </Button>
              </Group>
            </Group>
          </Stack>
        )}
      </Modal>
    </WithGameEditTab>
  )
}

export default ArenaModeAdmin
