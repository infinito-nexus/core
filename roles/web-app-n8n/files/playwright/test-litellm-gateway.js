const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");

const credentialName = decodeDotenvQuotedValue(process.env.N8N_LITELLM_CREDENTIAL_NAME);
const gatewayBaseUrl = decodeDotenvQuotedValue(process.env.N8N_LITELLM_BASE_URL);
const gatewayModel = decodeDotenvQuotedValue(process.env.N8N_LITELLM_MODEL);

const CREDENTIAL_TYPE = "openAiApi";
const PROBE_WORKFLOW = "infinito:litellm-probe";
const REQUEST_NODE = "Gateway";
const PROMPT = "Reply with exactly the word: pong";
const FINAL_STATUSES = new Set(["success", "error", "crashed", "canceled"]);
const COMPLETION_TIMEOUT_MS = 240_000;

/**
 * Return a caller for n8n's internal `/rest` API bound to the page's session.
 *
 * n8n binds the `n8n-auth` JWT to the `browser-id` the frontend generated at
 * login time, so a request that omits the header is rejected with 401 while
 * the very same cookie works in the tab. The SSO path (files/hooks.js) issues
 * a cookie without one, hence the empty-value tolerance.
 *
 * Args:
 *   page: the signed-in Playwright page.
 *   baseUrl: origin of the n8n vhost.
 */
async function restClient(page, baseUrl) {
  const browserId = await page.evaluate(() => {
    try {
      const stored = window.localStorage.getItem("n8n-browserId");
      if (stored) {
        return stored;
      }
      const key = Object.keys(window.localStorage).find((name) => /browser.?id/i.test(name));
      return key ? window.localStorage.getItem(key) || "" : "";
    } catch {
      return "";
    }
  });

  return async function rest(method, path, payload) {
    const headers = { accept: "application/json" };
    if (browserId) {
      headers["browser-id"] = browserId;
    }
    const options = { method, headers, failOnStatusCode: false, timeout: 120_000 };
    if (payload !== undefined) {
      options.data = payload;
    }
    const response = await page.request.fetch(`${baseUrl}${path}`, options);
    const text = await response.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    return { status: response.status(), body, text: text.slice(0, 400) };
  };
}

/**
 * Sign in as the n8n instance owner, the account that owns the managed
 * credential, over whichever login surface the deploy exposes.
 *
 * Args:
 *   page: a page with cleared cookies.
 *   shared: the role's `_shared` module.
 */
async function signInAsOwner(page, shared) {
  if (shared.env.oidcEnabled) {
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    await shared.signInViaN8nOidc(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword,
      "administrator"
    );
    return;
  }

  expect(shared.env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  expect(shared.env.n8nOwnerPassword, "N8N_OWNER_PASSWORD must be set").toBeTruthy();
  await page.goto(`${shared.env.n8nBaseUrl}/`);
  await shared.performN8nLoginForm(page, shared.env.adminEmail, shared.env.n8nOwnerPassword);
}

/**
 * Revive the `data` field of an execution read over `/rest`.
 *
 * n8n 1.95.3 hands the field back exactly as it stores it: a `flatted` string,
 * a JSON array whose object and string members are numeric indices back into
 * that same array. Reading `.resultData` off that string yields `undefined`,
 * which is indistinguishable from a node that never ran.
 *
 * Args:
 *   payload: the execution's `data` field, flatted string or plain object.
 */
function reviveExecutionData(payload) {
  if (typeof payload !== "string") {
    return payload;
  }
  const nodes = JSON.parse(payload);
  if (!Array.isArray(nodes)) {
    return nodes;
  }
  const revived = new Map();
  const revive = (index) => {
    const value = nodes[index];
    if (value === null || typeof value !== "object") {
      return value;
    }
    if (revived.has(index)) {
      return revived.get(index);
    }
    const output = Array.isArray(value) ? [] : {};
    revived.set(index, output);
    for (const [key, reference] of Object.entries(value)) {
      output[key] = typeof reference === "string" ? revive(Number(reference)) : reference;
    }
    return output;
  };
  return revive(0);
}

/**
 * Poll one manual execution until it reaches a final state.
 *
 * Args:
 *   page: the signed-in Playwright page.
 *   rest: the `/rest` caller.
 *   executionId: id returned by the manual run.
 *   timeoutMs: budget for the whole completion.
 */
async function pollExecution(page, rest, executionId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const latest = await rest("GET", `/rest/executions/${executionId}`);
    const execution = latest.body?.data;
    const status = String(execution?.status || "");
    if (execution && (execution.finished === true || FINAL_STATUSES.has(status))) {
      return { execution, latest };
    }
    if (Date.now() >= deadline) {
      return { execution: null, latest };
    }
    await page.waitForTimeout(2_000);
  }
}

