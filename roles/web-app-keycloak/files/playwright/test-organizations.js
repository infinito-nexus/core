const { createHash, randomBytes, randomUUID } = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");
const {
  apiFetchOnion,
  decodeDotenvQuotedValue,
  keycloakAdminToken,
  normalizeBaseUrl,
  requireDotenvValue,
  waitForEmailInMailbox,
  webmailSsoLogin,
} = require("./personas");
const { TASK_FINISHED, WORKSPACE_RESULT_LINE, WORKSPACE_RUN_MS, workspaceSurvey } = require("./personas/utils/workspace");

const issuerBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.ISSUER_BASE_URL, "ISSUER_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME");
const superAdminPassword = requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const emailSmtp = requireDotenvValue(process.env.KEYCLOAK_EMAIL_SMTP, "KEYCLOAK_EMAIL_SMTP") === "true";
const emailMailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
const webmailBaseUrl = normalizeBaseUrl(process.env.WEBMAIL_BASE_URL);
const organizationsEnabled =
  requireDotenvValue(process.env.KEYCLOAK_ORGANIZATIONS_ENABLED, "KEYCLOAK_ORGANIZATIONS_ENABLED") === "true";
const workspacesEnabled = process.env.SEMAPHORE_WORKSPACES_ENABLED === "true";
const workspacesClientId = requireDotenvValue(process.env.KEYCLOAK_WORKSPACES_CLIENT_ID, "KEYCLOAK_WORKSPACES_CLIENT_ID");
const rolesClaim = requireDotenvValue(process.env.KEYCLOAK_WORKSPACE_ROLES_CLAIM, "KEYCLOAK_WORKSPACE_ROLES_CLAIM");
const membersClientId = requireDotenvValue(
  process.env.KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ID,
  "KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ID",
);
const membersClientSecret = organizationsEnabled
  ? requireDotenvValue(process.env.KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_SECRET, "KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_SECRET")
  : "";
const recipientAttribute = requireDotenvValue(
  process.env.KEYCLOAK_EXPORT_RECIPIENT_ATTRIBUTE,
  "KEYCLOAK_EXPORT_RECIPIENT_ATTRIBUTE",
);
const groupClaim = requireDotenvValue(process.env.KEYCLOAK_RBAC_GROUP_CLAIM, "KEYCLOAK_RBAC_GROUP_CLAIM");
const rbacRoot = requireDotenvValue(process.env.KEYCLOAK_RBAC_GROUP_NAME, "KEYCLOAK_RBAC_GROUP_NAME");
const semaphoreOperatorGroup = requireDotenvValue(
  process.env.SEMAPHORE_OPERATOR_GROUP_PATH,
  "SEMAPHORE_OPERATOR_GROUP_PATH",
);
const storeClientId = decodeDotenvQuotedValue(process.env.KEYCLOAK_STORE_CLIENT_ID);
const semaphoreClientId = decodeDotenvQuotedValue(process.env.SEMAPHORE_CLIENT_ID);
const openbaoClientId = decodeDotenvQuotedValue(process.env.OPENBAO_CLIENT_ID);
const giteaClientId = decodeDotenvQuotedValue(process.env.GITEA_CLIENT_ID);
const workspaceTasks = organizationsEnabled && workspacesEnabled && Boolean(storeClientId);
const semaphoreBaseUrl = workspaceTasks
  ? normalizeBaseUrl(requireDotenvValue(process.env.SEMAPHORE_BASE_URL, "SEMAPHORE_BASE_URL"))
  : "";
const workspacesProject = workspaceTasks
  ? requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PROJECT, "SEMAPHORE_WORKSPACES_PROJECT")
  : "";
const openbaoBaseUrl = workspaceTasks
  ? normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"))
  : "";
const playwrightAppRole = workspaceTasks
  ? {
      role_id: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_ROLE_ID, "OPENBAO_PLAYWRIGHT_ROLE_ID"),
      secret_id: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SECRET_ID, "OPENBAO_PLAYWRIGHT_SECRET_ID"),
    }
  : null;
const playwrightLogins = workspaceTasks
  ? {
      mount: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_MOUNT, "OPENBAO_PLAYWRIGHT_MOUNT"),
      semaphore: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH, "OPENBAO_PLAYWRIGHT_SEMAPHORE_PATH"),
      store: requireDotenvValue(process.env.OPENBAO_PLAYWRIGHT_STORE_PATH, "OPENBAO_PLAYWRIGHT_STORE_PATH"),
    }
  : null;
const giteaBaseUrl = giteaClientId
  ? normalizeBaseUrl(requireDotenvValue(process.env.GITEA_BASE_URL, "GITEA_BASE_URL"))
  : "";

const realmPath = encodeURIComponent(realmName);
const realmUrl = `${issuerBaseUrl}/realms/${realmPath}`;
const adminUrl = `${issuerBaseUrl}/admin/realms/${realmPath}`;
const tokenUrl = `${realmUrl}/protocol/openid-connect/token`;
const ROLES = ["Owner", "Admin", "Operator", "Billing", "Viewer"];
const MARKER = "workspace.id";
const PENDING = "workspace.pending.";
const INVITE = "workspace.invite.";
const PROBE_PREFIX = "orgprobe";
const PROBE_CALLBACK = "orgprobe/callback";
const STORE_SCOPE = "openid organization:*";
const ACCOUNT_CONSOLE = "account-console";
const REALM_MANAGEMENT = "realm-management";
const EVENT_RIGHTS = ["manage-events", "manage-realm"];
const AGE_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
const ACTION_TOKEN_LINK = "a[href*='/login-actions/action-token']";
const CALL_MS = 30_000;
const TOKEN_REFRESH_MS = 30_000;
const CLOCK_SLACK_MS = 2_000;
const MEMBERS_RUN_MS = 300_000;
const MAIL_MS = 180_000;
const FLOW_MS = 300_000;
const TEARDOWN_STEP_MS = 120_000;

const WITHOUT_ORGANIZATIONS = "KEYCLOAK_ORGANIZATIONS_ENABLED=false";
const WITHOUT_WORKSPACES = "SEMAPHORE_WORKSPACES_ENABLED=false: no Workspaces project runs the workspace tasks";
const WITHOUT_STORE = "KEYCLOAK_STORE_CLIENT_ID is empty: the deployment holds no store client";
const WITHOUT_SMTP = "KEYCLOAK_EMAIL_SMTP=false: Keycloak sends no invitation without SMTP";
const WITH_MAILBOX_POLICY = "KEYCLOAK_EMAIL_POLICY=mailbox: an invitee address lies outside the mail domain";
const WITHOUT_WEBMAIL = "WEBMAIL_BASE_URL is empty: no webmail reads the invitation";
const SPLIT_REALM = "clearnet webmail with an onion OIDC issuer: unreachable from one browser";
const WITHOUT_SEMAPHORE_CLIENT = "SEMAPHORE_CLIENT_ID is empty: Semaphore signs in through no Keycloak client";
const WITHOUT_OPENBAO_CLIENT = "OPENBAO_CLIENT_ID is empty: OpenBao signs in through no Keycloak client";
const WITHOUT_GITEA_CLIENT = "GITEA_CLIENT_ID is empty: Gitea signs in through no Keycloak client";

function bearer(token) {
  return { Authorization: `Bearer ${token}` };
}

function jwtPayload(token) {
  const part = String(token).split(".")[1];
  expect(part, "the token must be a JWT").toBeTruthy();
  return JSON.parse(Buffer.from(part, "base64url").toString("utf8"));
}

function audiences(payload) {
  return [].concat(payload.aud ?? []);
}

function aliasesOf(claim) {
  if (Array.isArray(claim)) {
    return [...claim].sort();
  }
  if (claim && typeof claim === "object") {
    return Object.keys(claim).sort();
  }
  return claim ? [claim] : [];
}

function workspaceRolesIn(payload) {
  return [...(payload[rolesClaim] ?? [])].sort();
}

function rolesOfWorkspace(payload, workspace) {
  return workspaceRolesIn(payload).filter((role) => role.startsWith(`${workspace}:`));
}

function probeAddress(tag) {
  return `${PROBE_PREFIX}${tag}-${randomBytes(4).toString("hex")}@example.net`;
}

function subAddress(address, tag) {
  const at = address.lastIndexOf("@");
  return `${address.slice(0, at)}+${PROBE_PREFIX}${tag}${randomBytes(3).toString("hex")}${address.slice(at)}`.toLowerCase();
}

function probePassword() {
  return `${randomBytes(18).toString("base64url")}Aa1!`;
}

function ageRecipient() {
  return `age1${[...randomBytes(58)].map((byte) => AGE_ALPHABET[byte % AGE_ALPHABET.length]).join("")}`;
}

function htmlAttribute(value) {
  return value
    .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCharCode(parseInt(code, 16)))
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&");
}

function formAction(html) {
  const match = /<form\b[^>]*\baction="([^"]*\/login-actions\/authenticate[^"]*)"/i.exec(html);
  return match ? htmlAttribute(match[1]) : "";
}

function actionTokenHref(html) {
  const match = /href="([^"]*\/login-actions\/action-token[^"]*)"/i.exec(html);
  return match ? htmlAttribute(match[1]) : "";
}

function withoutTrailingSlash(url) {
  return String(url).replace(/\/+$/, "");
}

function attributesOf(representation) {
  return representation.attributes ?? {};
}

function pendingEntries(organization) {
  const attributes = attributesOf(organization);
  const entries = {};
  for (const role of ROLES) {
    for (const key of attributes[`${PENDING}${role}`] ?? []) {
      entries[key] = { role, address: (attributes[`${INVITE}${key}`] ?? [])[0] };
    }
  }
  return entries;
}

