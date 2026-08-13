<template>
  <div v-loading="loading" class="page-stack">
    <div class="toolbar-row">
      <el-button type="primary" @click="openAdd">添加成员</el-button>
      <el-button @click="loadData">刷新</el-button>
      <el-button :loading="policyRunning" @click="runPolicy">执行自动策略</el-button>
    </div>

    <div class="table-shell">
    <el-table :data="members" stripe @selection-change="onSelect">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="account_id" label="账号 ID" width="90" />
      <el-table-column prop="full_name" label="姓名" min-width="100" />
      <el-table-column prop="username" label="用户名" min-width="100" />
      <el-table-column prop="cursor_email" label="邮箱" min-width="160" show-overflow-tooltip />
      <el-table-column prop="membership_type" label="会员" width="90" />
      <el-table-column prop="enabled" label="启用" width="70">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            @change="(v: string | number | boolean) => toggleEnabled(row, Boolean(v))"
          />
        </template>
      </el-table-column>
      <el-table-column prop="priority" label="优先级" width="80" />
      <el-table-column prop="source" label="来源" width="80" />
      <el-table-column prop="usage_total" label="用量%" width="80" />
      <el-table-column prop="cycle_remaining_days" label="周期剩余天" width="110" />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确定移出号池？" @confirm="handleRemove(row.account_id)">
            <template #reference>
              <el-button type="danger" link>移除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <div v-if="selectedIds.length" class="batch-bar">
      <el-button @click="batchSet(true)">批量启用</el-button>
      <el-button @click="batchSet(false)">批量禁用</el-button>
    </div>

    <el-dialog v-model="addVisible" title="添加号池成员" width="480px">
      <el-form label-width="100px">
        <el-form-item label="候选账号">
          <el-select
            v-model="addForm.account_id"
            filterable
            placeholder="选择账号"
            style="width: 100%"
          >
            <el-option
              v-for="c in candidates"
              :key="c.account_id"
              :label="`${c.full_name || c.cursor_email} (#${c.account_id})`"
              :value="c.account_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="addForm.priority" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="日 Token 上限">
          <el-input-number
            v-model="addForm.max_daily_tokens"
            :min="0"
            placeholder="留空不限"
            controls-position="right"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleAdd">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑号池成员" width="480px">
      <el-form label-width="100px">
        <el-form-item label="优先级">
          <el-input-number v-model="editForm.priority" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="日 Token 上限">
          <el-input-number
            v-model="editForm.max_daily_tokens"
            :min="0"
            controls-position="right"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as poolApi from '@/api/pool'
import type { PoolCandidate, PoolMember } from '@/types'

const loading = ref(false)
const saving = ref(false)
const policyRunning = ref(false)
const members = ref<PoolMember[]>([])
const candidates = ref<PoolCandidate[]>([])
const selectedIds = ref<number[]>([])

const addVisible = ref(false)
const editVisible = ref(false)
const editAccountId = ref(0)

const addForm = reactive({
  account_id: undefined as number | undefined,
  priority: 0,
  max_daily_tokens: undefined as number | undefined,
})

const editForm = reactive({
  priority: 0,
  max_daily_tokens: undefined as number | undefined,
})

function onSelect(rows: PoolMember[]) {
  selectedIds.value = rows.map((r) => r.account_id)
}

async function loadData() {
  loading.value = true
  try {
    members.value = await poolApi.listPoolMembers()
  } finally {
    loading.value = false
  }
}

async function openAdd() {
  candidates.value = await poolApi.listPoolCandidates()
  addForm.account_id = undefined
  addForm.priority = 0
  addForm.max_daily_tokens = undefined
  addVisible.value = true
}

function openEdit(row: PoolMember) {
  editAccountId.value = row.account_id
  editForm.priority = row.priority
  editForm.max_daily_tokens = row.max_daily_tokens ?? undefined
  editVisible.value = true
}

async function handleAdd() {
  if (!addForm.account_id) {
    ElMessage.warning('请选择账号')
    return
  }
  saving.value = true
  try {
    await poolApi.addPoolMember({
      account_id: addForm.account_id,
      priority: addForm.priority,
      max_daily_tokens: addForm.max_daily_tokens ?? null,
    })
    ElMessage.success('已添加')
    addVisible.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function handleEdit() {
  saving.value = true
  try {
    await poolApi.updatePoolMember(editAccountId.value, {
      priority: editForm.priority,
      max_daily_tokens: editForm.max_daily_tokens ?? null,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row: PoolMember, enabled: boolean) {
  await poolApi.updatePoolMember(row.account_id, { enabled })
  row.enabled = enabled
}

async function handleRemove(accountId: number) {
  await poolApi.removePoolMember(accountId)
  ElMessage.success('已移除')
  await loadData()
}

async function batchSet(enabled: boolean) {
  await poolApi.batchPoolMembers({ account_ids: selectedIds.value, enabled })
  ElMessage.success('批量操作完成')
  await loadData()
}

async function runPolicy() {
  policyRunning.value = true
  try {
    await poolApi.runAutoPoolPolicy()
    ElMessage.success('自动策略已执行')
    await loadData()
  } finally {
    policyRunning.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.batch-bar {
  display: flex;
  gap: 8px;
}
</style>
