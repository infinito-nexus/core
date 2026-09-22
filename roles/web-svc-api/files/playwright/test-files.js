const { test, expect } = require("@playwright/test");

const SNAPSHOT_ROOT = ["default.env", "inventories", "locale", "meta", "roles", "tests"];

exports.register = function (shared) {
  test("tree, file and todos read a ref without a clone", async ({ request }) => {
    const tree = (await shared.getJson(request, "/v1/tree", { ref: "deployed", path: `roles/${shared.translatedRole}` })).body;
    expect(tree.entries.map((entry) => entry.name)).toEqual(expect.arrayContaining(["meta", "tasks", "files"]));

    const file = await request.get(
      shared.apiUrl("/v1/file", { ref: "deployed", path: `roles/${shared.translatedRole}/meta/domains.yml` }),
    );
    expect(file.status()).toBe(200);
    expect(file.headers()["content-type"]).toContain("text/plain");
    expect(file.headers()["x-content-type-options"]).toBe("nosniff");
    expect(await file.text()).toContain("api.{{ DOMAIN_PRIMARY }}");

    const todos = (await shared.getJson(request, "/v1/todos", { ref: "deployed" })).body;
    expect(todos.items.length).toBeGreaterThan(0);
    for (const item of todos.items.slice(0, 20)) {
      expect(["TODO", "FIXME"]).toContain(item.kind);
      expect(item.line).toBeGreaterThan(0);
      expect(item.text).toContain(item.kind);
    }
  });

  test("invalid paths answer 400 and missing paths 404", async ({ request }) => {
    expect(await shared.statusOf(request, "/v1/file", { ref: "deployed", path: "../etc/passwd" })).toBe(400);
    expect(await shared.statusOf(request, "/v1/file", { ref: "deployed", path: "/etc/passwd" })).toBe(400);
    expect(await shared.statusOf(request, "/v1/file", { ref: "deployed", path: "roles/no-such-file.yml" })).toBe(404);
    expect(await shared.statusOf(request, "/v1/tree", { ref: "deployed", path: "default.env" })).toBe(404);
  });

  test("the deployed snapshot holds no credential of the deployment", async ({ request }) => {
    expect(shared.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    const root = (await shared.getJson(request, "/v1/tree", { ref: "deployed", path: "" })).body;
    expect(root.entries.map((entry) => entry.name).sort()).toEqual(SNAPSHOT_ROOT);
    const inventories = (await shared.getJson(request, "/v1/tree", { ref: "deployed", path: "inventories" })).body;
    expect(inventories.entries.map((entry) => entry.name), "Expected no inventory but the bundles in the snapshot").toEqual(["bundles"]);
    const payloads = [
      await request.get(shared.apiUrl("/v1/roles", { ref: "deployed" })),
      await request.get(shared.apiUrl("/v1/bundles", { ref: "deployed" })),
      await request.get(shared.apiUrl("/v1/file", { ref: "deployed", path: "default.env" })),
    ];
    for (const payload of payloads) {
      expect(payload.status()).toBe(200);
      expect(await payload.text(), `Expected no administrator password in ${payload.url()}`).not.toContain(shared.adminPassword);
    }
  });
};
