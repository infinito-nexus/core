const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("repositories list core and its forks, and the log follows a ref", async ({ request }) => {
    test.setTimeout(resolveTimeout(960_000)); // the first fetch of core and every fork after the container start
    const repositories = await shared.repositoriesWithForks(request);
    const root = repositories.find((entry) => entry.root);
    expect(root.repository).toBe("infinito-nexus/core");
    expect(root.branches.map((branch) => branch.name)).toContain("main");
    for (const ref of [...root.branches, ...root.tags]) {
      expect(ref.sha, `Expected ${ref.name} to carry a commit SHA`).toMatch(/^[0-9a-f]{40}$/);
      expect(Date.parse(ref.date), `Expected ${ref.name} to carry a date`).not.toBeNaN();
    }

    const tag = shared.newestReleaseTag(repositories);
    const { body } = await shared.getJson(request, "/v1/log", { ref: tag.name, limit: "5" });
    expect(body.commit).toBe(tag.sha);
    expect(body.commits).toHaveLength(5);
    expect(body.commits[0].sha).toBe(tag.sha);
    for (const commit of body.commits) {
      expect(Object.keys(commit).sort()).toEqual(["date", "message", "parents", "sha"]);
    }

    const bounded = await shared.getJson(request, "/v1/log", { ref: tag.name, limit: "50", until: body.commits[2].date });
    const limit = Date.parse(body.commits[2].date);
    expect(bounded.body.commits.length).toBeGreaterThan(0);
    expect(bounded.body.commits.every((commit) => Date.parse(commit.date) <= limit)).toBe(true);
  });
};
