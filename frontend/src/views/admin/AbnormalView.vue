<template>
  <div v-loading="loading" class="page-stack">
    <div class="toolbar-row">
      <el-button type="primary" @click="loadData">刷新</el-button>
    </div>
    <div class="table-shell">
      <el-table :data="accounts" stripe>
        <el-table-column prop="full_name" label="姓名" min-width="100" />
        <el-table-column prop="username" label="用户名" min-width="100" />
        <el-table-column prop="cursor_email" label="邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column prop="bind_status" label="绑定" width="90">
          <template #default="{ row }">
            <el-tag :type="row.bind_status === 1 ? 'success' : 'danger'" size="small">
              {{ row.bind_status === 1 ? '正常' : '异常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_error" label="错误信息" min-width="200" show-overflow-tooltip />
        <el-table-column prop="last_sync_text" label="同步" min-width="140" />
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
    accounts.value = await cursorApi.listAbnormal()
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
