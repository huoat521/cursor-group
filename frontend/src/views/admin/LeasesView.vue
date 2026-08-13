<template>
  <div v-loading="loading" class="page-stack">
    <div class="toolbar-row">
      <el-button type="primary" @click="loadData">刷新</el-button>
    </div>
    <div class="table-shell">
      <el-table :data="leases" stripe>
        <el-table-column prop="user_id" label="用户 ID" width="90" />
        <el-table-column prop="full_name" label="姓名" min-width="100" />
        <el-table-column prop="username" label="用户名" min-width="100" />
        <el-table-column prop="account_id" label="账号 ID" width="90" />
        <el-table-column prop="cursor_email" label="Cursor 邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column prop="lease_id" label="租约 ID" min-width="120" show-overflow-tooltip />
        <el-table-column label="剩余" width="100">
          <template #default="{ row }">
            {{ formatSeconds(row.sticky_remaining_seconds) }}
          </template>
        </el-table-column>
        <el-table-column prop="expires_at" label="过期时间" min-width="160" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-popconfirm
              :title="`强制释放用户 #${row.user_id} 的租约？`"
              @confirm="handleRelease(row.user_id)"
            >
              <template #reference>
                <el-button type="danger" link :loading="releasingId === row.user_id">
                  强制释放
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as proxyApi from '@/api/proxy'
import type { ActiveLease } from '@/types'

const loading = ref(false)
const leases = ref<ActiveLease[]>([])
const releasingId = ref<number | null>(null)

function formatSeconds(s?: number) {
  if (s == null || s <= 0) return '-'
  const m = Math.floor(s / 60)
  const sec = s % 60
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`
}

async function loadData() {
  loading.value = true
  try {
    const data = await proxyApi.listActiveLeases()
    leases.value = Array.isArray(data) ? data : []
  } finally {
    loading.value = false
  }
}

async function handleRelease(userId?: number) {
  if (userId == null) return
  releasingId.value = userId
  try {
    await proxyApi.forceReleaseLease(userId)
    ElMessage.success('已释放')
    await loadData()
  } finally {
    releasingId.value = null
  }
}

onMounted(loadData)
</script>