function restClient(request, base, authorize) {
  const send = async (method, path, data) =>
    request.fetch(`${base}/${path}`, {
      method,
      headers: { ...(await authorize()), "Content-Type": "application/json", Accept: "application/json" },
      data,
      failOnStatusCode: false,
      timeout: resolveTimeout(CALL_MS),
    });
  const json = async (method, path, data, expected, message) => {
    const response = await send(method, path, data);
    expect([].concat(expected), `${message}: ${method} ${path} answered ${response.status()}`).toContain(
      response.status(),
    );
    const text = await response.text();
    return text ? JSON.parse(text) : null;
  };
  return { send, json };
}

function keycloakAdmin(request) {
  let token = "";
  let minted = 0;
  return restClient(request, adminUrl, async () => {
    if (!token || Date.now() - minted > TOKEN_REFRESH_MS) {
      token = await keycloakAdminToken(request, issuerBaseUrl, superAdminUsername, superAdminPassword);
      minted = Date.now();
    }
    return bearer(token);
  });
}

async function clientCredentials(request, clientId, secret) {
  return request.post(tokenUrl, {
    form: { grant_type: "client_credentials", client_id: clientId, client_secret: secret },
    timeout: resolveTimeout(CALL_MS),
  });
}

async function membersAccount(request) {
  const response = await clientCredentials(request, membersClientId, membersClientSecret);
  expect(response.status(), `${membersClientId} must receive a client-credentials token`).toBe(200);
  const token = (await response.json()).access_token;
  return restClient(request, adminUrl, async () => bearer(token));
}

async function userNamed(kc, username) {
  const found = await kc.json(
    "GET",
    `users?username=${encodeURIComponent(username)}&exact=true`,
    undefined,
    200,
    `looking ${username} up`,
  );
  return found.find((user) => user.username === username.toLowerCase());
}

async function removeUserNamed(kc, username) {
  const user = await userNamed(kc, username);
  if (user) {
    await kc.json("DELETE", `users/${user.id}`, undefined, [204, 404], `deleting ${username}`);
  }
}

async function createProbeUser(kc, name, email) {
  const username = `${PROBE_PREFIX}${name}`;
  await removeUserNamed(kc, username);
  const password = probePassword();
  const response = await kc.send("POST", "users", {
    username,
    email,
    firstName: "Organization",
    lastName: `Probe ${name}`,
    enabled: true,
    emailVerified: true,
    requiredActions: [],
    credentials: [{ type: "password", value: password, temporary: false }],
  });
  expect(response.status(), `creating ${username} must succeed`).toBe(201);
  const id = response.headers()["location"].split("/").pop();
  const created = await kc.json("GET", `users/${id}`, undefined, 200, `reading ${username}`);
  if ((created.requiredActions ?? []).length > 0) {
    await kc.json("PUT", `users/${id}`, { ...created, requiredActions: [] }, 204, `clearing the actions of ${username}`);
  }
  return { id, username, email, password };
}

async function clientNamed(kc, clientId) {
  const found = await kc.json(
    "GET",
    `clients?clientId=${encodeURIComponent(clientId)}&search=false`,
    undefined,
    200,
    `looking the client ${clientId} up`,
  );
  const client = found.find((candidate) => candidate.clientId === clientId);
  expect(client, `the realm must hold the client ${clientId}`).toBeTruthy();
  return client;
}

async function clientSecret(kc, client) {
  const body = await kc.json(
    "GET",
    `clients/${client.id}/client-secret`,
    undefined,
    200,
    `reading the secret of ${client.clientId}`,
  );
  expect(Boolean(body && body.value), `${client.clientId} must hold a client secret`).toBe(true);
  return body.value;
}

async function consumer(kc, clientId) {
  const client = await clientNamed(kc, clientId);
  return { client, secret: await clientSecret(kc, client) };
}

async function markedOrganizations(kc, workspace) {
  const query = new URLSearchParams({ q: `${MARKER}:${workspace}`, briefRepresentation: "false", first: "0", max: "10" });
  const found = await kc.json("GET", `organizations?${query}`, undefined, 200, `searching the marker ${workspace}`);
  return found.filter((organization) => (attributesOf(organization)[MARKER] ?? []).includes(workspace));
}

async function organizationsAliased(kc, alias) {
  const query = new URLSearchParams({ search: alias, exact: "true", briefRepresentation: "false", first: "0", max: "10" });
  const found = await kc.json("GET", `organizations?${query}`, undefined, 200, `searching the alias ${alias}`);
  return found.filter((organization) => organization.alias === alias);
}

async function theOrganization(kc, workspace) {
  const marked = await markedOrganizations(kc, workspace);
  expect(marked, `exactly one organization must carry the marker of ${workspace}`).toHaveLength(1);
  return marked[0];
}

async function readOrganization(kc, organizationId) {
  return kc.json("GET", `organizations/${organizationId}`, undefined, 200, `reading the organization ${organizationId}`);
}

async function organizationGroups(kc, organizationId) {
  const found = await kc.json(
    "GET",
    `organizations/${organizationId}/groups?briefRepresentation=false&first=0&max=100`,
    undefined,
    200,
    `listing the groups of ${organizationId}`,
  );
  return Object.fromEntries(found.map((group) => [group.name, group]));
}

async function holdersOf(kc, organizationId) {
  const groups = await organizationGroups(kc, organizationId);
  const holders = {};
  for (const role of ROLES) {
    expect(groups[role], `the organization ${organizationId} must hold the role group ${role}`).toBeTruthy();
    const members = await kc.json(
      "GET",
      `organizations/${organizationId}/groups/${groups[role].id}/members?first=0&max=100&briefRepresentation=true`,
      undefined,
      200,
      `listing the members of ${role}`,
    );
    holders[role] = new Set(members.map((member) => member.id));
  }
  return { groups, holders };
}

async function rolesOf(kc, organizationId, userId) {
  const { holders } = await holdersOf(kc, organizationId);
  return ROLES.filter((role) => holders[role].has(userId));
}

async function memberIds(kc, organizationId) {
  const members = await kc.json(
    "GET",
    `organizations/${organizationId}/members?first=0&max=100&briefRepresentation=true`,
    undefined,
    200,
    `listing the members of ${organizationId}`,
  );
  return members.map((member) => member.id).sort();
}

async function enrol(kc, organizationId, userId) {
  await kc.json(
    "POST",
    `organizations/${organizationId}/members`,
    JSON.stringify(userId),
    [201, 409],
    `making ${userId} a member of ${organizationId}`,
  );
}

async function ensureRole(kc, organizationId, role, userId) {
  await enrol(kc, organizationId, userId);
  const groups = await organizationGroups(kc, organizationId);
  await kc.json(
    "PUT",
    `organizations/${organizationId}/groups/${groups[role].id}/members/${userId}`,
    undefined,
    [201, 204, 409],
    `putting ${userId} into ${role}`,
  );
}

async function leaveRole(kc, organizationId, role, userId) {
  const groups = await organizationGroups(kc, organizationId);
  await kc.json(
    "DELETE",
    `organizations/${organizationId}/groups/${groups[role].id}/members/${userId}`,
    undefined,
    204,
    `taking ${userId} out of ${role}`,
  );
}

async function invitationsFor(kc, organizationId, address) {
  const query = new URLSearchParams({ email: address, first: "0", max: "10" });
  const found = await kc.json(
    "GET",
    `organizations/${organizationId}/invitations?${query}`,
    undefined,
    200,
    `listing the invitations of ${organizationId}`,
  );
  return found.filter((invitation) => String(invitation.email).toLowerCase() === address);
}

