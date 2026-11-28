const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-nextcloud/files/playwright/addons/integration_zammad.spec.js");
const NEXTCLOUD_URL = `https://next.cloud.${DOMAIN}`;
const AUTHORIZE_URL = `https://zammad.helpdesk.${DOMAIN}/oauth/authorize?client_id=uid&response_type=code&state=s`;
const WIZARD_INTERCEPTS = /firstrunwizard.*intercepts pointer events/;

function expect(value, message) {
  return {
    toBeTruthy: () => assert.ok(value, message),
    toBe: (wanted) => assert.equal(value, wanted, message),
  };
}

const PLAIN_CLICK = { clickWithModalRetry: async (_page, _frame, target) => target.click() };

/**
 * Args:
 *   shared: the `../_shared` module the spec drives its clicks through.
 *
 * Returns:
 *   The spec's connectToZammad.
 */
function loadConnect(shared) {
  return loadInternals(
    SPEC,
    ["connectToZammad"],
    {
      "@playwright/test": { test: () => undefined, expect },
      "../timeouts": { resolveTimeout: (ms) => ms },
      "../_shared": shared,
    },
    {},
  ).connectToZammad;
}

/**
 * Args:
 *   scenario.href: the href of the Connect control, null for a button.
 *   scenario.savedStatus: the status of the PUT sensitive-config its click sends, null when the click sends none.
 *   scenario.redirects: whether an accepted PUT is followed by the browser's request to the partner /oauth/authorize.
 *   scenario.clickError: the error the click throws, null for a click that lands.
 *   scenario.wizard: whether the Nextcloud first-run wizard covers the control until it is dismissed.
 *
 * Returns:
 *   The page, the Connect control and dismissWizard, which closes the first-run wizard. Waits for a request or
 *   response the click does not produce reject the way a Playwright wait times out.
 */
function connectedAccounts(scenario) {
  const waiters = [];
  const state = { wizardOpen: scenario.wizard };
  const wait = (kind, predicate) => new Promise((resolve, reject) => waiters.push({ kind, predicate, resolve, reject }));
  const emit = (kind, event) => {
    for (const waiter of waiters) {
      if (!waiter.done && waiter.kind === kind && waiter.predicate(event)) {
        waiter.done = true;
        waiter.resolve(event);
      }
    }
  };
  const timeOut = () => {
    for (const waiter of waiters) {
      if (!waiter.done) {
        waiter.done = true;
        waiter.reject(new Error(`waiting for ${waiter.kind}: Timeout exceeded`));
      }
    }
  };
  const response = (method, url, status) => ({
    url: () => url,
    status: () => status,
    ok: () => status >= 200 && status < 300,
    request: () => ({ method: () => method }),
  });

  const page = {
    waitForResponse: (predicate) => wait("response", predicate),
    waitForRequest: (predicate) => wait("request", predicate),
  };
  const connect = {
    getAttribute: async (name) => (name === "href" ? scenario.href : null),
    click: async () => {
      if (state.wizardOpen) {
        throw new Error("locator.click: <div id=\"firstrunwizard\"> subtree intercepts pointer events");
      }
      if (scenario.clickError) {
        timeOut();
        throw scenario.clickError;
      }
      emit("response", response("GET", `${NEXTCLOUD_URL}/apps/integration_zammad/sensitive-config`, 200));
      if (scenario.savedStatus !== null) {
        emit("response", response("PUT", `${NEXTCLOUD_URL}/apps/integration_zammad/sensitive-config`, scenario.savedStatus));
        if (scenario.savedStatus < 300 && scenario.redirects) emit("request", { url: () => AUTHORIZE_URL });
      }
      timeOut();
    },
  };
  const dismissWizard = () => {
    state.wizardOpen = false;
  };
  return { page, connect, dismissWizard };
}

test("a click that stores the OAuth state and redirects returns the partner authorize request", async () => {
  const { page, connect } = connectedAccounts({ href: null, savedStatus: 200, redirects: true, clickError: null, wizard: false });

  assert.equal(await loadConnect(PLAIN_CLICK)(page, connect), AUTHORIZE_URL);
});

test("a state store the app answers with 204 No Content counts as accepted", async () => {
  const { page, connect } = connectedAccounts({ href: null, savedStatus: 204, redirects: true, clickError: null, wizard: false });

  assert.equal(await loadConnect(PLAIN_CLICK)(page, connect), AUTHORIZE_URL);
});

test("a Connect link to the authorize endpoint is returned without clicking it", async () => {
  const unclicked = new Error("the link must not be clicked");
  const { page, connect } = connectedAccounts({ href: AUTHORIZE_URL, savedStatus: null, redirects: false, clickError: unclicked, wizard: false });

  assert.equal(await loadConnect(PLAIN_CLICK)(page, connect), AUTHORIZE_URL);
});

test("a stored state without the authorize request fails naming the missing redirect, not the Nextcloud host", async () => {
  const { page, connect } = connectedAccounts({ href: null, savedStatus: 200, redirects: false, clickError: null, wizard: false });

  await assert.rejects(loadConnect(PLAIN_CLICK)(page, connect), /must send the browser to the partner \/oauth\/authorize/);
});

test("a click that sends no PUT sensitive-config fails naming the missing state store", async () => {
  const { page, connect } = connectedAccounts({ href: null, savedStatus: null, redirects: false, clickError: null, wizard: false });

  await assert.rejects(loadConnect(PLAIN_CLICK)(page, connect), /must PUT the OAuth state to \/apps\/integration_zammad\/sensitive-config/);
});

test("a refused PUT sensitive-config fails naming the refusal", async () => {
  const { page, connect } = connectedAccounts({ href: null, savedStatus: 403, redirects: true, clickError: null, wizard: false });

  await assert.rejects(loadConnect(PLAIN_CLICK)(page, connect), /must accept the OAuth state PUT/);
});

test("negative control: an error of the Connect click propagates instead of being swallowed", async () => {
  const clickError = new Error("locator.click: Timeout 10000ms exceeded");
  const { page, connect } = connectedAccounts({ href: null, savedStatus: 200, redirects: true, clickError, wizard: false });

  await assert.rejects(loadConnect(PLAIN_CLICK)(page, connect), (error) => error === clickError);
});

test("the Connect click goes through the modal-dismissing click of the page itself", async () => {
  const { page, connect } = connectedAccounts({ href: null, savedStatus: 200, redirects: true, clickError: null, wizard: false });
  const calls = [];
  const recording = {
    clickWithModalRetry: async (...args) => {
      calls.push(args);
      return args[2].click();
    },
  };

  assert.equal(await loadConnect(recording)(page, connect), AUTHORIZE_URL);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], page);
  assert.equal(calls[0][1], page);
  assert.equal(calls[0][2], connect);
});

test("a first-run wizard that mounts after the page settled is dismissed before the Connect click lands", async () => {
  const { page, connect, dismissWizard } = connectedAccounts({ href: null, savedStatus: 200, redirects: true, clickError: null, wizard: true });
  const dismissing = {
    clickWithModalRetry: async (_page, _frame, target) => {
      dismissWizard();
      return target.click();
    },
  };

  assert.equal(await loadConnect(dismissing)(page, connect), AUTHORIZE_URL);
});

test("negative control: a click that does not dismiss the first-run wizard fails on its interception", async () => {
  const { page, connect } = connectedAccounts({ href: null, savedStatus: 200, redirects: true, clickError: null, wizard: true });

  await assert.rejects(loadConnect(PLAIN_CLICK)(page, connect), WIZARD_INTERCEPTS);
});
