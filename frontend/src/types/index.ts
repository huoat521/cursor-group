/** API response envelope */
export interface ApiResponse<T = unknown> {
  status: number
  msg: string
  data: T
  errors?: unknown
}

export interface User {
  id: number
  username?: string
  email?: string
  full_name?: string
  role?: string
  is_superuser?: boolean
  is_active?: boolean
}

export interface LoginResult {
  access_token: string
  token_type?: string
}

export interface AuthSettings {
  oidc_enabled?: boolean
  ldap_enabled?: boolean
  local_enabled?: boolean
  local_auth_enabled?: boolean
  auto_provision?: boolean
  auto_provision_role?: string
  oidc_provider?: string
}

export interface CursorAccount {
  id?: number
  cursor_email?: string
  membership_type?: string
  subscription_status?: string
  bind_status?: number
  last_sync_at?: string
  last_sync_text?: string
  last_error?: string
  usage_raw?: Record<string, unknown>
  cycle_total_tokens?: number
  cycle_tokens_text?: string
  calendar_total_tokens?: number
  calendar_tokens_text?: string
  calendar_month?: string
  billing_cycle_text?: string
  usage_total?: number
  usage_auto?: number
  usage_api?: number
  plan_used?: number
  plan_limit?: number
  plan_remaining?: number
}

export interface OAuthStart {
  login_id: string
  verification_uri: string
  expires_in: number
  interval_seconds: number
}

export interface OAuthPoll {
  status: string
  account?: CursorAccount
  message?: string
}

export interface LeaseStatus {
  has_lease: boolean
  lease_id?: string
  account_id?: number
  cursor_email?: string
  sticky_remaining_seconds?: number
  expires_at?: string
  gateway_enabled?: boolean
  reclaim_local?: boolean
  reclaim_reason?: string
}

export interface AdminAccount extends CursorAccount {
  user_id?: number
  username?: string
  full_name?: string
  is_abnormal?: boolean
  usage_level?: string
}

export interface DashboardData {
  summary?: Record<string, unknown>
  usage_distribution?: Array<Record<string, unknown>>
  membership_stats?: Array<Record<string, unknown>>
  rankings?: Array<Record<string, unknown>>
  month_usage_rankings?: Array<Record<string, unknown>>
  token_rankings?: Array<Record<string, unknown>>
  daily_team_trend?: Array<Record<string, unknown>>
  daily_summary?: Record<string, unknown>
}

export interface PoolMember {
  id: number
  account_id: number
  enabled: boolean
  priority: number
  max_daily_tokens?: number | null
  circuit_fail_count?: number
  circuit_open_until?: string | null
  source?: string
  user_id?: number | null
  full_name?: string | null
  username?: string | null
  cursor_email?: string | null
  membership_type?: string | null
  bind_status?: number | null
  plan_remaining?: number | null
  plan_limit?: number | null
  usage_total?: number | null
  billing_cycle_text?: string | null
  cycle_remaining_days?: number | null
}

export interface PoolCandidate {
  account_id: number
  full_name?: string
  cursor_email?: string
  membership_type?: string
}

export interface ProxyConfig {
  gateway_enabled?: boolean
  scheduler_strategy?: string
  lease_expiry_mode?: string
  lease_min_renter_usage_percent?: number
  lease_max_concurrent_pro?: number
  lease_max_concurrent_pro_plus?: number
  lease_max_concurrent_ultra?: number
  auto_pool_enabled?: boolean
  auto_pool_join_rules?: Array<{ remaining_days: number; remaining_usage_percent: number }>
  auto_pool_remove_on_cycle_refresh?: boolean
  max_retries?: number
  rate_limit_per_user_rpm?: number
  allowed_models?: string[]
  exclude_self_account?: boolean
  circuit_fail_threshold?: number
  alert_enabled?: boolean
  alert_usage_threshold?: number
  peak_hours_start?: number
  peak_hours_end?: number
}

export interface ActiveLease {
  user_id?: number
  username?: string
  full_name?: string
  account_id?: number
  cursor_email?: string
  lease_id?: string
  sticky_remaining_seconds?: number
  expires_at?: string
}

export interface CreateUserPayload {
  username: string
  password: string
  email?: string
  full_name?: string
  role?: string
  is_active?: boolean
}

export interface PersonalAccessToken {
  token: string
  name?: string
  expires_at?: string
}
