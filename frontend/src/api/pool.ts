import { request } from './request'
import type { PoolCandidate, PoolMember } from '@/types'

export function listPoolMembers() {
  return request<PoolMember[]>({ method: 'GET', url: '/cursor/pool/members' })
}

export function listPoolCandidates() {
  return request<PoolCandidate[]>({
    method: 'GET',
    url: '/cursor/pool/candidates',
  })
}

export function addPoolMember(data: {
  account_id: number
  priority?: number
  max_daily_tokens?: number | null
}) {
  return request<PoolMember>({
    method: 'POST',
    url: '/cursor/pool/members',
    data,
  })
}

export function updatePoolMember(
  accountId: number,
  data: {
    enabled?: boolean
    priority?: number
    max_daily_tokens?: number | null
  },
) {
  return request<PoolMember>({
    method: 'PATCH',
    url: `/cursor/pool/members/${accountId}`,
    data,
  })
}

export function removePoolMember(accountId: number) {
  return request<void>({
    method: 'DELETE',
    url: `/cursor/pool/members/${accountId}`,
  })
}

export function batchPoolMembers(data: { account_ids: number[]; enabled: boolean }) {
  return request<{ count: number }>({
    method: 'POST',
    url: '/cursor/pool/members/batch',
    data,
  })
}

export function runAutoPoolPolicy() {
  return request<Record<string, unknown>>({
    method: 'POST',
    url: '/cursor/pool/auto-policy/run',
  })
}
