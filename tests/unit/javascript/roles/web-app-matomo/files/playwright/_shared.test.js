const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://matomo.example.org";

function strictExpect(actual, message) {
  return {
    toBe: (expected) => assert.equal(actual, expected, message),
    toBeLessThan: (limit) => assert.ok(actual < limit, message),
  };
}

/**
 * Args:
 *   visitsToday: what VisitsSummary.getVisits answers for site 1.
 *
 * Returns:
 *   The `seedVisits` of _shared.js and the form of every request it sent, keyed by path.
 */
function loadSeedVisits(visitsToday) {
  const sent = [];
  const apiFetchOnion = async (request, url, { form }) => {
    const { pathname } = new URL(url);
    sent.push({ pathname, form });
    return pathname === "/index.php"
      ? { status: () => 200, json: async () => ({ value: visitsToday }) }
      : { status: () => 204 };
  };
  const { seedVisits } = loadInternals(
    path.join(PROJECT_ROOT, "roles/web-app-matomo/files/playwright/_shared.js"),
    ["seedVisits"],
    {
      "@playwright/test": { expect: strictExpect, test: {} },
      "./timeouts": { resolveTimeout: (ms) => ms },
      "./personas": {
        apiFetchOnion,
        decodeDotenvJsonList: () => [],
        decodeDotenvQuotedValue: (value) => value,
        normalizeBaseUrl: () => BASE,
        requireDotenvValue: (value) => value,
      },
    },
    { URL },
  );
  return { seedVisits, sent };
}

test("a site 1 without today's showcase visits gets them recorded through the tracking API", async () => {
  const { seedVisits, sent } = loadSeedVisits(0);

  await seedVisits({});

  const [count, ...hits] = sent;
  assert.equal(count.pathname, "/index.php");
  assert.deepEqual(
    { method: count.form.method, idSite: count.form.idSite, period: count.form.period, date: count.form.date },
    { method: "VisitsSummary.getVisits", idSite: "1", period: "day", date: "today" },
  );
  assert.equal(hits.length, 20);
  assert.ok(hits.every(({ pathname, form }) => pathname === "/matomo.php" && form.idsite === "1" && form.rec === "1"));
});

test("a site 1 that already holds today's showcase visits gets no further hit", async () => {
  const { seedVisits, sent } = loadSeedVisits(20);

  await seedVisits({});

  assert.deepEqual(
    sent.map(({ pathname }) => pathname),
    ["/index.php"],
  );
});
