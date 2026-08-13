<template>
  <div v-loading="loading" class="page-stack">
    <div class="toolbar-row">
      <el-button type="primary" @click="loadData">刷新</el-button>
    </div>
    <div class="table-shell">
      <el-table :data="accounts" stripe>
        <el-table-column prop="full_name" label="姓名" min-width="100" />
        <el-table-column prop="username" label="用户名" min-width="100" />
        <el-table-column prop="cursor_email" label="Cursor 邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column prop="membership_type" label="会员" width="100" />
        <el-table-column prop="usage_total" label="用量%" width="80" />
        <el-table-column prop="plan_remaining" label="剩余" width="80" />
        <el-table-column prop="usage_level" label="等级" width="80" />
        <el-table-column prop="last_sync_text" label="同步" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              link
              :loading="syncingId === row.id"
              @click="handleSync(row.id)"
            >
              同步
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as cursorApi from '@/api/cursor'
import type { AdminAccount } from '@/types'

const loading = ref(false)
const accounts = ref<AdminAccount[]>([])
const syncingId = ref<number | null>(null)

async function loadData() {
  loading.value = true
  try {
    accounts.value = await cursorApi.listAccounts()
  } finally {
    loading.value = false
  }
}

async function handleSync(accountId: number) {
  syncingId.value = accountId
  try {
    await cursorApi.syncAccount(accountId)
    ElMessage.success('同步完成')
    await loadData()
  } finally {
    syncingId.value = null
  }
}

onMounted(loadData)
</script>
