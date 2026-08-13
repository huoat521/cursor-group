"use strict";

const vscode = require("vscode");

/**
 * Sidebar Webview: login form, or status + 租号 / 归还.
 */
class LeasePanelProvider {
  /**
   * @param {vscode.ExtensionContext} context
   * @param {{
   *   getSnapshot: () => Promise<object>,
   *   login: (creds: {username: string, password: string, scope: string}) => Promise<void>,
   *   logout: () => Promise<void>,
   *   acquire: () => Promise<void>,
   *   release: () => Promise<void>,
   * }} actions
   */
  constructor(context, actions) {
    this._context = context;
    this._actions = actions;
    this._view = null;
  }

  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._context.extensionUri],
    };
    webviewView.webview.html = this._html();
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      try {
        switch (msg?.type) {
          case "ready":
          case "refresh":
            await this.refresh();
            break;
          case "login":
            if (msg.authMode === "token") {
              await this._actions.login({
                token: String(msg.token || "").trim(),
              });
            } else {
              await this._actions.login({
                username: String(msg.username || "").trim(),
                password: String(msg.password || ""),
                scope: msg.scope === "email" ? "email" : "username",
              });
            }
            await this.refresh();
            break;
          case "logout":
            await this._actions.logout();
            await this.refresh();
            break;
          case "acquire":
            await this._actions.acquire();
            await this.refresh();
            break;
          case "release":
            await this._actions.release();
            await this.refresh();
            break;
          default:
            break;
        }
      } catch (err) {
        const message = String(err?.message || err || "操作失败");
        try {
          const snap = await this._actions.getSnapshot();
          this._post({ type: "state", ...snap, error: message });
        } catch {
          this._post({ type: "error", message });
        }
      }
    });
    void this.refresh();
  }

  async refresh() {
    if (!this._view) return;
    try {
      const snap = await this._actions.getSnapshot();
      this._post({ type: "state", ...snap });
    } catch (err) {
      this._post({
        type: "state",
        loggedIn: false,
        error: String(err?.message || err),
      });
    }
  }

  _post(payload) {
    if (!this._view) return;
    void this._view.webview.postMessage(payload);
  }

  _html() {
    const nonce = String(Date.now());
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    :root { --gap: 10px; --radius: 6px; }
    html.vscode-dark, html.vscode-high-contrast { color-scheme: dark; }
    html.vscode-light { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 14px 12px 20px;
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: transparent;
    }
    h1 {
      margin: 0 0 4px;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.02em;
      opacity: 0.9;
    }
    .sub {
      margin: 0 0 14px;
      font-size: 11px;
      opacity: 0.65;
      line-height: 1.4;
    }
    label {
      display: block;
      margin: 0 0 4px;
      font-size: 11px;
      opacity: 0.75;
    }
    input, button {
      width: 100%;
      font: inherit;
      border-radius: var(--radius);
    }
    input {
      padding: 7px 9px;
      margin-bottom: var(--gap);
      border: 1px solid var(--vscode-input-border, transparent);
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      outline: none;
      color-scheme: inherit;
    }
    input:focus {
      border-color: var(--vscode-focusBorder);
    }
    .seg {
      display: flex;
      gap: 4px;
      margin: 0 0 12px;
      padding: 3px;
      border-radius: 8px;
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border, var(--vscode-widget-border, rgba(127,127,127,0.35)));
    }
    .seg-btn {
      flex: 1;
      width: auto;
      margin: 0;
      padding: 6px 8px;
      border: none;
      border-radius: 6px;
      background: transparent;
      color: var(--vscode-foreground);
      opacity: 0.72;
      cursor: pointer;
    }
    .seg-btn.active {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      opacity: 1;
    }
    .seg-btn:hover:not(.active) {
      background: var(--vscode-list-hoverBackground);
    }
    button {
      padding: 8px 10px;
      margin-top: 4px;
      border: none;
      cursor: pointer;
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }
    button:hover { background: var(--vscode-button-hoverBackground); }
    button:disabled {
      opacity: 0.55;
      cursor: default;
    }
    button.secondary {
      background: transparent;
      color: var(--vscode-foreground);
      border: 1px solid var(--vscode-widget-border, rgba(127,127,127,0.35));
    }
    button.secondary:hover {
      background: var(--vscode-list-hoverBackground);
    }
    button.danger {
      background: transparent;
      color: var(--vscode-errorForeground, #f14c4c);
      border: 1px solid color-mix(in srgb, var(--vscode-errorForeground, #f14c4c) 45%, transparent);
    }
    .row { display: flex; gap: 8px; margin-top: 8px; }
    .row button { flex: 1; }
    .card {
      padding: 12px;
      margin-bottom: 12px;
      border-radius: var(--radius);
      background: var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,0.12));
    }
    .status-line {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }
    .dot {
      width: 8px; height: 8px; border-radius: 50%;
      flex-shrink: 0;
      background: var(--vscode-descriptionForeground);
    }
    .dot.on { background: #3fb950; }
    .dot.warn { background: #d29922; }
    .meta { font-size: 12px; line-height: 1.55; opacity: 0.9; }
    .meta strong { font-weight: 600; opacity: 1; }
    .muted { opacity: 0.6; font-size: 11px; }
    .err {
      margin: 8px 0 0;
      padding: 8px;
      border-radius: var(--radius);
      font-size: 12px;
      line-height: 1.4;
      color: var(--vscode-errorForeground, #f14c4c);
      background: color-mix(in srgb, var(--vscode-errorForeground, #f14c4c) 12%, transparent);
    }
    .err-inline {
      display: block;
      margin-top: 6px;
      color: var(--vscode-errorForeground, #f14c4c);
      font-size: 12px;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .hidden { display: none !important; }
    .linkish {
      margin-top: 12px;
      padding: 0;
      width: auto;
      background: none;
      border: none;
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      font-size: 11px;
      text-align: left;
    }
    .linkish:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <h1>Cursor Group 号池</h1>
  <p class="sub" id="subtitle">用平台账号或 Access Token 登录后租用 Cursor</p>

  <div id="loginView" class="hidden">
    <label>登录方式</label>
    <div class="seg" id="authModeSeg" role="tablist">
      <button type="button" class="seg-btn active" data-mode="password">账号密码</button>
      <button type="button" class="seg-btn" data-mode="token">Access Token</button>
    </div>
    <div id="passwordFields">
      <label for="username">用户名 / 邮箱</label>
      <input id="username" type="text" autocomplete="username" spellcheck="false" />
      <label for="password">密码</label>
      <input id="password" type="password" autocomplete="current-password" />
    </div>
    <div id="tokenFields" class="hidden">
      <label for="token">Access Token / PAT</label>
      <input id="token" type="password" autocomplete="off" spellcheck="false" />
    </div>
    <button id="loginBtn" type="button">登录</button>
  </div>

  <div id="mainView" class="hidden">
    <div class="card">
      <div class="status-line">
        <span class="dot" id="dot"></span>
        <span id="statusTitle">—</span>
      </div>
      <div class="meta" id="statusMeta"></div>
    </div>
    <div class="row">
      <button id="acquireBtn" type="button">租号</button>
      <button id="releaseBtn" class="danger" type="button">归还</button>
    </div>
    <button id="logoutBtn" class="linkish" type="button">退出登录</button>
  </div>

  <div id="errorBox" class="err hidden"></div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const $ = (id) => document.getElementById(id);

    function showError(msg) {
      const box = $("errorBox");
      if (!msg) {
        box.classList.add("hidden");
        box.textContent = "";
        return;
      }
      box.textContent = msg;
      box.classList.remove("hidden");
    }

    function setBusy(busy) {
      ["loginBtn", "acquireBtn", "releaseBtn", "logoutBtn"].forEach((id) => {
        const el = $(id);
        if (el) el.disabled = !!busy;
      });
    }

    let authMode = "password";

    function syncAuthMode() {
      const tokenMode = authMode === "token";
      $("passwordFields").classList.toggle("hidden", tokenMode);
      $("tokenFields").classList.toggle("hidden", !tokenMode);
      document.querySelectorAll(".seg-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.getAttribute("data-mode") === authMode);
      });
    }

    $("authModeSeg").addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      authMode = btn.getAttribute("data-mode") || "password";
      syncAuthMode();
    });
    syncAuthMode();

    $("loginBtn").addEventListener("click", () => {
      showError("");
      setBusy(true);
      if (authMode === "token") {
        vscode.postMessage({
          type: "login",
          authMode: "token",
          token: $("token").value,
        });
      } else {
        vscode.postMessage({
          type: "login",
          authMode: "password",
          username: $("username").value,
          password: $("password").value,
          scope: "username",
        });
      }
    });

    $("token").addEventListener("keydown", (e) => {
      if (e.key === "Enter") $("loginBtn").click();
    });

    $("password").addEventListener("keydown", (e) => {
      if (e.key === "Enter") $("loginBtn").click();
    });
    $("username").addEventListener("keydown", (e) => {
      if (e.key === "Enter") $("password").focus();
    });

    $("acquireBtn").addEventListener("click", () => {
      showError("");
      setBusy(true);
      vscode.postMessage({ type: "acquire" });
    });
    $("releaseBtn").addEventListener("click", () => {
      showError("");
      setBusy(true);
      vscode.postMessage({ type: "release" });
    });
    $("logoutBtn").addEventListener("click", () => {
      showError("");
      setBusy(true);
      vscode.postMessage({ type: "logout" });
    });

    function render(state) {
      setBusy(false);
      if (state.error && !state.loggedIn) {
        showError(state.error);
      } else if (state.error) {
        showError(state.error);
      } else {
        showError("");
      }

      const loggedIn = !!state.loggedIn;
      $("loginView").classList.toggle("hidden", loggedIn);
      $("mainView").classList.toggle("hidden", !loggedIn);

      if (!loggedIn) {
        $("subtitle").textContent = "用平台账号或 Access Token 登录后租用 Cursor";
        return;
      }

      $("subtitle").textContent = state.userLabel
        ? "已登录 · " + state.userLabel
        : "已登录";

      const hasLease = !!state.hasLease;
      const dot = $("dot");
      dot.className = "dot " + (hasLease ? "on" : "warn");
      $("statusTitle").textContent = hasLease ? "租用中" : "未租号";

      const lines = [];
      if (hasLease) {
        if (state.accountId != null) {
          lines.push("<strong>账号 #" + escapeHtml(String(state.accountId)) + "</strong>");
        }
        if (state.cursorEmail) {
          lines.push(escapeHtml(state.cursorEmail));
        }
        if (state.remainingText) {
          lines.push('<span class="muted">剩余 ' + escapeHtml(state.remainingText) + "</span>");
        }
        if (state.expiresAt) {
          lines.push('<span class="muted">到期 ' + escapeHtml(state.expiresAt) + "</span>");
        }
      } else {
        if (state.gatewayEnabled === false) {
          lines.push('<span class="err-inline">号池租号未启用，请联系管理员</span>');
        } else {
          lines.push('<span class="muted">点击「租号」从号池获取并注入本机</span>');
        }
        if (state.lastReason) {
          lines.push(
            '<span class="err-inline">上次：' +
              escapeHtml(state.lastReason) +
              "</span>"
          );
        }
      }
      $("statusMeta").innerHTML = lines.join("<br/>");
      $("acquireBtn").disabled = hasLease || state.gatewayEnabled === false;
      $("releaseBtn").disabled = !hasLease;
    }

    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    window.addEventListener("message", (event) => {
      const msg = event.data || {};
      if (msg.type === "state") {
        render(msg);
      } else if (msg.type === "error") {
        setBusy(false);
        showError(msg.message || "操作失败");
      }
    });

    vscode.postMessage({ type: "ready" });
  </script>
</body>
</html>`;
  }
}

module.exports = { LeasePanelProvider };
