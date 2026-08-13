# Cursor Group Lease Extension

从本仓库的号池租用 Cursor 账号，并把 OAuth token 注入本机 Cursor 登录态。总览见根目录 [README.md](../README.md)。

## 用法

1. 安装扩展后，**必须先配置网关地址**（扩展不内置任何 IP/域名）：
   - `cursorGroupLease.serverBaseUrl`（推荐，完整 URL），或
   - `cursorGroupLease.serverHost` + `cursorGroupLease.serverPort`
2. 打开左侧 **Group Lease** 面板登录：
   - **账号密码**：用户名 / 邮箱 + 密码
   - **Access Token / PAT**：直接粘贴平台 token（也可在设置 `cursorGroupLease.accessToken` 中预填）
3. 点击 **租号** 注入本机；用完后点 **归还**。

面板会显示当前租约状态（账号、邮箱、剩余时间）。侧栏登录框不会修改服务器地址。

## 如何连接网关

扩展用 HTTP(S) 访问 **FastAPI 网关**（默认端口 `8000`），不要填管理台前端地址（Docker 下常见 `5173`，本地 Vite 可能是 `5175`）。

在 Cursor 设置中搜索 **Cursor Group Lease**，或编辑用户 `settings.json`。解析顺序：

1. `cursorGroupLease.serverBaseUrl`（完整 URL，优先）
2. 否则 `cursorGroupLease.serverHost` + `cursorGroupLease.serverPort`（主机名或 IP + 端口）
3. 都为空：登录/租号报「未配置服务器地址」

实际请求：`{serverBaseUrl}/api/cursor/proxy/v1/<接口>`。

```json
{
  "cursorGroupLease.serverBaseUrl": "http://127.0.0.1:8000"
}
```

局域网示例：`"cursorGroupLease.serverBaseUrl": "http://172.30.111.241:8000"`。  
HTTPS / 域名 / 反代：填对外可达的完整 origin 即可，例如 `"https://lease.example.com"`。

改完设置立刻生效，不必重装扩展。

## 开发 / 打包

```bash
cd extension
npm install
npm run package
```

生成的 `.vsix` 可通过 Cursor / VS Code「从 VSIX 安装扩展」安装。

## 配置项

| 键 | 说明 |
|---|---|
| `cursorGroupLease.serverBaseUrl` | 网关完整 URL（优先）。指向 API，例如 `http://127.0.0.1:8000` |
| `cursorGroupLease.serverHost` | 主机名或 IP（`serverBaseUrl` 为空时与 port 一起用） |
| `cursorGroupLease.serverPort` | 端口（0 表示未设置） |
| `cursorGroupLease.accessToken` | 平台 PAT；设置后跳过密码登录 |
| `cursorGroupLease.autoAcquireOnStartup` | 启动时自动租号（需已登录） |

## API

扩展调用以下 lease 端点（相对 `{serverBaseUrl}/api/cursor/proxy/v1`）：

- `POST /lease/login` — 用户名密码登录（Bearer token 登录时跳过）
- `POST /lease/acquire` — 租号
- `GET /lease/status` — 状态
- `POST /lease/release` — 归还
- `POST /lease/renew` — 续期
- `POST /lease/rotate` — 换号

除 `/lease/login` 外，其余请求均携带 `Authorization: Bearer <token>`。

## 注意

- 注入会改本机 Cursor 登录态；操作前会备份 `state.vscdb`。
- 租号需在本机 Cursor 窗口执行（Remote-SSH 窗口无法写本机登录库）。
- **仅「租号 / 换号」会重启 Cursor**（写入登录态后自动重新打开）。「归还」「退出登录」、到期回收默认不重启；归还可选「归还并重启」。
- 注入的 `refreshToken` 是 **decoy（伪 RT）**：形态像 Cursor JWT，满足 IDE「已登录」校验，但无法向 Cursor 换新 access token。真实号池 RT 不会下发到 IDE。

## License

Apache-2.0，见仓库根目录 [LICENSE](../LICENSE)。
