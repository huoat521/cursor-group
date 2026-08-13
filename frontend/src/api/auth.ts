import { request } from './request'
import type {
  AuthSettings,
  CreateUserPayload,
  LoginResult,
  PersonalAccessToken,
  User,
} from '@/types'

export function login(username: string, password: string) {
  return request<LoginResult>({
    method: 'POST',
    url: '/auth/login',
    data: { username, password },
  })
}

export function getMe() {
  return request<User>({ method: 'GET', url: '/auth/me' })
}

export function getAuthSettings() {
  return request<AuthSettings>({ method: 'GET', url: '/auth/settings' })
}

export function oidcLoginUrl(): string {
  return '/api/auth/oidc/login'
}

export function exchangeOidc(code: string) {
  return request<LoginResult>({
    method: 'POST',
    url: '/auth/oidc/exchange',
    data: { code },
  })
}

export function createPat(data: { name?: string; expires_days?: number }) {
  return request<PersonalAccessToken>({
    method: 'POST',
    url: '/auth/pat',
    data,
  })
}

export function listUsers() {
  return request<User[]>({ method: 'GET', url: '/auth/users' })
}

export function createUser(data: CreateUserPayload) {
  return request<User>({ method: 'POST', url: '/auth/users', data })
}

export function updateUser(id: number, data: Partial<CreateUserPayload>) {
  return request<User>({ method: 'PUT', url: `/auth/users/${id}`, data })
}

export function deleteUser(id: number) {
  return request<void>({ method: 'DELETE', url: `/auth/users/${id}` })
}
