import { Box, Group, Stack, Text, Title } from '@mantine/core'
import cx from 'clsx'
import { CSSProperties, FC, PropsWithChildren, ReactNode } from 'react'
import classes from '@Styles/VoxelUI.module.css'

export type VoxelTone = 'grass' | 'stone' | 'obsidian' | 'wood' | 'danger' | 'sky'

interface VoxelPanelProps extends PropsWithChildren {
  tone?: VoxelTone
  title?: string
  eyebrow?: string
  action?: ReactNode
  className?: string
  compact?: boolean
}

export const VoxelPanel: FC<VoxelPanelProps> = ({
  tone = 'stone',
  title,
  eyebrow,
  action,
  className,
  compact,
  children,
}) => (
  <section className={cx(classes.panel, classes[tone], compact && classes.compact, className)}>
    {(title || eyebrow || action) && (
      <Group className={classes.panelHeader} justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={2}>
          {eyebrow && <Text className={classes.eyebrow}>{eyebrow}</Text>}
          {title && <Title order={3}>{title}</Title>}
        </Stack>
        {action}
      </Group>
    )}
    {children}
  </section>
)

interface SegmentedBarProps {
  value: number
  max?: number
  segments?: number
  tone?: 'health' | 'shield' | 'energy' | 'success'
  label?: string
  detail?: string
  size?: 'sm' | 'md' | 'lg'
}

export const SegmentedBar: FC<SegmentedBarProps> = ({
  value,
  max = 100,
  segments = 20,
  tone = 'health',
  label,
  detail,
  size = 'md',
}) => {
  const ratio = Math.max(0, Math.min(1, value / max))
  const filled = Math.round(ratio * segments)

  return (
    <Stack gap={5}>
      {(label || detail) && (
        <Group justify="space-between" gap="xs">
          <Text fw={800} size="sm">
            {label}
          </Text>
          <Text className={classes.barDetail}>{detail ?? `${Math.round(ratio * 100)}%`}</Text>
        </Group>
      )}
      <Box className={cx(classes.segmentedBar, classes[`bar-${tone}`], classes[`bar-${size}`])}>
        {Array.from({ length: segments }, (_, index) => (
          <span key={index} data-filled={index < filled || undefined} />
        ))}
      </Box>
    </Stack>
  )
}

interface PixelStatProps {
  label: string
  value: string | number
  accent?: string
  icon?: ReactNode
}

export const PixelStat: FC<PixelStatProps> = ({ label, value, accent, icon }) => (
  <div className={classes.stat} style={{ '--stat-accent': accent } as CSSProperties}>
    {icon && <span className={classes.statIcon}>{icon}</span>}
    <div>
      <Text className={classes.statValue}>{value}</Text>
      <Text className={classes.statLabel}>{label}</Text>
    </div>
  </div>
)

interface VoxelAvatarProps {
  color?: 'cyan' | 'orange' | 'boss' | 'green'
  size?: 'sm' | 'md' | 'lg'
  label?: string
}

export const VoxelAvatar: FC<VoxelAvatarProps> = ({ color = 'green', size = 'md', label }) => (
  <div className={cx(classes.avatar, classes[`avatar-${color}`], classes[`avatar-${size}`])} aria-label={label}>
    <span className={classes.avatarEye} />
    <span className={classes.avatarEye} />
    <span className={classes.avatarMouth} />
  </div>
)

export const VoxelBoss: FC = () => (
  <div className={classes.boss} aria-label="原创体素深岩守卫">
    <div className={classes.bossHornLeft} />
    <div className={classes.bossHornRight} />
    <div className={classes.bossHead}>
      <span className={classes.bossEyeLeft} />
      <span className={classes.bossEyeRight} />
      <span className={classes.bossCore} />
    </div>
    <div className={classes.bossBody}>
      <span />
      <span />
      <span />
    </div>
  </div>
)
