import axios, { type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types'

const TOKEN_KEY = 'access_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const payload = response.data as ApiResponse
    if (payload && typeof payload.status === 'number') {
      if (payload.status !== 0) {
        ElMessage.error(payload.msg || '请求失败')
        return Promise.reject(new Error(payload.msg || '请求失败'))
      }
      return payload.data as typeof response.data
    }
    return response.data
  },
  (error) => {
    const status = error.response?.status
    const body = error.response?.data
    const msg = body?.msg || body?.detail || error.message || '网络错误'
    const businessStatus = typeof body?.status === 'number' ? body.status : undefined
    if (status === 401 || businessStatus === 20008) {
      clearToken()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    ElMessage.error(msg)
    return Promise.reject(error)
  },
)

export async function request<T>(
  config: AxiosRequestConfig,
): Promise<T> {
  return http.request<unknown, T>(config) as Promise<T>
}

export default http
