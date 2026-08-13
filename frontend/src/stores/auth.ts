import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'
import { clearToken, getToken, setToken } from '@/api/request'
import type { User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => !!getToken())
  const isAdmin = computed(
    () => user.value?.role === 'admin' || !!user.value?.is_superuser,
  )

  async function fetchMe() {
    if (!getToken()) {
      user.value = null
      return null
    }
    loading.value = true
    try {
      user.value = await authApi.getMe()
      return user.value
    } finally {
      loading.value = false
    }
  }

  async function login(username: string, password: string) {
    const result = await authApi.login(username, password)
    setToken(result.access_token)
    await fetchMe()
  }

  async function exchangeOidc(code: string) {
    const result = await authApi.exchangeOidc(code)
    setToken(result.access_token)
    await fetchMe()
  }

  async function setSession(token: string) {
    setToken(token)
    await fetchMe()
  }

  function logout() {
    clearToken()
    user.value = null
  }

  return {
    user,
    loading,
    isLoggedIn,
    isAdmin,
    fetchMe,
    login,
    exchangeOidc,
    setSession,
    logout,
  }
})
