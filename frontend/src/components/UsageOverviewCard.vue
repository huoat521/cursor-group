<template>
  <el-card shadow="never">
    <template #header>
      <div>
        <div class="section-kicker">Usage</div>
        用量概览
      </div>
    </template>
    <el-empty v-if="!hasQuota" description="暂无用量数据，请先同步用量" />
    <div v-else class="usage-grid">
      <div class="quota">
        <div class="section-title">用量配额</div>
        <div class="bar-block">
          <div class="bar-head">
            <span>Total</span>
            <span>{{ usageTotal }}%</span>
          </div>
          <el-progress
            :percentage="clamp(usageTotal)"
            :stroke-width="10"
            :show-text="false"
            :color="barColor(usageTotal)"
          />
          <div class="hint">{{ usageAuto }}% Auto + {{ usageApi }}% API used</div>
        </div>

        <div class="sub-card">
          <div class="bar-head">
            <span>Auto + Composer</span>
            <span>{{ usageAuto }}%</span>
          </div>
          <el-progress
            :percentage="clamp(usageAuto)"
            :stroke-width="10"
            :show-text="false"
            :color="barColor(usageAuto)"
          />
          <div v-if="autoMsg" class="hint">{{ autoMsg }}</div>
        </div>

        <div class="sub-card">
          <div class="bar-head">
            <span>API</span>
            <span>{{ usageApi }}%</span>
          </div>
          <el-progress
            :percentage="clamp(usageApi)"
            :stroke-width="10"
            :show-text="false"
            :color="barColor(usageApi)"
          />
          <div v-if="apiMsg" class="hint">{{ apiMsg }}</div>
        </div>

        <div class="plan-foot">
          套餐额度 {{ planUsed }} / {{ planLimit }}（剩余 {{ planRemaining }}）
        </div>
      </div>

      <div v-if="tableRows.length" class="details">
        <div class="section-title">套餐用量明细</div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Tokens</th>
                <th>Usage</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, idx) in tableRows" :key="idx">
                <td :class="{ bold: row.bold, indent: !row.bold }">{{ row.name }}</td>
                <td>{{ formatTokensCn(row.tokens) }}</td>
                <td>{{ formatPercent(row.usage) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CursorAccount } from '@/types'
import {
  barColor,
  buildIncludedUsageRows,
  formatPercent,
  formatPlanNum,
  formatTokensCn,
  parseUsageRaw,
  roundPercent,
} from '@/utils/usage'

const props = defineProps<{
  account: CursorAccount
}>()

const usage = computed(() => parseUsageRaw(props.account.usage_raw))
const plan = computed(() => usage.value.individualUsage?.plan || {})

const usageTotal = computed(() => roundPercent(plan.value.totalPercentUsed))
const usageAuto = computed(() => roundPercent(plan.value.autoPercentUsed))
const usageApi = computed(() => roundPercent(plan.value.apiPercentUsed))
const hasQuota = computed(
  () =>
    plan.value.totalPercentUsed != null ||
    plan.value.autoPercentUsed != null ||
    plan.value.apiPercentUsed != null,
)
const autoMsg = computed(() => usage.value.autoModelSelectedDisplayMessage || '')
const apiMsg = computed(() => usage.value.namedModelSelectedDisplayMessage || '')
const planUsed = computed(() => formatPlanNum(plan.value.used))
const planLimit = computed(() => formatPlanNum(plan.value.limit))
const planRemaining = computed(() => formatPlanNum(plan.value.remaining))
const tableRows = computed(() => buildIncludedUsageRows(usage.value, plan.value))

function clamp(n: number) {
  return Math.max(0, Math.min(100, n))
}
</script>

<style scoped>
.usage-grid {
  display: grid;
  grid-template-columns: minmax(280px, 5fr) minmax(320px, 7fr);
  gap: 28px;
}
.section-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 14px;
}
.bar-block {
  margin-bottom: 16px;
}
.bar-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 650;
  color: var(--ink);
}
.hint {
  color: var(--muted);
  font-size: 12px;
  margin-top: 8px;
  line-height: 1.5;
}
.sub-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 12px;
}
.plan-foot {
  color: var(--ink-soft);
  font-size: 13px;
  margin-top: 4px;
}
.table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th {
  padding: 10px 12px;
  text-align: left;
  color: var(--muted);
  font-weight: 650;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
}
th:nth-child(2),
th:nth-child(3),
td:nth-child(2),
td:nth-child(3) {
  text-align: right;
  white-space: nowrap;
}
td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--surface-2);
  color: var(--ink-soft);
}
td.bold {
  font-weight: 650;
  color: var(--ink);
}
td.indent {
  padding-left: 28px;
}
tr:last-child td {
  border-bottom: none;
}
@media (max-width: 960px) {
  .usage-grid {
    grid-template-columns: 1fr;
  }
}
</style>
