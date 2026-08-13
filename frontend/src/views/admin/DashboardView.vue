<template>
  <div v-loading="loading" class="page-stack">
    <div class="toolbar-row">
      <el-input
        v-model="calendarMonth"
        placeholder="自然月 YYYY-MM"
        style="width: 180px"
        clearable
        @change="loadData"
      />
      <el-button type="primary" @click="loadData">刷新</el-button>
    </div>

    <div v-if="summaryCards.length" class="stat-grid">
      <div v-for="item in summaryCards" :key="item.label" class="stat-card">
        <div class="label">{{ item.label }}</div>
        <div class="value">{{ item.value }}</div>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :span="12">
        <el-card shadow="never">
          <template #header>
            <div>
              <div class="section-kicker">Membership</div>
              会员类型分布
            </div>
          </template>
          <div ref="memberChartRef" class="chart" />
        </el-card>
      </el-col>
      <el-col :xs="24" :span="12">
        <el-card shadow="never">
          <template #header>
            <div>
              <div class="section-kicker">Quota</div>
              用量分布
            </div>
          </template>
          <div ref="usageChartRef" class="chart" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <div>
          <div class="section-kicker">Trend</div>
          团队日趋势
        </div>
      </template>
      <div ref="trendChartRef" class="chart wide" />
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div>
          <div class="section-kicker">Rank</div>
          用量排行
        </div>
      </template>
      <el-table :data="rankings" stripe size="small" max-height="360">
        <el-table-column type="index" width="50" />
        <el-table-column
          v-for="col in rankColumns"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :min-width="col.minWidth"
          show-overflow-tooltip
        />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import * as echarts from 'echarts'
import * as cursorApi from '@/api/cursor'
import type { DashboardData } from '@/types'

const CHART_COLORS = ['#0f766e', '#c45c26', '#3d4a7a', '#b45309', '#57534e', '#0e7490']

const loading = ref(false)
const calendarMonth = ref('')
const dashboard = ref<DashboardData | null>(null)

const memberChartRef = ref<HTMLElement>()
const usageChartRef = ref<HTMLElement>()
const trendChartRef = ref<HTMLElement>()

const charts = shallowRef<echarts.ECharts[]>([])

const summary = computed(() => dashboard.value?.summary as Record<string, unknown> | undefined)

const summaryCards = computed(() => {
  const s = summary.value || {}
  const keys = [
    { key: 'total_accounts', label: '账号总数' },
    { key: 'bound_accounts', label: '已绑定' },
    { key: 'abnormal_count', label: '异常数' },
    { key: 'pool_members', label: '号池成员' },
  ]
  return keys
    .filter((k) => s[k.key] != null)
    .map((k) => ({ label: k.label, value: Number(s[k.key]) || 0 }))
})

const rankings = computed(() => dashboard.value?.rankings || dashboard.value?.token_rankings || [])

const rankColumns = computed(() => {
  const row = rankings.value[0] as Record<string, unknown> | undefined
  if (!row) {
    return [
      { prop: 'full_name', label: '姓名', minWidth: 100 },
      { prop: 'username', label: '用户名', minWidth: 100 },
      { prop: 'usage_total', label: '用量%', minWidth: 80 },
    ]
  }
  const labels: Record<string, string> = {
    full_name: '姓名',
    username: '用户名',
    cursor_email: '邮箱',
    usage_total: '用量%',
    total_tokens: 'Token',
    calendar_total_tokens: '月 Token',
  }
  return Object.keys(row)
    .filter((k) =>
      !['account_id', 'user_id', 'rank', 'id'].includes(k),
    )
    .slice(0, 6)
    .map((prop) => ({
      prop,
      label: labels[prop] || prop,
      minWidth: 90,
    }))
})

function disposeCharts() {
  charts.value.forEach((c) => c.dispose())
  charts.value = []
}

function mountChart(el: HTMLElement | undefined, option: echarts.EChartsOption) {
  if (!el) return
  const chart = echarts.init(el)
  chart.setOption(option)
  charts.value.push(chart)
}

const axisStyle = {
  axisLine: { lineStyle: { color: '#e6dfd6' } },
  axisLabel: { color: '#7a7168' },
  splitLine: { lineStyle: { color: '#eee8df' } },
}

function renderCharts() {
  disposeCharts()
  const d = dashboard.value
  if (!d) return

  const memberStats = d.membership_stats || []
  mountChart(memberChartRef.value, {
    color: CHART_COLORS,
    tooltip: { trigger: 'item' },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        itemStyle: { borderColor: '#fffcf8', borderWidth: 2 },
        label: { color: '#3f3833' },
        data: memberStats.map((x) => ({
          name: String(x.name || x.membership || x.membership_type || '未知'),
          value: Number(x.value ?? x.count ?? 0),
        })),
      },
    ],
  })

  const usageDist = d.usage_distribution || []
  mountChart(usageChartRef.value, {
    color: CHART_COLORS,
    tooltip: { trigger: 'item' },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        itemStyle: { borderColor: '#fffcf8', borderWidth: 2 },
        label: { color: '#3f3833' },
        data: usageDist.map((x) => ({
          name: String(x.name || x.level || x.label || ''),
          value: Number(x.value ?? x.count ?? 0),
        })),
      },
    ],
  })

  const trend = d.daily_team_trend || []
  mountChart(trendChartRef.value, {
    color: ['#0f766e'],
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 16, top: 24, bottom: 32 },
    xAxis: {
      type: 'category',
      data: trend.map((x) => String(x.date || x.usage_date || x.day || '')),
      ...axisStyle,
    },
    yAxis: { type: 'value', ...axisStyle },
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2.5 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(15, 118, 110, 0.28)' },
            { offset: 1, color: 'rgba(15, 118, 110, 0.02)' },
          ]),
        },
        data: trend.map((x) => Number(x.total_tokens ?? x.value ?? x.count ?? 0)),
      },
    ],
  })
}

async function loadData() {
  loading.value = true
  try {
    dashboard.value = await cursorApi.getDashboard({
      calendar_month: calendarMonth.value || undefined,
    })
    await nextTick()
    renderCharts()
  } finally {
    loading.value = false
  }
}

function onResize() {
  charts.value.forEach((c) => c.resize())
}

onMounted(async () => {
  await loadData()
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  disposeCharts()
})
</script>

<style scoped>
.chart {
  height: 300px;
}
.chart.wide {
  height: 320px;
}
</style>
