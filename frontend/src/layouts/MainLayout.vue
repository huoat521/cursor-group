<template>
  <div class="shell" :class="{ collapsed: sidebarCollapsed, 'nav-open': mobileOpen }">
    <div v-if="mobileOpen" class="scrim" @click="mobileOpen = false" />

    <aside class="aside">
      <div class="brand">
        <AppMark on-dark />
        <div v-if="!sidebarCollapsed" class="brand-text">
          <strong>Cursor Group</strong>
          <span>用量 · 号池 · 租约</span>
        </div>
      </div>

      <nav class="nav">
        <el-menu
          :default-active="activeMenu"
          :collapse="sidebarCollapsed"
          router
          class="menu"
          @select="mobileOpen = false"
        >
          <div v-if="!sidebarCollapsed" class="nav-label">工作台</div>
          <el-menu-item index="/me">
            <el-icon><User /></el-icon>
            <span>我的 Cursor</span>
          </el-menu-item>

          <template v-if="auth.isAdmin">
            <div v-if="!sidebarCollapsed" class="nav-label">用量</div>
            <el-menu-item index="/admin/dashboard">
              <el-icon><DataAnalysis /></el-icon>
              <span>用量仪表盘</span>
            </el-menu-item>
            <el-menu-item index="/admin/accounts">
              <el-icon><Postcard /></el-icon>
              <span>账号列表</span>
            </el-menu-item>
            <el-menu-item index="/admin/abnormal">
              <el-icon><WarningFilled /></el-icon>
              <span>异常账号</span>
            </el-menu-item>

            <div v-if="!sidebarCollapsed" class="nav-label">号池</div>
            <el-menu-item index="/admin/pool">
              <el-icon><Collection /></el-icon>
              <span>号池管理</span>
            </el-menu-item>
            <el-menu-item index="/admin/lease-config">
              <el-icon><SetUp /></el-icon>
              <span>租约配置</span>
            </el-menu-item>
            <el-menu-item index="/admin/leases">
              <el-icon><Timer /></el-icon>
              <span>活跃租约</span>
            </el-menu-item>

            <div v-if="!sidebarCollapsed" class="nav-label">系统</div>
            <el-menu-item index="/admin/users">
              <el-icon><UserFilled /></el-icon>
              <span>用户管理</span>
            </el-menu-item>
            <el-menu-item index="/admin/settings">
              <el-icon><Lock /></el-icon>
              <span>认证设置</span>
            </el-menu-item>
          </template>
        </el-menu>
      </nav>

      <div class="aside-foot">
        <button class="collapse-btn" type="button" @click="toggleSidebar">
          <el-icon><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
          <span v-if="!sidebarCollapsed">收起导航</span>
        </button>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <div class="title-block">
          <button class="mobile-toggle" type="button" @click="mobileOpen = true">
            <el-icon><Menu /></el-icon>
          </button>
          <div>
            <h1>{{ pageTitle }}</h1>
            <p v-if="pageSubtitle">{{ pageSubtitle }}</p>
          </div>
        </div>
        <div class="topbar-right">
          <div v-if="auth.user" class="who">
            <span class="avatar">{{ initials }}</span>
            <div class="who-meta">
              <strong>{{ displayName }}</strong>
              <span>{{ auth.isAdmin ? '管理员' : '成员' }}</span>
            </div>
          </div>
          <el-button class="logout" @click="handleLogout">退出</el-button>
        </div>
      </header>
      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Collection,
  DataAnalysis,
  Expand,
  Fold,
  Lock,
  Menu,
  Postcard,
  SetUp,
  Timer,
  User,
  UserFilled,
  WarningFilled,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import AppMark from '@/components/AppMark.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sidebarCollapsed = ref(false)
const mobileOpen = ref(false)

