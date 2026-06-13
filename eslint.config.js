const js = require("@eslint/js");
const playwright = require("eslint-plugin-playwright");
const globals = require("globals");

module.exports = [
  {
    ignores: [
      "node_modules/**",
      "venv/**",
      ".venv/**",
      "**/__pycache__/**",
      // Jinja2-templated JS — not valid JS until rendered.
      "roles/*/templates/**/*.js",
    ],
  },
  {
    linterOptions: {
      reportUnusedDisableDirectives: "warn",
    },
  },
  js.configs.recommended,
  {
    // Repo-root config / build files are CommonJS Node modules.
    files: ["*.js", "*.cjs"],
    languageOptions: {
      sourceType: "commonjs",
      globals: { ...globals.node },
    },
  },
  {
    files: ["roles/**/files/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "commonjs",
      globals: {
        ...globals.node,
        // Specs and persona helpers run inside `page.evaluate(() => …)`
        // callbacks where window/document/getComputedStyle/etc. are valid;
        // adding the browser globals avoids a sea of `no-undef` false
        // positives.
        ...globals.browser,
      },
    },
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "no-var": "error",
      "eqeqeq": ["error", "always"],
      "prefer-const": "error",
      "prefer-template": "error",
      "no-throw-literal": "error",
      "no-self-compare": "error",
      "default-case-last": "error",
      // Defensive: forbid string-driven code execution shapes outright.
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      // Empty `catch (e) {}` is the project's idiom for fire-and-forget
      // best-effort actions (localStorage probes, optional cleanups, …);
      // the catch protects the surrounding flow from incidental
      // failures it can't act on.
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
  {
    // SSO sidecar shims (oauth2-proxy header-auth / server patches) are
    // authored as ES modules (import/export), not CommonJS.
    files: ["roles/**/files/sso/**/*.js"],
    languageOptions: {
      sourceType: "module",
    },
  },
  {
    files: [
      "roles/**/files/playwright/**/*.js",
      "roles/test-e2e-playwright/files/personas/**/*.js",
    ],
    plugins: { playwright },
    rules: {
      ...playwright.configs["flat/recommended"].rules,
      // skipUnlessServiceEnabled() drives a real test.skip(...) on
      // runtime-detected disabled services — that's the project's
      // contract, not an oversight.
      "playwright/no-skipped-test": "off",
      // Persona helpers (runGuestFlow / runBiberFlow / runAdminFlow) branch
      // on isVisible() / isServiceEnabled() before expect(); the conditional
      // is the contract, not a bug.
      "playwright/no-conditional-expect": "off",
      "playwright/no-conditional-in-test": "off",
      // Some specs use waitForTimeout deliberately for OIDC settle delays
      // and federation propagation — banning it would force rewrites.
      "playwright/no-wait-for-timeout": "off",
      // The OIDC + post-redirect dance settles when the page is idle, not
      // on a single load event. Several specs rely on
      // waitForLoadState("networkidle") for that; banning it would force
      // a coordinated rewrite of every flow. Tracked for a follow-up.
      "playwright/no-networkidle": "off",
      // Real lint signal, but the autofixer is not safe in every site we
      // hit (it produced a broken diff in personas/utils/dashboard.js by
      // dropping the `await getAttribute("href")` step and leaving a
      // trailing-comma `toHaveAttribute("href", )` call). Keep off until
      // a hand-migration pass; promote to "error" as those are reviewed.
      "playwright/prefer-web-first-assertions": "off",
      "playwright/no-wait-for-navigation": "error",
    },
  },
];
