<template>
  <div class="login-page">
    <div class="login-art">
      <div class="art-inner">
        <div class="brand-row">
          <AppMark on-dark />
          <span>Cursor Group</span>
        </div>
        <h1>团队用量与号池，放在一处。</h1>
        <p>绑定 Cursor、看清配额，再从号池租号注入本机 IDE。</p>
        <ul>
          <li>加密保管账号凭证</li>
          <li>临期优先调度租约</li>
          <li>扩展一键注入本机登录态</li>
        </ul>
      </div>
    </div>

    <div class="login-panel">
      <div class="login-card">
        <p class="section-kicker">Welcome back</p>
        <h2>登录控制台</h2>
        <p class="lead">使用平台账号，或走企业身份提供商。</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="handleLogin"
        >
          <el-form-item label="用户名 / 邮箱" prop="username">
            <el-input
              v-model="form.username"
              size="large"
              placeholder="用户名或邮箱"
              autocomplete="username"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              placeholder="密码"
              autocomplete="current-password"
              @keyup.enter="handleLogin"
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="submit"
            :loading="loading"
            @click="handleLogin"
          >
            进入控制台
          </el-button>
          <el-button
            v-if="settings?.oidc_enabled"
            size="large"
            class="oidc"
            @click="goOidc"
          >
            使用 OIDC 登录
          </el-button>
        </el-form>

        <p v-if="settings?.ldap_enabled" class="ldap">
          LDAP 已启用：可用企业账号登录，本地账号仍走上方表单。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { getAuthSettings, oidcLoginUrl } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { AuthSettings } from '@/types'
import AppMark from '@/components/AppMark.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const settings = ref<AuthSettings | null>(null)

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function isSafeRedirect(path: unknown): string | null {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) {
    return null
  }
  if (path.includes('\\') || path.includes('://')) {
    return null
  }
  return path
}

onMounted(async () => {
  try {
    settings.value = await getAuthSettings()
  } catch {
    /* settings optional on login page */
  }

  const oidcCode = route.query.oidc_code as string | undefined
  if (oidcCode) {
    try {
      await auth.exchangeOidc(oidcCode)
      ElMessage.success('OIDC 登录成功')
      router.replace(isSafeRedirect(route.query.redirect) || '/me')
    } catch {
      /* error shown by interceptor */
    }
  }
})

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push(isSafeRedirect(route.query.redirect) || '/me')
  } catch {
    /* error shown by interceptor */
  } finally {
    loading.value = false
  }
}

function goOidc() {
  window.location.href = oidcLoginUrl()
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(320px, 1.05fr) minmax(380px, 0.95fr);
  background: var(--canvas);
}

.login-art {
  position: relative;
  background:
    radial-gradient(circle at 20% 20%, rgba(196, 92, 38, 0.22), transparent 36%),
    radial-gradient(circle at 80% 80%, rgba(15, 118, 110, 0.2), transparent 40%),
    var(--ink);
  color: #f6efe7;
  overflow: hidden;
}

.login-art::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 252, 248, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 252, 248, 0.05) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(circle at 30% 30%, #000 20%, transparent 75%);
}

.art-inner {
  position: relative;
  max-width: 460px;
  padding: 64px 56px;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 700;
  letter-spacing: -0.03em;
}

.art-inner h1 {
  margin: 48px 0 16px;
  font-family: var(--font-display);
  font-size: 46px;
  font-weight: 560;
  line-height: 1.15;
  letter-spacing: -0.04em;
}

.art-inner > p {
  margin: 0;
  color: #cbbfb3;
  font-size: 16px;
  line-height: 1.7;
}

.art-inner ul {
  margin: 36px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 10px;
  color: #e8d5c4;
}

.art-inner li {
  padding-left: 18px;
  position: relative;
}

.art-inner li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.55em;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c45c26;
}

.login-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
}

.login-card {
  width: min(420px, 100%);
}

.login-card h2 {
  margin: 8px 0 6px;
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: 560;
  letter-spacing: -0.04em;
}

.lead {
  margin: 0 0 28px;
  color: var(--muted);
}

.submit,
.oidc {
  width: 100%;
  margin-left: 0 !important;
}

.submit {
  margin-top: 8px;
}

.oidc {
  margin-top: 10px;
}

.ldap {
  margin: 20px 0 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }
  .login-art {
    min-height: 280px;
  }
  .art-inner {
    padding: 36px 24px 28px;
  }
  .art-inner h1 {
    font-size: 32px;
    margin-top: 24px;
  }
  .art-inner ul {
    display: none;
  }
}
</style>
