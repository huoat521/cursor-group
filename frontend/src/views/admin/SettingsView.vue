<template>
  <div v-loading="loading" class="page-stack">
    <el-card shadow="never">
      <template #header>
        <div>
          <div class="section-kicker">Auth</div>
          认证与 SSO 设置
        </div>
      </template>

      <el-descriptions v-if="settings" :column="2" class="soft-desc">
        <el-descriptions-item label="本地登录">
          <el-tag
            :type="
              (settings.local_enabled ?? settings.local_auth_enabled) !== false
                ? 'success'
                : 'info'
            "
          >
            {{
              (settings.local_enabled ?? settings.local_auth_enabled) !== false
                ? '已启用'
                : '未启用'
            }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="OIDC">
          <el-tag :type="settings.oidc_enabled ? 'success' : 'info'">
            {{ settings.oidc_enabled ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="LDAP">
          <el-tag :type="settings.ldap_enabled ? 'success' : 'info'">
            {{ settings.ldap_enabled ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="自动开通">
          <el-tag :type="settings.auto_provision ? 'success' : 'info'">
            {{ settings.auto_provision ? '是' : '否' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item v-if="settings.oidc_provider" label="OIDC 提供商" :span="2">
          {{ settings.oidc_provider }}
        </el-descriptions-item>
      </el-descriptions>

      <el-empty v-else description="无法加载设置" />

      <el-divider />

      <h4>Personal Access Token</h4>
      <p class="hint">创建 PAT 可用于 API / 扩展等非浏览器场景。</p>
      <el-form inline>
        <el-form-item label="名称">
          <el-input v-model="patName" placeholder="可选" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="patLoading" @click="handleCreatePat">
            创建 PAT
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="patToken"
        type="success"
        :closable="false"
        show-icon
        title="PAT 已创建（请立即复制，仅显示一次）"
        class="pat-alert"
      >
        <template #default>
          <el-input :model-value="patToken" readonly>
            <template #append>
              <el-button @click="copyPat">复制</el-button>
            </template>
          </el-input>
        </template>
      </el-alert>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as authApi from '@/api/auth'
import type { AuthSettings } from '@/types'

const loading = ref(false)
const settings = ref<AuthSettings | null>(null)

const patName = ref('')
const patLoading = ref(false)
const patToken = ref('')

async function loadData() {
  loading.value = true
  try {
    settings.value = await authApi.getAuthSettings()
  } finally {
    loading.value = false
  }
}

async function handleCreatePat() {
  patLoading.value = true
  try {
    const res = await authApi.createPat({ name: patName.value || undefined })
    patToken.value = res.token
    ElMessage.success('PAT 已创建')
  } finally {
    patLoading.value = false
  }
}

async function copyPat() {
  await navigator.clipboard.writeText(patToken.value)
  ElMessage.success('已复制')
}

onMounted(loadData)
</script>

<style scoped>
.hint {
  color: var(--muted);
  font-size: 13px;
  margin: 0 0 12px;
}
.pat-alert {
  margin-top: 16px;
}
h4 {
  margin: 8px 0 6px;
  letter-spacing: -0.02em;
}
.soft-desc :deep(.el-descriptions__label) {
  color: var(--muted);
}
</style>
