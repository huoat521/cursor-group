# Cursor Group

自托管的 Cursor **团队用量看板** + **号池租号** 平台。

团队给全员开通 Cursor 之后，额度很少按人头均匀消耗：有人周期还没过完就已经打满，有人整月几乎不动。各自锁在自己的账号里，闲着的额度帮不上忙，忙的人只能干等刷新或再买一份。

这套系统把已开通的账号收进号池，按剩余用量和计费周期租给正在写代码的人，让额度在团队内部周转，而不是按账号闲置。

日常用法：员工在管理台用 OAuth 绑定自己的 Cursor 账号，管理员决定谁入池；要用时，成员在本机 Cursor 里打开扩展、登录平台、点一次租号，扩展把登录态写进 IDE 并重启，之后按平时那样写代码。用完可归还，租约到期或管理员回收后，号回到池里给下一个人。管理台同时给出用量与异常一览。支持本地账号、LDAP、OIDC 与 PAT，适合在受控团队环境内部署。

许可证：[Apache-2.0](LICENSE)。

## 功能

- **账号绑定**：员工完成 Cursor OAuth，token 加密入库，定时同步用量与计费周期
- **用量看板**：会员类型分布、配额分布、团队日趋势、用量排行；异常账号一览
- **号池**：手工入池或按「周期剩余天数 + 剩余用量」自动入池；可设优先级与每号并发
- **租约**：默认开启网关、临期优先调度、按计费周期过期；支持强制回收
- **扩展**：侧栏登录 / PAT → 租号 → 写入本机登录态并重启 Cursor
- **告警**：可选 Webhook（飞书 / Slack / 任意 URL）

本项目**不提供**模型中继或第三方 API 网关，只做用量与租号。

## 架构

```text
管理台 (Vue 3 + Element Plus)
  │  JWT / PAT
  ▼
FastAPI
  ├─ /api/auth/*               登录、OIDC、PAT、用户管理
  ├─ /api/cursor/*             绑定、用量、看板、号池、租约管理
  └─ /api/cursor/proxy/v1      扩展租号 API
        │
        ├─ MySQL    用户、账号、号池、租约配置
        ├─ Redis    OAuth 会话、活跃租约
        └─ Celery   用量同步、租约回收、清理、告警
```

更细的模块说明见 [docs/architecture.md](docs/architecture.md)，部署细节见 [docs/deploy.md](docs/deploy.md)。

## 环境要求

- Python 3.11+
- Node.js 20+（构建前端与扩展）
- MySQL 8、Redis 7
- Docker Compose（可选，一键部署）



## 快速开始（Docker）

```bash
cp .env.example .env
# 必须改掉 SECRET_KEY、CURSOR_TOKEN_ENCRYPT_KEY、BOOTSTRAP_ADMIN_PASSWORD、MYSQL_* 示例值

cd frontend && npm install && npm run build && cd ..
cd extension && npm install && npm run package   # 可选，生成租号扩展
cd ..

docker compose up -d --build
```


