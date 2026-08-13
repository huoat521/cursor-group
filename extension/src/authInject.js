"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { spawn, spawnSync } = require("child_process");

/** Prefer sql.js only for small DBs; large Cursor state.vscdb needs native/CLI. */
const SQLJS_MAX_BYTES = 256 * 1024 * 1024;

const AUTH_KEYS = {
  accessToken: "cursorAuth/accessToken",
  refreshToken: "cursorAuth/refreshToken",
  cachedEmail: "cursorAuth/cachedEmail",
  cachedSignUpType: "cursorAuth/cachedSignUpType",
  membershipType: "cursorAuth/stripeMembershipType",
  subscriptionStatus: "cursorAuth/stripeSubscriptionStatus",
  authId: "cursorAuth/authId",
  // Cockpit Tools also writes these legacy aliases — Cursor Settings reads them.
  cursorAccessToken: "cursor.accessToken",
  cursorEmail: "cursor.email",
};

const CLEANUP_KEYS = [
  "cursorAuth/onboardingDate",
  "cursorAuth/stripeCustomerId",
];

function decodeJwtPayload(token) {
  try {
    const parts = String(token || "").split(".");
    if (parts.length < 2) return null;
    let b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4) b64 += "=";
    const json = Buffer.from(b64, "base64").toString("utf8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function extractAuthIdFromAccessToken(accessToken) {
  const payload = decodeJwtPayload(accessToken);
  const sub = payload && payload.sub != null ? String(payload.sub).trim() : "";
  return sub || null;
}

function b64urlJson(obj) {
  return Buffer.from(JSON.stringify(obj), "utf8")
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

/**
 * JWT-shaped decoy refresh token.
 * Cursor needs a refreshToken field to show logged-in, but a real RT can mint a
 * new AT after session revoke. Never reuse accessToken as refreshToken — Cursor
 * accepts AT as RT.
 */
function buildDecoyRefreshToken(accessToken) {
  const payload = decodeJwtPayload(accessToken) || {};
  const now = Math.floor(Date.now() / 1000);
  let exp = now + 60 * 86400;
  if (payload.exp != null) {
    const n = Number(payload.exp);
    if (Number.isFinite(n) && n > now) exp = n;
  }
  const header = { alg: "HS256", typ: "JWT" };
  const body = {
    sub: payload.sub || "auth0|user_lease_decoy",
    time: String(now),
    randomness: `${crypto.randomBytes(8).toString("hex")}-${crypto
      .randomBytes(2)
      .toString("hex")}`,
    exp,
    iss: "https://authentication.cursor.sh",
    scope: "openid profile email offline_access",
    aud: "https://cursor.com",
    type: "session",
  };
  const sig = crypto
    .randomBytes(32)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
  return `${b64urlJson(header)}.${b64urlJson(body)}.${sig}`;
}

/**
 * Resolve refresh token for injection: prefer server decoy/value; else local decoy.
 * Never fall back to accessToken.
 */
function resolveInjectRefreshToken(credentials, accessToken) {
  const fromServer =
    credentials && credentials.refresh_token
      ? String(credentials.refresh_token).trim()
      : "";
  if (fromServer && fromServer !== accessToken) {
    return fromServer;
  }
  return buildDecoyRefreshToken(accessToken);
}

function cursorUserDataRoots() {
  const home = os.homedir();
  const platform = process.platform;
  const roots = [];

  if (platform === "win32") {
    const appData = process.env.APPDATA || path.join(home, "AppData", "Roaming");
    roots.push(path.join(appData, "Cursor"));
    if (process.env.CURSOR_USER_DATA_DIR) {
      roots.unshift(process.env.CURSOR_USER_DATA_DIR);
    }
  } else if (platform === "darwin") {
    roots.push(path.join(home, "Library", "Application Support", "Cursor"));
  } else {
    roots.push(
      path.join(home, ".config", "Cursor"),
      path.join(home, ".cursor")
    );
  }
  return roots;
}

function findStateDb(extraRoots = []) {
  const roots = [...extraRoots, ...cursorUserDataRoots()].filter(Boolean);
  for (const root of roots) {
    try {
      if (fs.existsSync(root) && fs.statSync(root).isFile()) {
        return root;
      }
    } catch {
      // ignore
    }
    if (String(root).endsWith(".vscdb") && fs.existsSync(root)) {
      return root;
    }
    const candidate = path.join(root, "User", "globalStorage", "state.vscdb");
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function describeSearchPaths(extraRoots = []) {
  return [...extraRoots, ...cursorUserDataRoots()]
    .filter(Boolean)
    .map((root) =>
      root.endsWith("state.vscdb")
        ? root
        : path.join(root, "User", "globalStorage", "state.vscdb")
    );
}

function fileSize(dbPath) {
  try {
    return fs.statSync(dbPath).size;
  } catch {
    return 0;
  }
}

function dropStaleWal(dbPath) {
  for (const suffix of ["-wal", "-shm"]) {
    const side = `${dbPath}${suffix}`;
    try {
      if (fs.existsSync(side)) fs.unlinkSync(side);
    } catch {
      // ignore
    }
  }
}

function sqlLiteral(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function buildUpsertSqlCompatible(pairs) {
  const lines = ["BEGIN;"];
  for (const [key, value] of pairs) {
    const k = sqlLiteral(key);
    const v = sqlLiteral(value);
    lines.push(
      `UPDATE ItemTable SET value = ${v} WHERE key = ${k};` +
        `INSERT INTO ItemTable (key, value) SELECT ${k}, ${v} ` +
        `WHERE NOT EXISTS (SELECT 1 FROM ItemTable WHERE key = ${k});`
    );
  }
  lines.push("COMMIT;");
  return lines.join("\n");
}

function buildDeleteSql(keys) {
  const lines = ["BEGIN;"];
  for (const key of keys) {
    lines.push(`DELETE FROM ItemTable WHERE key = ${sqlLiteral(key)};`);
  }
  lines.push("COMMIT;");
  return lines.join("\n");
}

function runSqliteCli(dbPath, sql) {
  const candidates =
    process.platform === "win32"
      ? ["sqlite3.exe", "sqlite3"]
      : ["sqlite3"];
  for (const bin of candidates) {
    const result = spawnSync(bin, [dbPath], {
      input: sql,
      encoding: "utf8",
      windowsHide: true,
      timeout: 120000,
      maxBuffer: 4 * 1024 * 1024,
    });
    if (result.error && result.error.code === "ENOENT") continue;
    if (result.status === 0) return { ok: true, via: bin };
    const err = (result.stderr || result.stdout || "").trim();
    throw new Error(`sqlite3 CLI 失败: ${err || `exit ${result.status}`}`);
  }
  return { ok: false };
}

function findPython() {
  const candidates =
    process.platform === "win32"
      ? ["py", "python", "python3", "pythonw"]
      : ["python3", "python"];
  for (const bin of candidates) {
    const args =
      bin === "py"
        ? ["-3", "-c", "import sqlite3; print('ok')"]
        : ["-c", "import sqlite3; print('ok')"];
    const probe = spawnSync(bin, args, {
      encoding: "utf8",
      windowsHide: true,
      timeout: 10000,
    });
    if (probe.status !== 0 || !String(probe.stdout || "").includes("ok")) {
      continue;
    }
    // Prefer absolute path so Start/cmd launch still finds it without user PATH.
    if (process.platform === "win32") {
      const located = spawnSync("where", [bin], {
        encoding: "utf8",
        windowsHide: true,
        timeout: 5000,
      });
      const first = String(located.stdout || "")
        .split(/\r?\n/)
        .map((s) => s.trim())
        .find((s) => s && /\.exe$/i.test(s));
      if (first) return first;
    } else {
      const located = spawnSync("which", [bin], {
        encoding: "utf8",
        timeout: 5000,
      });
      const first = String(located.stdout || "").trim().split("\n")[0];
      if (first) return first;
    }
    return bin;
  }
  return null;
}

function runPythonSqlite(dbPath, mode, payload) {
  const py = findPython();
  if (!py) return { ok: false };

  const script = `
import json, sqlite3, sys
db_path = sys.argv[1]
mode = sys.argv[2]
payload = json.loads(sys.argv[3])
conn = sqlite3.connect(db_path, timeout=60)
try:
    conn.execute("PRAGMA busy_timeout=60000")
    cur = conn.cursor()
    if mode == "upsert":
        for key, value in payload:
            cur.execute("SELECT 1 FROM ItemTable WHERE key = ?", (key,))
            if cur.fetchone():
                cur.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (value, key))
            else:
                cur.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)", (key, value))
    elif mode == "delete":
        for key in payload:
            cur.execute("DELETE FROM ItemTable WHERE key = ?", (key,))
    elif mode == "apply":
        for key, value in payload.get("upsert", []):
            cur.execute("SELECT 1 FROM ItemTable WHERE key = ?", (key,))
            if cur.fetchone():
                cur.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (value, key))
            else:
                cur.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)", (key, value))
        for key in payload.get("delete", []):
            cur.execute("DELETE FROM ItemTable WHERE key = ?", (key,))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
    elif mode == "read":
        out = {}
        for key in payload:
            cur.execute("SELECT value FROM ItemTable WHERE key = ?", (key,))
            row = cur.fetchone()
            out[key] = row[0] if row else None
        print(json.dumps(out, ensure_ascii=False))
        raise SystemExit(0)
    else:
        raise SystemExit("unknown mode")
    conn.commit()
finally:
    conn.close()
print("ok")
`.trim();

  const args =
    py === "py"
      ? ["-3", "-c", script, dbPath, mode, JSON.stringify(payload)]
      : ["-c", script, dbPath, mode, JSON.stringify(payload)];

  const result = spawnSync(py, args, {
    encoding: "utf8",
    windowsHide: true,
    timeout: 180000,
    maxBuffer: 8 * 1024 * 1024,
  });
  if (mode === "read") {
    if (result.status !== 0) {
      const err = (result.stderr || result.stdout || "").toString().trim();
      throw new Error(`读取 state.vscdb 失败: ${err || `exit ${result.status}`}`);
    }
    try {
      return { ok: true, via: `python:${py}`, data: JSON.parse(result.stdout.trim()) };
    } catch (err) {
      throw new Error(`解析读取结果失败: ${err.message || err}`);
    }
  }
  if (result.status === 0 && String(result.stdout || "").includes("ok")) {
    return { ok: true, via: `python:${py}` };
  }
  const err = (result.stderr || result.stdout || result.error || "").toString().trim();
  throw new Error(`Python sqlite 写入失败: ${err || `exit ${result.status}`}`);
}

async function runSqlJs(dbPath, applyFn) {
  // eslint-disable-next-line import/no-extraneous-dependencies
  const initSqlJs = require("sql.js");
  const SQL = await initSqlJs({
    locateFile: (file) =>
      path.join(__dirname, "..", "node_modules", "sql.js", "dist", file),
  });
  const filebuffer = fs.readFileSync(dbPath);
  const db = new SQL.Database(filebuffer);
  try {
    applyFn(db);
    const data = db.export();
    fs.writeFileSync(dbPath, Buffer.from(data));
    dropStaleWal(dbPath);
    return { ok: true, via: "sql.js" };
  } finally {
    db.close();
  }
}

function sqlJsUpsert(db, pairs) {
  db.run("BEGIN");
  for (const [key, value] of pairs) {
    const stmt = db.prepare("SELECT 1 AS x FROM ItemTable WHERE key = ?");
    stmt.bind([key]);
    const exists = stmt.step();
    stmt.free();
    if (exists) {
      db.run("UPDATE ItemTable SET value = ? WHERE key = ?", [value, key]);
    } else {
      db.run("INSERT INTO ItemTable (key, value) VALUES (?, ?)", [key, value]);
    }
  }
  db.run("COMMIT");
}

function sqlJsDelete(db, keys) {
  db.run("BEGIN");
  for (const key of keys) {
    db.run("DELETE FROM ItemTable WHERE key = ?", [key]);
  }
  db.run("COMMIT");
}

async function mutateStateDb(dbPath, { upsertPairs = null, deleteKeys = null, apply = null }) {
  const size = fileSize(dbPath);
  const errors = [];

  try {
    if (apply) {
      const r = runPythonSqlite(dbPath, "apply", apply);
      if (r.ok) return r;
    } else if (upsertPairs) {
      const r = runPythonSqlite(dbPath, "upsert", upsertPairs);
      if (r.ok) return r;
    } else if (deleteKeys) {
      const r = runPythonSqlite(dbPath, "delete", deleteKeys);
      if (r.ok) return r;
    }
  } catch (err) {
    errors.push(String(err.message || err));
  }

  try {
    if (apply) {
      const sql =
        buildUpsertSqlCompatible(apply.upsert || []) +
        "\n" +
        buildDeleteSql(apply.delete || []);
      const r = runSqliteCli(dbPath, sql);
      if (r.ok) {
        dropStaleWal(dbPath);
        return r;
      }
    } else {
      const sql = upsertPairs
        ? buildUpsertSqlCompatible(upsertPairs)
        : buildDeleteSql(deleteKeys || []);
      const r = runSqliteCli(dbPath, sql);
      if (r.ok) {
        dropStaleWal(dbPath);
        return r;
      }
    }
  } catch (err) {
    errors.push(String(err.message || err));
  }

  if (size > 0 && size <= SQLJS_MAX_BYTES) {
    try {
      if (apply) {
        return await runSqlJs(dbPath, (db) => {
          sqlJsUpsert(db, apply.upsert || []);
          sqlJsDelete(db, apply.delete || []);
        });
      }
      if (upsertPairs) {
        return await runSqlJs(dbPath, (db) => sqlJsUpsert(db, upsertPairs));
      }
      return await runSqlJs(dbPath, (db) => sqlJsDelete(db, deleteKeys || []));
    } catch (err) {
      errors.push(String(err.message || err));
    }
  } else if (size > SQLJS_MAX_BYTES) {
    errors.push(
      `state.vscdb 约 ${(size / (1024 * 1024 * 1024)).toFixed(2)} GiB，无法用内置 sql.js（限 2GiB）整文件加载`
    );
  }

  throw new Error(
    "无法写入 Cursor state.vscdb。\n" +
      "请安装 Python3（推荐）或 sqlite3 命令行后重试。\n" +
      `数据库: ${dbPath}（${(size / (1024 * 1024)).toFixed(1)} MB）\n` +
      (errors.length ? `详情:\n- ${errors.join("\n- ")}` : "")
  );
}

function readAuthSnapshot(dbPath) {
  const keys = [
    AUTH_KEYS.accessToken,
    AUTH_KEYS.refreshToken,
    AUTH_KEYS.cachedEmail,
    AUTH_KEYS.membershipType,
    AUTH_KEYS.subscriptionStatus,
    AUTH_KEYS.authId,
    AUTH_KEYS.cursorAccessToken,
    AUTH_KEYS.cursorEmail,
  ];
  try {
    const r = runPythonSqlite(dbPath, "read", keys);
    return r.data || {};
  } catch {
    return {};
  }
}

function buildAuthMutation(credentials) {
  const accessToken = String(credentials.access_token || "").trim();
  if (!accessToken) {
    throw new Error("租约响应缺少 access_token");
  }
  const refreshToken = resolveInjectRefreshToken(credentials, accessToken);
  const email = String(credentials.cursor_email || "").trim();
  const membership =
    String(
      credentials.membership_type || credentials.stripeMembershipType || "pro"
    ).trim() || "pro";
  const subStatus =
    String(
      credentials.subscription_status ||
        credentials.stripeSubscriptionStatus ||
        "active"
    ).trim() || "active";
  const authId = extractAuthIdFromAccessToken(accessToken);

  // Mirror Cockpit Tools inject_to_cursor keys exactly.
  const upsert = [
    [AUTH_KEYS.accessToken, accessToken],
    [AUTH_KEYS.cursorAccessToken, accessToken],
    [AUTH_KEYS.refreshToken, refreshToken],
    [AUTH_KEYS.cachedSignUpType, "Auth_0"],
    [AUTH_KEYS.membershipType, membership],
    [AUTH_KEYS.subscriptionStatus, subStatus],
  ];
  if (email) {
    upsert.push([AUTH_KEYS.cachedEmail, email]);
    upsert.push([AUTH_KEYS.cursorEmail, email]);
  }
  if (authId) {
    upsert.push([AUTH_KEYS.authId, authId]);
  }

  return {
    upsert,
    delete: [...CLEANUP_KEYS],
    expected: {
      accessToken,
      refreshToken,
      email: email || null,
    },
  };
}

function verifyAuthMutation(dbPath, expected) {
  const snap = readAuthSnapshot(dbPath);
  const gotAccess = snap[AUTH_KEYS.accessToken] || "";
  const gotAlias = snap[AUTH_KEYS.cursorAccessToken] || "";
  const gotEmail = snap[AUTH_KEYS.cachedEmail] || "";
  const gotAliasEmail = snap[AUTH_KEYS.cursorEmail] || "";
  const gotRefresh = snap[AUTH_KEYS.refreshToken] || null;

  const problems = [];
  if (!gotAccess || gotAccess !== expected.accessToken) {
    problems.push("cursorAuth/accessToken 未写入或被覆盖");
  }
  if (!gotAlias || gotAlias !== expected.accessToken) {
    problems.push("cursor.accessToken 未写入（Cockpit 同款别名）");
  }
  if (expected.email && gotEmail !== expected.email) {
    problems.push(
      `cachedEmail 仍为「${gotEmail || "(空)"}」，期望「${expected.email}」`
    );
  }
  if (expected.email && gotAliasEmail !== expected.email) {
    problems.push(
      `cursor.email 仍为「${gotAliasEmail || "(空)"}」，期望「${expected.email}」`
    );
  }
  if (expected.refreshToken && gotRefresh !== expected.refreshToken) {
    problems.push("refreshToken 未写入（旧 refresh 会导致重启后回到原账号）");
  }
  if (!expected.refreshToken) {
    problems.push("缺少 decoy refreshToken（Cursor 无 RT 会显示未登录）");
  } else if (expected.refreshToken === expected.accessToken) {
    problems.push("refreshToken 不能与 accessToken 相同（AT 可作为 RT 续票）");
  }
  return { ok: problems.length === 0, problems, snap };
}

/**
 * Write OAuth credentials into Cursor's local auth store (state.vscdb).
 */
async function injectCursorAuth(credentials, options = {}) {
  const dbPath = findStateDb(options.extraRoots || []);
  if (!dbPath) {
    const searched = describeSearchPaths(options.extraRoots || []).join("\n  - ");
    throw new Error(
      "未找到 Cursor state.vscdb。\n" +
        "本扩展必须在「本机 Cursor」窗口运行（不要在 Remote-SSH 远程窗口里注入）。\n" +
        "请：关闭远程窗口 → 本地打开任意文件夹 → 再点「租号并注入」。\n" +
        `已搜索：\n  - ${searched}`
    );
  }

  const mutation = buildAuthMutation(credentials);
  const size = fileSize(dbPath);
  let backupPath = null;
  if (size > 0 && size <= SQLJS_MAX_BYTES) {
    backupPath = `${dbPath}.cgl-lease-backup-${Date.now()}`;
    fs.copyFileSync(dbPath, backupPath);
  }

  const result = await mutateStateDb(dbPath, { apply: mutation });
  const verified = verifyAuthMutation(dbPath, mutation.expected);
  if (!verified.ok) {
    throw new Error(
      "写入后校验失败（Cursor 可能仍在用内存/WAL 覆盖）：\n- " +
        verified.problems.join("\n- ") +
        "\n请完全退出 Cursor 后重试。"
    );
  }

  return {
    dbPath,
    backupPath,
    via: result.via,
    dbSizeBytes: size,
    verifiedEmail: verified.snap[AUTH_KEYS.cachedEmail] || mutation.expected.email,
    mutation,
  };
}

function authClearKeys() {
  return [
    AUTH_KEYS.accessToken,
    AUTH_KEYS.refreshToken,
    AUTH_KEYS.cachedEmail,
    AUTH_KEYS.cachedSignUpType,
    AUTH_KEYS.membershipType,
    AUTH_KEYS.subscriptionStatus,
    AUTH_KEYS.authId,
    AUTH_KEYS.cursorAccessToken,
    AUTH_KEYS.cursorEmail,
    ...CLEANUP_KEYS,
  ];
}

/**
 * Resolve the desktop Cursor binary for post-quit relaunch.
 * Avoid PATH's remote-cli / cursor-server stubs (common on Linux).
 * @param {{ exe?: string, appRoot?: string }} [options]
 */
function resolveCursorDesktopExe(options = {}) {
  const hints = [];
  if (options.exe) hints.push(String(options.exe));
  if (options.appRoot) {
    const root = String(options.appRoot);
    hints.push(path.resolve(root, "..", "..", "cursor"));
    hints.push(path.resolve(root, "..", "..", "Cursor"));
    hints.push(path.resolve(root, "..", "cursor"));
  }
  if (process.execPath) hints.push(process.execPath);

  if (process.platform === "linux") {
    hints.push(
      "/usr/share/cursor/cursor",
      "/usr/share/Cursor/cursor",
      "/opt/Cursor/cursor",
      "/opt/cursor/cursor",
      path.join(os.homedir(), ".local", "share", "cursor", "cursor")
    );
  } else if (process.platform === "darwin") {
    hints.push("/Applications/Cursor.app/Contents/MacOS/Cursor");
  } else if (process.platform === "win32") {
    const local = process.env.LOCALAPPDATA || "";
    hints.push(
      path.join(local, "Programs", "cursor", "Cursor.exe"),
      path.join(local, "Programs", "Cursor", "Cursor.exe")
    );
  }

  for (const candidate of hints) {
    if (!candidate) continue;
    if (/cursor-server|remote-cli/i.test(candidate)) continue;
    try {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        return candidate;
      }
    } catch {
      // ignore
    }
  }
  return "";
}

/**
 * Cockpit Tools flow: kill Cursor → mutate state.vscdb → relaunch.
 * Writing while Cursor is alive is unreliable (memory/WAL overwrite).
 * @param {{
 *   dbPath: string,
 *   upsert?: [string, string][],
 *   delete?: string[],
 *   expectedEmail?: string,
 *   expectedAccess?: string,
 *   mode?: "inject" | "clear",
 * }} mutation
 */
function schedulePostQuitMutation(mutation, options = {}) {
  const py = findPython();
  if (!py) {
    return { scheduled: false, reason: "no_python" };
  }

  const relaunchExe = resolveCursorDesktopExe({
    exe: options.relaunchExe || options.exe,
    appRoot: options.appRoot,
  });

  const payload = {
    mode: mutation.mode || "inject",
    db_path: mutation.dbPath,
    upsert: mutation.upsert || [],
    delete: mutation.delete || [],
    expected_email: mutation.expectedEmail || "",
    expected_access: mutation.expectedAccess || "",
    relaunch: options.relaunch !== false,
    relaunch_exe: relaunchExe,
    wait_seconds: Number(options.waitSeconds || 120),
    force_kill: options.forceKill !== false,
  };

  const pendingPath = path.join(
    os.tmpdir(),
    `cgl-lease-pending-${Date.now()}.json`
  );
  const scriptPath = path.join(
    os.tmpdir(),
    `cgl-lease-reapply-${Date.now()}.py`
  );
  fs.writeFileSync(pendingPath, JSON.stringify(payload), "utf8");

  // Mirrors cockpit-tools: close Cursor processes, then inject_to_cursor, then start.
  const script = `
import json, os, sqlite3, subprocess, sys, time

pending = sys.argv[1]
with open(pending, "r", encoding="utf-8") as f:
    cfg = json.load(f)

db_path = cfg["db_path"]
wait_s = int(cfg.get("wait_seconds") or 120)
deadline = time.time() + wait_s
log_path = pending + ".log"
relaunch_exe = (cfg.get("relaunch_exe") or "").strip()

def log(msg):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg + "\\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass

def ignore_cmdline(cmd):
    low = (cmd or "").lower()
    return (
        "cursor-server" in low
        or "remote-cli" in low
        or "cgl-lease-" in low
        or "cgl-lease-reapply" in low
    )

def cursor_pids_win():
    pids = []
    for name in ("Cursor.exe",):
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq %s" % name, "/FO", "CSV", "/NH"],
                creationflags=0x08000000,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", "ignore")
        except Exception:
            continue
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("INFO:"):
                continue
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.append(int(parts[1]))
    return sorted(set(pids))

def linux_cursor_pids():
    """Match desktop Cursor by /proc exe; never match cursor-server/remote-cli."""
    pids = []
    want = os.path.realpath(relaunch_exe) if relaunch_exe else ""
    want_base = os.path.basename(want).lower() if want else ""
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            try:
                cmd = open("/proc/%s/cmdline" % pid, "rb").read().decode("utf-8", "ignore")
            except Exception:
                continue
            if ignore_cmdline(cmd):
                continue
            link = ""
            try:
                link = os.path.realpath(os.readlink("/proc/%s/exe" % pid))
            except Exception:
                link = ""
            if want and link and (link == want or os.path.realpath(link) == want):
                pids.append(pid)
                continue
            # Fallback: electron main named cursor/Cursor, not helpers with --type=
            base = os.path.basename(link).lower() if link else ""
            if base in ("cursor",) or (want_base and base == want_base):
                if "--type=" in cmd:
                    continue
                pids.append(pid)
    except Exception as e:
        log("linux_pid_scan_error=%s" % e)
    return sorted(set(pids))

def darwin_cursor_running():
    try:
        out = subprocess.check_output(
            ["pgrep", "-x", "Cursor"], stderr=subprocess.DEVNULL
        )
        return bool(out.strip())
    except Exception:
        return False

def cursor_running():
    try:
        if sys.platform.startswith("win"):
            return bool(cursor_pids_win())
        if sys.platform == "darwin":
            return darwin_cursor_running()
        return bool(linux_cursor_pids())
    except Exception:
        return False

def force_kill_cursor():
    try:
        if sys.platform.startswith("win"):
            for name in ("Cursor.exe",):
                subprocess.call(
                    ["taskkill", "/F", "/IM", name, "/T"],
                    creationflags=0x08000000,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            for pid in cursor_pids_win():
                subprocess.call(
                    ["taskkill", "/F", "/PID", str(pid), "/T"],
                    creationflags=0x08000000,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        elif sys.platform == "darwin":
            subprocess.call(["osascript", "-e", 'quit app "Cursor"'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            subprocess.call(["pkill", "-9", "-x", "Cursor"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            for pid in linux_cursor_pids():
                try:
                    os.kill(pid, 9)
                    log("kill_pid=%s" % pid)
                except Exception as e:
                    log("kill_pid_error=%s err=%s" % (pid, e))
    except Exception as e:
        log("kill_error=%s" % e)

def resolve_relaunch_cmd():
    if relaunch_exe and os.path.isfile(relaunch_exe):
        return [relaunch_exe]
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or ""
        for exe in (
            os.path.join(local, "Programs", "cursor", "Cursor.exe"),
            os.path.join(local, "Programs", "Cursor", "Cursor.exe"),
        ):
            if os.path.isfile(exe):
                return [exe]
        return []
    if sys.platform == "darwin":
        return ["open", "-a", "Cursor"]
    for exe in (
        "/usr/share/cursor/cursor",
        "/usr/share/Cursor/cursor",
        "/opt/Cursor/cursor",
        "/opt/cursor/cursor",
    ):
        if os.path.isfile(exe):
            return [exe]
    return []

log("start force_kill=%s relaunch_exe=%s pid=%s" % (
    cfg.get("force_kill", True), relaunch_exe, os.getpid()))

# Prefer graceful quit from the extension; only force-kill after a short wait.
grace_s = 3.0
log("waiting_graceful_exit=%.1fs" % grace_s)
t0 = time.time()
while time.time() < t0 + grace_s and cursor_running():
    time.sleep(0.4)
log("after_grace running=%s" % cursor_running())

while time.time() < deadline and cursor_running():
    if cfg.get("force_kill", True):
        log("force_kill_attempt")
        force_kill_cursor()
    time.sleep(0.6)

if cursor_running():
    log("error=cursor_still_running_after_timeout pids=%s" % (
        cursor_pids_win() if sys.platform.startswith("win") else
        ([] if sys.platform == "darwin" else linux_cursor_pids())
    ))
    sys.exit(2)

time.sleep(1.2)
log("cursor_exited")

# Drop stale WAL so our write is what Cursor loads next.
for suffix in ("-wal", "-shm"):
    side = db_path + suffix
    try:
        if os.path.exists(side):
            os.remove(side)
            log("removed %s" % side)
    except Exception as e:
        log("wal_remove_error=%s" % e)

conn = sqlite3.connect(db_path, timeout=60)
try:
    conn.execute("PRAGMA busy_timeout=60000")
    cur = conn.cursor()
    # Cockpit uses INSERT OR REPLACE INTO ItemTable
    for key, value in cfg.get("upsert") or []:
        try:
            cur.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (key, value),
            )
        except sqlite3.IntegrityError:
            cur.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (value, key))
            if cur.rowcount == 0:
                cur.execute(
                    "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                    (key, value),
                )
    for key in cfg.get("delete") or []:
        cur.execute("DELETE FROM ItemTable WHERE key = ?", (key,))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    conn.commit()

    def read_key(k):
        cur.execute("SELECT value FROM ItemTable WHERE key = ?", (k,))
        row = cur.fetchone()
        return row[0] if row else ""

    email = read_key("cursorAuth/cachedEmail")
    token = read_key("cursorAuth/accessToken")
    alias_token = read_key("cursor.accessToken")
    alias_email = read_key("cursor.email")
finally:
    conn.close()

mode = cfg.get("mode") or "inject"
ok = True
if mode == "clear":
    if token or alias_token or email or alias_email:
        ok = False
        log("clear_incomplete token=%s alias_token=%s email=%s alias_email=%s"
            % (bool(token), bool(alias_token), email, alias_email))
else:
    if cfg.get("expected_email") and email != cfg.get("expected_email"):
        ok = False
        log("email_mismatch got=%s expected=%s" % (email, cfg.get("expected_email")))
    if cfg.get("expected_access") and token != cfg.get("expected_access"):
        ok = False
        log("token_mismatch")
    if cfg.get("expected_access") and alias_token != cfg.get("expected_access"):
        ok = False
        log("alias_token_mismatch")
    if cfg.get("expected_email") and alias_email != cfg.get("expected_email"):
        ok = False
        log("alias_email_mismatch got=%s" % alias_email)

log("ok=%s mode=%s email=%s alias_email=%s" % (ok, mode, email, alias_email))

if not ok:
    sys.exit(3)

if cfg.get("relaunch"):
    try:
        cmd = resolve_relaunch_cmd()
        if not cmd:
            log("relaunch_missing_exe")
        else:
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform.startswith("win"):
                kwargs["close_fds"] = True
                kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen(cmd, **kwargs)
            log("relaunch=%s" % " ".join(cmd))
    except Exception as e:
        log("relaunch_error=%s" % e)

try:
    os.remove(pending)
except Exception:
    pass
`.trim();

  fs.writeFileSync(scriptPath, script, "utf8");

  const args =
    py === "py" || /[/\\]py\.exe$/i.test(py)
      ? ["-3", scriptPath, pendingPath]
      : [scriptPath, pendingPath];

  const launch = spawnDetachedWorker(py, args);
  if (!launch.ok) {
    return { scheduled: false, reason: launch.reason || "spawn_failed" };
  }

  return {
    scheduled: true,
    pendingPath,
    scriptPath,
    bootLogPath: launch.bootLogPath || null,
    launcherPath: launch.launcherPath || null,
    via: `python:${py}`,
    relaunchExe,
  };
}

/**
 * Launch the post-quit worker so it survives Cursor exit.
 * On Windows, Electron Job Objects kill plain child processes on quit — use
 * `cmd /c start` via a .cmd wrapper (classic breakaway).
 */
function spawnDetachedWorker(py, args) {
  if (process.platform === "win32") {
    const stamp = Date.now();
    const launcherPath = path.join(os.tmpdir(), `cgl-lease-launch-${stamp}.cmd`);
    const bootLogPath = path.join(os.tmpdir(), `cgl-lease-launch-${stamp}.boot.log`);
    const q = (s) => `"${String(s).replace(/"/g, '""')}"`;
    const cmdline = [py, ...args].map(q).join(" ");
    const body = [
      "@echo off",
      `echo boot %DATE% %TIME%>${q(bootLogPath)}`,
      `echo py=${q(py)}>>${q(bootLogPath)}`,
      `echo cmdline=${cmdline}>>${q(bootLogPath)}`,
      `${cmdline}>>${q(bootLogPath)} 2>&1`,
      `echo exit=%ERRORLEVEL%>>${q(bootLogPath)}`,
    ].join("\r\n");
    try {
      fs.writeFileSync(launcherPath, body, "utf8");
    } catch (err) {
      return { ok: false, reason: `write_launcher:${err.message || err}` };
    }

    // start "" /min <cmd> — empty title is required; breaks out of Job Object.
    const child = spawn(
      process.env.ComSpec || "cmd.exe",
      ["/d", "/c", "start", '""', "/min", launcherPath],
      {
        detached: true,
        stdio: "ignore",
        windowsHide: true,
      }
    );
    child.unref();
    return {
      ok: true,
      bootLogPath,
      launcherPath,
      child,
    };
  }

  const child = spawn(py, args, {
    detached: true,
    stdio: "ignore",
  });
  child.unref();
  return { ok: true, child };
}

/** Wait until Windows launcher boot log appears (script actually started). */
async function waitForWorkerBoot(bootLogPath, timeoutMs = 2500) {
  if (!bootLogPath) return true;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      if (fs.existsSync(bootLogPath)) {
        const text = fs.readFileSync(bootLogPath, "utf8");
        if (/boot /i.test(text)) return true;
      }
    } catch {
      // ignore
    }
    await new Promise((r) => setTimeout(r, 120));
  }
  return false;
}

/**
 * After quit: re-apply inject mutation (Cockpit order).
 */
function schedulePostQuitReinjection(injectResult, options = {}) {
  return schedulePostQuitMutation(
    {
      mode: "inject",
      dbPath: injectResult.dbPath,
      upsert: injectResult.mutation.upsert,
      delete: injectResult.mutation.delete,
      expectedEmail: injectResult.mutation.expected.email,
      expectedAccess: injectResult.mutation.expected.accessToken,
    },
    options
  );
}

/**
 * After quit: delete auth keys so Cursor relaunches logged out.
 * Live clear while Cursor is running is unreliable (same as inject).
 */
function schedulePostQuitClear(dbPath, options = {}) {
  return schedulePostQuitMutation(
    {
      mode: "clear",
      dbPath,
      upsert: [],
      delete: authClearKeys(),
    },
    options
  );
}

/**
 * Best-effort live clear. Prefer schedulePostQuitClear for authoritative logout.
 */
async function clearCursorAuth(options = {}) {
  const dbPath = findStateDb(options.extraRoots || []);
  if (!dbPath) {
    return { cleared: false, reason: "state.vscdb not found", dbPath: null };
  }

  const keys = authClearKeys();
  const size = fileSize(dbPath);
  let backupPath = null;
  if (size > 0 && size <= SQLJS_MAX_BYTES) {
    backupPath = `${dbPath}.cgl-lease-reclaim-${Date.now()}`;
    fs.copyFileSync(dbPath, backupPath);
  }

  const result = await mutateStateDb(dbPath, { deleteKeys: keys });
  return {
    cleared: true,
    dbPath,
    backupPath,
    via: result.via,
  };
}

/** Whether state.vscdb still holds Cursor access tokens. */
function hasInjectedAuth(options = {}) {
  const dbPath =
    options.dbPath || findStateDb(options.extraRoots || []);
  if (!dbPath) return false;
  const snap = readAuthSnapshot(dbPath);
  return Boolean(
    snap[AUTH_KEYS.accessToken] || snap[AUTH_KEYS.cursorAccessToken]
  );
}

/**
 * Live-clear auth keys and verify they are gone.
 * Cursor may still keep tokens in memory until restart — callers decide whether
 * to hard-quit. Soft clear is enough when server already revoked the session.
 */
async function clearCursorAuthSoft(options = {}) {
  const live = await clearCursorAuth(options);
  if (!live.dbPath) {
    return { ...live, verified: false };
  }
  const verified = !hasInjectedAuth({ dbPath: live.dbPath });
  return { ...live, verified };
}

module.exports = {
  AUTH_KEYS,
  findStateDb,
  injectCursorAuth,
  clearCursorAuth,
  clearCursorAuthSoft,
  hasInjectedAuth,
  resolveCursorDesktopExe,
  schedulePostQuitReinjection,
  schedulePostQuitClear,
  schedulePostQuitMutation,
  waitForWorkerBoot,
  cursorUserDataRoots,
  describeSearchPaths,
  mutateStateDb,
  readAuthSnapshot,
  verifyAuthMutation,
  buildAuthMutation,
  buildAuthMutationForLease: buildAuthMutation,
  buildDecoyRefreshToken,
  resolveInjectRefreshToken,
  authClearKeys,
};
