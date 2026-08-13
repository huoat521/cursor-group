"use strict";

const vscode = require("vscode");
const leaseClient = require("./leaseClient");
const authInject = require("./authInject");
const { LeasePanelProvider } = require("./panel");

/** @type {vscode.StatusBarItem} */
let statusBar;
/** @type {vscode.ExtensionContext} */
let extContext;
/** @type {NodeJS.Timeout | null} */
let reclaimTimer = null;
/** @type {NodeJS.Timeout | null} */
let renewTimer = null;
/** @type {string | null} */
let activeLeaseId = null;
/** @type {LeasePanelProvider | null} */
let panelProvider = null;
/** Cached display label after login */
let cachedUserLabel = "";
/** Skip deactivate teardown while quitting for inject/clear switch. */
let suppressDeactivateTeardown = false;

const STATE_LEASE_EXPIRES_AT = "cursorGroupLease.expiresAt";
const STATE_LEASE_ID = "cursorGroupLease.leaseId";
const STATE_USER_LABEL = "cursorGroupLease.userLabel";
const STATE_LAST_REASON = "cursorGroupLease.lastReason";
const STATE_PENDING_SWITCH = "cursorGroupLease.pendingSwitch";
const STATE_PREV_CONFIRM_CLOSE = "cursorGroupLease.prevConfirmBeforeClose";

function setStatus(text, tooltip) {
  if (!statusBar) return;
  statusBar.text = text;
  statusBar.tooltip = tooltip || text;
  statusBar.show();
}

function clearTimers() {
  if (reclaimTimer) {
    clearTimeout(reclaimTimer);
    reclaimTimer = null;
  }
  if (renewTimer) {
    clearInterval(renewTimer);
    renewTimer = null;
  }
}

async function persistLeaseMeta(lease) {
  const expiresAt = lease?.expires_at || null;
  const leaseId = lease?.lease_id || null;
  await extContext.globalState.update(STATE_LEASE_EXPIRES_AT, expiresAt);
  await extContext.globalState.update(STATE_LEASE_ID, leaseId);
  activeLeaseId = leaseId;
}

async function clearLeaseMeta() {
  await extContext.globalState.update(STATE_LEASE_EXPIRES_AT, undefined);
  await extContext.globalState.update(STATE_LEASE_ID, undefined);
  activeLeaseId = null;
}

async function beginPendingSwitch() {
  suppressDeactivateTeardown = true;
  if (extContext) {
    await extContext.globalState.update(STATE_PENDING_SWITCH, true);
  }
}

async function clearPendingSwitch() {
  suppressDeactivateTeardown = false;
  if (extContext) {
    await extContext.globalState.update(STATE_PENDING_SWITCH, undefined);
  }
}

function localLeaseExpired() {
  const expiresAt = extContext?.globalState?.get?.(STATE_LEASE_EXPIRES_AT);
  if (!expiresAt) return false;
  const ms = Date.parse(String(expiresAt));
  return !Number.isNaN(ms) && ms <= Date.now();
}

/**
 * Soft-clear local Cursor auth without quitting.
 * Enough after server revoke: AT is already dead; UI may still show old email
 * until next 租号 restart.
 */
async function softClearLocalAuth() {
  try {
    return await authInject.clearCursorAuthSoft();
  } catch {
    return { cleared: false, verified: false, dbPath: null };
  }
}

/**
 * Hard path: quit Cursor → clear state.vscdb → relaunch.
 * Only needed when we must reliably switch/remove the in-memory login identity.
 */
async function hardRestartClearAuth(message) {
  const dbPath = authInject.findStateDb();
  if (!dbPath) {
    vscode.window.showWarningMessage(
      `${message || "需要清除登录态"}，但未找到 state.vscdb，请手动退出 Cursor 登录。`
    );
    return false;
  }
  try {
    await authInject.clearCursorAuth();
  } catch {
    // post-quit script is authoritative
  }
  const post = authInject.schedulePostQuitClear(dbPath, {
    relaunch: true,
    waitSeconds: 120,
    forceKill: true,
    appRoot: vscode.env.appRoot,
  });
  if (!post.scheduled) {
    vscode.window.showWarningMessage(
      `${message || "需要清除登录态"}。无法启动后台清登录脚本（需 Python3），请手动退出 Cursor 登录。`
    );
    return false;
  }
  const booted = await authInject.waitForWorkerBoot(post.bootLogPath);
  if (!booted) {
    vscode.window.showErrorMessage(
      "后台重启脚本未能启动。请确认已安装 Python，并查看 %TEMP%\\cgl-lease-launch-*.boot.log"
    );
    return false;
  }
  if (message) {
    vscode.window.showInformationMessage(message);
  }
  await beginPendingSwitch();
  await quitCursorForSwitch();
  return true;
}