function probeWorkflow(credentialId, endpoint) {
  return {
    name: PROBE_WORKFLOW,
    active: false,
    settings: { executionOrder: "v1" },
    nodes: [
      {
        id: "infinito-litellm-start",
        name: "Start",
        type: "n8n-nodes-base.manualTrigger",
        typeVersion: 1,
        position: [0, 0],
        parameters: {},
      },
      {
        id: "infinito-litellm-request",
        name: REQUEST_NODE,
        type: "n8n-nodes-base.httpRequest",
        typeVersion: 4.2,
        position: [220, 0],
        parameters: {
          method: "POST",
          url: `${endpoint}/chat/completions`,
          authentication: "predefinedCredentialType",
          nodeCredentialType: CREDENTIAL_TYPE,
          sendBody: true,
          contentType: "json",
          specifyBody: "json",
          jsonBody: JSON.stringify({
            model: gatewayModel,
            messages: [{ role: "user", content: PROMPT }],
            stream: false,
          }),
          options: { timeout: COMPLETION_TIMEOUT_MS },
        },
        credentials: { [CREDENTIAL_TYPE]: { id: credentialId, name: credentialName } },
      },
    ],
    connections: { Start: { main: [[{ node: REQUEST_NODE, type: "main", index: 0 }]] } },
  };
}

