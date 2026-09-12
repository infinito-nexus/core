const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

const INSPECTOR_MODULE = "ext.visualEditorPlus.inlineTextInspector";

test("VisualEditorPlus: the extension is loaded and serves the inspector module AIEditingAssistant depends on", async ({
  request,
}) => {
  skipUnlessAddonEnabled("VisualEditorPlus");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const siteinfo = await request.get(
    `${appBaseUrl}/api.php?action=query&meta=siteinfo&siprop=extensions&format=json&formatversion=2`,
    { timeout: resolveTimeout(60_000) },
  );
  expect(
    siteinfo.status(),
    "the MediaWiki action API must answer so the loaded extension list can be read",
  ).toBe(200);

  const installed = ((await siteinfo.json()).query?.extensions || []).map(
    (extension) => extension.name,
  );
  expect(
    installed,
    "VisualEditor must be loaded: AIEditingAssistant's extension.json hard-requires it and " +
      "ExtensionRegistry raises a fatal ExtensionDependencyError when it is absent",
  ).toContain("VisualEditor");
  expect(
    installed,
    "VisualEditorPlus is not loaded; it is not bundled in the mediawiki image, so a missing " +
      "tarball or an unfinished composer install left LocalSettings.php's file_exists guard closed",
  ).toContain("VisualEditorPlus");

  const module = await request.get(
    `${appBaseUrl}/load.php?modules=${INSPECTOR_MODULE}&only=scripts&raw=1&debug=1`,
    { timeout: resolveTimeout(60_000) },
  );
  expect(module.status(), `load.php must serve ${INSPECTOR_MODULE}`).toBe(200);

  const script = await module.text();
  expect(
    script.length,
    `${INSPECTOR_MODULE} rendered an empty payload; AIEditingAssistant's inspector module ` +
      "depends on it and would never load in VisualEditor",
  ).toBeGreaterThan(0);
  expect(
    /"missing"|no such module/i.test(script),
    `ResourceLoader reports ${INSPECTOR_MODULE} as missing, so VisualEditorPlus registered no ` +
      `modules: ${script.slice(0, 300)}`,
  ).toBe(false);
});