async function workspaceClientRoles(kc, clientUuid, workspace) {
  const found = await kc.json(
    "GET",
    `clients/${clientUuid}/roles?search=${encodeURIComponent(workspace)}&first=0&max=100&briefRepresentation=true`,
    undefined,
    200,
    `listing the client roles of ${workspace}`,
  );
  return found
    .filter((role) => role.name.startsWith(`${workspace}:`))
    .map((role) => ({ id: role.id, name: role.name }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

async function structureOf(kc, organizationId, clientUuid, workspace) {
  const groups = Object.values(await organizationGroups(kc, organizationId))
    .map((group) => ({
      id: group.id,
      name: group.name,
      mapped: [...((group.clientRoles ?? {})[workspacesClientId] ?? [])].sort(),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
  return { groups, roles: await workspaceClientRoles(kc, clientUuid, workspace) };
}

async function adminEventsIn(kc, window) {
  const query = new URLSearchParams({ dateFrom: String(window.from), dateTo: String(window.to), first: "0", max: "1000" });
  const events = await kc.json("GET", `admin-events?${query}`, undefined, 200, "reading the admin events");
  return events.filter((event) => event.time >= window.from && event.time <= window.to);
}

function windowOf(run) {
  return { from: run.started - CLOCK_SLACK_MS, to: run.finished + CLOCK_SLACK_MS };
}

function eventPath(event) {
  return decodeURIComponent(event.resourcePath ?? "");
}

function redirectFor(client) {
  const pattern = (client.redirectUris ?? []).find((uri) => uri.endsWith("/*"));
  expect(pattern, `${client.clientId} must accept a redirect URI ending in /*`).toBeTruthy();
  const absolute = pattern.startsWith("/") ? `${issuerBaseUrl}${pattern}` : pattern;
  return `${absolute.slice(0, -1)}${PROBE_CALLBACK}`;
}

async function submitLogin(request, client, user, scope) {
  const verifier = randomBytes(32).toString("base64url");
  const state = randomUUID();
  const redirectUri = redirectFor(client);
  const query = new URLSearchParams({
    client_id: client.clientId,
    redirect_uri: redirectUri,
    response_type: "code",
    scope,
    state,
    nonce: randomUUID(),
    code_challenge: createHash("sha256").update(verifier).digest("base64url"),
    code_challenge_method: "S256",
  });
  let response = await request.get(`${realmUrl}/protocol/openid-connect/auth?${query}`, {
    maxRedirects: 0,
    timeout: resolveTimeout(CALL_MS),
  });
  if (response.status() === 200) {
    const action = formAction(await response.text());
    expect(action, `the sign-in page of ${client.clientId} must show the login form`).toBeTruthy();
    response = await request.post(action, {
      form: { username: user.username, password: user.password, credentialId: "" },
      maxRedirects: 0,
      timeout: resolveTimeout(CALL_MS),
    });
  }
  return { response, verifier, state, redirectUri };
}

async function authorize(request, client, user, scope) {
  const { response, verifier, state, redirectUri } = await submitLogin(request, client, user, scope);
  expect(response.status(), `${user.username} signing in to ${client.clientId} must be redirected back`).toBe(302);
  const location = new URL(response.headers()["location"], issuerBaseUrl);
  expect(`${location.origin}${location.pathname}`, `the redirect of ${client.clientId} must reach its redirect URI`).toBe(
    redirectUri,
  );
  expect(location.searchParams.get("state"), `the redirect of ${client.clientId} must return its state`).toBe(state);
  const code = location.searchParams.get("code");
  expect(code, `the redirect of ${client.clientId} must carry a code`).toBeTruthy();
  return { code, verifier, redirectUri };
}

async function exchange(request, client, secret, grant) {
  const form = {
    grant_type: "authorization_code",
    code: grant.code,
    redirect_uri: grant.redirectUri,
    client_id: client.clientId,
    code_verifier: grant.verifier,
  };
  const response = await request.post(tokenUrl, {
    form: secret ? { ...form, client_secret: secret } : form,
    timeout: resolveTimeout(CALL_MS),
  });
  expect(response.status(), `the code of ${client.clientId} must exchange for tokens`).toBe(200);
  return response.json();
}

async function signIn(browser, target, user, scope) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    return await exchange(context.request, target.client, target.secret, await authorize(context.request, target.client, user, scope));
  } finally {
    await context.close();
  }
}

async function userinfo(request, accessToken) {
  const response = await request.get(`${realmUrl}/protocol/openid-connect/userinfo`, {
    headers: bearer(accessToken),
    timeout: resolveTimeout(CALL_MS),
  });
  expect(response.status(), "the userinfo endpoint must answer the access token").toBe(200);
  return response.json();
}

async function playwrightLogin(request, path) {
  const send = (method, route, options) =>
    apiFetchOnion(request, `${openbaoBaseUrl}/v1/${route}`, {
      method,
      ...options,
      failOnStatusCode: false,
      timeout: resolveTimeout(CALL_MS),
    });
  const login = await send("POST", "auth/approle/login", { data: playwrightAppRole });
  expect(login.status(), "OpenBao must accept the Playwright AppRole").toBe(200);
  const headers = { "X-Vault-Token": (await login.json()).auth.client_token };
  try {
    const read = await send("GET", `${playwrightLogins.mount}/data/${path}`, { headers });
    expect(read.status(), `OpenBao must hand the Playwright AppRole the login ${playwrightLogins.mount}/${path}`).toBe(200);
    return (await read.json()).data.data;
  } finally {
    const revoke = await send("POST", "auth/token/revoke-self", { headers });
    expect(revoke.status(), "the OpenBao token of the Playwright AppRole must be revoked").toBe(204);
  }
}

async function semaphoreSession(request) {
  const breakglass = await playwrightLogin(request, playwrightLogins.semaphore);
  const call = async (method, route, data) => {
    const response = await apiFetchOnion(request, `${semaphoreBaseUrl}/api${route}`, {
      method,
      data,
      failOnStatusCode: false,
      timeout: resolveTimeout(CALL_MS),
    });
    expect(response.ok(), `Semaphore ${method} /api${route} answered ${response.status()}`).toBe(true);
    const body = await response.text();
    return body ? JSON.parse(body) : null;
  };
  const login = await apiFetchOnion(request, `${semaphoreBaseUrl}/api/auth/login`, {
    method: "POST",
    data: { auth: breakglass.username, password: breakglass.password },
    failOnStatusCode: false,
    timeout: resolveTimeout(CALL_MS),
  });
  expect(login.status(), "Semaphore must sign the break-glass account in").toBe(204);
  const project = (await call("GET", "/projects")).find((candidate) => candidate.name === workspacesProject);
  expect(project, `Semaphore must hold the project ${workspacesProject}`).toBeTruthy();
  const templates = Object.fromEntries(
    (await call("GET", `/project/${project.id}/templates`)).map((template) => [template.name, template.id]),
  );
  for (const name of ["workspace", "members", "user"]) {
    expect(templates[name], `${workspacesProject} must hold the template ${name}`).toBeTruthy();
  }
  return { call, projectId: project.id, templates };
}

async function runTask(sem, template, environment, budgetMs) {
  const started = Date.now();
  const task = await sem.call("POST", `/project/${sem.projectId}/tasks`, {
    template_id: sem.templates[template],
    environment: JSON.stringify(environment),
  });
  let record;
  await expect
    .poll(
      async () => {
        record = await sem.call("GET", `/project/${sem.projectId}/tasks/${task.id}`);
        return TASK_FINISHED.has(record.status);
      },
      { timeout: resolveTimeout(budgetMs), intervals: [3_000], message: `the ${template} task ${task.id} must finish` },
    )
    .toBe(true);
  const output = await sem.call("GET", `/project/${sem.projectId}/tasks/${task.id}/output`);
  const lines = output.map((line) => String(line.output).trim()).filter(Boolean);
  return { template, id: task.id, status: record.status, record, lines, started, finished: Date.now() };
}

function workspaceTask(sem, workspace, action) {
  return runTask(sem, "workspace", workspaceSurvey(workspace, action), WORKSPACE_RUN_MS);
}

function workspaceResult(run) {
  expect(run.status, `workspace task ${run.id} must succeed; its output is in Semaphore`).toBe("success");
  const line = [...run.lines].reverse().find((candidate) => WORKSPACE_RESULT_LINE.test(candidate));
  expect(line, `workspace task ${run.id} must print its result line`).toBeTruthy();
  return JSON.parse(line);
}

function membersTask(sem, workspace, action, fields = {}) {
  return runTask(
    sem,
    "members",
    { WORKSPACE: workspace, MEMBERS_ACTION: action, WORKSPACE_SUSPENDED: "false", ...fields },
    MEMBERS_RUN_MS,
  );
}

function eraseTask(sem, userId) {
  return runTask(sem, "user", { USER_ACTION: "erase", USER_ID: userId }, MEMBERS_RUN_MS);
}

function lastJson(run) {
  const line = run.lines.at(-1) ?? "";
  expect(line.startsWith("{"), `the ${run.template} task ${run.id} must end with one JSON object`).toBe(true);
  return JSON.parse(line);
}

function succeeded(run, label) {
  expect(run.status, `${label}: task ${run.id} ended ${run.status} with ${run.lines.at(-1)}`).toBe("success");
  return lastJson(run);
}

function refusedWith(run, workspace, reason, label) {
  expect(run.status, `${label}: task ${run.id} must end as error`).toBe("error");
  expect(lastJson(run), `${label}: task ${run.id} must refuse with ${reason}`).toEqual({ workspace, refused: reason });
}

function changeLines(run) {
  return run.lines.filter((line) => line.startsWith("change workspace="));
}

function semaphoreLines(run) {
  return run.lines.filter((line) => line.startsWith("semaphore "));
}

function memberEntry(line, userId) {
  const entry = line.members.find((member) => member.id === userId);
  expect(entry, `the membership line must name ${userId}`).toBeTruthy();
  return entry;
}

function storeVault(request) {
  const login = async () => {
    const response = await apiFetchOnion(request, `${openbaoBaseUrl}/v1/auth/approle/login`, {
      method: "POST",
      data: await playwrightLogin(request, playwrightLogins.store),
      failOnStatusCode: false,
      timeout: resolveTimeout(CALL_MS),
    });
    expect(response.status(), "the store AppRole must log in to OpenBao with the SecretID the deploy seeded").toBe(200);
    return (await response.json()).auth.client_token;
  };
  const send = async (method, path, data) =>
    apiFetchOnion(request, `${openbaoBaseUrl}/v1/platform/${path}`, {
      method,
      headers: { "X-Vault-Token": await login() },
      data,
      failOnStatusCode: false,
      timeout: resolveTimeout(CALL_MS),
    });
  return {
    async stage(workspace, key, email, role) {
      const response = await send("POST", `data/store/invites/${workspace}/${key}`, { data: { email, role } });
      expect([200, 204], `staging the invitation ${key} must succeed`).toContain(response.status());
    },
    async unstage(workspace, key) {
      const response = await send("DELETE", `metadata/store/invites/${workspace}/${key}`);
      expect([204, 404], `deleting the staged invitation ${key} must succeed`).toContain(response.status());
    },
  };
}

async function semaphoreAccount(sem, username) {
  return (await sem.call("GET", "/users")).find((user) => user.username === username);
}

async function projectUserIds(sem, projectId) {
  return (await sem.call("GET", `/project/${projectId}/users`)).map((user) => user.id);
}

async function removeSemaphoreProbes(sem) {
  for (const user of await sem.call("GET", "/users")) {
    if (user.username.startsWith(PROBE_PREFIX)) {
      await sem.call("DELETE", `/users/${user.id}`);
    }
  }
}

async function appControlProject(sem) {
  for (const project of await sem.call("GET", "/projects")) {
    if (project.name.startsWith("ws-") || project.id === sem.projectId) {
      continue;
    }
    const templates = await sem.call("GET", `/project/${project.id}/templates`);
    if (templates.some((template) => template.name.startsWith("stop "))) {
      return project;
    }
  }
  throw new Error("Semaphore holds no app-control project with stop templates");
}

async function semaphoreOidcSignIn(request, user) {
  const options = await apiFetchOnion(request, `${semaphoreBaseUrl}/api/auth/login`, {
    method: "GET",
    failOnStatusCode: false,
    timeout: resolveTimeout(CALL_MS),
  });
  expect(options.status(), "Semaphore must describe its login options").toBe(200);
  const provider = ((await options.json()).oidc_providers ?? [])[0];
  expect(Boolean(provider && provider.id), "Semaphore must offer an OIDC provider").toBe(true);
  const form = await request.get(`${semaphoreBaseUrl}/api/auth/oidc/${encodeURIComponent(provider.id)}/login`, {
    timeout: resolveTimeout(CALL_MS),
  });
  expect(form.status(), "Semaphore's OIDC login must reach Keycloak's sign-in page").toBe(200);
  const action = formAction(await form.text());
  expect(action, "Semaphore's OIDC login must show Keycloak's login form").toBeTruthy();
  const landed = await request.post(action, {
    form: { username: user.username, password: user.password, credentialId: "" },
    timeout: resolveTimeout(CALL_MS),
  });
  expect(landed.ok(), `${user.username} must land back in Semaphore`).toBe(true);
  const me = await apiFetchOnion(request, `${semaphoreBaseUrl}/api/user`, {
    method: "GET",
    failOnStatusCode: false,
    timeout: resolveTimeout(CALL_MS),
  });
  expect(me.status(), `${user.username} must hold a Semaphore session after the OIDC sign-in`).toBe(200);
  expect((await me.json()).username, "the Semaphore session must belong to the workspace member").toBe(user.username);
}

async function giteaOidcSource(request) {
  const response = await request.get(`${giteaBaseUrl}/user/login`, { maxRedirects: 0, timeout: resolveTimeout(CALL_MS) });
  const location = response.headers()["location"] ?? "";
  const found = location.includes("/user/oauth2/")
    ? location
    : htmlAttribute((/href="([^"]*\/user\/oauth2\/[^"?#/]+)"/.exec(await response.text()) ?? ["", ""])[1]);
  expect(found, "Gitea's sign-in page must link its OIDC source").toBeTruthy();
  return new URL(found, giteaBaseUrl).pathname;
}

function bounded(promise, ms) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`a teardown step exceeded ${ms} ms`)), resolveTimeout(ms));
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

async function teardown(failed, steps) {
  const problems = [];
  for (const [ms, step] of steps) {
    try {
      await bounded(step(), ms);
    } catch (error) {
      problems.push(error.message);
    }
  }
  if (problems.length === 0) {
    return;
  }
  if (failed) {
    console.warn(`teardown after a failed test also failed: ${problems.join("; ")}`);
    return;
  }
  throw new Error(`teardown failed: ${problems.join("; ")}`);
}

function skipUnlessInvitationMail() {
  test.skip(!emailSmtp, WITHOUT_SMTP);
  test.skip(emailMailbox, WITH_MAILBOX_POLICY);
  test.skip(!webmailBaseUrl, WITHOUT_WEBMAIL);
  test.skip(isSplitRealmOidc(), SPLIT_REALM);
}

function registerWorkspaceTasks() {
  test.describe.serial("keycloak organizations: workspace tasks", () => {
    test.skip(!organizationsEnabled, WITHOUT_ORGANIZATIONS);
    test.skip(!workspacesEnabled, WITHOUT_WORKSPACES);
    test.skip(!storeClientId, WITHOUT_STORE);

    const ids = { X: randomUUID(), Y: randomUUID(), Z: randomUUID() };
    const state = { failed: false, applied: [], handmade: [], staged: [], projects: {} };
    let ctx = null;

    async function stage(workspace, key, email, role) {
      state.staged.push([workspace, key]);
      await ctx.vault.stage(workspace, key, email, role);
    }

    async function serviceAccountWrites(run) {
      return (await adminEventsIn(ctx.kc, windowOf(run))).filter(
        (event) => (event.authDetails ?? {}).userId === ctx.serviceAccountId,
      );
    }

    async function destroyWorkspace(workspace) {
      const result = workspaceResult(await workspaceTask(ctx.sem, workspace, "destroy"));
      expect(result.destroyed, `destroy of ${workspace} must report the workspace destroyed`).toBe(true);
      expect(await markedOrganizations(ctx.kc, workspace), `destroy of ${workspace} must leave no organization`).toEqual([]);
    }

    test.beforeAll(async ({ browser }) => {
      test.setTimeout(resolveTimeout(FLOW_MS));
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      const api = context.request;
      const kc = keycloakAdmin(api);
      const sem = await semaphoreSession(api);
      await removeSemaphoreProbes(sem);
      const biber = await userNamed(kc, biberUsername);
      expect(Boolean(biber && biber.email), "biber must hold an address the invitation mail can reach").toBe(true);
      const membersClient = await clientNamed(kc, membersClientId);
      const serviceAccount = await kc.json(
        "GET",
        `clients/${membersClient.id}/service-account-user`,
        undefined,
        200,
        `reading the service account of ${membersClientId}`,
      );
      const users = {};
      for (const name of ["owner", "second", "outsider", "admin", "claims", "remove", "erase"]) {
        users[name] = await createProbeUser(kc, name, probeAddress(name));
      }
      users.invitee = await createProbeUser(
        kc,
        "invitee",
        emailMailbox ? probeAddress("invitee") : subAddress(biber.email, "invitee"),
      );
      ctx = {
        context,
        api,
        kc,
        sem,
        users,
        vault: storeVault(api),
        store: await consumer(kc, storeClientId),
        semaphore: semaphoreClientId ? await consumer(kc, semaphoreClientId) : null,
        workspacesClient: await clientNamed(kc, workspacesClientId),
        serviceAccountId: serviceAccount.id,
      };
    });

    test.afterEach(async () => {
      state.failed ||= test.info().status !== test.info().expectedStatus;
    });

    test.afterAll(async () => {
      test.setTimeout(resolveTimeout(2 * (WORKSPACE_RUN_MS + TEARDOWN_STEP_MS) + 4 * TEARDOWN_STEP_MS));
      if (!ctx) {
        return;
      }
      await teardown(state.failed, [
        ...state.applied.map((workspace) => [WORKSPACE_RUN_MS + TEARDOWN_STEP_MS, () => destroyWorkspace(workspace)]),
        ...state.handmade.map((id) => [
          TEARDOWN_STEP_MS,
          () => ctx.kc.json("DELETE", `organizations/${id}`, undefined, [204, 404], "deleting the unmarked organization"),
        ]),
        ...state.staged.map(([workspace, key]) => [TEARDOWN_STEP_MS, () => ctx.vault.unstage(workspace, key)]),
        [TEARDOWN_STEP_MS, () => removeSemaphoreProbes(ctx.sem)],
        ...Object.values(ctx.users).map((user) => [TEARDOWN_STEP_MS, () => removeUserNamed(ctx.kc, user.username)]),
        [TEARDOWN_STEP_MS, () => ctx.context.close()],
      ]);
    });

    test("organizations: apply creates one marked organization", async () => {
      test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + 3 * MEMBERS_RUN_MS));
      const { kc, sem } = ctx;
      const { X, Z } = ids;
      expect(await markedOrganizations(kc, X), `no organization may carry the marker of ${X} before its apply`).toEqual([]);
      state.applied.push(X);
      const first = workspaceResult(await workspaceTask(sem, X, "apply"));
      expect([first.alias, first.workspace], "the apply result must name the workspace").toEqual([`ws-${X}`, X]);
      state.projects[X] = first.project_id;
      const created = await theOrganization(kc, X);
      expect(created.alias, "the organization must carry the alias ws-<id>").toBe(`ws-${X}`);
      expect(attributesOf(created)[MARKER], "the organization must carry the marker").toEqual([X]);
      expect((await organizationsAliased(kc, `ws-${X}`)).map((organization) => organization.id)).toEqual([created.id]);

      workspaceResult(await workspaceTask(sem, X, "apply"));
      expect(
        (await markedOrganizations(kc, X)).map((organization) => organization.id),
        "a second apply must find the organization by its marker",
      ).toEqual([created.id]);
      expect(
        (await organizationsAliased(kc, `ws-${X}`)).map((organization) => organization.id),
        "a second apply must create no organization",
      ).toEqual([created.id]);

      const handmade = await kc.send("POST", "organizations", { name: `ws-${Z}`, alias: `ws-${Z}`, enabled: true });
      expect(handmade.status(), "the super administrator must create the unmarked organization").toBe(201);
      const handmadeId = handmade.headers()["location"].split("/").pop();
      state.handmade.push(handmadeId);
      const snapshot = async () => ({
        organization: await readOrganization(kc, handmadeId),
        groups: Object.keys(await organizationGroups(kc, handmadeId)).sort(),
        roles: await workspaceClientRoles(kc, ctx.workspacesClient.id, Z),
        projects: (await sem.call("GET", "/projects")).filter((project) => project.name === `ws-${Z}`),
      });
      const before = await snapshot();
      const collision = await workspaceTask(sem, Z, "apply");
      expect(collision.status, `apply of ${Z}, whose alias an unmarked organization holds, must fail`).toBe("error");
      expect(await markedOrganizations(kc, Z), "the failed apply must mark no organization").toEqual([]);
      expect(await snapshot(), "the failed apply must change nothing").toEqual(before);
      const writes = (await adminEventsIn(kc, windowOf(collision))).filter(
        (event) => eventPath(event).includes(handmadeId) || eventPath(event).includes(Z),
      );
      expect(writes, "the admin events of the failed apply must hold no write").toEqual([]);
      await kc.json("DELETE", `organizations/${handmadeId}`, undefined, 204, "deleting the unmarked organization");
    });

    test("organizations: apply creates groups, roles and mappings once", async () => {
      test.setTimeout(resolveTimeout(2 * WORKSPACE_RUN_MS + 2 * MEMBERS_RUN_MS));
      const { kc, sem } = ctx;
      const { Y } = ids;
      state.applied.push(Y);
      const result = workspaceResult(await workspaceTask(sem, Y, "apply"));
      state.projects[Y] = result.project_id;
      const organization = await theOrganization(kc, Y);
      const clientUuid = ctx.workspacesClient.id;
      const structure = await structureOf(kc, organization.id, clientUuid, Y);
      expect(structure.groups.map((group) => group.name), "apply must create exactly the five role groups").toEqual(
        [...ROLES].sort(),
      );
      expect(structure.roles.map((role) => role.name), "apply must create exactly the five client roles").toEqual(
        ROLES.map((role) => `${Y}:${role}`).sort(),
      );
      for (const group of structure.groups) {
        expect(group.mapped, `the group ${group.name} must map exactly its own client role`).toEqual([`${Y}:${group.name}`]);
      }

      const again = await workspaceTask(sem, Y, "apply");
      workspaceResult(again);
      expect(await structureOf(kc, organization.id, clientUuid, Y), "a second apply must change nothing").toEqual(structure);
      const groupIds = structure.groups.map((group) => group.id);
      const writes = (await adminEventsIn(kc, windowOf(again))).filter((event) => {
        const path = eventPath(event);
        return (
          path.includes(organization.id) ||
          groupIds.some((id) => path.includes(id)) ||
          (path.startsWith(`clients/${clientUuid}/roles`) && path.includes(Y))
        );
      });
      expect(writes, "the admin events of the second apply must hold no write").toEqual([]);
    });

    test("members: add makes the first owner only", async () => {
      test.skip(!emailSmtp, WITHOUT_SMTP);
      test.setTimeout(resolveTimeout(6 * MEMBERS_RUN_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      const key = randomUUID();
      await stage(X, key, probeAddress("k0"), "Viewer");
      succeeded(await membersTask(sem, X, "invite", { INVITE_KEY: key }), "invite of a pending invitation");
      refusedWith(
        await membersTask(sem, X, "add", { WORKSPACE_MEMBER: users.owner.id }),
        X,
        "not_first",
        "add beside a pending invitation",
      );
      expect(await memberIds(kc, organization.id), "the refused add must add no member").toEqual([]);
      expect(
        Object.keys(pendingEntries(await readOrganization(kc, organization.id))),
        "the refused add must keep the pending invitation",
      ).toEqual([key]);
      succeeded(await membersTask(sem, X, "uninvite", { INVITE_KEY: key }), "uninvite of the pending invitation");
      await ctx.vault.unstage(X, key);

      const added = await membersTask(sem, X, "add", { WORKSPACE_MEMBER: users.owner.id });
      const line = succeeded(added, "add of the first member");
      expect(line, "the first member must be the only member, in Owner").toEqual({
        workspace: X,
        members: [{ id: users.owner.id, groups: ["Owner"], enabled: true }],
        pending: [],
      });
      expect(changeLines(added), "add must print each change").toEqual([
        `change workspace=${X} action=add user=${users.owner.id} change=joined_organization`,
        `change workspace=${X} action=add user=${users.owner.id} group=Owner change=joined`,
      ]);
      expect(await memberIds(kc, organization.id)).toEqual([users.owner.id]);
      expect(await rolesOf(kc, organization.id, users.owner.id)).toEqual(["Owner"]);

      const again = await membersTask(sem, X, "add", { WORKSPACE_MEMBER: users.owner.id });
      expect(succeeded(again, "second add"), "a second add must print the same membership").toEqual(line);
      expect([...changeLines(again), ...semaphoreLines(again)], "a second add must change nothing").toEqual([]);
      expect(await serviceAccountWrites(again), "a second add must write nothing to Keycloak").toEqual([]);

      refusedWith(
        await membersTask(sem, X, "add", { WORKSPACE_MEMBER: users.second.id }),
        X,
        "not_first",
        "add beside another member",
      );
      expect(await memberIds(kc, organization.id), "the refused add must add no member").toEqual([users.owner.id]);
    });

    test("members: role keeps exactly one role group", async () => {
      test.setTimeout(resolveTimeout(3 * MEMBERS_RUN_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      const second = users.second.id;
      await enrol(kc, organization.id, second);
      expect(await rolesOf(kc, organization.id, second), "the second member must start without a role group").toEqual([]);

      const toAdmin = succeeded(
        await membersTask(sem, X, "role", { WORKSPACE_MEMBER: second, WORKSPACE_ROLE: "Admin" }),
        "role to Admin",
      );
      expect(memberEntry(toAdmin, second).groups).toEqual(["Admin"]);
      expect(await rolesOf(kc, organization.id, second)).toEqual(["Admin"]);

      await ensureRole(kc, organization.id, "Viewer", second);
      expect(await rolesOf(kc, organization.id, second), "the member must hold two role groups before the move").toEqual([
        "Admin",
        "Viewer",
      ]);
      const toOperator = succeeded(
        await membersTask(sem, X, "role", { WORKSPACE_MEMBER: second, WORKSPACE_ROLE: "Operator" }),
        "role to Operator",
      );
      expect(memberEntry(toOperator, second).groups, "role must leave exactly the named role group").toEqual(["Operator"]);
      expect(await rolesOf(kc, organization.id, second)).toEqual(["Operator"]);

      const membersBefore = await memberIds(kc, organization.id);
      refusedWith(
        await membersTask(sem, X, "role", { WORKSPACE_MEMBER: users.outsider.id, WORKSPACE_ROLE: "Viewer" }),
        X,
        "not_member",
        "role of a user outside the workspace",
      );
      expect(await memberIds(kc, organization.id), "the refused role must change no membership").toEqual(membersBefore);
    });

    test("members: a disabled owner does not count", async () => {
      test.setTimeout(resolveTimeout(3 * MEMBERS_RUN_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      const [owner, second] = [users.owner.id, users.second.id];
      await ensureRole(kc, organization.id, "Owner", owner);
      await ensureRole(kc, organization.id, "Owner", second);
      const record = await kc.json("GET", `users/${second}`, undefined, 200, "reading the second owner");
      await kc.json("PUT", `users/${second}`, { ...record, enabled: false }, 204, "disabling the second owner");
      try {
        const listed = succeeded(await membersTask(sem, X, "list"), "list with a disabled owner");
        expect(memberEntry(listed, owner), "the enabled owner must show enabled").toMatchObject({
          groups: expect.arrayContaining(["Owner"]),
          enabled: true,
        });
        expect(memberEntry(listed, second), "the disabled owner must show enabled false").toMatchObject({
          groups: expect.arrayContaining(["Owner"]),
          enabled: false,
        });
        refusedWith(
          await membersTask(sem, X, "role", { WORKSPACE_MEMBER: owner, WORKSPACE_ROLE: "Admin" }),
          X,
          "last_owner",
          "moving the only enabled owner",
        );
        expect(await rolesOf(kc, organization.id, owner), "the refused move must keep the owner in Owner").toContain("Owner");
      } finally {
        await kc.json("PUT", `users/${second}`, { ...record, enabled: true }, 204, "enabling the second owner again");
      }
    });

    test("organizations: core writes keep the marker and the pending entries", async () => {
      test.skip(!emailSmtp, WITHOUT_SMTP);
      test.setTimeout(resolveTimeout(WORKSPACE_RUN_MS + 4 * MEMBERS_RUN_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      await ensureRole(kc, organization.id, "Owner", users.owner.id);
      await ensureRole(kc, organization.id, "Owner", users.second.id);
      const key = randomUUID();
      const address = probeAddress("k1");
      await stage(X, key, address, "Viewer");
      succeeded(await membersTask(sem, X, "invite", { INVITE_KEY: key }), "invite before the core writes");
      const kept = async () => {
        const current = await readOrganization(kc, organization.id);
        return { marker: attributesOf(current)[MARKER], entries: pendingEntries(current) };
      };
      const expected = { marker: [X], entries: { [key]: { role: "Viewer", address } } };
      expect(await kept(), "the invite must record its pending entry").toEqual(expected);

      succeeded(
        await membersTask(sem, X, "role", { WORKSPACE_MEMBER: users.second.id, WORKSPACE_ROLE: "Admin" }),
        "role during a pending invitation",
      );
      expect(await kept(), "members role must keep the marker and every pending entry").toEqual(expected);

      const applied = await workspaceTask(sem, X, "apply");
      workspaceResult(applied);
      expect(await kept(), "a second apply must keep the marker and every pending entry").toEqual(expected);
      const updates = (await adminEventsIn(kc, windowOf(applied))).filter(
        (event) =>
          event.resourceType === "ORGANIZATION" &&
          event.operationType === "UPDATE" &&
          eventPath(event) === `organizations/${organization.id}`,
      );
      expect(updates, "an apply on an existing organization must not update it").toEqual([]);

      succeeded(await membersTask(sem, X, "uninvite", { INVITE_KEY: key }), "uninvite after the core writes");
      await ctx.vault.unstage(X, key);
    });

    test("members: list shows one workspace and changes nothing", async () => {
      test.skip(!emailSmtp, WITHOUT_SMTP);
      test.setTimeout(resolveTimeout(3 * MEMBERS_RUN_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X, Y } = ids;
      const organization = await theOrganization(kc, Y);
      await ensureRole(kc, organization.id, "Admin", users.admin.id);
      const key = randomUUID();
      await stage(Y, key, probeAddress("k2"), "Viewer");
      succeeded(await membersTask(sem, Y, "invite", { INVITE_KEY: key }), "invite of the pending Viewer");

      const first = await membersTask(sem, Y, "list");
      const second = await membersTask(sem, Y, "list");
      const expected = {
        workspace: Y,
        members: [{ id: users.admin.id, groups: ["Admin"], enabled: true }],
        pending: [{ key, role: "Viewer" }],
      };
      expect(succeeded(first, "first list"), "list must show exactly the member and the pending invitation").toEqual(expected);
      expect(succeeded(second, "second list"), "a second list must show the same").toEqual(expected);
      expect(second.lines.at(-1), "both lists must print the same last line").toBe(first.lines.at(-1));
      for (const run of [first, second]) {
        expect(run.lines.join("\n"), `list task ${run.id} must name nothing of workspace X`).not.toContain(X);
        expect(await serviceAccountWrites(run), `the admin events of list task ${run.id} must hold no write`).toEqual([]);
      }
    });

    test("members: an invite keeps the address out of Semaphore", async () => {
      test.skip(!emailSmtp, WITHOUT_SMTP);
      test.setTimeout(resolveTimeout(3 * MEMBERS_RUN_MS + FLOW_MS));
      const { sem } = ctx;
      const { Y } = ids;
      const key = randomUUID();
      const address = probeAddress("k3");
      await stage(Y, key, address, "Viewer");
      const runs = [
        await membersTask(sem, Y, "invite", { INVITE_KEY: key }),
        await membersTask(sem, Y, "list"),
        await membersTask(sem, Y, "uninvite", { INVITE_KEY: key }),
      ];
      for (const run of runs) {
        succeeded(run, `members task ${run.id}`);
      }
      expect(JSON.stringify(runs[0].record), "the stored task input must be the one the spec sent").toContain(key);
      const template = await sem.call("GET", `/project/${sem.projectId}/templates/${sem.templates.members}`);
      expect(JSON.stringify(template).toLowerCase(), "the members survey must not hold the staged address").not.toContain(
        address,
      );
      for (const run of runs) {
        const stored = await sem.call("GET", `/project/${sem.projectId}/tasks/${run.id}`);
        const output = await sem.call("GET", `/project/${sem.projectId}/tasks/${run.id}/output`);
        expect(JSON.stringify(stored).toLowerCase(), `task ${run.id} must not store the staged address`).not.toContain(address);
        expect(JSON.stringify(output).toLowerCase(), `the log of task ${run.id} must not hold the staged address`).not.toContain(
          address,
        );
      }
      await ctx.vault.unstage(Y, key);
    });

    test("organizations: the flat claim lists each membership", async ({ browser }) => {
      test.skip(!semaphoreClientId, WITHOUT_SEMAPHORE_CLIENT);
      test.setTimeout(resolveTimeout(FLOW_MS));
      const { kc, users } = ctx;
      const { X, Y } = ids;
      const claims = users.claims;
      await ensureRole(kc, (await theOrganization(kc, X)).id, "Operator", claims.id);
      await ensureRole(kc, (await theOrganization(kc, Y)).id, "Viewer", claims.id);
      const tokens = await signIn(browser, ctx.store, claims, STORE_SCOPE);
      const answers = [
        ["access token", jwtPayload(tokens.access_token)],
        ["ID token", jwtPayload(tokens.id_token)],
        ["userinfo answer", await userinfo(ctx.api, tokens.access_token)],
      ];
      for (const [label, payload] of answers) {
        expect(workspaceRolesIn(payload), `the store's ${label} must list exactly both workspace roles`).toEqual(
          [`${X}:Operator`, `${Y}:Viewer`].sort(),
        );
        expect(aliasesOf(payload.organization), `the store's ${label} must name both organizations`).toEqual(
          [`ws-${X}`, `ws-${Y}`].sort(),
        );
      }
      const semaphoreTokens = await signIn(browser, ctx.semaphore, claims, "openid");
      for (const [label, token] of [
        ["access token", semaphoreTokens.access_token],
        ["ID token", semaphoreTokens.id_token],
      ]) {
        expect(jwtPayload(token)[rolesClaim], `a Semaphore ${label} must carry no workspace roles`).toBeUndefined();
      }
    });

    test("organizations: leaving a group drops its claim entry", async ({ browser }) => {
      test.setTimeout(resolveTimeout(FLOW_MS));
      const { kc, users } = ctx;
      const { X, Y } = ids;
      const claims = users.claims;
      const organization = await theOrganization(kc, X);
      await ensureRole(kc, organization.id, "Operator", claims.id);
      await ensureRole(kc, (await theOrganization(kc, Y)).id, "Viewer", claims.id);
      const before = jwtPayload((await signIn(browser, ctx.store, claims, STORE_SCOPE)).access_token);
      expect(workspaceRolesIn(before), "the member must hold both entries before leaving").toEqual(
        [`${X}:Operator`, `${Y}:Viewer`].sort(),
      );
      await leaveRole(kc, organization.id, "Operator", claims.id);
      const after = jwtPayload((await signIn(browser, ctx.store, claims, STORE_SCOPE)).access_token);
      expect(workspaceRolesIn(after), "the next token must drop the entry of the group left").toEqual([`${Y}:Viewer`]);
    });

    test("organizations: workspace roles grant nothing on the platform", async ({ browser }) => {
      test.skip(!semaphoreClientId, WITHOUT_SEMAPHORE_CLIENT);
      test.setTimeout(resolveTimeout(FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const operator = users.claims;
      await ensureRole(kc, (await theOrganization(kc, X)).id, "Operator", operator.id);
      const groups = await kc.json(
        "GET",
        `users/${operator.id}/groups?briefRepresentation=true&first=0&max=100`,
        undefined,
        200,
        "listing the groups of the workspace Operator",
      );
      expect(
        groups.filter((group) => String(group.path).startsWith(`${rbacRoot}/`)),
        "a workspace Operator must hold no platform RBAC group",
      ).toEqual([]);
      const tokens = await signIn(browser, ctx.semaphore, operator, "openid");
      for (const token of [tokens.access_token, tokens.id_token]) {
        const held = [].concat(jwtPayload(token)[groupClaim] ?? []).map(String);
        expect(held, "the Semaphore token must carry no platform operator group").not.toContain(semaphoreOperatorGroup);
        expect(held.filter((path) => path.startsWith(`${rbacRoot}/`)), "the Semaphore token must carry no RBAC group").toEqual(
          [],
        );
      }
      const appControl = await appControlProject(sem);
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        await semaphoreOidcSignIn(context.request, operator);
        const listed = await apiFetchOnion(context.request, `${semaphoreBaseUrl}/api/projects`, {
          method: "GET",
          failOnStatusCode: false,
          timeout: resolveTimeout(CALL_MS),
        });
        expect(listed.status(), "the workspace Operator must list projects").toBe(200);
        expect(
          (await listed.json()).map((project) => project.id),
          "the app-control project must not be listed to a workspace Operator",
        ).not.toContain(appControl.id);
        const direct = await apiFetchOnion(context.request, `${semaphoreBaseUrl}/api/project/${appControl.id}/templates`, {
          method: "GET",
          failOnStatusCode: false,
          timeout: resolveTimeout(CALL_MS),
        });
        expect([401, 403, 404], "Semaphore's app-control project must deny a workspace Operator").toContain(direct.status());
      } finally {
        await context.close();
      }
    });

    test("clients: a token for one consumer is refused by another", async ({ browser }) => {
      test.skip(!semaphoreClientId, WITHOUT_SEMAPHORE_CLIENT);
      test.skip(!openbaoClientId, WITHOUT_OPENBAO_CLIENT);
      test.skip(!giteaClientId, WITHOUT_GITEA_CLIENT);
      test.setTimeout(resolveTimeout(FLOW_MS));
      const user = ctx.users.claims;
      const tokens = await signIn(browser, ctx.semaphore, user, "openid");
      expect(audiences(jwtPayload(tokens.id_token)), "the ID token must name Semaphore's client alone").toEqual([
        semaphoreClientId,
      ]);

      const openbao = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const direct = await apiFetchOnion(openbao.request, `${openbaoBaseUrl}/v1/auth/oidc/login`, {
          method: "POST",
          data: { jwt: tokens.id_token },
          failOnStatusCode: false,
          timeout: resolveTimeout(CALL_MS),
        });
        expect(direct.status(), "OpenBao's OIDC login must refuse an ID token minted for Semaphore").toBe(400);
        expect((await direct.json()).auth, "the refused login must issue no OpenBao token").toBeFalsy();
        const started = await apiFetchOnion(openbao.request, `${openbaoBaseUrl}/v1/auth/oidc/oidc/auth_url`, {
          method: "POST",
          data: { role: "", redirect_uri: `${openbaoBaseUrl}/ui/vault/auth/oidc/oidc/callback` },
          failOnStatusCode: false,
          timeout: resolveTimeout(CALL_MS),
        });
        expect(started.status(), "OpenBao must start its own OIDC login").toBe(200);
        const authUrl = (await started.json()).data.auth_url;
        expect(authUrl, "OpenBao must hand out an authorization URL").toBeTruthy();
        const openbaoState = new URL(authUrl).searchParams.get("state");
        expect(new URL(authUrl).searchParams.get("client_id"), "OpenBao must sign in through its own client").toBe(openbaoClientId);
        const foreign = await authorize(openbao.request, ctx.semaphore.client, user, "openid");
        const callback = await apiFetchOnion(
          openbao.request,
          `${openbaoBaseUrl}/v1/auth/oidc/oidc/callback?${new URLSearchParams({ state: openbaoState, code: foreign.code })}`,
          { method: "GET", failOnStatusCode: false, timeout: resolveTimeout(CALL_MS) },
        );
        expect(callback.status(), "OpenBao must refuse a code Keycloak issued to Semaphore").toBe(400);
        expect((await callback.json()).auth, "the refused callback must issue no OpenBao token").toBeFalsy();
      } finally {
        await openbao.close();
      }

      const gitea = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const { request } = gitea;
        const source = await giteaOidcSource(request);
        const start = await request.get(`${giteaBaseUrl}${source}`, { maxRedirects: 0, timeout: resolveTimeout(CALL_MS) });
        expect([302, 303, 307], "Gitea must send the browser to Keycloak").toContain(start.status());
        const keycloakAuth = new URL(start.headers()["location"]);
        expect(keycloakAuth.searchParams.get("client_id"), "Gitea must sign in through its own client").toBe(giteaClientId);
        const foreign = await authorize(request, ctx.semaphore.client, user, "openid");
        const callbackQuery = new URLSearchParams({ code: foreign.code, state: keycloakAuth.searchParams.get("state") });
        await request.get(`${giteaBaseUrl}${source}/callback?${callbackQuery}`, {
          maxRedirects: 0,
          timeout: resolveTimeout(CALL_MS),
        });
        const settings = await request.get(`${giteaBaseUrl}/user/settings`, { maxRedirects: 0, timeout: resolveTimeout(CALL_MS) });
        expect(settings.status(), "Gitea must stay signed out after a code Keycloak issued to Semaphore").not.toBe(200);
        expect(settings.headers()["location"] ?? "", "Gitea must send the browser to its sign-in page").toContain("/user/login");
      } finally {
        await gitea.close();
      }
    });

    test("organizations: an invitation reaches the invitee", async ({ browser }) => {
      skipUnlessInvitationMail();
      test.setTimeout(resolveTimeout(MEMBERS_RUN_MS + MAIL_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      const invitee = users.invitee;
      const key = randomUUID();
      state.inviteKey = key;
      await stage(X, key, invitee.email, "Admin");
      const run = await membersTask(sem, X, "invite", { INVITE_KEY: key });
      succeeded(run, "invite of the invitee");
      expect(changeLines(run), "invite must print the sent and the pending change").toEqual(
        expect.arrayContaining([
          `change workspace=${X} action=invite invite=${key} group=Admin change=sent`,
          `change workspace=${X} action=invite invite=${key} group=Admin change=pending`,
        ]),
      );
      const attributes = attributesOf(await readOrganization(kc, organization.id));
      expect(attributes[`${PENDING}Admin`] ?? [], "the key must be listed under workspace.pending.Admin").toContain(key);
      expect(attributes[`${INVITE}${key}`], "the address must be recorded under workspace.invite.<key>").toEqual([invitee.email]);
      expect(
        (await invitationsFor(kc, organization.id, invitee.email)).map((invitation) => invitation.status),
        "Keycloak must hold one pending invitation",
      ).toEqual(["PENDING"]);

      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        await webmailSsoLogin(page, biberUsername, biberPassword, webmailBaseUrl);
        const row = await waitForEmailInMailbox(page, webmailBaseUrl, `ws-${X}`, resolveTimeout(MAIL_MS));
        await row.click({ timeout: resolveTimeout(CALL_MS) });
        const href =
          (await page
            .frameLocator("#messagecontframe")
            .locator(ACTION_TOKEN_LINK)
            .first()
            .getAttribute("href", { timeout: resolveTimeout(CALL_MS) })
            .catch(() => null)) ??
          (await page.locator(ACTION_TOKEN_LINK).first().getAttribute("href", { timeout: resolveTimeout(CALL_MS) }));
        expect(href, "the invitation mail must carry its action-token link").toBeTruthy();
        expect(new URL(href).pathname, "the link must lead to the realm's action-token endpoint").toBe(
          `/realms/${realmName}/login-actions/action-token`,
        );
        state.inviteLink = href;
      } finally {
        await context.close();
      }
    });

    test("organizations: an accepted invitation returns to the store", async ({ browser }) => {
      skipUnlessInvitationMail();
      test.setTimeout(resolveTimeout(FLOW_MS));
      const { kc, users } = ctx;
      const organization = await theOrganization(kc, ids.X);
      expect(state.inviteLink, "the invitation link must have reached the mailbox").toBeTruthy();
      const store = ctx.store.client;
      const landing = /^https?:\/\//.test(store.baseUrl ?? "")
        ? store.baseUrl
        : `${withoutTrailingSlash(store.rootUrl ?? "")}${store.baseUrl ?? ""}`;
      expect(landing, "the store's client must declare a baseUrl").toMatch(/^https?:\/\//);
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const info = await context.request.get(state.inviteLink, { timeout: resolveTimeout(CALL_MS) });
        expect(info.status(), "the invitation link must open Keycloak's confirmation page").toBe(200);
        const proceed = actionTokenHref(await info.text());
        expect(proceed, "the confirmation page must offer to proceed").toBeTruthy();
        const accepted = await context.request.get(new URL(proceed, issuerBaseUrl).href, {
          maxRedirects: 0,
          timeout: resolveTimeout(CALL_MS),
        });
        expect(accepted.status(), "accepting the invitation must redirect").toBe(302);
        expect(withoutTrailingSlash(accepted.headers()["location"]), "the invitee must return to the store's baseUrl").toBe(
          withoutTrailingSlash(landing),
        );
      } finally {
        await context.close();
      }
      expect(await memberIds(kc, organization.id), "the accepted invitee must be a member").toContain(users.invitee.id);
      expect(
        await invitationsFor(kc, organization.id, users.invitee.email),
        "the accepted invitation must be gone",
      ).toEqual([]);
    });

    test("members: an accepted invitee is placed at the next task", async ({ browser }) => {
      skipUnlessInvitationMail();
      test.setTimeout(resolveTimeout(MEMBERS_RUN_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      const invitee = users.invitee;
      expect(await rolesOf(kc, organization.id, invitee.id), "the invitee must hold no role group before a task").toEqual([]);
      const before = jwtPayload((await signIn(browser, ctx.store, invitee, STORE_SCOPE)).access_token);
      expect(aliasesOf(before.organization), "the invitee's token must name the organization").toContain(`ws-${X}`);
      expect(rolesOfWorkspace(before, X), "the invitee's token must hold no role of the workspace yet").toEqual([]);
      const sync = await membersTask(sem, X, "sync");
      succeeded(sync, "sync after the acceptance");
      state.placement = sync;
      const after = jwtPayload((await signIn(browser, ctx.store, invitee, STORE_SCOPE)).access_token);
      expect(rolesOfWorkspace(after, X), "the next token must hold the invited role").toEqual([`${X}:Admin`]);
    });

    test("members: an accepted invitation lands in its role group", async () => {
      skipUnlessInvitationMail();
      test.setTimeout(resolveTimeout(4 * MEMBERS_RUN_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      const invitee = users.invitee;
      const key = state.inviteKey;
      expect(state.placement, "the sync after the acceptance must have run").toBeTruthy();
      expect(changeLines(state.placement), "the sync must place the invitee and drop the invitation").toEqual(
        expect.arrayContaining([
          `change workspace=${X} action=sync user=${invitee.id} group=Admin change=joined`,
          `change workspace=${X} action=sync invite=${key} group=Admin change=placed`,
        ]),
      );
      const placed = lastJson(state.placement);
      expect(memberEntry(placed, invitee.id).groups).toEqual(["Admin"]);
      expect(placed.pending.map((entry) => entry.key), "the placed key must leave the pending list").not.toContain(key);
      const attributes = attributesOf(await readOrganization(kc, organization.id));
      expect(attributes[`${PENDING}Admin`] ?? [], "the sync must drop the pending key").not.toContain(key);
      expect(attributes[`${INVITE}${key}`], "the sync must drop the recorded address").toBeUndefined();
      expect(await rolesOf(kc, organization.id, invitee.id), "the invitee must hold exactly Admin").toEqual(["Admin"]);

      const memberKey = randomUUID();
      await stage(X, memberKey, invitee.email, "Viewer");
      refusedWith(
        await membersTask(sem, X, "invite", { INVITE_KEY: memberKey }),
        X,
        "member_address",
        "invitation of a member's address",
      );
      expect(pendingEntries(await readOrganization(kc, organization.id))[memberKey]).toBeUndefined();
      await ctx.vault.unstage(X, memberKey);

      const otherKey = randomUUID();
      const address = probeAddress("k6");
      await stage(X, otherKey, address, "Viewer");
      succeeded(await membersTask(sem, X, "invite", { INVITE_KEY: otherKey }), "invite to be withdrawn");
      expect(await invitationsFor(kc, organization.id, address), "Keycloak must hold the invitation").toHaveLength(1);
      expect(pendingEntries(await readOrganization(kc, organization.id))[otherKey]).toEqual({ role: "Viewer", address });
      const withdrawn = await membersTask(sem, X, "uninvite", { INVITE_KEY: otherKey });
      succeeded(withdrawn, "uninvite");
      expect(changeLines(withdrawn), "uninvite must print the deletion and the drop").toEqual(
        expect.arrayContaining([
          `change workspace=${X} action=uninvite invite=${otherKey} change=invitation_deleted`,
          `change workspace=${X} action=uninvite invite=${otherKey} group=Viewer change=dropped`,
        ]),
      );
      expect(await invitationsFor(kc, organization.id, address), "uninvite must delete the invitation").toEqual([]);
      expect(pendingEntries(await readOrganization(kc, organization.id))[otherKey], "uninvite must drop the entry").toBeUndefined();
      await ctx.vault.unstage(X, otherKey);
    });

    test("organizations: remove ends the membership and keeps the user", async ({ browser }) => {
      test.setTimeout(resolveTimeout(2 * MEMBERS_RUN_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const { X } = ids;
      const organization = await theOrganization(kc, X);
      const leaver = users.remove;
      await ensureRole(kc, organization.id, "Admin", leaver.id);
      await ensureRole(kc, organization.id, "Viewer", leaver.id);
      succeeded(await membersTask(sem, X, "sync"), "sync before the removal");
      const account = await semaphoreAccount(sem, leaver.username);
      expect(account, `${leaver.username} must hold a Semaphore account after the sync`).toBeTruthy();
      expect(await projectUserIds(sem, state.projects[X]), "the member must hold a role in the project").toContain(account.id);

      const removal = await membersTask(sem, X, "remove", { WORKSPACE_MEMBER: leaver.id });
      const line = succeeded(removal, "remove");
      expect(line.members.map((member) => member.id), "the membership line must drop the member").not.toContain(leaver.id);
      expect(changeLines(removal), "remove must leave both groups and the organization").toEqual(
        expect.arrayContaining([
          `change workspace=${X} action=remove user=${leaver.id} group=Admin change=left`,
          `change workspace=${X} action=remove user=${leaver.id} group=Viewer change=left`,
          `change workspace=${X} action=remove user=${leaver.id} change=left_organization`,
        ]),
      );
      expect((await kc.send("GET", `users/${leaver.id}`)).status(), "the removed member's user must still exist").toBe(200);
      expect(await memberIds(kc, organization.id), "the membership must end").not.toContain(leaver.id);
      const token = jwtPayload((await signIn(browser, ctx.store, leaver, STORE_SCOPE)).access_token);
      expect(rolesOfWorkspace(token, X), "the next token must hold no role of the workspace").toEqual([]);
      expect(aliasesOf(token.organization), "the next token must not name the organization").not.toContain(`ws-${X}`);
      expect(await projectUserIds(sem, state.projects[X]), "the member must hold no role in the project").not.toContain(
        account.id,
      );
    });

    test("users: erase removes the platform account", async ({ browser }) => {
      test.setTimeout(resolveTimeout(2 * MEMBERS_RUN_MS + FLOW_MS));
      const { kc, sem, users } = ctx;
      const erased = users.erase;
      const byAddress = { username: erased.email, password: erased.password };
      const control = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        await authorize(control.request, ctx.store.client, byAddress, "openid");
      } finally {
        await control.close();
      }

      const first = await eraseTask(sem, erased.id);
      expect(first.status, `erase task ${first.id} must succeed`).toBe("success");
      expect(first.lines, "erase must name the deleted user").toContain(`erased user ${erased.id}`);
      expect(lastJson(first)).toEqual({ user: erased.id, erased: true });
      expect((await kc.send("GET", `users/${erased.id}`)).status(), "the erased user must be gone").toBe(404);
      expect(await userNamed(kc, erased.username), "no account may answer to the erased username").toBeUndefined();
      expect(
        await kc.json("GET", `users?email=${encodeURIComponent(erased.email)}&exact=true`, undefined, 200, "searching the address"),
        "no account may answer to the erased address",
      ).toEqual([]);
      const refused = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const { response } = await submitLogin(refused.request, ctx.store.client, byAddress, "openid");
        expect(response.status(), "a login with the erased address must find no account").not.toBe(302);
      } finally {
        await refused.close();
      }

      const second = await eraseTask(sem, erased.id);
      expect(second.status, `the repeated erase task ${second.id} must succeed`).toBe("success");
      expect(lastJson(second)).toEqual({ user: erased.id, erased: true });
      expect(second.lines, "the repeated erase must delete nothing").not.toContain(`erased user ${erased.id}`);
    });
  });
}

function registerClientsAndRecipient() {
  test.describe.serial("keycloak organizations: clients and recipient", () => {
    test.skip(!organizationsEnabled, WITHOUT_ORGANIZATIONS);

    const state = { failed: false };
    let ctx = null;

    test.beforeAll(async ({ browser }) => {
      test.setTimeout(resolveTimeout(FLOW_MS));
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      const kc = keycloakAdmin(context.request);
      ctx = {
        context,
        api: context.request,
        kc,
        users: {
          audience: await createProbeUser(kc, "audience", probeAddress("audience")),
          recipient: await createProbeUser(kc, "recipient", probeAddress("recipient")),
        },
      };
    });

    test.afterEach(async () => {
      state.failed ||= test.info().status !== test.info().expectedStatus;
    });

    test.afterAll(async () => {
      if (!ctx) {
        return;
      }
      await teardown(state.failed, [
        ...Object.values(ctx.users).map((user) => [TEARDOWN_STEP_MS, () => removeUserNamed(ctx.kc, user.username)]),
        [TEARDOWN_STEP_MS, () => ctx.context.close()],
      ]);
    });

    test("clients: the store's client holds no admin right", async () => {
      test.skip(!storeClientId, WITHOUT_STORE);
      const { kc, api } = ctx;
      const store = await consumer(kc, storeClientId);
      expect(store.client.serviceAccountsEnabled, "the store's client must hold no service account").toBe(false);
      const account = await kc.send("GET", `clients/${store.client.id}/service-account-user`);
      expect(account.status(), "the store's client must hold no service-account user").not.toBe(200);
      const grant = await clientCredentials(api, storeClientId, store.secret);
      expect([400, 401], "a client-credentials grant of the store's client must be refused").toContain(grant.status());
      const body = await grant.json();
      expect(body.error, "the refusal must name unauthorized_client").toBe("unauthorized_client");
      expect(body.access_token, "the refusal must issue no token").toBeUndefined();
    });

    test("clients: a store access token names the store as audience", async ({ browser }) => {
      test.skip(!storeClientId, WITHOUT_STORE);
      const store = await consumer(ctx.kc, storeClientId);
      const access = jwtPayload((await signIn(browser, store, ctx.users.audience, "openid")).access_token);
      expect(audiences(access), "the store's access token must hold its client id in aud").toContain(storeClientId);
      expect(access.azp, "the store's access token must be issued to the store").toBe(storeClientId);
    });

    test("export: only the user sets the recipient", async ({ browser }) => {
      const { kc, api, users } = ctx;
      const recipient = users.recipient;
      const own = ageRecipient();
      const foreign = ageRecipient();
      const accountConsole = { client: await clientNamed(kc, ACCOUNT_CONSOLE), secret: "" };
      const tokens = await signIn(browser, accountConsole, recipient, "openid");
      const headers = { ...bearer(tokens.access_token), Accept: "application/json" };
      const profile = await api.get(`${realmUrl}/account`, { headers, timeout: resolveTimeout(CALL_MS) });
      expect(profile.status(), "the account API must answer the user").toBe(200);
      const representation = await profile.json();
      const set = await api.post(`${realmUrl}/account`, {
        headers,
        data: { ...representation, attributes: { ...attributesOf(representation), [recipientAttribute]: [own] } },
        timeout: resolveTimeout(CALL_MS),
      });
      expect(set.status(), "the user must set the export recipient through the account API").toBe(204);
      const recorded = async () =>
        attributesOf(await kc.json("GET", `users/${recipient.id}`, undefined, 200, "reading the recipient"))[recipientAttribute];
      expect(await recorded(), "the account API must store the user's recipient").toEqual([own]);

      const members = await membersAccount(api);
      const current = await members.json("GET", `users/${recipient.id}`, undefined, 200, `reading the user as ${membersClientId}`);
      const unchanged = await members.send("PUT", `users/${recipient.id}`, current);
      expect(unchanged.status(), `${membersClientId} must hold manage-users, so an unchanged write passes`).toBe(204);
      const write = await members.send("PUT", `users/${recipient.id}`, {
        ...current,
        attributes: { ...attributesOf(current), [recipientAttribute]: [foreign] },
      });
      expect(write.status(), `${membersClientId} must not write the export recipient`).toBe(400);
      expect(await write.text(), "the refusal must name the read-only attribute").toContain("error-user-attribute-read-only");
      expect(await recorded(), "the refused write must leave the recipient as the user set it").toEqual([own]);
    });

    test("organizations: no store path touches admin events", async () => {
      test.skip(!storeClientId, WITHOUT_STORE);
      const { kc, api } = ctx;
      const membersClient = await clientNamed(kc, membersClientId);
      const account = await kc.json(
        "GET",
        `clients/${membersClient.id}/service-account-user`,
        undefined,
        200,
        `reading the service account of ${membersClientId}`,
      );
      const management = await clientNamed(kc, REALM_MANAGEMENT);
      const held = await kc.json(
        "GET",
        `users/${account.id}/role-mappings/clients/${management.id}/composite`,
        undefined,
        200,
        `reading the realm-management roles of ${membersClientId}`,
      );
      expect(
        held.map((role) => role.name).filter((name) => EVENT_RIGHTS.includes(name)),
        `${membersClientId} must hold no event right before the spec probes the event endpoints`,
      ).toEqual([]);
      const config = await kc.json("GET", "events/config", undefined, 200, "reading the events configuration");
      const members = await membersAccount(api);
      expect((await members.send("PUT", "events/config", config)).status(), "the events configuration must stay closed").toBe(
        403,
      );
      expect((await members.send("DELETE", "admin-events")).status(), "the admin events must not be deletable").toBe(403);
      const store = await consumer(kc, storeClientId);
      const grant = await clientCredentials(api, storeClientId, store.secret);
      expect([400, 401], "the store's client must get no client-credentials token").toContain(grant.status());
      const body = await grant.json();
      expect(body.error, "the refusal must name unauthorized_client").toBe("unauthorized_client");
      expect(body.access_token, "the refusal must issue no token").toBeUndefined();
    });
  });
}

exports.register = function () {
  registerWorkspaceTasks();
  registerClientsAndRecipient();
};