/**
 * Disable confirm-before-close so quit isn't stuck on a dialog; external
 * script will taskkill if quit still doesn't happen.
 */
async function quitCursorForSwitch() {
  try {
    const conf = vscode.workspace.getConfiguration("window");
    const prev = conf.get("confirmBeforeClose");
    if (extContext && prev != null && prev !== "never") {
      await extContext.globalState.update(STATE_PREV_CONFIRM_CLOSE, prev);
    }
    await conf.update(
      "confirmBeforeClose",
      "never",
      vscode.ConfigurationTarget.Global
    );
  } catch {
    // ignore
  }
  await new Promise((r) => setTimeout(r, 400));
  try {
    await vscode.commands.executeCommand("workbench.action.quit");
  } catch {
    // ignore — worker force-kills Cursor.exe
  }
}

/**
 * Clear local injection without talking to the server.
 * Used when offline / server unreachable but sticky deadline already passed.
 */
async function reclaimLocalOffline(reason) {
  clearTimers();
  await clearLeaseMeta();
  setStatus("$(key) Group Lease", reason || "本地租约已到期");
  void panelProvider?.refresh();
  await softClearLocalAuth();
  vscode.window.showWarningMessage(reason || "本地租约已到期");
}

function formatRemaining(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分钟`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h} 小时 ${rm} 分` : `${h} 小时`;
}

async function rememberLastReason(reason) {
  if (!extContext) return;
  const text = String(reason || "").trim();
  await extContext.globalState.update(
    STATE_LAST_REASON,
    text || undefined
  );
}

async function reclaimLocal(reason) {
  clearTimers();
  await clearLeaseMeta();
  await rememberLastReason(reason || "租约已到期回收");
  setStatus("$(key) Group Lease", reason || "租约已到期回收");
  void panelProvider?.refresh();

  // Server already revoked the session; soft-clear is enough — no forced quit.
  await softClearLocalAuth();
  vscode.window.showWarningMessage(`号池租约已回收（${reason || "到期"}）`);
}

async function releaseCommand() {
  clearTimers();

  const confirm = await vscode.window.showWarningMessage(
    "确认归还当前租用账号？",
    { modal: true },
    "归还",
    "归还并重启",
    "取消"
  );
  if (!confirm || confirm === "取消") {
    return;
  }
  const hardClear = confirm === "归还并重启";

  try {
    await leaseClient.releaseLease(extContext);
  } catch (err) {
    vscode.window.showWarningMessage(`服务端释放失败: ${err.message || err}`);
  }
  await clearLeaseMeta();
  setStatus("$(key) Group Lease", "无活跃租约");
  void panelProvider?.refresh();

  if (hardClear) {
    await hardRestartClearAuth("已归还，正在重启 Cursor");
    return;
  }

  await softClearLocalAuth();
  vscode.window.showInformationMessage("已归还");
}