exports.register = function (shared) {
  test("administrator: the managed openAiApi credential answers a prompt through the in-cluster gateway", async ({ page }) => {
    shared.skipUnlessServiceEnabled("litellm");
    test.setTimeout(360_000);

    expect(credentialName, "N8N_LITELLM_CREDENTIAL_NAME must be set").toBeTruthy();
    expect(gatewayBaseUrl, "N8N_LITELLM_BASE_URL must be set").toBeTruthy();
    expect(gatewayModel, "N8N_LITELLM_MODEL must be set").toBeTruthy();

    await signInAsOwner(page, shared);

    const rest = await restClient(page, shared.env.n8nBaseUrl);

    const list = await rest("GET", "/rest/credentials");
    expect(
      list.status,
      `the owner session must be able to list credentials over /rest (HTTP ${list.status}: ${list.text})`
    ).toBe(200);

    const managed = (Array.isArray(list.body?.data) ? list.body.data : []).filter(
      (entry) => entry?.name === credentialName
    );
    expect(
      managed,
      `exactly one credential named "${credentialName}" must exist; tasks/utils/ai_gateway.yml upserts it, so 0 means the gateway wiring never ran and every AI Agent node stays unconfigured`
    ).toHaveLength(1);
    expect(
      String(managed[0]?.type),
      `the managed credential must be of type ${CREDENTIAL_TYPE}; that is the only type an AI Agent node reads its endpoint and key from`
    ).toBe(CREDENTIAL_TYPE);

    const credentialId = String(managed[0].id);
    const detail = await rest("GET", `/rest/credentials/${credentialId}?includeData=true`);
    expect(
      detail.status,
      `the owner must be able to read the managed credential with its data (HTTP ${detail.status})`
    ).toBe(200);

    const storedUrl = String(detail.body?.data?.data?.url || "");
    expect(
      storedUrl.length,
      "the managed credential must carry a base URL; an empty one falls back to the openAiApi vendor default at api.openai.com and sends every prompt off the deployment"
    ).toBeGreaterThan(0);
    expect(
      storedUrl,
      "the stored base URL must be the in-cluster gateway address the deploy configured (N8N_LITELLM_BASE_URL)"
    ).toBe(gatewayBaseUrl);

    const endpoint = new URL(storedUrl);
    expect(
      endpoint.protocol,
      "the gateway endpoint must be plain http on the container network; https would mean the prompt leaves through the public ingress"
    ).toBe("http:");
    expect(
      endpoint.hostname.includes("."),
      `the gateway host must be an undotted container name (got "${endpoint.hostname}"); a dotted host is completed by the container dns-search suffix and resolves through the public ingress, which is the leak the platform forbids`
    ).toBe(false);
    expect(
      endpoint.host.toLowerCase(),
      "the gateway must be a distinct in-cluster service, not n8n pointing at itself"
    ).not.toBe(new URL(shared.env.n8nBaseUrl).host.toLowerCase());

    const probe = await rest("POST", "/rest/credentials/test", {
      credentials: {
        id: credentialId,
        name: credentialName,
        type: CREDENTIAL_TYPE,
        data: detail.body.data.data,
      },
    });
    expect(
      probe.status,
      `n8n must accept a credential test for the managed credential (HTTP ${probe.status})`
    ).toBe(200);
    expect(
      String(probe.body?.data?.status),
      `n8n tests an ${CREDENTIAL_TYPE} credential with GET ${storedUrl}/models, so anything but "OK" means n8n cannot reach the gateway or the gateway rejects this role's virtual key: ${String(probe.body?.data?.message || probe.status)}`
    ).toBe("OK");

    const workflow = probeWorkflow(credentialId, storedUrl.replace(/\/+$/, ""));
    const created = await rest("POST", "/rest/workflows", workflow);
    expect(
      created.status,
      `n8n must accept the probe workflow that sends one prompt through the managed credential (HTTP ${created.status}: ${created.text})`
    ).toBeLessThan(300);

    const workflowId = String(created.body?.data?.id || "");
    expect(
      workflowId.length,
      `the created probe workflow must carry an id to run it with (HTTP ${created.status}: ${created.text})`
    ).toBeGreaterThan(0);

    try {
      const run = await rest("POST", `/rest/workflows/${workflowId}/run`, {
        workflowData: { ...workflow, id: workflowId },
      });
      expect(
        run.status,
        `n8n must accept the manual run of the probe workflow (HTTP ${run.status}: ${run.text})`
      ).toBeLessThan(300);

      const executionId = String(run.body?.data?.executionId || "");
      expect(
        executionId.length,
        `the manual run must report an execution id to read the answer from (HTTP ${run.status}: ${run.text})`
      ).toBeGreaterThan(0);

      const { execution, latest } = await pollExecution(
        page,
        rest,
        executionId,
        COMPLETION_TIMEOUT_MS
      );
      expect(
        execution,
        `execution ${executionId} must reach a final state within ${COMPLETION_TIMEOUT_MS} ms (last HTTP ${latest.status}: ${latest.text})`
      ).toBeTruthy();
      const result = reviveExecutionData(execution.data);
      expect(
        String(execution.status),
        `the prompt must be answered through the gateway; a failed execution is n8n reaching ${storedUrl} and being refused or timed out: ${JSON.stringify(result?.resultData?.error || {}).slice(0, 400)}`
      ).toBe("success");

      const item = result?.resultData?.runData?.[REQUEST_NODE]?.[0]?.data?.main?.[0]?.[0];
      expect(
        item?.json,
        `the ${REQUEST_NODE} node must have produced a response item; empty runData means the node never ran and nothing was asked of the gateway`
      ).toBeTruthy();

      const answer = String(item.json?.choices?.[0]?.message?.content || "").trim();
      expect(
        answer.length,
        `the gateway must return non-empty assistant text over n8n -> ${storedUrl} -> ${gatewayModel} (got ${JSON.stringify(item.json).slice(0, 300)})`
      ).toBeGreaterThan(0);
    } finally {
      await rest("DELETE", `/rest/workflows/${workflowId}`).catch(() => {});
      await shared.n8nLogout(page).catch(() => {});
    }
  });
};
