const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-joomla/files/playwright/test-profile-lock.js");
const noop = () => undefined;
const SITE = "http://joomla.example.test";
const EDITOR_FIELD = "jform[params][editor]";
const EDITORS = ["", "codemirror", "none", "tinymce"];
const LOCK_BROKEN = new Error("a direct profile POST must not change #jform_name");
const BREAK_GLASS = "administrator: a local break-glass session";
const LOCK_CATALOGUE = JSON.stringify({ en: { locked: "Managed by the SSO login" } });
const RENDERED_DOCUMENT = { documentElement: { lang: "en-GB" } };

/**
 * Args:
 *   matcher: what every assertion method does.
 * Returns:
 *   object: an expect() result whose every method, `.not` included, runs matcher.
 */
function assertion(matcher) {
  const result = new Proxy(
    {},
    {
      get: (target, name) => {
        if (name === "then") return undefined;
        return name === "not" ? result : matcher;
      },
    },
  );
  return result;
}

const passes = assertion(async () => undefined);
const breaksLock = assertion(async () => {
  throw LOCK_BROKEN;
});
let failingMessage = null;

const { expectDirectSaveKeeps } = loadInternals(
  SPEC,
  ["expectDirectSaveKeeps"],
  {
    "@playwright/test": {
      test: Object.assign(noop, { use: noop }),
      expect: (actual, message) => (failingMessage && String(message).startsWith(failingMessage) ? breaksLock : passes),
    },
    "./personas": {
      decodeDotenvQuotedValue: (value) => value,
      gotoOnion: async () => undefined,
      normalizeBaseUrl: () => SITE,
      requireDotenvValue: () => "{}",
    },
  },
  { URL },
);

const scenarios = [];
const browserGlobals = { URL, document: RENDERED_DOCUMENT, navigator: { language: "en-US" } };

loadInternals(
  SPEC,
  [],
  {
    "@playwright/test": {
      test: Object.assign((title, body) => scenarios.push({ title, body }), { use: noop, setTimeout: noop }),
      expect: (actual) => assertion(async () => (actual && typeof actual.settle === "function" ? actual.settle() : undefined)),
    },
    "./personas": {
      decodeDotenvQuotedValue: (value) => value,
      gotoOnion: async () => undefined,
      installCspViolationObserver: async () => undefined,
      normalizeBaseUrl: () => SITE,
      requireDotenvValue: (value, name) => (name === "PROFILE_LOCK_I18N_JSON" ? LOCK_CATALOGUE : "{}"),
    },
    "./joomla-session": {
      signInToAdministrator: async () => undefined,
      signInToSite: async () => undefined,
      userManagerRow: async (page) => page.locator("form#adminForm table tbody tr"),
    },
  },
  browserGlobals,
);

/**
 * Args:
 *   editor: the editor the account stores before the spec runs.
 * Returns:
 *   object: a profile form page whose `posts` records every profile POST and whose `stored` is the account's editor.
 */
function profilePage(editor) {
  const page = { stored: editor, posts: [] };
  page.locator = (selector) => {
    const self = {
      first: () => self,
      inputValue: async () => page.stored,
      evaluate: async (fn) =>
        selector.endsWith("#jform_params_editor")
          ? fn({ value: page.stored, options: EDITORS.map((value) => ({ value })) })
          : {
              action: `${SITE}/index.php/component/users/profile?layout=edit`,
              fields: { "jform[name]": "Biber", [EDITOR_FIELD]: page.stored },
            },
    };
    return self;
  };
  page.request = {
    post: async (action, { form }) => {
      page.posts.push(form);
      page.stored = form[EDITOR_FIELD];
      return { headers: () => ({ location: "/index.php?option=com_users&view=profile" }), status: () => 303 };
    },
  };
  return page;
}

/**
 * Returns:
 *   object: a Joomla page whose link click commits a document the parser has not built a root element for yet, and
 *     whose locator assertions wait until it has, as the browser does after a click that navigates.
 */
function navigatingPage() {
  const page = {
    on: noop,
    evaluate: async (fn) => fn(),
  };
  page.locator = (selector) => {
    const self = {
      selector,
      first: () => self,
      locator: (inner) => page.locator(`${selector} ${inner}`),
      click: async () => {
        browserGlobals.document = { documentElement: null };
      },
      settle: () => {
        browserGlobals.document = RENDERED_DOCUMENT;
      },
    };
    return self;
  };
  return page;
}

const browser = {
  newContext: async () => ({
    newPage: async () => navigatingPage(),
    clearCookies: async () => undefined,
    close: async () => undefined,
  }),
};

test("the direct save proves the editor saves and then puts the account back on the site default editor", async () => {
  const page = profilePage("");
  await expectDirectSaveKeeps(page, { "jform[name]": "Biber" }, { "jform[name]": "Biber tampered" });
  assert.deepEqual(
    page.posts.map((form) => form[EDITOR_FIELD]),
    ["codemirror", ""],
  );
  assert.equal(page.stored, "");
});

test("an account a failed earlier attempt left on another editor ends on the default editor, not on that snapshot", async () => {
  const page = profilePage("codemirror");
  await expectDirectSaveKeeps(page, { "jform[name]": "Biber" }, {});
  assert.equal(page.posts.at(-1)[EDITOR_FIELD], "");
  assert.equal(page.stored, "");
});

test("an assertion failing between the two POSTs still sends the restoring POST and propagates its own error", async () => {
  failingMessage = "a direct profile POST must not change";
  const page = profilePage("");
  try {
    await assert.rejects(
      expectDirectSaveKeeps(page, { "jform[name]": "Biber" }, { "jform[name]": "Biber tampered" }),
      (error) => error === LOCK_BROKEN,
    );
  } finally {
    failingMessage = null;
  }
  assert.deepEqual(
    page.posts.map((form) => form[EDITOR_FIELD]),
    ["codemirror", ""],
  );
  assert.equal(page.stored, "", "the retry must start from the default editor");
});

test("only the tampering POST carries the overridden locked fields, the restoring POST sends the form as rendered", async () => {
  const page = profilePage("");
  await expectDirectSaveKeeps(page, { "jform[name]": "Biber" }, { "jform[name]": "Biber tampered" });
  assert.equal(page.posts[0]["jform[name]"], "Biber tampered");
  assert.equal(page.posts[1]["jform[name]"], "Biber");
  assert.ok(page.posts.every((form) => form.task === "profile.save"));
});

test("the break-glass scenario reads the backend page language only once the user edit form the click opens rendered", async () => {
  const breakGlass = scenarios.find((scenario) => scenario.title.startsWith(BREAK_GLASS));
  assert.ok(breakGlass, "the spec must register the break-glass scenario");
  browserGlobals.document = RENDERED_DOCUMENT;
  await breakGlass.body({ browser });
});
