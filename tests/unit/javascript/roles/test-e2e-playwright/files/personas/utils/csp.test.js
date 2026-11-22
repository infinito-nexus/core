const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");

const playwrightStub = {
  expect: (actual, message) => ({
    toBe(expected) {
      if (actual !== expected) throw new Error(message || `expected ${expected}, got ${actual}`);
    },
    toEqual(expected) {
      assert.deepEqual(actual, expected, message);
    },
  }),
};
const loadModule = Module._load;
Module._load = function (request, ...rest) {
  return request === "@playwright/test" ? playwrightStub : loadModule.call(this, request, ...rest);
};

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { assertCspInjections, expectNoCspViolations, installCspHeaderRecorder } = require(
  path.join(
    PROJECT_ROOT,
    "roles/test-e2e-playwright/files/personas/utils/csp.js",
  ),
);

Module._load = loadModule;

const CDN = "https://cdn.example.test";
const WITH_CDN = `default-src 'self' ${CDN}`;
const WITHOUT_CDN = "default-src 'self'";
const TRACKER_HOST = "tracker.example.test";
const TRACKER_SCRIPT = `https://${TRACKER_HOST}/script.js`;
const TRACKER_BLOCK = { expected: [{ host: TRACKER_HOST, directive: "script-src" }] };

/**
 * Build a stub `page` that records its response listeners.
 *
 * @param {object|null} refetchHeaders - headers the page.request.get
 *   fallback returns, or null to make that fallback fail
 * @returns {object} the stub page plus its inspection handles
 */
function stubPage(refetchHeaders = null) {
  const listeners = [];
  const mainFrame = { name: "main" };
  let refetchCalls = 0;

  const page = {
    url: () => "https://app.example.test/",
    mainFrame: () => mainFrame,
    on: (event, handler) => {
      if (event === "response") listeners.push(handler);
    },
    request: {
      get: async () => {
        refetchCalls += 1;
        if (!refetchHeaders) throw new Error("apiRequestContext.get: Timeout 10000ms exceeded.");
        return { headers: () => refetchHeaders };
      },
    },
  };

  return {
    page,
    mainFrame,
    listenerCount: () => listeners.length,
    refetchCalls: () => refetchCalls,
    emit: (response) => listeners.forEach((handler) => handler(response)),
  };
}

function response(frame, headers, resourceType = "document") {
  return {
    frame: () => frame,
    request: () => ({ resourceType: () => resourceType }),
    headers: () => headers,
  };
}

/**
 * Run `run` with the given env vars applied, then restore them.
 *
 * @param {object} vars - env var name to value, or undefined to unset
 * @param {function} run - async callback
 * @returns {Promise<*>} whatever `run` resolves to
 */
async function withEnv(vars, run) {
  const previous = {};
  for (const name of Object.keys(vars)) {
    previous[name] = process.env[name];
    if (vars[name] === undefined) delete process.env[name];
    else process.env[name] = vars[name];
  }
  try {
    return await run();
  } finally {
    for (const name of Object.keys(previous)) {
      if (previous[name] === undefined) delete process.env[name];
      else process.env[name] = previous[name];
    }
  }
}

/**
 * Run `expectNoCspViolations` against recorded violations and console text.
 *
 * @param {{blockedURI: string, effectiveDirective: string}[]} violations -
 *   the securitypolicyviolation events the page recorded
 * @param {string[]} consoleTexts - the CSP-related console entries
 * @param {object} [opts] - the helper's fourth argument, omitted when undefined
 * @returns {Promise<void>} rejects when the helper fails the page
 */
function checkViolations(violations, consoleTexts, opts) {
  const page = { evaluate: async () => violations };
  const cspRelated = consoleTexts.map((text) => ({ source: "console", text }));
  const args = [page, { cspRelated }, "dashboard"];
  return expectNoCspViolations(...(opts === undefined ? args : [...args, opts]));
}