function scheduleReclaim(lease) {
  clearTimers();
  const stickySeconds = Number(lease?.sticky_seconds || 0);
  const expiresAt = lease?.expires_at ? Date.parse(lease.expires_at) : NaN;
  let msUntilExpiry;
  if (!Number.isNaN(expiresAt)) {
    msUntilExpiry = expiresAt - Date.now();
  } else if (stickySeconds > 0) {
    msUntilExpiry = stickySeconds * 1000;
  } else {
    return;
  }

  const renewEveryMs = Math.min(
    15 * 60 * 1000,
    Math.max(60_000, Math.floor((stickySeconds > 0 ? stickySeconds : 1800) * 500))
  );
  renewTimer = setInterval(async () => {
    try {
      const status = await leaseClient.renewLease(extContext);
      if (status?.reclaim_local) {
        void reclaimLocal(status.reclaim_reason || "计费周期回收");
        return;
      }
      if (status?.expires_at) {
        await persistLeaseMeta({
          lease_id: status.lease_id || activeLeaseId,
          expires_at: status.expires_at,
          sticky_seconds: status.sticky_remaining_seconds,
        });
        if (reclaimTimer) clearTimeout(reclaimTimer);
        const nextMs = Date.parse(status.expires_at) - Date.now();
        if (nextMs > 0) {
          reclaimTimer = setTimeout(
            () => reclaimLocal("sticky 到期"),
            nextMs + 1000
          );
        }
        setStatus(
          `$(key) #${status.account_id}`,
          `${status.cursor_email || ""} · ${status.sticky_remaining_seconds}s`
        );
        void panelProvider?.refresh();
      }
    } catch (err) {
      const msg = String(err?.message || err);
      if (msg.includes("计费周期")) {
        void reclaimLocal(msg);
      } else if (localLeaseExpired()) {
        // Server unreachable but local sticky deadline passed — clear injection offline.
        void reclaimLocalOffline("租约已到期（离线回收）");
      }
      // other renew failures — hard reclaim timer still fires
    }
  }, renewEveryMs);

  if (msUntilExpiry <= 0) {
    void reclaimLocal("sticky 已过期");
    return;
  }
  reclaimTimer = setTimeout(() => reclaimLocal("sticky 到期"), msUntilExpiry + 1000);
}

async function getSnapshot() {
  const token = await leaseClient.getAuthToken(extContext);
  if (!token) {
    return { loggedIn: false };
  }
  const userLabel =
    cachedUserLabel || extContext.globalState.get(STATE_USER_LABEL) || "";
  const lastReason = extContext.globalState.get(STATE_LAST_REASON) || "";
  try {
    const data = await leaseClient.leaseStatus(extContext);
    return {
      loggedIn: true,
      userLabel,
      hasLease: !!data.has_lease,
      accountId: data.account_id ?? null,
      cursorEmail: data.cursor_email || "",
      leaseId: data.lease_id || "",
      expiresAt: data.expires_at || "",
      remainingText: data.has_lease
        ? formatRemaining(data.sticky_remaining_seconds)
        : "",
      stickySeconds: data.sticky_remaining_seconds || 0,
      lastReason: data.has_lease ? "" : lastReason,
      gatewayEnabled: data.gateway_enabled !== false,
    };
  } catch (err) {
    return {
      loggedIn: true,
      userLabel,
      hasLease: false,
      error: String(err?.message || err),
      lastReason,
    };
  }
}

async function panelLogin(creds) {
  if (creds.token) {
    await leaseClient.loginWithToken(extContext, creds.token);
    cachedUserLabel = "token";
    try {
      const status = await leaseClient.leaseStatus(extContext);
      cachedUserLabel =
        status?.username ||
        status?.current_user ||
        status?.cursor_email ||
        "token";
    } catch {
      // token may still work for acquire even if status fails
    }
  } else {
    const info = await leaseClient.login(extContext, creds);
    cachedUserLabel = info.username || info.email || creds.username || "";
  }
  await extContext.globalState.update(STATE_USER_LABEL, cachedUserLabel);
  await refreshStatus();
}

/**
 * Login via InputBox — works even when sidebar Webview ServiceWorker is broken.
 */
