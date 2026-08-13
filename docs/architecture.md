# 架构

```text
管理台 (Vue 3 + Element Plus + Pinia)
  │  JWT / PAT
  ▼
FastAPI
  ├─ /api/auth/*               本地 / LDAP / OIDC / PAT / 用户管理
  ├─ /api/cursor/*             绑定、用量、看板、号池、租约管理
  ├─ /api/extension            当前可下载的扩展版本
  └─ /api/cursor/proxy/v1      扩展租号 API
        │
        ├─ MySQL   users、cursor_*、号池、proxy_config
        ├─ Redis   OAuth session、lease key、revoke meta
        └─ Celery  同步 / 回收 / 清理 / 告警
              │
              └─ Webhook（可选）
```

## 职责划分

| 部分 | 职责 |
|---|---|
| `backend/app/api/auth` | 登录、OIDC 一次性码、PAT、用户 CRUD |
| `backend/app/api/cursor` | OAuth 绑定、用量同步、看板、号池 |
| `backend/app/api/cursor/proxy` | 租约 acquire / renew / release、调度、Redis 租约状态 |
| `frontend` | 管理台 SPA；开发时 Vite 把 `/api`、`/downloads` 代理到 `:8000` |
| `extension` | 登录网关、租号、注入本机 Cursor `state.vscdb` |

## 租约状态

活跃租约存在 Redis，TTL 对齐过期模式（默认计费周期结束日次日 0 点；周期未知则最多 7 天）。过期后 `release` 会吊销当时记下的 Cursor session；该号没有其他租用人时再轮换号池 OAuth。

扩展注入的 `refreshToken` 是伪 JWT，不能换新的 access token。