function blocked(blockedURI, effectiveDirective) {
  return { blockedURI, effectiveDirective, violatedDirective: effectiveDirective };
}

function blockedMessage(url, directive) {
  return `Loading the script '${url}' violates the Content Security Policy directive: "${directive}".`;
}

const withCdnEnv = (run) => withEnv({ CDN_BASE_URL: CDN }, run);

const cdnEnabled = (service) => service === "cdn";

const assertCdn = (page) =>
  withCdnEnv(() => assertCspInjections(page, { isEnabled: cdnEnabled }));

test("the recorded header is used without a second request", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITH_CDN }));

  await assertCdn(stub.page);

  assert.equal(
    stub.refetchCalls(),
    0,
    "re-fetching resolves DNS separately from the browser and is the slow path",
  );
});

test("a recorded header missing an enabled injector host fails the assertion", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITHOUT_CDN }));

  await assert.rejects(() => assertCdn(stub.page), /cdn\.example\.test/);
});

test("report-only counts as a recorded policy", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(
    response(stub.mainFrame, { "content-security-policy-report-only": WITHOUT_CDN }),
  );

  await assert.rejects(() => assertCdn(stub.page), /cdn\.example\.test/);
});

test("the last main-frame document wins over an earlier redirect", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITHOUT_CDN }));
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITH_CDN }));

  await assertCdn(stub.page);
});

test("sub-frame and sub-resource responses are ignored", async () => {
  const stub = stubPage({ "content-security-policy": WITH_CDN });
  installCspHeaderRecorder(stub.page);
  stub.emit(response({ name: "iframe" }, { "content-security-policy": WITHOUT_CDN }));
  stub.emit(
    response(stub.mainFrame, { "content-security-policy": WITHOUT_CDN }, "script"),
  );

  await assertCdn(stub.page);

  assert.equal(stub.refetchCalls(), 1, "nothing was recorded, so the fallback runs");
});

test("a spec that never installed the recorder falls back to a re-fetch", async () => {
  const stub = stubPage({ "content-security-policy": WITH_CDN });

  await assertCdn(stub.page);

  assert.equal(stub.refetchCalls(), 1);
});

test("no policy anywhere asserts nothing rather than throwing", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);

  await assertCdn(stub.page);

  assert.equal(stub.refetchCalls(), 1);
});

test("installing the recorder twice keeps one listener", () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  installCspHeaderRecorder(stub.page);

  assert.equal(stub.listenerCount(), 1);
});

test("an enforced policy wins over report-only on the same response", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(
    response(stub.mainFrame, {
      "content-security-policy": WITHOUT_CDN,
      "content-security-policy-report-only": WITH_CDN,
    }),
  );

  await assert.rejects(
    () => assertCdn(stub.page),
    /cdn\.example\.test/,
    "the enforced header is the policy the browser applies; report-only must not mask it",
  );
});

test("a disabled injector is not asserted", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITHOUT_CDN }));

  await withCdnEnv(() => assertCspInjections(stub.page, { isEnabled: () => false }));
});

test("a gate that throws counts as disabled", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITHOUT_CDN }));

  await withCdnEnv(() =>
    assertCspInjections(stub.page, {
      isEnabled: () => {
        throw new Error("gate unavailable");
      },
    }),
  );
});

test("an enabled injector without a base URL is tolerated", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITHOUT_CDN }));

  await withEnv({ CDN_BASE_URL: undefined }, () =>
    assertCspInjections(stub.page, { isEnabled: cdnEnabled }),
  );
});

test("no gate function reads nothing and asserts nothing", async () => {
  const stub = stubPage({ "content-security-policy": WITHOUT_CDN });

  await assertCspInjections(stub.page, {});

  assert.equal(stub.refetchCalls(), 0);
});

test("every enabled injector is checked, not just the first", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITH_CDN }));

  await assert.rejects(
    () =>
      withEnv(
        { CDN_BASE_URL: CDN, MATOMO_BASE_URL: "https://matomo.example.test" },
        () =>
          assertCspInjections(stub.page, {
            isEnabled: (s) => s === "cdn" || s === "matomo",
          }),
      ),
    /matomo\.example\.test/,
  );
});

