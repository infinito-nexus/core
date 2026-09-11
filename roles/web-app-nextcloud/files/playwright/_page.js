const { resolveTimeout } = require("./timeouts");
const { findFirstVisibleCandidate } = require("./personas");

function getNextcloudShellCandidates(target) {
  return [
    {
      kind: "shell",
      locator: target.locator("#app-content-vue, #app-navigation-vue, #app-dashboard")
    },
    {
      kind: "shell",
      locator: target.locator("nav.app-menu, #user-menu")
    }
  ];
}

async function waitForFirstVisible(page, locators, timeout = resolveTimeout(60_000)) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    for (const locator of locators) {
      if (await locator.first().isVisible().catch(() => false)) {
        return locator.first();
      }
    }

    await page.waitForTimeout(resolveTimeout(500));
  }

  throw new Error("Timed out waiting for one of the expected Nextcloud selectors to become visible");
}

const serverErrorByPage = new WeakMap();
const LOGIN_CALLBACK = /\/apps\/(?:sociallogin|oidc_login)\//;

function trackServerErrors(page) {
  if (serverErrorByPage.has(page)) {
    return;
  }

  serverErrorByPage.set(page, null);
  page.on("response", (response) => {
    const request = response.request();

    if (request.resourceType() !== "document") {
      return;
    }

    if (request.frame() !== page.mainFrame()) {
      return;
    }

    const status = response.status();
    const url = response.url().split("?")[0];
    const failed = status >= 500 || (status >= 400 && LOGIN_CALLBACK.test(url));
    serverErrorByPage.set(page, failed ? { status, url } : null);
  });
}

async function waitForVisibleCandidate(
  page,
  candidates,
  timeout = resolveTimeout(60_000),
  errorMessage = "Timed out waiting for one of the expected Nextcloud selectors to become visible"
) {
  const deadline = Date.now() + timeout;

  trackServerErrors(page);

  while (Date.now() < deadline) {
    const visibleCandidate = await findFirstVisibleCandidate(candidates);

    if (visibleCandidate) {
      return visibleCandidate;
    }

    const serverError = serverErrorByPage.get(page);

    if (serverError) {
      throw new Error(
        `${errorMessage} — the page itself failed: HTTP ${serverError.status} for ${serverError.url}`
      );
    }

    await page.waitForTimeout(resolveTimeout(500));
  }

  throw new Error(errorMessage);
}

async function dismissBlockingNextcloudModals(page, nextcloudFrame, maxDismissals = 4) {
  const modalOverlay = nextcloudFrame.locator(
    "#firstrunwizard.modal-mask, #firstrunwizard[role='dialog'], .modal-mask[role='dialog'], [role='dialog'][aria-modal='true']"
  );
  const dismissButtonCandidates = [
    nextcloudFrame.getByRole("button", { name: /^close$/i }),
    nextcloudFrame.getByRole("button", { name: /^schlie(?:ss|ß)en$/i }),
    nextcloudFrame.locator(
      ".modal-mask .modal-container__close, .modal-mask .header-close, [role='dialog'] .modal-container__close, [role='dialog'] .header-close"
    ),
    nextcloudFrame.locator(
      ".modal-mask .next, .modal-mask button[aria-label='Next'], [role='dialog'] .next, [role='dialog'] button[aria-label='Next']"
    ),
    nextcloudFrame.getByRole("button", { name: /skip|not now|later|dismiss|done|got it/i })
  ];
  let stableChecksWithoutModal = 0;

  for (let i = 0; i < maxDismissals; i += 1) {
    if (!(await modalOverlay.first().isVisible().catch(() => false))) {
      stableChecksWithoutModal += 1;
      if (stableChecksWithoutModal >= 2) {
        return;
      }
      await page.waitForTimeout(resolveTimeout(600));
      continue;
    }

    stableChecksWithoutModal = 0;
    let dismissed = false;

    for (const candidate of dismissButtonCandidates) {
      const button = candidate.first();
      if (await button.isVisible().catch(() => false)) {
        await button.click({ timeout: resolveTimeout(2_000) }).catch(() => {});
        dismissed = true;
        break;
      }
    }

    if (!dismissed) {
      await page.keyboard.press("Escape").catch(() => {});
    }

    await page.waitForTimeout(resolveTimeout(300));
  }
}

async function clickWithModalRetry(page, nextcloudFrame, target, attempts = 5) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    await dismissBlockingNextcloudModals(page, nextcloudFrame, 6);

    try {
      await target.click({ timeout: resolveTimeout(4_000) });
      return;
    } catch (error) {
      const message = String(error && error.message ? error.message : error);
      const retriable = /intercepts pointer events|timed out|timeout/i.test(message);

      if (!retriable || attempt === attempts) {
        throw error;
      }
      await page.waitForTimeout(resolveTimeout(500));
    }
  }
}

module.exports = {
  getNextcloudShellCandidates,
  waitForFirstVisible,
  trackServerErrors,
  waitForVisibleCandidate,
  dismissBlockingNextcloudModals,
  clickWithModalRetry,
};