async function loginViaPrompt() {
  let server = "";
  try {
    server = await leaseClient.getServerBaseUrl();
  } catch (err) {
    vscode.window.showErrorMessage(String(err?.message || err));
    return;
  }

  const modePick = await vscode.window.showQuickPick(
    [
      { label: "账号密码", description: "用户名 / 邮箱 + 密码", mode: "password" },
      { label: "Access Token / PAT", description: "直接使用 Bearer token", mode: "token" },
    ],
    {
      title: `Cursor Group Lease 登录（${server}）`,
      placeHolder: "选择登录方式",
      ignoreFocusOut: true,
    }
  );
  if (!modePick) return;

  if (modePick.mode === "token") {
    const cfg = vscode.workspace.getConfiguration("cursorGroupLease");
    const preset = String(cfg.get("accessToken") || "").trim();
    const token = await vscode.window.showInputBox({
      title: "Cursor Group Lease 登录",
      prompt: "Access Token / PAT",
      password: true,
      value: preset || undefined,
      ignoreFocusOut: true,
    });
    if (!token) return;

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Cursor Group Lease: 登录中…",
      },
      async () => {
        await panelLogin({ token: token.trim() });
      }
    );
  } else {
    const username = await vscode.window.showInputBox({
      title: "Cursor Group Lease 登录",
      prompt: "用户名或邮箱",
      ignoreFocusOut: true,
    });
    if (!username) return;

    const password = await vscode.window.showInputBox({
      title: "Cursor Group Lease 登录",
      prompt: "密码",
      password: true,
      ignoreFocusOut: true,
    });
    if (password == null) return;

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Cursor Group Lease: 登录中…",
      },
      async () => {
        await panelLogin({
          username: username.trim(),
          password,
          scope: "username",
        });
      }
    );
  }

  vscode.window.showInformationMessage(
    `已登录 Cursor Group${cachedUserLabel ? `（${cachedUserLabel}）` : ""}`
  );
  void panelProvider?.refresh();
}

async function logoutCommand() {
  clearTimers();
  let hadLease = Boolean(activeLeaseId || extContext?.globalState?.get?.(STATE_LEASE_ID));
  try {
    const token = await leaseClient.getAuthToken(extContext);
    if (token) {
      try {
        const status = await leaseClient.leaseStatus(extContext);
        if (status?.has_lease) hadLease = true;
      } catch {
        // ignore
      }
      if (hadLease) {
        try {
          await leaseClient.releaseLease(extContext);
        } catch {
          // ignore
        }
      }
    }
  } catch {
    // ignore
  }
  await leaseClient.logout(extContext);
  await clearLeaseMeta();
  cachedUserLabel = "";
  await extContext.globalState.update(STATE_USER_LABEL, undefined);
  setStatus("$(key) Group Lease", "未登录");
  void panelProvider?.refresh();

  // 退出登录本身不需要重启 Cursor。
  // 仅当刚释放过租约时，软清一下本机登录库；默认不强制退出。
  if (hadLease || authInject.hasInjectedAuth()) {
    await softClearLocalAuth();
  }
  vscode.window.showInformationMessage("已退出 Cursor Group Lease");
}

function assertLocalUiHost() {
  if (vscode.env.remoteName) {
    throw new Error(
      `当前窗口是远程（${vscode.env.remoteName}），无法写入本机 Cursor 登录库。\n` +
        "请关闭 Remote-SSH 窗口，在本机打开任意本地文件夹后再租号。"
    );
  }
}

async function acquireAndInject(options = {}) {
  assertLocalUiHost();

  const confirm = await vscode.window.showWarningMessage(
    "租号将重启 Cursor 以切换登录账号，请确认已保存工作。",
    { modal: true },
    "继续",
    "取消"
  );
  if (confirm !== "继续") {
    return;
  }

  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Cursor Group Lease: 租号中…",
      cancellable: false,
    },
    async () => {
      const lease = options.rotate
        ? await leaseClient.rotateLease(extContext, options)
        : await leaseClient.acquireLease(extContext, options);

      const dbPath = authInject.findStateDb();
      if (!dbPath) {
        throw new Error("未找到本机 state.vscdb");
      }

      let result;
      try {
        result = await authInject.injectCursorAuth(lease);
      } catch (err) {
        result = {
          dbPath,
          backupPath: null,
          via: "deferred",
          verifiedEmail: lease.cursor_email,
          mutation: authInject.buildAuthMutationForLease(lease),
        };
        vscode.window.showWarningMessage(
          `运行中写入未完全成功（${err.message || err}），将在退出后重试。`
        );
      }

      await persistLeaseMeta(lease);
      setStatus(
        `$(key) #${lease.account_id}`,
        `${lease.cursor_email || ""} · lease ${lease.lease_id}`
      );
      void panelProvider?.refresh();

      const post = authInject.schedulePostQuitReinjection(result, {
        relaunch: true,
        waitSeconds: 120,
        forceKill: true,
        appRoot: vscode.env.appRoot,
      });
      if (!post.scheduled) {
        throw new Error(
          "无法启动后台切号脚本（需要本机 Python3）。请安装 Python 后重试。"
        );
      }
      const booted = await authInject.waitForWorkerBoot(post.bootLogPath);
      if (!booted) {
        throw new Error(
          "后台重启脚本未能启动。请确认已安装 Python，并查看 %TEMP%\\cgl-lease-launch-*.boot.log"
        );
      }

      const email = result.verifiedEmail || lease.cursor_email || "unknown";
      vscode.window.showInformationMessage(
        `已租到 #${lease.account_id}（${email}），正在重启 Cursor…`
      );

      await beginPendingSwitch();
      await quitCursorForSwitch();
      return lease;
    }
  );
}

