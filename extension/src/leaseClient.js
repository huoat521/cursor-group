"use strict";

const vscode = require("vscode");

const SECRET_SESSION = "cursorGroupLease.sessionToken";
const FETCH_TIMEOUT_MS = 15000;

const SERVER_NOT_CONFIGURED_MSG =
  "未配置服务器地址。请在设置中填写 cursorGroupLease.serverBaseUrl，或 serverHost 与 serverPort。";

function parseServerBase(url) {
  const raw = String(url || "").trim();
  if (!raw) {
    return null;
  }
  try {
    const withProto = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
    const u = new URL(withProto);
    const port = u.port
      ? Number(u.port)
      : u.protocol === "https:"
        ? 443
        : 80;
    return {
      host: u.hostname,
      port,
      protocol: (u.protocol || "http:").replace(":", "") || "http",
    };
  } catch {
    return null;
  }
}

function buildServerBaseUrl(host, port, protocol = "http") {
  const h = String(host || "").trim();
  const p = Number(port);
  if (!h || !p) {
    throw new Error(SERVER_NOT_CONFIGURED_MSG);
  }
  const proto = protocol === "https" ? "https" : "http";
  const defaultPort = proto === "https" ? 443 : 80;
  if (p === defaultPort) {
    return `${proto}://${h}`;
  }
  return `${proto}://${h}:${p}`;
}

async function getServerBaseUrl() {
  const cfg = vscode.workspace.getConfiguration("cursorGroupLease");
  const configured = String(cfg.get("serverBaseUrl") || "").trim();
  if (configured) {
    return configured.replace(/\/+$/, "");
  }
  const host = String(cfg.get("serverHost") || "").trim();
  const port = Number(cfg.get("serverPort") || 0);
  if (!host || !port) {
    throw new Error(SERVER_NOT_CONFIGURED_MSG);
  }
  return buildServerBaseUrl(host, port);
}

async function setServerBaseUrl(baseUrl) {
  const normalized = String(baseUrl || "").trim().replace(/\/+$/, "");
  if (!normalized) {
    throw new Error(SERVER_NOT_CONFIGURED_MSG);
  }
  const parsed = parseServerBase(normalized);
  if (!parsed || !parsed.host || !parsed.port) {
    throw new Error("无效的服务器地址");
  }
  const cfg = vscode.workspace.getConfiguration("cursorGroupLease");
  await cfg.update(
    "serverBaseUrl",
    buildServerBaseUrl(parsed.host, parsed.port, parsed.protocol),
    vscode.ConfigurationTarget.Global
  );
  await cfg.update("serverHost", parsed.host, vscode.ConfigurationTarget.Global);
  await cfg.update("serverPort", parsed.port, vscode.ConfigurationTarget.Global);
}

async function getLeaseApiBaseUrl() {
  const server = await getServerBaseUrl();
  return `${server}/api/cursor/proxy/v1`;
}

async function getSessionToken(context) {
  return (await context.secrets.get(SECRET_SESSION)) || "";
}

async function setSessionToken(context, token) {
  await context.secrets.store(SECRET_SESSION, String(token || "").trim());
}

async function clearSessionToken(context) {
  await context.secrets.delete(SECRET_SESSION);
}

async function getAuthToken(context) {
  const stored = await getSessionToken(context);
  if (stored) {
    return stored;
  }
  const cfg = vscode.workspace.getConfiguration("cursorGroupLease");
  return String(cfg.get("accessToken") || "").trim();
}

async function fetchWithTimeout(url, init = {}, timeoutMs = FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new Error(`请求超时（${Math.round(timeoutMs / 1000)}s）：${url}`);
    }
    const detail = String(err?.message || err || "unknown");
    throw new Error(`连接服务器失败（${detail}）：${url}`);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Store a platform Access Token / PAT and use it as Bearer auth (skip /lease/login).
 */
async function loginWithToken(context, token) {
  const trimmed = String(token || "").trim();
  if (!trimmed) {
    throw new Error("Access Token 不能为空");
  }
  await setSessionToken(context, trimmed);
  return { token: trimmed };
}

/**
 * Login with username/password → platform JWT via /lease/login.
 */
async function login(context, creds) {
  const base = await getLeaseApiBaseUrl();
  const scope = creds.scope === "email" ? "email" : "username";
  const resp = await fetchWithTimeout(`${base}/lease/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      username: String(creds.username || "").trim(),
      password: String(creds.password || ""),
      scope,
    }),
  });
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!resp.ok) {
    const msg =
      (data && data.error && (data.error.message || data.error.code)) ||
      (data && (data.msg || data.detail || data.message)) ||
      text ||
      `HTTP ${resp.status}`;
    throw new Error(String(msg));
  }
  const token =
    (data && data.access_token) ||
    (data && data.data && data.data.access_token) ||
    "";
  if (!token) {
    throw new Error("登录成功但未返回 access_token");
  }
  await setSessionToken(context, token);
  return {
    token,
    username: data?.username || data?.data?.username,
    email: data?.current_user || data?.data?.current_user,
    user_id: data?.id || data?.data?.id,
  };
}

async function logout(context) {
  await clearSessionToken(context);
}

async function requestJson(context, method, path, body) {
  const base = await getLeaseApiBaseUrl();
  const token = await getAuthToken(context);
  if (!token) {
    throw new Error("未登录。请先运行「Cursor Group Lease: 登录」或设置 accessToken");
  }
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/json",
  };
  const init = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const resp = await fetchWithTimeout(url, init);
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!resp.ok) {
    const msg =
      (data && data.error && (data.error.message || data.error.code)) ||
      (data && (data.msg || data.detail || data.message)) ||
      text ||
      `HTTP ${resp.status}`;
    const err = new Error(String(msg));
    err.status = resp.status;
    err.code =
      (data && data.error && (data.error.code || data.error.type)) ||
      undefined;
    err.payload = data;
    throw err;
  }
  return data;
}

async function acquireLease(context, options = {}) {
  return requestJson(context, "POST", "/lease/acquire", {
    reason: options.reason || "manual",
    force_rotate: Boolean(options.forceRotate),
    exclude_account_ids: options.excludeAccountIds || [],
    client_version: vscode.version,
    client_os: process.platform,
  });
}

async function rotateLease(context, options = {}) {
  return requestJson(context, "POST", "/lease/rotate", {
    reason: options.reason || "rotate",
    exclude_account_ids: options.excludeAccountIds || [],
    client_version: vscode.version,
    client_os: process.platform,
  });
}

async function releaseLease(context) {
  return requestJson(context, "POST", "/lease/release", {});
}

async function renewLease(context) {
  return requestJson(context, "POST", "/lease/renew", {});
}

async function leaseStatus(context) {
  return requestJson(context, "GET", "/lease/status");
}

module.exports = {
  SECRET_SESSION,
  SERVER_NOT_CONFIGURED_MSG,
  FETCH_TIMEOUT_MS,
  parseServerBase,
  buildServerBaseUrl,
  getServerBaseUrl,
  setServerBaseUrl,
  getLeaseApiBaseUrl,
  getGatewayBaseUrl: getLeaseApiBaseUrl,
  getSessionToken,
  setSessionToken,
  clearSessionToken,
  getAuthToken,
  loginWithToken,
  login,
  logout,
  acquireLease,
  rotateLease,
  releaseLease,
  renewLease,
  leaseStatus,
};
