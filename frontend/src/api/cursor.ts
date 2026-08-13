import { request } from './request'
import type {
  AdminAccount,
  CursorAccount,
  DashboardData,
  OAuthPoll,
  OAuthStart,
} from '@/types'

export function oauthStart() {
  return request<OAuthStart>({ method: 'POST', url: '/cursor/oauth/start' })
}

export function oauthPoll(loginId: string) {
  return request<OAuthPoll>({
    method: 'GET',
    url: '/cursor/oauth/poll',
    params: { login_id: loginId },
  })
}

export function oauthCancel(loginId: string) {
  return request<void>({
    method: 'DELETE',
    url: '/cursor/oauth/cancel',
    params: { login_id: loginId },
  })
}

export function getMyAccount() {
  return request<CursorAccount | null>({ method: 'GET', url: '/cursor/my' })
}

export function unbindMy() {
  return request<void>({ method: 'DELETE', url: '/cursor/my' })
}

export function syncMy() {
  return request<CursorAccount>({ method: 'POST', url: '/cursor/my/sync' })
}

export function getDashboard(params?: {
  calendar_month?: string
}) {
  return request<DashboardData>({
    method: 'GET',
    url: '/cursor/admin/dashboard',
    params,
  })
}

export function listAccounts() {
  return request<AdminAccount[]>({
    method: 'GET',
    url: '/cursor/admin/accounts',
  })
}

export function listAbnormal() {
  return request<AdminAccount[]>({
    method: 'GET',
    url: '/cursor/admin/abnormal',
  })
}

export function syncAccount(accountId: number) {
  return request<AdminAccount>({
    method: 'POST',
    url: `/cursor/admin/sync/${accountId}`,
  })
}
