<template>
  <div v-loading="pageLoading" class="me-page">
    <div class="row-status">
      <el-card shadow="never" class="fill-card">
        <template #header>
          <div class="card-header">
            <div>
              <div class="section-kicker">Account</div>
              <span>Cursor 账号绑定</span>
            </div>
            <el-button
              v-if="oauthPolling"
              type="warning"
              size="small"
              @click="cancelOAuth"
            >
              取消绑定
            </el-button>
          </div>
        </template>

        <template v-if="!account">
          <div class="empty-bind">
            <p v-if="!oauthPolling" class="lead">
              还没有绑定 Cursor。完成后即可同步用量，并作为号池候选。
            </p>
            <p v-else class="lead">
              请在浏览器中完成 Cursor 授权：
              <el-link :href="oauthUri" target="_blank" type="primary">
                {{ oauthUri }}
              </el-link>
            </p>
            <el-button
              type="primary"
              :loading="oauthStarting"
              :disabled="oauthPolling"
              @click="startOAuth"
            >
              {{ oauthPolling ? '等待授权…' : '绑定 Cursor OAuth' }}
            </el-button>
          </div>
        </template>

        <template v-else>
          <el-descriptions :column="2" class="soft-desc">
            <el-descriptions-item label="邮箱">
              {{ account.cursor_email || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="会员类型">
              {{ account.membership_type || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="订阅状态">
              {{ account.subscription_status || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="绑定状态">
              <el-tag :type="account.bind_status === 1 ? 'success' : 'danger'">
                {{ account.bind_status === 1 ? '正常' : '异常' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="计费周期">
              {{ account.billing_cycle_text || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="上次同步">
              {{ account.last_sync_text || account.last_sync_at || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="周期 Token">
              {{ account.cycle_tokens_text || formatTokens(account.cycle_total_tokens) }}
            </el-descriptions-item>
            <el-descriptions-item label="自然月 Token">
              {{ account.calendar_tokens_text || formatTokens(account.calendar_total_tokens) }}
              <span v-if="account.calendar_month">（{{ account.calendar_month }}）</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="account.last_error" label="错误" :span="2">
              <el-text type="danger">{{ account.last_error }}</el-text>
            </el-descriptions-item>
          </el-descriptions>

          <div class="actions">
            <el-button type="primary" :loading="syncing" @click="handleSync">
              同步用量
            </el-button>
            <el-popconfirm title="确定解绑 Cursor 账号？" @confirm="handleUnbind">
              <template #reference>
                <el-button>解绑</el-button>
              </template>
            </el-popconfirm>
          </div>
        </template>
      </el-card>

      <el-card shadow="never" class="fill-card lease-card">
        <template #header>
          <div class="card-header">
            <div>
              <div class="section-kicker">Lease</div>
              <span>租约状态</span>
            </div>
            <el-button size="small" @click="loadLease">刷新</el-button>
          </div>
        </template>
        <div v-if="lease" class="lease-body">
          <div class="lease-pill" :class="lease.has_lease ? 'on' : 'off'">
            {{ lease.has_lease ? '持有中' : '未租号' }}
          </div>
          <el-descriptions :column="1" class="soft-desc">
            <el-descriptions-item v-if="lease.has_lease" label="账号邮箱">
              {{ lease.cursor_email || '-' }}
            </el-descriptions-item>
            <el-descriptions-item v-if="lease.has_lease" label="剩余时间">
              {{ formatSeconds(lease.sticky_remaining_seconds) }}
            </el-descriptions-item>
            <el-descriptions-item v-if="lease.expires_at" label="过期时间">
              {{ lease.expires_at }}
            </el-descriptions-item>
            <el-descriptions-item label="网关">
              {{ lease.gateway_enabled ? '已启用' : '未启用' }}
            </el-descriptions-item>
            <el-descriptions-item v-if="lease.reclaim_local" label="回收提示">
              <el-text type="warning">{{ lease.reclaim_reason || '需清理本地注入' }}</el-text>
            </el-descriptions-item>
          </el-descriptions>
        </div>
        <el-empty v-else description="暂无租约信息" :image-size="72" />
      </el-card>
    </div>

    <UsageOverviewCard v-if="account" :account="account" />

    <div class="row-tools">
      <el-card shadow="never" class="fill-card">
        <template #header>
          <div>
            <div class="section-kicker">Extension</div>
            VS Code 扩展
          </div>
        </template>
        <p class="tool-text">
          安装 Cursor Group Lease 扩展，从号池租用账号并注入本机 Cursor。
        </p>
        <el-link
          v-if="extInfo?.available"
          type="primary"
          :href="vsixHref"
        >
          下载扩展 VSIX（{{ extInfo.version }}）
        </el-link>
        <span v-else class="tool-text">扩展安装包尚未生成。</span>
      </el-card>

      <el-card shadow="never" class="fill-card">
        <template #header>
          <div>
            <div class="section-kicker">Token</div>
            扩展登录 Token（PAT）
          </div>
        </template>
        <p class="tool-text">
          OIDC 用户请用 PAT 在扩展中登录；本地/LDAP 用户也可直接用账号密码。
        </p>
        <el-button type="primary" size="small" :loading="patLoading" @click="createPat">
          生成 PAT
        </el-button>
        <el-alert
          v-if="patToken"
          type="success"
          :closable="false"
          show-icon
          class="pat-alert"
          title="请立即复制，仅显示一次"
        >
          <el-input :model-value="patToken" readonly />
        </el-alert>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as authApi from '@/api/auth'
import * as cursorApi from '@/api/cursor'
import * as proxyApi from '@/api/proxy'
import UsageOverviewCard from '@/components/UsageOverviewCard.vue'
import type { CursorAccount, LeaseStatus } from '@/types'

const pageLoading = ref(false)
const account = ref<CursorAccount | null>(null)
const lease = ref<LeaseStatus | null>(null)

const oauthStarting = ref(false)
const oauthPolling = ref(false)
const oauthUri = ref('')
let loginId = ''
let pollTimer: ReturnType<typeof setInterval> | null = null

const syncing = ref(false)
const patLoading = ref(false)
const patToken = ref('')
const extInfo = ref<{ available?: boolean; version?: string } | null>(null)
const vsixHref = computed(
  () => `/downloads/cursor-group-lease.vsix?v=${encodeURIComponent(extInfo.value?.version || '')}`,
)

async function createPat() {
  patLoading.value = true
  try {
    const data = await authApi.createPat({ name: 'extension', expires_days: 90 })
    patToken.value = data.token
    ElMessage.success('PAT 已生成')
  } finally {
    patLoading.value = false
  }
}

function formatTokens(n?: number | null) {
  if (n == null) return '-'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatSeconds(s?: number) {
  if (s == null || s <= 0) return '-'
  const m = Math.floor(s / 60)
  const sec = s % 60
  return m > 0 ? `${m} 分 ${sec} 秒` : `${sec} 秒`
}

async function loadAccount() {
  account.value = await cursorApi.getMyAccount()
}

async function loadLease() {
  lease.value = await proxyApi.getLeaseStatus()
}

async function loadExtensionInfo() {
  try {
    const resp = await fetch('/api/extension')
    if (!resp.ok) return
    extInfo.value = await resp.json()
  } catch {
    /* optional */
  }
}

async function startOAuth() {
  oauthStarting.value = true
  try {
    const data = await cursorApi.oauthStart()
    loginId = data.login_id
    oauthUri.value = data.verification_uri
    oauthPolling.value = true
    window.open(data.verification_uri, '_blank')
    startPoll(data.interval_seconds * 1000 || 2000)
  } finally {
    oauthStarting.value = false
  }
}

function startPoll(intervalMs: number) {
  stopPoll()
  pollTimer = setInterval(async () => {
    try {
      const result = await cursorApi.oauthPoll(loginId)
      if (result.status === 'complete' && result.account) {
        account.value = result.account
        oauthPolling.value = false
        stopPoll()
        ElMessage.success('绑定成功')
      } else if (result.status === 'error') {
        oauthPolling.value = false
        stopPoll()
        ElMessage.error(result.message || '授权失败')
      }
    } catch {
      oauthPolling.value = false
      stopPoll()
    }
  }, intervalMs)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function cancelOAuth() {
  if (loginId) {
    try {
      await cursorApi.oauthCancel(loginId)
    } catch {
      /* ignore */
    }
  }
  oauthPolling.value = false
  stopPoll()
}

async function handleSync() {
  syncing.value = true
  try {
    account.value = await cursorApi.syncMy()
    ElMessage.success('同步完成')
  } finally {
    syncing.value = false
  }
}

async function handleUnbind() {
  await cursorApi.unbindMy()
  account.value = null
  ElMessage.success('已解绑')
}

onMounted(async () => {
  pageLoading.value = true
  try {
    await Promise.all([loadAccount(), loadLease(), loadExtensionInfo()])
  } finally {
    pageLoading.value = false
  }
})

onUnmounted(() => {
  stopPoll()
})
</script>

<style scoped>
.me-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.row-status,
.row-tools {
  display: grid;
  gap: 16px;
  align-items: stretch;
}
.row-status {
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.9fr);
}
.row-tools {
  grid-template-columns: 1fr 1fr;
}
.fill-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.fill-card :deep(.el-card__body) {
  flex: 1;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.lead {
  margin: 0 0 16px;
  color: var(--muted);
  line-height: 1.7;
}
.empty-bind {
  padding: 8px 0 4px;
}
.actions {
  margin-top: 18px;
  display: flex;
  gap: 8px;
}
.tool-text {
  margin: 0 0 14px;
  color: var(--muted);
  line-height: 1.7;
}
.pat-alert {
  margin-top: 12px;
}
.lease-pill {
  display: inline-flex;
  align-items: center;
  margin-bottom: 14px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.lease-pill.on {
  background: var(--accent-soft);
  color: var(--accent-hover);
}
.lease-pill.off {
  background: var(--surface-2);
  color: var(--muted);
}
.soft-desc :deep(.el-descriptions__label) {
  color: var(--muted);
}
@media (max-width: 960px) {
  .row-status,
  .row-tools {
    grid-template-columns: 1fr;
  }
}
</style>
