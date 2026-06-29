/*
 * Bluesky login-broker.
 *
 * Architecture (variant A+, web-app-bluesky):
 *
 *     Browser
 *       │
 *       │  https://web.bluesky.<DOMAIN>/...
 *       ▼
 *     nginx (front-proxy)
 *       │
 *       ▼
 *     oauth2-proxy ── (Keycloak OIDC) ──► Keycloak realm
 *       │
 *       │  forward + X-Forwarded-User / X-Forwarded-Email
 *       ▼
 *     login-broker (this process)
 *       │
 *       │  - Auto-provision PDS account on first visit
 *       │    via com.atproto.server.createAccount
 *       │  - Encrypt the synthesised app-password with AES-256-GCM
 *       │    and store it as a Keycloak user attribute
 *       │  - Decrypt the password, call createSession against the PDS
 *       │  - Render an HTML handoff page that drops the resulting
 *       │    session JWTs into localStorage["BSKY_STORAGE"] and
 *       │    redirects to "/" (the social-app)
 *       ▼
 *     social-app  (the official @bluesky-social/social-app web UI)
 *
 * The encrypted app-password never leaves the broker as cleartext
 * over the wire; the synthesised password lives encrypted-at-rest in
 * Keycloak and is only decrypted in-process when needed for a
 * createSession call. This is the scope of the encryption hardening
 * agreed in the autonomous iteration with the operator (no plaintext
 * in Keycloak).
 *
 * Future hardening (out-of-scope for this iteration, tracked in the
 * doc 013 "Future Hardening" section): rotating the encryption key,
 * moving the app-password into an external secrets store, and
 * registering a Keycloak event-listener SPI so the encrypted
 * attribute also lives on the user record in case the broker is
 * down.
 */

"use strict";

const http = require("node:http");
const https = require("node:https");
const crypto = require("node:crypto");
const { URL } = require("node:url");

// --- Configuration --------------------------------------------------

