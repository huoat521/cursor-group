<template>
  <div v-loading="loading" class="page-stack">
    <div class="toolbar-row">
      <el-button type="primary" @click="openCreate">新建用户</el-button>
      <el-button @click="loadData">刷新</el-button>
    </div>

    <div class="table-shell">
    <el-table :data="users" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip />
      <el-table-column prop="full_name" label="姓名" min-width="100" />
      <el-table-column prop="role" label="角色" width="90" />
      <el-table-column prop="is_active" label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active !== false ? 'success' : 'info'" size="small">
            {{ row.is_active !== false ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="is_superuser" label="超管" width="70">
        <template #default="{ row }">
          {{ row.is_superuser ? '是' : '否' }}
        </template>
      </el-table-column>
    </el-table>
    </div>

    <el-dialog v-model="createVisible" title="新建用户" width="480px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.full_name" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="普通用户" value="member" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import * as authApi from '@/api/auth'
import type { User } from '@/types'

const loading = ref(false)
const saving = ref(false)
const users = ref<User[]>([])
const createVisible = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  username: '',
  password: '',
  email: '',
  full_name: '',
  role: 'member',
  is_active: true,
})

const rules: FormRules = {
  username: [{ required: true, message: '必填', trigger: 'blur' }],
  password: [{ required: true, message: '必填', trigger: 'blur' }],
}

async function loadData() {
  loading.value = true
  try {
    users.value = await authApi.listUsers()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.username = ''
  form.password = ''
  form.email = ''
  form.full_name = ''
  form.role = 'member'
  form.is_active = true
  createVisible.value = true
}

async function handleCreate() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    await authApi.createUser({ ...form })
    ElMessage.success('用户已创建')
    createVisible.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

onMounted(loadData)
</script>

