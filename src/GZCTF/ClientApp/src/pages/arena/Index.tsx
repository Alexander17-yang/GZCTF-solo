import { arenaApi } from '@Services/ArenaApi'
import { Badge, Box, Button, Group, Loader, SimpleGrid, Stack, Text, ThemeIcon, Title } from '@mantine/core'
import {
  mdiAccountMultiple,
  mdiAlertCircleOutline,
  mdiArrowRight,
  mdiFire,
  mdiMapMarkerPath,
  mdiRefresh,
  mdiShieldSword,
  mdiSwordCross,
  mdiTimerSand,
  mdiTrophy,
} from '@mdi/js'
import { Icon } from '@mdi/react'
import { FC, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { WithNavBar } from '@Components/WithNavbar'
import { VoxelAvatar, VoxelBoss, VoxelPanel } from '@Components/arena/VoxelUI'
import { usePageTitle } from '@Hooks/usePageTitle'
import classes from '@Styles/Arena.module.css'

type ArenaPublicData = Awaited<ReturnType<typeof arenaApi.public.getActive>>
type LoadStatus = 'loading' | 'ready' | 'empty' | 'error'

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

const ArenaHome: FC = () => {
  const [arena, setArena] = useState<ArenaPublicData | null>(null)
  const [status, setStatus] = useState<LoadStatus>('loading')
  const [message, setMessage] = useState('正在同步已发布的竞技场配置…')

  usePageTitle('方块竞技场')

  const loadArena = useCallback(async (quiet = false) => {
    if (!quiet) setStatus('loading')
    try {
      const config = await arenaApi.public.getActive()
      setArena(config)
      setStatus('ready')
      setMessage('')
    } catch (error) {
      setArena(null)
      if (errorStatus(error) === 404) {
        setStatus('empty')
        setMessage('暂无已发布的方块竞技场，请等待管理员完成配置并发布。')
      } else {
        setStatus('error')
        setMessage(errorMessage(error))
      }
    }
  }, [])

  useEffect(() => {
    void loadArena()
    const timer = window.setInterval(() => void loadArena(true), 10000)
    return () => window.clearInterval(timer)
  }, [loadArena])

  const hasPk = arena?.mode === 'solo_pk' || arena?.mode === 'hybrid'
  const hasOneWay = arena?.mode === 'one_way_onebyone'
  const hasBoss = arena?.mode === 'boss_raid' || arena?.mode === 'hybrid'
  const pkChallengeCount =
    arena?.challenges.filter((challenge) => challenge.modes.includes('pk') && challenge.pk).length ?? 0
  const bossChallengeCount =
    arena?.challenges.filter((challenge) => challenge.modes.includes('boss') && challenge.boss).length ?? 0
  const bossState = arena?.bossState
  const hpRate = bossState && bossState.maxHp > 0 ? (bossState.hp / bossState.maxHp) * 100 : 0
  const modeLabel = useMemo(() => {
    if (!arena) return '等待发布'
    if (arena.mode === 'hybrid') return 'PK + Boss'
    if (arena.mode === 'solo_pk') return 'Solo PK'
    if (arena.mode === 'one_way_onebyone') return 'One-way One-by-one'
    if (arena.mode === 'boss_raid') return 'Boss Raid'
    return 'Classic'
  }, [arena])

  return (
    <WithNavBar width="min(1180px, 94%)" minWidth={0} withFooter>
      <main className={classes.world}>
        <section className={classes.hero}>
          <div className={classes.skyPixels} aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </div>
          <div className={classes.heroContent}>
            <Badge className={classes.seasonBadge}>
              {arena
                ? `ARENA #${arena.gameId} · REV ${arena.revision}`
                : status === 'loading'
                  ? 'SYNCING WORLD'
                  : 'WAITING FOR PUBLISH'}
            </Badge>
            <Title className={classes.heroTitle}>
              进入 <span>方块竞技场</span>
            </Title>
            <Text className={classes.heroText}>
              {arena
                ? `当前开放 ${modeLabel}。题目、计分规则和 Boss 血量均由管理员后台实时发布。`
                : '在实时 Solo 对决中证明你的技术，或召集队伍深入遗迹，共同击败数据世界中的体素巨兽。'}
            </Text>
            <Group gap="md" mt="lg">
              {hasPk ? (
                <Button
                  component={Link}
                  to="/arena/pk"
                  className={classes.pixelButton}
                  leftSection={<Icon path={mdiSwordCross} size={0.9} />}
                >
                  开始 PK
                </Button>
              ) : (
                <Button className={classes.pixelButton} disabled leftSection={<Icon path={mdiSwordCross} size={0.9} />}>
                  PK 未开放
                </Button>
              )}
              {hasBoss ? (
                <Button
                  component={Link}
                  to="/arena/boss"
                  className={classes.pixelButtonAlt}
                  leftSection={<Icon path={mdiFire} size={0.9} />}
                >
                  加入讨伐
                </Button>
              ) : (
                <Button className={classes.pixelButtonAlt} disabled leftSection={<Icon path={mdiFire} size={0.9} />}>
                  Boss 未开放
                </Button>
              )}
              {hasOneWay ? (
                <Button
                  component={Link}
                  to="/arena/one-way"
                  className={classes.pixelButtonAlt}
                  leftSection={<Icon path={mdiMapMarkerPath} size={0.9} />}
                >
                  单方向单挑
                </Button>
              ) : (
                <Button
                  className={classes.pixelButtonAlt}
                  disabled
                  leftSection={<Icon path={mdiMapMarkerPath} size={0.9} />}
                >
                  单方向单挑未开放
                </Button>
              )}
            </Group>
          </div>
          <div className={classes.heroTotems} aria-hidden="true">
            <VoxelAvatar color="cyan" size="lg" />
            <span className={classes.versus}>VS</span>
            <VoxelAvatar color="orange" size="lg" />
          </div>
        </section>

        {status !== 'ready' && (
          <VoxelPanel
            tone={status === 'error' ? 'danger' : 'stone'}
            compact
            title={status === 'loading' ? '同步竞技场' : '竞技场尚未就绪'}
            eyebrow="LIVE CONFIG"
          >
            <Group justify="space-between">
              <Group>
                {status === 'loading' ? (
                  <Loader size="sm" color="yellow" type="bars" />
                ) : (
                  <Icon path={mdiAlertCircleOutline} size={0.9} />
                )}
                <Text size="sm">{message}</Text>
              </Group>
              {status !== 'loading' && (
                <Button size="xs" leftSection={<Icon path={mdiRefresh} size={0.75} />} onClick={() => void loadArena()}>
                  重试
                </Button>
              )}
            </Group>
          </VoxelPanel>
        )}

        <SimpleGrid cols={{ base: 1, md: 3 }} spacing="xl" className={classes.modeGrid}>
          <VoxelPanel tone="obsidian" className={classes.modeCard}>
            <div className={classes.modeCardTop}>
              <ThemeIcon className={classes.pkIcon} size={58}>
                <Icon path={mdiSwordCross} size={1.45} />
              </ThemeIcon>
              <div>
                <Text className={classes.modeKicker}>SOLO RANKED</Text>
                <Title order={2}>矿坑决斗 · PK</Title>
              </div>
            </div>
            <Text className={classes.modeDescription}>
              {arena
                ? `${arena.pkConfig.teamSize}v${arena.pkConfig.teamSize} 对抗，服务端按 ${arena.pkConfig.scoreMode === 'dynamic' ? '动态分值' : '固定分值'} 结算，并实时同步个人积分与排行榜。`
                : '管理员发布 PK 配置后，真实题池、分值、冷却与排行榜将在这里自动载入。'}
            </Text>
            <SimpleGrid cols={3} spacing="xs" className={classes.miniStats}>
              <div>
                <Icon path={mdiAccountMultiple} size={0.78} />
                <strong>{arena ? `${arena.pkConfig.teamSize}v${arena.pkConfig.teamSize}` : '--'}</strong>
                <span>规模</span>
              </div>
              <div>
                <Icon path={mdiTimerSand} size={0.78} />
                <strong>{arena ? `${Math.ceil(arena.pkConfig.matchSeconds / 60)}m` : '--'}</strong>
                <span>时限</span>
              </div>
              <div>
                <Icon path={mdiTrophy} size={0.78} />
                <strong>{arena ? pkChallengeCount : '--'}</strong>
                <span>题目</span>
              </div>
            </SimpleGrid>
            {hasPk ? (
              <Button
                fullWidth
                component={Link}
                to="/arena/pk"
                className={classes.cardAction}
                rightSection={<Icon path={mdiArrowRight} size={0.85} />}
              >
                进入 PK 大厅
              </Button>
            ) : (
              <Button fullWidth disabled className={classes.cardAction}>
                当前未开启 PK
              </Button>
            )}
          </VoxelPanel>

          <VoxelPanel tone="wood" className={classes.modeCard}>
            <div className={classes.modeCardTop}>
              <ThemeIcon className={classes.pkIcon} size={58} color="violet">
                <Icon path={mdiMapMarkerPath} size={1.45} />
              </ThemeIcon>
              <div>
                <Text className={classes.modeKicker}>ONE-WAY ONE-BY-ONE</Text>
                <Title order={2}>单方向单挑</Title>
              </div>
            </div>
            <Text className={classes.modeDescription}>
              {arena
                ? `创建房间前选择挑战方向，进行 ${arena.oneWayConfig.roundCount} 轮逐题竞速。每轮只有一题，首位解出者立即获胜，超时则平局。`
                : '管理员配置方向题池、挑战轮次与每轮时限后，玩家可以创建 6 位私人房间进行逐轮竞速。'}
            </Text>
            <SimpleGrid cols={3} spacing="xs" className={classes.miniStats}>
              <div>
                <Icon path={mdiMapMarkerPath} size={0.78} />
                <strong>{arena ? arena.oneWayConfig.directions.length : '--'}</strong>
                <span>方向</span>
              </div>
              <div>
                <Icon path={mdiTimerSand} size={0.78} />
                <strong>{arena ? `${Math.ceil(arena.oneWayConfig.roundSeconds / 60)}m` : '--'}</strong>
                <span>单轮</span>
              </div>
              <div>
                <Icon path={mdiTrophy} size={0.78} />
                <strong>{arena ? arena.oneWayConfig.roundCount : '--'}</strong>
                <span>轮次</span>
              </div>
            </SimpleGrid>
            {hasOneWay ? (
              <Button
                fullWidth
                component={Link}
                to="/arena/one-way"
                className={classes.cardAction}
                rightSection={<Icon path={mdiArrowRight} size={0.85} />}
              >
                进入单挑大厅
              </Button>
            ) : (
              <Button fullWidth disabled className={classes.cardAction}>
                当前未开启单方向单挑
              </Button>
            )}
          </VoxelPanel>

          <VoxelPanel tone="danger" className={classes.modeCard}>
            <div className={classes.bossCardVisual}>
              <VoxelBoss />
              <Badge className={classes.liveBadge}>
                {bossState?.status === 'defeated' ? '讨伐完成' : hasBoss ? '全服作战中' : '等待开放'}
              </Badge>
            </div>
            <div className={classes.modeCardTop}>
              <ThemeIcon className={classes.bossIcon} size={58}>
                <Icon path={mdiShieldSword} size={1.45} />
              </ThemeIcon>
              <div>
                <Text className={classes.modeKicker}>GLOBAL RAID</Text>
                <Title order={2}>{arena?.bossConfig.name ?? '深岩守卫 · Boss'}</Title>
              </div>
            </div>
            <Text className={classes.modeDescription}>
              {arena
                ? `全服共享 ${arena.bossConfig.maxHp.toLocaleString()} HP 与 ${arena.bossConfig.phaseCount} 个阶段，攻克 ${bossChallengeCount} 道真实挑战累计伤害。`
                : '管理员发布 Boss 配置后，阶段、血量、题目和全服贡献榜将在这里实时同步。'}
            </Text>
            <div className={classes.compactHealth}>
              <Group justify="space-between">
                <Text fw={900}>Boss HP</Text>
                <Text ff="monospace" fw={900}>
                  {bossState ? `${hpRate.toFixed(1)}%` : '--'}
                </Text>
              </Group>
              <div>
                <span style={{ width: `${hpRate}%` }} />
              </div>
            </div>
            {hasBoss ? (
              <Button
                fullWidth
                component={Link}
                to="/arena/boss"
                className={classes.cardActionDanger}
                rightSection={<Icon path={mdiArrowRight} size={0.85} />}
              >
                加入 Boss 战
              </Button>
            ) : (
              <Button fullWidth disabled className={classes.cardActionDanger}>
                当前未开启 Boss
              </Button>
            )}
          </VoxelPanel>
        </SimpleGrid>

        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="lg" mt="xl">
          <VoxelPanel tone="grass" compact title="竞技场状态" eyebrow="LIVE CONFIG">
            <Stack gap={8}>
              <Text size="sm">{arena ? `赛事 #${arena.gameId} · ${modeLabel}` : '等待管理员发布'}</Text>
              <Box className={classes.questBar}>
                <span style={{ width: arena ? '100%' : '0%' }} />
              </Box>
              <Text size="xs" c="dimmed">
                {arena ? `配置修订版本 ${arena.revision}` : '发布后玩家端自动开放'}
              </Text>
            </Stack>
          </VoxelPanel>
          <VoxelPanel tone="wood" compact title="PK 计分情报" eyebrow="SCORING">
            <Text size="sm">
              {arena
                ? `首解 +${arena.pkConfig.firstBloodBonus}，连胜每层 +${arena.pkConfig.streakBonus}，提交冷却 ${arena.pkConfig.cooldownSeconds} 秒。`
                : '等待真实计分配置。'}
            </Text>
          </VoxelPanel>
          <VoxelPanel tone="stone" compact title="Boss 通关门槛" eyebrow="RAID RULE">
            <Group justify="space-between">
              <div>
                <Text size="xs" c="dimmed">
                  最低贡献
                </Text>
                <Text fw={900} c="yellow.4">
                  {arena ? arena.bossConfig.minTeamContribution.toLocaleString() : '--'}
                </Text>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  当前阶段
                </Text>
                <Text fw={900}>{bossState ? `${bossState.phase}/${arena?.bossConfig.phaseCount}` : '--'}</Text>
              </div>
            </Group>
          </VoxelPanel>
        </SimpleGrid>
      </main>
    </WithNavBar>
  )
}

export default ArenaHome