const CONFIG = {
  listenPort: parseInt(process.env.BROKER_PORT || "8080", 10),
  socialAppUrl: requireEnv("SOCIAL_APP_URL"),
  pdsUrl: requireEnv("PDS_URL"),
  pdsHandleDomain: requireEnv("PDS_HANDLE_DOMAIN"),
  pdsInviteCode: process.env.PDS_INVITE_CODE || "",
  // Optional: enables the broker to recover from `Handle already
  // taken` (cross-variant deploys / broker restart with persistent
  // PDS volume) by resetting the existing account's password via
  // the PDS admin API. When unset, the broker still works for the
  // first-deploy path but a recovery is impossible.
  pdsAdminPassword: process.env.PDS_ADMIN_PASSWORD || "",
  encryptionKey: decodeKey(requireEnv("BLUESKY_BRIDGE_ENCRYPTION_KEY")),
  handoffCookieName: process.env.HANDOFF_COOKIE_NAME || "bsky_handoff_done",
  handoffCookieMaxAgeSec: parseInt(process.env.HANDOFF_COOKIE_MAX_AGE || "3300", 10),
  insecureTls: (process.env.INSECURE_TLS || "false").toLowerCase() === "true",
  logoutPath: "/sso/logout"
};

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env: ${name}`);
  }
  return value;
}

function decodeKey(value) {
  // Accept the project-canonical `base64:<...>` prefix (algorithm
  // `base64_prefixed_32` in meta/schema.yml) so the same vaulted
  // value flows through the env without further mangling.
  let b64 = value || "";
  if (b64.startsWith("base64:")) b64 = b64.slice(7);
  const buf = Buffer.from(b64, "base64");
  if (buf.length !== 32) {
    throw new Error(`BLUESKY_BRIDGE_ENCRYPTION_KEY must decode to 32 bytes, got ${buf.length}`);
  }
  return buf;
}

// --- AES-256-GCM helpers --------------------------------------------

function encrypt(plaintext) {
  const nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", CONFIG.encryptionKey, nonce);
  const ct = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([nonce, ct, tag]).toString("base64");
}

function decrypt(b64) {
  const blob = Buffer.from(b64, "base64");
  if (blob.length < 12 + 16) {
    throw new Error("ciphertext too short");
  }
  const nonce = blob.subarray(0, 12);
  const tag = blob.subarray(blob.length - 16);
  const ct = blob.subarray(12, blob.length - 16);
  const decipher = crypto.createDecipheriv("aes-256-gcm", CONFIG.encryptionKey, nonce);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]).toString("utf8");
}

// --- HTTP helpers ---------------------------------------------------

function fetchJson(method, urlString, opts = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlString);
    const isHttps = u.protocol === "https:";
    const lib = isHttps ? https : http;
    const headers = Object.assign({ "Accept": "application/json" }, opts.headers || {});
    let body = opts.body;
    if (body && typeof body !== "string" && !(body instanceof Buffer)) {
      body = JSON.stringify(body);
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
    }
    if (body) {
      headers["Content-Length"] = Buffer.byteLength(body);
    }
    const req = lib.request({
      method,
      hostname: u.hostname,
      port: u.port || (isHttps ? 443 : 80),
      path: u.pathname + u.search,
      headers,
      rejectUnauthorized: !CONFIG.insecureTls
    }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const buf = Buffer.concat(chunks);
        const ct = (res.headers["content-type"] || "").split(";")[0].trim();
        let parsed = null;
        if (buf.length > 0 && ct === "application/json") {
          try { parsed = JSON.parse(buf.toString("utf8")); } catch { /* tolerate */ }
        }
        resolve({ status: res.statusCode || 0, body: parsed, raw: buf.toString("utf8") });
      });
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

// --- PDS client -----------------------------------------------------

function sanitiseHandle(username) {
  if (!username) return "kc-user";
  const lower = username.toLowerCase().slice(0, 256);
  const mapped = lower.replace(/[^a-z0-9-]+/g, "-").replace(/^-+/, "").replace(/-+$/, "");
  // PDS reserves common service handles ("administrator", "admin", "api",
  // "support", "www", "bsky", "atproto", etc.) and rejects createAccount
  // with `HandleNotAvailable: Reserved handle`. Always prefix with `kc-`
  // so Keycloak-derived handles cannot collide with that reserved list,
  // independent of which usernames the realm carries.
  return `kc-${mapped || "user"}`;
}

async function pdsCreateAccount({ handle, email, password }) {
  const url = `${CONFIG.pdsUrl}/xrpc/com.atproto.server.createAccount`;
  const body = { handle, email, password };
  if (CONFIG.pdsInviteCode) {
    body.inviteCode = CONFIG.pdsInviteCode;
  }
  const res = await fetchJson("POST", url, { body });
  if (res.status < 200 || res.status >= 300) {
    const err = new Error(`PDS createAccount failed: status=${res.status} body=${res.raw}`);
    err.pdsStatus = res.status;
    err.pdsBody = res.body;
    throw err;
  }
  return res.body;
}

async function pdsCreateSession({ handle, password }) {
  const url = `${CONFIG.pdsUrl}/xrpc/com.atproto.server.createSession`;
  const res = await fetchJson("POST", url, { body: { identifier: handle, password } });
  if (res.status < 200 || res.status >= 300) {
    throw new Error(`PDS createSession failed: status=${res.status} body=${res.raw}`);
  }
  return res.body;
}

async function pdsResolveHandle(handle) {
  const url = `${CONFIG.pdsUrl}/xrpc/com.atproto.identity.resolveHandle?handle=${encodeURIComponent(handle)}`;
  const res = await fetchJson("GET", url);
  if (res.status !== 200 || !res.body || !res.body.did) {
    throw new Error(`PDS resolveHandle failed: status=${res.status} body=${res.raw}`);
  }
  return res.body.did;
}

// PDS admin API uses HTTP Basic auth with `admin:<PDS_ADMIN_PASSWORD>`.
// Used to recover from `Handle already taken` when the broker's
// in-process cache has been lost (broker container restart, or
// cross-variant deploy that shares the PDS data volume) but PDS
// still has the account from a previous broker session. Resetting
// the password lets us mint a fresh one we control.
async function pdsAdminUpdatePassword(did, newPassword) {
  if (!CONFIG.pdsAdminPassword) {
    throw new Error("PDS_ADMIN_PASSWORD not configured — cannot recover from Handle already taken");
  }
  const url = `${CONFIG.pdsUrl}/xrpc/com.atproto.admin.updateAccountPassword`;
  const auth = Buffer.from(`admin:${CONFIG.pdsAdminPassword}`).toString("base64");
  const res = await fetchJson("POST", url, {
    headers: { Authorization: `Basic ${auth}` },
    body: { did, password: newPassword }
  });
  if (res.status < 200 || res.status >= 300) {
    throw new Error(`PDS admin updateAccountPassword failed: status=${res.status} body=${res.raw}`);
  }
}

// --- High-level orchestration --------------------------------------

// Per-user PDS app-password / DID / handle cache, keyed by Keycloak
// username. In-memory, AES-256-GCM-encrypted at rest.
//
// We deliberately do NOT write the encrypted blob into Keycloak user
// attributes (the previous design): on a realm with LDAP federation
// in WRITABLE mode the bluesky_* attribute write triggers an LDAP
// schema-violating sync push and leaves the federated user in a
// partially-synced state, which then breaks subsequent direct OIDC
// logins for that user (every other realm-OIDC test in the matrix
// would regress as a side-effect of running the broker once). The
// broker is a single-instance sidecar so an in-memory map is enough;
// on broker restart the user re-creates a PDS app-password on first
// SSO visit. The previous app-password remains valid in PDS until
// rotated explicitly — acceptable for this auto-provision flow.
const sessionCache = new Map();

async function ensurePdsSession({ kcUsername, kcEmail }) {
  const fullHandle = `${sanitiseHandle(kcUsername)}.${CONFIG.pdsHandleDomain}`;
  const cached = sessionCache.get(kcUsername);
  let appPasswordEnc = cached ? cached.appPasswordEnc : null;
  let did = cached ? cached.did : null;
  if (!appPasswordEnc) {
    const synthesised = crypto.randomBytes(18).toString("base64url");
    try {
      const created = await pdsCreateAccount({
        handle: fullHandle,
        email: kcEmail || `${kcUsername}@bridge.local`,
        password: synthesised
      });
      did = created.did || did;
    } catch (err) {
      // Recover from `Handle already taken` — happens when the broker's
      // in-memory cache has been lost (container restart, cross-variant
      // deploy that shares the PDS data volume) but the PDS still has
      // the account from a previous broker session. Use the PDS admin
      // API to reset the password to a fresh value we control, so the
      // subsequent createSession works again.
      const isHandleTaken =
        err.pdsBody && err.pdsBody.error === "InvalidRequest" &&
        typeof err.pdsBody.message === "string" &&
        err.pdsBody.message.includes("Handle already taken");
      if (!isHandleTaken) throw err;
      did = await pdsResolveHandle(fullHandle);
      await pdsAdminUpdatePassword(did, synthesised);
    }
    appPasswordEnc = encrypt(synthesised);
    sessionCache.set(kcUsername, { appPasswordEnc, did, handle: fullHandle });
  }
  const password = decrypt(appPasswordEnc);
  const session = await pdsCreateSession({ handle: fullHandle, password });
  return {
    service: CONFIG.pdsUrl,
    did: session.did || did,
    handle: session.handle || fullHandle,
    email: kcEmail || `${kcUsername}@bridge.local`,
    emailConfirmed: true,
    accessJwt: session.accessJwt,
    refreshJwt: session.refreshJwt
  };
}

// --- HTTP server ----------------------------------------------------

function logSafe(v) {
  // eslint-disable-next-line no-control-regex -- intentional: strip control chars to prevent log injection
  return String(v).replace(/[\r\n]+/g, " ").replace(/[\x00-\x1f\x7f]/g, "");
}

function escapeHtml(v) {
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function parseCookies(req) {
  const out = Object.create(null);
  const header = req.headers["cookie"];
  if (!header) return out;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const key = part.slice(0, i).trim();
    if (key === "__proto__" || key === "prototype" || key === "constructor") continue;
    out[key] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

// Build a schema-compliant social-app storage payload (matches
// `bluesky-social/social-app@1.121.0` `state/persisted/schema.ts`
// defaults). Without ALL required keys present, social-app's
// `tryParse()` call uses zod `safeParse()` which returns failure
// and the persistence layer DROPS the entire stored value — the
// session never sticks. The `defaults` object below mirrors the
// upstream `defaults` constant verbatim plus our session.
function buildBskyStorage(session) {
  return {
    colorMode: "system",
    darkTheme: "dim",
    session: {
      accounts: [Object.assign({}, session, { active: true })],
      currentAccount: Object.assign({}, session, { active: true })
    },
    reminders: {},
    languagePrefs: {
      primaryLanguage: "en",
      contentLanguages: ["en"],
      postLanguage: "en",
      postLanguageHistory: ["en", "ja", "pt", "de"],
      appLanguage: "en"
    },
    requireAltTextEnabled: false,
    largeAltBadgeEnabled: false,
    externalEmbeds: {},
    mutedThreads: [],
    invites: { copiedInvites: [] },
    onboarding: { step: "Home" },
    hiddenPosts: [],
    pdsAddressHistory: [],
    disableHaptics: false,
    disableAutoplay: false,
    kawaii: false,
    hasCheckedForStarterPack: false,
    subtitlesEnabled: true,
    trendingDisabled: false,
    trendingVideoDisabled: false
  };
}

function renderHandoff(session, redirectTo) {
  const storageJson = JSON.stringify(buildBskyStorage(session));
  const safeRedirect = JSON.stringify(redirectTo || "/");
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Bluesky SSO handoff</title>
<meta name="referrer" content="no-referrer" />
<style>body{font-family:sans-serif;background:#001a33;color:#eef;margin:0;padding:2em;text-align:center}</style>
</head>
<body>
<p id="status">Signing you in to Bluesky…</p>
<script>
(function(){
  try {
    var storage = ${storageJson};
    localStorage.setItem("BSKY_STORAGE", JSON.stringify(storage));
    document.cookie = ${JSON.stringify(CONFIG.handoffCookieName)} + "=1; Path=/; Max-Age=" + ${JSON.stringify(CONFIG.handoffCookieMaxAgeSec)} + "; SameSite=Lax";
    window.location.replace(${safeRedirect});
  } catch (e) {
    document.getElementById("status").textContent = "SSO handoff error: " + (e && e.message ? e.message : e);
  }
})();
</script>
<noscript>This SSO handoff requires JavaScript.</noscript>
</body>
</html>`;
}