async function refreshStatus() {
  try {
    const token = await leaseClient.getAuthToken(extContext);
    if (!token) {
      setStatus("$(key) Group Lease", "未登录");
      void panelProvider?.refresh();
      return;
    }
    const data = await leaseClient.leaseStatus(extContext);
    if (data.reclaim_local) {
      void reclaimLocal(data.reclaim_reason || "计费周期回收");
      return;
    }
    if (data.has_lease) {
      await rememberLastReason(undefined);
      setStatus(
        `$(key) #${data.account_id}`,
        `${data.cursor_email || ""} · ${data.sticky_remaining_seconds}s`
      );
      if (data.expires_at || data.sticky_remaining_seconds > 0) {
        scheduleReclaim({
          lease_id: data.lease_id,
          expires_at: data.expires_at,
          sticky_seconds: data.sticky_remaining_seconds,
          account_id: data.account_id,
          cursor_email: data.cursor_email,
        });
      }
    } else {
      setStatus("$(key) Group Lease", data.gateway_enabled ? "已登录，未租号" : "号池租号未启用");
    }
  } catch (err) {
    setStatus("$(key) Group Lease", err.message || String(err));
  }
  void panelProvider?.refresh();
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  extContext = context;
  cachedUserLabel = context.globalState.get(STATE_USER_LABEL) || "";
  // Apply configured accessToken if no session secret yet.
  void (async () => {
    try {
      const existing = await leaseClient.getSessionToken(context);
      if (existing) return;
      const cfg = vscode.workspace.getConfiguration("cursorGroupLease");
      const preset = String(cfg.get("accessToken") || "").trim();
      if (preset) {
        await leaseClient.loginWithToken(context, preset);
        cachedUserLabel = cachedUserLabel || "token";
      }
    } catch {
      // ignore — user can log in manually
    }
  })();
  // Clear switch flag from previous quit-for-inject cycle.
  if (context.globalState.get(STATE_PENDING_SWITCH)) {
    void clearPendingSwitch();
  }
  // Restore confirmBeforeClose if we temporarily disabled it for restart.
  const prevConfirm = context.globalState.get(STATE_PREV_CONFIRM_CLOSE);
  if (prevConfirm != null) {
    void vscode.workspace
      .getConfiguration("window")
      .update(
        "confirmBeforeClose",
        prevConfirm,
        vscode.ConfigurationTarget.Global
      )
      .then(() =>
        context.globalState.update(STATE_PREV_CONFIRM_CLOSE, undefined)
      );
  }

  statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBar.command = "cursorGroupLease.focusPanel";
  statusBar.text = "$(key) Group Lease";
  statusBar.tooltip = vscode.env.remoteName
    ? `远程窗口（${vscode.env.remoteName}）— 注入需在本机窗口操作`
    : "打开 Cursor Group Lease 面板";
  statusBar.show();
  context.subscriptions.push(statusBar);
  context.subscriptions.push({ dispose: () => clearTimers() });

  if (vscode.env.remoteName) {
    void vscode.window.showWarningMessage(
      "Cursor Group Lease 检测到 Remote 窗口。登录可以，但租号必须在本机 Cursor 窗口执行。"
    );
  }

  panelProvider = new LeasePanelProvider(context, {
    getSnapshot,
    login: panelLogin,
    logout: logoutCommand,
    acquire: async () => {
      const snap = await getSnapshot();
      if (snap.hasLease) {
        throw new Error("当前已在租用中，请先归还后再租号");
      }
      try {
        await acquireAndInject({ reason: "manual" });
        await rememberLastReason(undefined);
      } catch (err) {
        const message = String(err?.message || err || "租号失败");
        await rememberLastReason(message);
        vscode.window.showErrorMessage(`租号失败: ${message}`);
        throw err;
      }
    },
    release: () => releaseCommand(),
  });

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("cursorGroupLease.panel", panelProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("cursorGroupLease.focusPanel", async () => {
      try {
        await vscode.commands.executeCommand("cursorGroupLease.panel.focus");
      } catch {
        // Sidebar webview may be broken (ServiceWorker). Fall back to prompts.
        await loginViaPrompt().catch((err) =>
          vscode.window.showErrorMessage(`登录失败: ${err.message || err}`)
        );
      }
    }),
    vscode.commands.registerCommand("cursorGroupLease.login", async () => {
      try {
        await loginViaPrompt();
      } catch (err) {
        vscode.window.showErrorMessage(`登录失败: ${err.message || err}`);
      }
    }),
    vscode.commands.registerCommand("cursorGroupLease.logout", () => logoutCommand()),
    vscode.commands.registerCommand("cursorGroupLease.configure", async () => {
      try {
        await loginViaPrompt();
      } catch (err) {
        vscode.window.showErrorMessage(`登录失败: ${err.message || err}`);
      }
    }),
    vscode.commands.registerCommand("cursorGroupLease.acquire", async () => {
      try {
        const snap = await getSnapshot();
        if (!snap.loggedIn) {
          await loginViaPrompt();
        }
        const again = await getSnapshot();
        if (again.hasLease) {
          vscode.window.showWarningMessage("当前已在租用中，请先归还后再租号");
          return;
        }
        await acquireAndInject({ reason: "manual" });
        await rememberLastReason(undefined);
      } catch (err) {
        const message = String(err?.message || err || "租号失败");
        await rememberLastReason(message);
        vscode.window.showErrorMessage(`租号失败: ${message}`);
      }
    }),
    vscode.commands.registerCommand("cursorGroupLease.release", () =>
      releaseCommand().catch((err) =>
        vscode.window.showErrorMessage(`归还失败: ${err.message || err}`)
      )
    ),
    // Kept for power users / command palette; not shown in panel.
    vscode.commands.registerCommand("cursorGroupLease.rotate", () =>
      acquireAndInject({ rotate: true, reason: "manual_rotate" }).catch((err) =>
        vscode.window.showErrorMessage(`换号失败: ${err.message || err}`)
      )
    )
  );

  setTimeout(() => {
    // Even if server is unreachable: honor locally stored sticky deadline.
    if (localLeaseExpired()) {
      void reclaimLocalOffline("租约已到期（离线回收）");
      return;
    }
    void refreshStatus();
    const cfg = vscode.workspace.getConfiguration("cursorGroupLease");
    if (cfg.get("autoAcquireOnStartup")) {
      void (async () => {
        try {
          const token = await leaseClient.getAuthToken(context);
          if (token) {
            await acquireAndInject({ reason: "startup" });
          }
        } catch (err) {
          vscode.window.showWarningMessage(
            `启动自动租号失败: ${err.message || err}`
          );
        }
      })();
    }
  }, 0);
}

function deactivate() {
  clearTimers();
  // Window quit during 租号/归还 also triggers deactivate. Must NOT release/clear
  // then, or we revoke the session and wipe auth before the post-quit inject script runs.
  const pending =
    suppressDeactivateTeardown ||
    (extContext && extContext.globalState.get(STATE_PENDING_SWITCH));
  if (pending) {
    return;
  }
  // Best-effort server release on extension disable/uninstall only (no local clear race).
  return (async () => {
    if (!extContext) return;
    try {
      const token = await leaseClient.getAuthToken(extContext);
      if (token) {
        try {
          await leaseClient.releaseLease(extContext);
        } catch {
          // ignore
        }
      }
    } catch {
      // ignore
    }
  })();
}

module.exports = { activate, deactivate };
