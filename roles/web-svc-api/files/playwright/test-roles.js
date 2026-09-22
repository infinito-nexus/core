const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

function forkRef(repositories) {
  const fork = repositories.find((entry) => !entry.root && entry.branches.length > 0);
  return `${fork.repository.split("/")[0]}:${fork.branches[0].name}`;
}

exports.register = function (shared) {
  test("roles of the deployed working tree carry title, description, categories and invokable flag", async ({ request }) => {
    const { body } = await shared.getJson(request, "/v1/roles", { ref: "deployed" });
    const role = body.roles.find((entry) => entry.id === shared.translatedRole);
    expect(role, `Expected ${shared.translatedRole} among the deployed roles`).toBeTruthy();
    expect(role.title).toBeTruthy();
    expect(role.description).toBeTruthy();
    expect(role.categories).toEqual(["web", "web.svc"]);
    expect(role.invokable).toBe(true);
    expect(body.roles.find((entry) => entry.id === "sys-ctl-cln-bkps")?.invokable).toBe(false);
  });

  test("role detail returns every meta file, vars and the README title", async ({ request }) => {
    const { body } = await shared.getJson(request, `/v1/roles/${shared.translatedRole}`, { ref: "deployed" });
    expect(Object.keys(body.role.meta).sort()).toEqual(
      expect.arrayContaining(["csp", "domains", "info", "main", "networks", "services", "variants", "volumes"]),
    );
    expect(body.role.meta.domains.canonical[0]).toContain("api.");
    expect(body.role.vars.application_id).toBe(shared.translatedRole);
    expect(body.role.title).toBe("API");
  });

  test("categories and bundles are served for a ref", async ({ request }) => {
    const categories = (await shared.getJson(request, "/v1/categories", { ref: "deployed" })).body.categories;
    const web = categories.find((category) => category.id === "web");
    expect(web.children.map((child) => child.id)).toContain("web.app");
    const bundles = (await shared.getJson(request, "/v1/bundles", { ref: "deployed" })).body.bundles;
    expect(bundles.length).toBeGreaterThan(0);
    for (const bundle of bundles) {
      expect(bundle.id).toBe(`${bundle.deploy_target}/${bundle.slug}`);
      expect(bundle.title, `Expected a title on bundle ${bundle.id}`).toBeTruthy();
      expect(Array.isArray(bundle.role_ids), `Expected a role list on bundle ${bundle.id}`).toBe(true);
    }
    expect(bundles.some((bundle) => bundle.role_ids.includes("web-app-keycloak")), "Expected a bundle deploying keycloak").toBe(true);
  });

  test("the same role request answers for deployed, a tag, its SHA and a fork branch", async ({ request }) => {
    test.setTimeout(resolveTimeout(960_000)); // the first fetch of core and every fork after the container start
    const repositories = await shared.repositoriesWithForks(request);
    const tag = shared.newestReleaseTag(repositories);
    for (const ref of ["deployed", tag.name, tag.sha, tag.sha.slice(0, 12), forkRef(repositories)]) {
      const { response, body } = await shared.getJson(request, "/v1/roles", { ref });
      expect(body.roles.length, `Expected roles at ${ref}`).toBeGreaterThan(100);
      expect(body.roles.find((role) => role.id === "web-app-keycloak"), `Expected keycloak at ${ref}`).toBeTruthy();
      if (ref === tag.sha) {
        expect(body.commit).toBe(tag.sha);
        expect(response.headers()["cache-control"]).toContain("immutable");
      }
    }
  });

  test("invalid refs answer 400 and unknown refs or roles answer 404", async ({ request }) => {
    for (const ref of ["-x", "a..b", "x:y:z", "main@{1}"]) {
      expect(await shared.statusOf(request, "/v1/roles", { ref }), `Expected ${ref} to be invalid`).toBe(400);
    }
    expect(await shared.statusOf(request, "/v1/roles", {})).toBe(400);
    expect(await shared.statusOf(request, "/v1/roles", { ref: "no-such-branch-for-sure" })).toBe(404);
    expect(await shared.statusOf(request, "/v1/roles/web-app-no-such-role", { ref: "deployed" })).toBe(404);
  });
};