function endHtml(res, status, html) {
  res.writeHead(status, {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(html);
}

function endText(res, status, text, headers = {}) {
  res.writeHead(status, Object.assign({ "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" }, headers));
  res.end(text);
}

function proxyToSocialApp(req, res) {
  const upstream = new URL(CONFIG.socialAppUrl);
  const isHttps = upstream.protocol === "https:";
  const lib = isHttps ? https : http;
  const headers = Object.assign({}, req.headers);
  headers.host = upstream.host;
  const upstreamReq = lib.request({
    method: req.method,
    hostname: upstream.hostname,
    port: upstream.port || (isHttps ? 443 : 80),
    path: req.url,
    headers,
    rejectUnauthorized: !CONFIG.insecureTls
  }, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
    upstreamRes.pipe(res);
  });
  upstreamReq.on("error", (err) => {
    endText(res, 502, `social-app upstream error: ${escapeHtml(err.message)}`);
  });
  req.pipe(upstreamReq);
}

const server = http.createServer(async (req, res) => {
  const reqId = Math.random().toString(36).slice(2, 8);
  const reqStart = Date.now();
  console.log(`[broker:${reqId}] ${logSafe(req.method)} ${logSafe(req.url)} from=${logSafe(req.headers["x-forwarded-for"] || "?")} fwd-user=${logSafe(req.headers["x-forwarded-user"] || req.headers["x-forwarded-preferred-username"] || "-")}`);
  try {
    const requestUrl = new URL(req.url, "http://internal");
    const path = requestUrl.pathname;

    if (path === "/healthz") {
      endText(res, 200, "ok");
      return;
    }
    if (path === CONFIG.logoutPath) {
      // Clear our handoff cookie and forward to oauth2-proxy sign_out
      // which itself bounces to the OIDC end-session endpoint.
      res.writeHead(302, {
        "Set-Cookie": `${CONFIG.handoffCookieName}=; Path=/; Max-Age=0; SameSite=Lax`,
        "Location": "/oauth2/sign_out"
      });
      res.end();
      return;
    }

    const cookies = parseCookies(req);
    if (cookies[CONFIG.handoffCookieName] === "1") {
      console.log(`[broker:${reqId}] handoff cookie present → proxying to social-app (${Date.now() - reqStart}ms)`);
      proxyToSocialApp(req, res);
      return;
    }

    // Need a fresh handoff. The OIDC identity comes from oauth2-proxy
    // forwarded headers — without them the broker cannot proceed and
    // the request is rejected.
    const kcUsername = (req.headers["x-forwarded-preferred-username"] || req.headers["x-forwarded-user"] || "").toString();
    const kcEmail = (req.headers["x-forwarded-email"] || "").toString();
    if (!kcUsername) {
      console.log(`[broker:${reqId}] missing X-Forwarded-User → 401 (${Date.now() - reqStart}ms)`);
      endHtml(res, 401, `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><title>Bluesky login required</title></head><body><p>Missing X-Forwarded-User from oauth2-proxy. Refusing handoff.</p></body></html>`);
      return;
    }

    const session = await ensurePdsSession({ kcUsername, kcEmail });
    console.log(`[broker:${reqId}] PDS session ready did=${logSafe(session.did)} handle=${logSafe(session.handle)} hasAccessJwt=${!!session.accessJwt} (${Date.now() - reqStart}ms)`);
    const html = renderHandoff(session, requestUrl.pathname + (requestUrl.search || ""));
    endHtml(res, 200, html);
    console.log(`[broker:${reqId}] handoff HTML sent (${Date.now() - reqStart}ms)`);
  } catch (err) {
    console.error(`[broker:${reqId}] error:`, err.stack || err.message);
    endText(res, 500, `Broker error: ${escapeHtml(err.message)}`);
  }
});

server.listen(CONFIG.listenPort, () => {
  console.log(`[broker] listening on ${CONFIG.listenPort}, social-app=${CONFIG.socialAppUrl}, pds=${CONFIG.pdsUrl}`);
});
