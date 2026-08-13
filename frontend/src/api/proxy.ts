import { request } from './request'
import type { ActiveLease, LeaseStatus, ProxyConfig } from '@/types'

export function getLeaseStatus() {
  return request<LeaseStatus>({
    method: 'GET',
    url: '/cursor/proxy/lease/status',
  })
}

export function getProxyConfig() {
  return request<ProxyConfig>({ method: 'GET', url: '/cursor/proxy/config' })
}

export function updateProxyConfig(data: ProxyConfig) {
  return request<ProxyConfig>({
    method: 'PUT',
    url: '/cursor/proxy/config',
    data,
  })
}

export function listActiveLeases() {
  return request<ActiveLease[]>({
    method: 'GET',
    url: '/cursor/proxy/lease/active',
  })
}

export function forceReleaseLease(userId: number) {
  return request<LeaseStatus>({
    method: 'POST',
    url: `/cursor/proxy/lease/release/${userId}`,
  })
}

export function releaseMyLease() {
  return request<LeaseStatus>({
    method: 'POST',
    url: '/cursor/proxy/lease/release',
  })
}

export function renewMyLease() {
  return request<LeaseStatus>({
    method: 'POST',
    url: '/cursor/proxy/lease/renew',
  })
}

export function acquireMyLease() {
  return request<Record<string, unknown>>({
    method: 'POST',
    url: '/cursor/proxy/lease/acquire',
    data: {},
  })
}
