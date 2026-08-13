import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '@/api/request'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      redirect: '/me',
      children: [
        {
          path: 'me',
          name: 'me',
          component: () => import('@/views/MeView.vue'),
          meta: { title: '我的 Cursor', subtitle: '绑定账号、查看配额，并管理扩展登录凭证' },
        },
        {
          path: 'admin/dashboard',
          name: 'admin-dashboard',
          component: () => import('@/views/admin/DashboardView.vue'),
          meta: { title: '用量仪表盘', subtitle: '团队绑定、配额分布与用量趋势', admin: true },
        },
        {
          path: 'admin/accounts',
          name: 'admin-accounts',
          component: () => import('@/views/admin/AccountsView.vue'),
          meta: { title: '账号列表', subtitle: '已绑定 Cursor 账号与同步状态', admin: true },
        },
        {
          path: 'admin/abnormal',
          name: 'admin-abnormal',
          component: () => import('@/views/admin/AbnormalView.vue'),
          meta: { title: '异常账号', subtitle: '绑定失败或同步报错的账号', admin: true },
        },
        {
          path: 'admin/pool',
          name: 'admin-pool',
          component: () => import('@/views/admin/PoolView.vue'),
          meta: { title: '号池管理', subtitle: '维护可租账号、优先级与自动入池', admin: true },
        },
        {
          path: 'admin/lease-config',
          name: 'admin-lease-config',
          component: () => import('@/views/admin/LeaseConfigView.vue'),
          meta: { title: '租约配置', subtitle: '网关、调度策略与并发限制', admin: true },
        },
        {
          path: 'admin/leases',
          name: 'admin-leases',
          component: () => import('@/views/admin/LeasesView.vue'),
          meta: { title: '活跃租约', subtitle: '当前正在租用的会话，可强制回收', admin: true },
        },
        {
          path: 'admin/users',
          name: 'admin-users',
          component: () => import('@/views/admin/UsersView.vue'),
          meta: { title: '用户管理', subtitle: '创建成员与管理员账号', admin: true },
        },
        {
          path: 'admin/settings',
          name: 'admin-settings',
          component: () => import('@/views/admin/SettingsView.vue'),
          meta: { title: '认证设置', subtitle: '本地登录、OIDC、LDAP 与 PAT', admin: true },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/me' },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (to.path === '/login' && getToken()) {
      return '/me'
    }
    return true
  }

  if (!getToken()) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  const auth = useAuthStore()
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  if (to.meta.admin && !auth.isAdmin) {
    return '/me'
  }

  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'Cursor Group'
  document.title = to.path === '/login' ? '登录 · Cursor Group' : `${title} · Cursor Group`
})

export default router