const activeMenu = computed(() => route.path)
const pageTitle = computed(() => (route.meta.title as string) || 'Cursor Group')
const pageSubtitle = computed(() => (route.meta.subtitle as string) || '')
const displayName = computed(() => {
  const u = auth.user
  if (!u) return ''
  return u.full_name || u.username || u.email || `用户#${u.id}`
})
const initials = computed(() => {
  const name = displayName.value.trim()
  if (!name) return 'U'
  return name.slice(0, 1).toUpperCase()
})

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  background:
    radial-gradient(1200px 480px at 100% -10%, rgba(196, 92, 38, 0.08), transparent 55%),
    radial-gradient(900px 420px at -10% 0%, rgba(15, 118, 110, 0.08), transparent 50%),
    var(--canvas);
}

.aside {
  width: 248px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--sidebar);
  color: var(--sidebar-text);
  position: sticky;
  top: 0;
  height: 100vh;
  z-index: 20;
  transition: width 0.22s ease;
}

.collapsed .aside {
  width: 76px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 18px 18px;
  min-height: 84px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.brand-text strong {
  color: #f6efe7;
  font-size: 15px;
  letter-spacing: -0.03em;
}

.brand-text span {
  margin-top: 2px;
  font-size: 11px;
  color: #9a8e82;
  letter-spacing: 0.04em;
}

.nav {
  flex: 1;
  overflow: auto;
  padding: 0 10px 12px;
}

.nav-label {
  padding: 16px 12px 6px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #8a7f74;
}

.menu {
  background: transparent;
  border: none;
  width: 100%;
}

.menu:not(.el-menu--collapse) {
  width: 100%;
}

.menu :deep(.el-menu-item) {
  height: 42px;
  margin: 2px 0;
  border-radius: 10px;
  color: #cbbfb3;
  font-weight: 550;
}

.menu :deep(.el-menu-item .el-icon) {
  color: #9a8e82;
}

.menu :deep(.el-menu-item:hover) {
  background: rgba(255, 252, 248, 0.06);
  color: #f6efe7;
}

.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(196, 92, 38, 0.22), rgba(255, 252, 248, 0.08));
  color: #fff8f2;
}

.menu :deep(.el-menu-item.is-active .el-icon) {
  color: #e8d5c4;
}

.aside-foot {
  padding: 12px 10px 16px;
  border-top: 1px solid rgba(255, 252, 248, 0.06);
}

.collapse-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 0;
  background: transparent;
  color: #9a8e82;
  cursor: pointer;
  border-radius: 10px;
  padding: 10px 12px;
  font: inherit;
  font-size: 12px;
}

.collapse-btn:hover {
  background: rgba(255, 252, 248, 0.06);
  color: #f6efe7;
}

.workspace {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 28px 8px;
}

.title-block {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}

.title-block h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 560;
  letter-spacing: -0.04em;
  line-height: 1.15;
}

.title-block p {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.mobile-toggle {
  display: none;
  width: 40px;
  height: 40px;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 12px;
  cursor: pointer;
  color: var(--ink);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.who {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px 6px 6px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 999px;
  box-shadow: var(--shadow);
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--ink);
  color: #f6efe7;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
}

.who-meta {
  display: flex;
  flex-direction: column;
  padding-right: 6px;
}

.who-meta strong {
  font-size: 13px;
  line-height: 1.2;
}

.who-meta span {
  font-size: 11px;
  color: var(--muted);
}

.logout {
  border-radius: 999px !important;
}

.content {
  flex: 1;
  padding: 12px 28px 32px;
}

.scrim {
  display: none;
}

@media (max-width: 960px) {
  .aside {
    position: fixed;
    left: 0;
    top: 0;
    transform: translateX(-105%);
    transition: transform 0.22s ease;
    width: 248px !important;
  }
  .nav-open .aside {
    transform: none;
  }
  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(22, 19, 17, 0.45);
    z-index: 15;
  }
  .mobile-toggle {
    display: grid;
    place-items: center;
  }
  .topbar,
  .content {
    padding-left: 16px;
    padding-right: 16px;
  }
  .who-meta {
    display: none;
  }
}
</style>