| 入口       | 地址                                                                   |
| -------- | -------------------------------------------------------------------- |
| 管理台      | [http://127.0.0.1:5173](http://127.0.0.1:5173)                       |
| API 健康检查 | [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health) |
| 管理员      | `.env` 中的 `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD`    |


启动时会拒绝过短/示例密钥，以及弱密码 `admin123`。Compose 里的 Redis **不映射**到宿主机 6379，避免和本机 Redis 冲突。

## 本地开发

```bash
# 只起数据库（也可使用已有 MySQL / Redis，改 .env 连接串）
docker compose up -d mysql redis

cp .env.example .env
# 本地直连 Compose MySQL 时，ASYNC_MYSQL_URI 端口为 3307

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source ../.env && set +a
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000

# 另开终端：定时任务
cd backend && source .venv/bin/activate
set -a && source ../.env && set +a
PYTHONPATH=. celery -A app.celery_app.celery_app worker -l info
PYTHONPATH=. celery -A app.celery_app.celery_app beat -l info

# 再开终端：管理台（默认 5173；被占用时加 --port 5175）
cd frontend && npm install && npm run dev -- --host 0.0.0.0 --port 5175
```

首次启动会跑 Alembic 建表并创建管理员。本机若开了 `http_proxy`，访问 `127.0.0.1` 请设 `NO_PROXY=*`。

局域网访问时：

- 管理台：`http://<服务器IP>:5175`（开发）或 `:5173`（Compose nginx）
- 扩展必须指向 **API 端口 8000**，不是管理台端口
- 若局域网打不开，检查防火墙是否放行 `5175/tcp`、`8000/tcp`



## 配置

复制 `.env.example` 为 `.env`。常用项：


| 变量                         | 说明                                               |
| -------------------------- | ------------------------------------------------ |
| `SECRET_KEY`               | JWT 签名密钥，≥32 位                                   |
| `CURSOR_TOKEN_ENCRYPT_KEY` | 账号 token 加密密钥，≥16 位                              |
| `CURSOR_OAUTH_CLIENT_ID`   | Cursor OAuth Client ID（需自行准备并遵守 Cursor 条款）       |
| `BOOTSTRAP_ADMIN_*`        | 空库时创建的首位管理员                                      |
| `AUTH_LOCAL_ENABLED`       | 本地用户名/邮箱 + 密码                                    |
| `AUTH_LDAP_ENABLED`        | 表单密码走 LDAP bind                                  |
| `AUTH_OIDC_ENABLED`        | OIDC；回调发一次性 `oidc_code`，前端再换 JWT                 |
| `AUTH_AUTO_PROVISION`      | 默认 `false`；开启后只自动创建 `member`，按 IdP `sub` / DN 关联 |
| `WEBHOOK_ALERT_URL`        | 号池 / 异常告警回调                                      |
| `CORS_ORIGINS`             | 管理台来源，逗号分隔                                       |
| `ASYNC_MYSQL_URI`          | MySQL（async）；Compose 宿主机端口为 **3307**             |


完整列表见 `.env.example`。Celery 默认：用量同步每 2 小时；租约回收每小时 :20；清理 03:30；号池告警 9/14/18 点；绑定巡检 04:10。

## 租号扩展

目录 `extension/`，包名 `cursor-group-lease`。详细说明见 [extension/readme.md](extension/readme.md)。

1. `cd extension && npm install && npm run package`
2. Cursor / VS Code：**Install from VSIX**（或从管理台「我的 Cursor」下载，页面会显示当前版本如 0.1.1）
3. **先配置网关地址**（扩展不内置任何 IP/域名）
4. 用平台用户名/邮箱 + 密码登录，或填写 PAT



### 如何连接网关

扩展用 HTTP(S) 访问 **FastAPI**（默认 `8000`），不要填管理台地址。

在 Cursor 设置中搜索 **Cursor Group Lease**，或编辑用户 `settings.json`：

1. 优先 `cursorGroupLease.serverBaseUrl`（完整 URL）
2. 否则 `cursorGroupLease.serverHost` + `cursorGroupLease.serverPort`
3. 都为空：登录/租号报「未配置服务器地址」

请求发到 `{serverBaseUrl}/api/cursor/proxy/v1/...`。


| 场景         | `serverBaseUrl`             | 实际请求                                                      |
| ---------- | --------------------------- | --------------------------------------------------------- |
| 本机         | `http://127.0.0.1:8000`     | `http://127.0.0.1:8000/api/cursor/proxy/v1/lease/acquire` |
| 局域网        | `http://192.168.1.10:8000`  | 主机换成该 IP                                                  |
| HTTPS / 反代 | `https://lease.example.com` | `https://lease.example.com/api/cursor/proxy/v1/...`       |


也可拆开写 `serverHost` + `serverPort`。改完设置立刻生效，不必重装。侧栏登录框不会改这个地址。

租约接口（除 `/lease/login` 外均带 `Authorization: Bearer`）：

- `POST /lease/login` 登录
- `POST /lease/acquire` 租号
- `GET /lease/status` 状态
- `POST /lease/renew` 续期
- `POST /lease/release` 归还
- `POST /lease/rotate` 换号



### 租号过程

从开通到日常使用，按这个顺序走即可。

1. **管理员准备平台**
  部署后创建用户（或打开 LDAP / OIDC），在「租约配置」里确认网关已开，并选好调度（默认临期优先）和过期方式（默认跟号的计费周期走）。
2. **全员绑定自己的号**
  每人打开「我的 Cursor」，用 Cursor OAuth 绑定个人账号。平台会定时同步用量和计费周期；管理员可在看板和账号列表里看到余量、会员类型和异常号。
3. **把有余量的号放进号池**
  管理员在「号池管理」里手工入池，或按「周期还剩几天 + 还剩多少用量」自动入池。可以设优先级、每号允许多少人同时租。没入池的号只给本人看用量，不会被租走。
4. **成员安装扩展并连上网关**
  从「我的 Cursor」下载 VSIX（或按上面步骤本地打包），在本机 Cursor 里安装。先在设置里填 API 地址，再用平台用户名/邮箱 + 密码登录侧栏，或填 PAT。扩展不连管理台页面。
5. **租号**
  必须在**本机 Cursor 窗口**操作（Remote-SSH 窗口写不进本机登录态）。点租号后，网关按策略挑一个号：你已有未过期的租约就继续用原来的号，否则按临期优先或剩余用量优先选新号。扩展写入本机登录态并重启 Cursor，重启后即可当普通 Cursor 使用。
6. **写代码、续期、换号、归还**
  侧栏可看当前租约状态。需要延长时点续期；当前号额度不够或异常时点换号（会再重启一次）。当天活干完可以归还，号回到池里。计费周期结束、租约过期，或管理员在「活跃租约」里强制回收，效果相同：本机这份登录会失效，号重新可被别人租。

仅「租号 / 换号」会重启 Cursor；登录扩展、看状态、续期、归还不会。同一个租约有效期内反复打开 Cursor，不必重新租。

## 默认租约策略

未保存过配置时：


| 项    | 默认                         |
| ---- | -------------------------- |
| 启用网关 | 开                          |
| 调度   | 临期优先（周期剩余天数少的先租）           |
| 过期模式 | 计费周期（号池号或租用人自有号周期结束/刷新则回收） |
| 每号并发 | 0 = 不限制                    |
| 自动号池 | 关                          |


也可改为「剩余用量优先」。租约仍有效时跟同一号；过期后按策略重新选号。

## 管理台页面


| 页面          | 谁能看 | 做什么                       |
| ----------- | --- | ------------------------- |
| 我的 Cursor   | 全员  | 绑定/解绑、用量、租约状态、下载扩展、生成 PAT |
| 用量仪表盘       | 管理员 | 汇总与图表                     |
| 账号列表 / 异常账号 | 管理员 | 同步与排错                     |
| 号池管理        | 管理员 | 入池、启停、自动策略                |
| 租约配置        | 管理员 | 网关、调度、并发                  |
| 活跃租约        | 管理员 | 查看与强制释放                   |
| 用户管理 / 认证设置 | 管理员 | 建用户、查看 SSO 开关             |




## 安全

- 账号 token 使用 AES-GCM 加密存储；启动时拒绝默认/过短密钥
- 空库拒绝弱管理员密码
- 租号会把号池账号的登录态下发到授权客户端的本机 IDE；归还或回收后该登录会失效
- 请仅在受控团队环境自托管，并自行评估与 Cursor 服务条款的合规风险



## 目录结构

```text
backend/     FastAPI + Celery + Alembic
frontend/    Vue 3 管理台
extension/   租号扩展（cursor-group-lease）
deploy/      Compose 用 nginx 配置
docs/        架构与部署补充
```

常用命令见根目录 `Makefile`：`make build-frontend`、`make build-extension`、`make up`。

## 贡献

Issue 与 PR 欢迎。请勿提交 `.env`、真实密钥、`.vsix` 二进制或本地 `node_modules` / `.venv`。改后端后需能通过启动时的 Alembic 迁移；改扩展后请升 `extension/package.json` 的 version 并重新 `npm run package`。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。

Cursor 是 Anysphere 的产品；本项目与 Anysphere / Cursor 官方无附属关系。
