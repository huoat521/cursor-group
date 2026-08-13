export type UsageAggregation = {
  tier?: number
  modelIntent?: string
  model?: string
  inputTokens?: number | string
  outputTokens?: number | string
  cacheWriteTokens?: number | string
  cacheReadTokens?: number | string
}

export type UsagePlan = {
  totalPercentUsed?: number | string
  autoPercentUsed?: number | string
  apiPercentUsed?: number | string
  used?: number | string
  limit?: number | string
  remaining?: number | string
}

export type UsageRaw = {
  individualUsage?: { plan?: UsagePlan }
  aggregatedUsage?: { aggregations?: UsageAggregation[] }
  autoModelSelectedDisplayMessage?: string
  namedModelSelectedDisplayMessage?: string
}

export type UsageDetailRow = {
  name: string
  tokens: number
  usage: number
  bold: boolean
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

export function parseUsageRaw(raw: unknown): UsageRaw {
  const root = asRecord(raw)
  const individual = asRecord(root.individualUsage)
  const aggregated = asRecord(root.aggregatedUsage)
  const aggregations = Array.isArray(aggregated.aggregations)
    ? (aggregated.aggregations as UsageAggregation[])
    : []
  return {
    individualUsage: { plan: asRecord(individual.plan) as UsagePlan },
    aggregatedUsage: { aggregations },
    autoModelSelectedDisplayMessage:
      typeof root.autoModelSelectedDisplayMessage === 'string'
        ? root.autoModelSelectedDisplayMessage
        : '',
    namedModelSelectedDisplayMessage:
      typeof root.namedModelSelectedDisplayMessage === 'string'
        ? root.namedModelSelectedDisplayMessage
        : '',
  }
}

export function parseTokenNum(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

export function roundPercent(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? Math.round(n) : 0
}

export function formatTokensCn(count: number): string {
  if (count >= 100_000_000) return `${(count / 100_000_000).toFixed(1)}亿`
  if (count >= 10_000) return `${(count / 10_000).toFixed(1)}万`
  return String(Math.round(count))
}

export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '-'
  return `${value.toFixed(1)}%`
}

export function formatPlanNum(value: unknown): string {
  if (value == null || value === '') return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10)
}

export function barColor(percent: number): string {
  if (percent >= 90) return '#ef4444'
  if (percent >= 70) return '#f59e0b'
  return '#22c55e'
}

function sumItemTokens(item: UsageAggregation): number {
  return (
    parseTokenNum(item.inputTokens) +
    parseTokenNum(item.outputTokens) +
    parseTokenNum(item.cacheWriteTokens) +
    parseTokenNum(item.cacheReadTokens)
  )
}

export function buildIncludedUsageRows(
  usage: UsageRaw,
  plan: UsagePlan,
): UsageDetailRow[] {
  const items = usage.aggregatedUsage?.aggregations || []
  if (!items.length) return []

  const tierOrder = [1, 2]
  const tierNames: Record<number, string> = {
    1: 'API',
    2: 'Auto + Composer',
  }
  const tierPercents: Record<number, number> = {
    1: Number(plan.apiPercentUsed) || 0,
    2: Number(plan.autoPercentUsed) || 0,
  }
  const grouped: Record<number, UsageAggregation[]> = {}
  for (const item of items) {
    const tier = Number(item.tier) || 1
    if (!grouped[tier]) grouped[tier] = []
    grouped[tier].push(item)
  }

  const rows: UsageDetailRow[] = []
  for (const tier of tierOrder) {
    const tierItems = grouped[tier]
    if (!tierItems?.length) continue
    const tierTokens = tierItems.reduce((sum, item) => sum + sumItemTokens(item), 0)
    const tierPct = tierPercents[tier] || 0
    rows.push({
      name: `${tierNames[tier]} (Total)`,
      tokens: tierTokens,
      usage: tierPct,
      bold: true,
    })
    ;[...tierItems]
      .sort((a, b) => sumItemTokens(b) - sumItemTokens(a))
      .forEach((item) => {
        const itemTokens = sumItemTokens(item)
        rows.push({
          name: item.modelIntent || item.model || '-',
          tokens: itemTokens,
          usage: tierTokens > 0 ? (itemTokens / tierTokens) * tierPct : 0,
          bold: false,
        })
      })
  }
  return rows
}