test("the host match ignores case", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(
    response(stub.mainFrame, {
      "content-security-policy": "default-src 'self' https://CDN.EXAMPLE.TEST",
    }),
  );

  await assertCdn(stub.page);
});

test("a torn-down response does not break the recorder", async () => {
  const stub = stubPage();
  installCspHeaderRecorder(stub.page);
  stub.emit(response(stub.mainFrame, { "content-security-policy": WITH_CDN }));
  stub.emit({
    frame: () => {
      throw new Error("Target page, context or browser has been closed");
    },
  });

  await assertCdn(stub.page);

  assert.equal(stub.refetchCalls(), 0);
});

test("an expected block under its directive is the one tolerated violation", async () => {
  await checkViolations(
    [blocked(TRACKER_SCRIPT, "script-src-elem"), blocked(TRACKER_SCRIPT, "script-src")],
    [
      blockedMessage(TRACKER_SCRIPT, "script-src-elem"),
      `Refused to load the script '${TRACKER_SCRIPT}' because it violates the following Content Security Policy directive: "script-src 'self' https://cdn.example.test". Note that 'script-src-elem' was not explicitly set, so 'script-src' is used as a fallback.`,
    ],
    TRACKER_BLOCK,
  );
  await checkViolations([], [], TRACKER_BLOCK);
});

test("a violation from any other source still fails beside an expected block", async () => {
  for (const violations of [
    [blocked("https://cdn.example.test/app.js", "script-src-elem")],
    [blocked("inline", "script-src-elem")],
    [blocked(`https://evil-${TRACKER_HOST}/script.js`, "script-src-elem")],
    [blocked(`https://x.${TRACKER_HOST}/script.js`, "script-src-elem")],
    [blocked(TRACKER_SCRIPT, "script-src-elem"), blocked("eval", "script-src")],
  ]) {
    await assert.rejects(() => checkViolations(violations, [], TRACKER_BLOCK), /securitypolicyviolation/);
  }
});

test("a console entry that does not name the expected host still fails", async () => {
  for (const text of [
    blockedMessage(`https://${TRACKER_HOST}.evil.test/x.js`, "script-src-elem"),
    blockedMessage(`https://evil-${TRACKER_HOST}/script.js`, "script-src-elem"),
    blockedMessage(`https://x.${TRACKER_HOST}/script.js`, "script-src-elem"),
    'Refused to apply inline style because it violates the Content Security Policy directive: "style-src".',
  ]) {
    await assert.rejects(() => checkViolations([], [text], TRACKER_BLOCK), /console\/pageerror/);
  }
});

test("the expected host under a different directive still fails", async () => {
  for (const directive of ["img-src", "connect-src", "script-srcx"]) {
    await assert.rejects(
      () => checkViolations([blocked(TRACKER_SCRIPT, directive)], [], TRACKER_BLOCK),
      /securitypolicyviolation/,
    );
    await assert.rejects(
      () => checkViolations([], [blockedMessage(TRACKER_SCRIPT, directive)], TRACKER_BLOCK),
      /console\/pageerror/,
    );
  }
  await assert.rejects(
    () =>
      checkViolations(
        [{ blockedURI: TRACKER_SCRIPT, effectiveDirective: "img-src", violatedDirective: "script-src" }],
        [],
        TRACKER_BLOCK,
      ),
    /securitypolicyviolation/,
  );
});

test("without the fourth argument every violation fails as before", async () => {
  await assert.rejects(
    () => checkViolations([blocked(TRACKER_SCRIPT, "script-src-elem")], []),
    /securitypolicyviolation/,
  );
  await assert.rejects(
    () => checkViolations([], [blockedMessage(TRACKER_SCRIPT, "script-src-elem")]),
    /console\/pageerror/,
  );
  await checkViolations([], []);
});
