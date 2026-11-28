const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");
const {
  gotoOnion,
  keycloakAdminCreateUser,
  keycloakAdminDeleteUser,
  keycloakAdminToken,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
  webmailSsoLogin,
} = require("./personas");
const workspaces = require("./workspace-fixture");

const LABEL = "administrator-export";
const EXPORT_TEMPLATE_PREFIX = "export";
const ANNOUNCE_TEMPLATE = "announce owners";
const PRUNE_TEMPLATE = "prune exports";
const TENANT_MOUNT = "tenant";
const OWNER_GROUP = "Owner";
const VIEWER_GROUP = "Viewer";
const FORMER_OWNER_GROUP = "Owner before the rename";
const NESTED_GROUP = "Nested owners";
const WORKSPACE_MARKER = "workspace.id";
const RECIPIENT_ATTRIBUTE = "export_recipient";
const ARCHIVE_MEMBERS = ["passphrase.age:0", "secrets.kdbx:0"];
const EXPORT_SURVEY = [
  ["WORKSPACE", true, "env"],
  ["EXPORT_FOR", true, "env"],
];
const GUEST_GRANT = { role_slug: "guest", permissions: 129 };
const REFUSED_NON_OWNER = "export refused: EXPORT_FOR is no direct member of the pinned Owner group";
const REFUSED_NO_RECIPIENT = "export refused: the owner holds no age recipient";
const STARTS_NOW = "An export of the workspace secrets starts now.";
const PRESIGNED = /X-Amz-Signature=/;
const AMZ_DATE = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/;
const MAILBOXES = ["INBOX", "Junk Mail"];
const MESSAGE_LIST = "#messagelist, table.messagelist";
const MESSAGE_ROWS = "#messagelist tbody tr, table.messagelist tbody tr";
const WITHOUT_WEBMAIL = "WEBMAIL_BASE_URL is empty: the mail provider serves no webmail to read the notices from";
const SPLIT_REALM = "clearnet webmail with an onion OIDC issuer: unreachable from one browser";
const PERSISTENCE_PROBE = `set -u
exec python3 - "$@" <<'PY'
import os, sys, tempfile
PSEUDO = {"cgroup", "cgroup2", "devpts", "mqueue", "proc", "sysfs"}
own, earlier = sys.argv[1], sys.argv[2:]
mounts = {}
with open("/proc/self/mounts") as table:
    for line in table:
        _, point, kind, options = line.split()[:4]
        mounts[point.encode().decode("unicode_escape")] = (kind, options.split(","))
writable = sorted(
    point
    for point, (kind, options) in mounts.items()
    if kind not in PSEUDO and "rw" in options and os.path.isdir(point) and os.access(point, os.W_OK)
)
def marked(point, marker):
    return os.path.join(point, ".probe-persist-" + marker)
def present(marker):
    return sum(os.path.lexists(marked(point, marker)) for point in writable)
def holder(target):
    target = os.path.realpath(target)
    return max((point for point in mounts if target == point or target.startswith(point.rstrip("/") + "/")), key=len)
def coverage(target):
    point = holder(target)
    if point in planted:
        return "yes"
    if "ro" in mounts[point][1] or not os.access(target, os.W_OK):
        return "ro"
    return "no"
planted = []
for point in writable:
    try:
        os.close(os.open(marked(point, own), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except OSError:
        continue
    planted.append(point)
print("PROBE root " + ("ro" if "ro" in mounts["/"][1] else "rw"))
for point in writable:
    print("PROBE mount " + point + " " + ("planted" if point in planted else "refused"))
for label, target in (("cwd", os.getcwd()), ("home", os.path.expanduser("~")), ("tempdir", tempfile.gettempdir())):
    print("PROBE covers " + label + " " + coverage(target))
print("PROBE control " + str(present(own)))
print("PROBE survived " + str(sum(present(marker) for marker in earlier)))
PY
`;
const PERSISTENCE_TMPFS = ["/tmp", "/tmp/semaphore"];
const PERSISTENCE_COVERS = { cwd: ["yes", "ro"], home: ["yes"], tempdir: ["yes"] };

const LINK_SECONDS = 900;
const DAY_MS = 24 * 60 * 60_000;
const PRUNE_AGE_MS = 60 * 60_000;
const CLOCK_GRACE_MS = 2 * 60_000;
const SETUP_MS = 45 * 60_000;
const CLEANUP_MS = 35 * 60_000;
const EXPORT_RUN_MS = 10 * 60_000;
const ANNOUNCE_RUN_MS = 10 * 60_000;
const PRUNE_RUN_MS = 10 * 60_000;
const LOGIN_MS = 120_000;
const MAIL_MS = 5 * 60_000;
const MAIL_POLL_INTERVAL_MS = 10_000;

function keycloakBase() {
  return normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
}

function realm() {
  return requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
}

function superAdmin() {
  return {
    username: requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME"),
    password: requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD"),
    options: {
      adminRealm: requireDotenvValue(process.env.KEYCLOAK_ADMIN_REALM, "KEYCLOAK_ADMIN_REALM"),
      adminClientId: requireDotenvValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID, "KEYCLOAK_ADMIN_CLI_CLIENT_ID"),
    },
  };
}

function exportProjectName() {
  return requireDotenvValue(process.env.SEMAPHORE_EXPORT_PROJECT_NAME, "SEMAPHORE_EXPORT_PROJECT_NAME");
}

function exportRunnerTag() {
  return requireDotenvValue(process.env.SEMAPHORE_EXPORT_RUNNER_TAG, "SEMAPHORE_EXPORT_RUNNER_TAG");
}

function minAgeDays() {
  return Number(requireDotenvValue(process.env.SEMAPHORE_EXPORT_OWNER_MIN_AGE_DAYS, "SEMAPHORE_EXPORT_OWNER_MIN_AGE_DAYS"));
}

function webmailBase() {
  return normalizeBaseUrl(process.env.WEBMAIL_BASE_URL);
}

function skipUnlessWebmail() {
  test.skip(!webmailBase(), WITHOUT_WEBMAIL);
  test.skip(isSplitRealmOidc(), SPLIT_REALM);
}

/**
 * Args:
 *   address: biber's mailbox address.
 *   tag: the subaddress tag.
 *
 * Returns:
 *   The tagged address, delivered to biber's mailbox.
 */
function subAddress(address, tag) {
  const at = address.lastIndexOf("@");
  return `${address.slice(0, at)}+${tag}${address.slice(at)}`.toLowerCase();
}

/**
 * Args:
 *   source: the raw source of a message.
 *
 * Returns:
 *   Its unfolded `to` header, lowercased, and its decoded text `body`.
 */
function mimeParts(source) {
  const split = source.search(/\r?\n\r?\n/);
  const headers = source.slice(0, split).replace(/\r?\n[ \t]+/g, " ");
  let body = source.slice(split).trim();
  const encoding = (/^content-transfer-encoding:\s*(\S+)/im.exec(headers) || [])[1];
  if (/^quoted-printable$/i.test(encoding || "")) {
    body = Buffer.from(
      body.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16))),
      "latin1",
    ).toString("utf8");
  } else if (/^base64$/i.test(encoding || "")) {
    body = Buffer.from(body, "base64").toString("utf8");
  }
  return { to: ((/^to:\s*(.*)$/im.exec(headers) || [])[1] || "").toLowerCase(), body: body.replace(/\r\n/g, "\n") };
}

async function sleepUntil(epochMs) {
  const wait = epochMs - Date.now();
  if (wait > 0) {
    await new Promise((resolve) => setTimeout(resolve, wait));
  }
}

exports.register = function (shared) {
  test.describe("workspace secret export", () => {
    test.describe.configure({ retries: 0 });
    let fixture;
    let world;
    let standingExport;

    /**
     * Args:
     *   method: the HTTP method.
     *   path: the path below the realm's admin API.
     *   data: the JSON body, undefined for none.
     *   statuses: the statuses the call accepts.
     *
     * Returns:
     *   The parsed answer, null for an empty one.
     */
    async function keycloakAdmin(method, path, data, statuses) {
      const admin = superAdmin();
      const token = await keycloakAdminToken(
        fixture.context.request,
        keycloakBase(),
        admin.username,
        admin.password,
        admin.options,
      );
      const response = await workspaces.http(
        fixture.context,
        method,
        `${keycloakBase()}/admin/realms/${encodeURIComponent(realm())}/${path}`,
        {
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          ...(data === undefined ? {} : { data }),
        },
      );
      await workspaces.expectStatus(response, statuses, `${LABEL}: Keycloak ${method} ${path.split("?")[0]}`);
      const text = await response.text();
      return text ? JSON.parse(text) : null;
    }

    async function markedOrganization() {
      const query = new URLSearchParams({
        q: `${WORKSPACE_MARKER}:${fixture.workspace}`,
        briefRepresentation: "false",
        first: "0",
        max: "2",
      });
      const found = await keycloakAdmin("GET", `organizations?${query}`, undefined, [200]);
      const marked = found.filter((organization) =>
        ((organization.attributes || {})[WORKSPACE_MARKER] || []).includes(fixture.workspace),
      );
      expect(marked, `${LABEL}: apply must leave exactly one Keycloak organization marked with ws-${fixture.workspace}`).toHaveLength(1);
      return marked[0].id;
    }

    /**
     * Args:
     *   tag: a word naming the user's part in the test.
     *
     * Returns:
     *   A fresh realm user whose mail reaches biber's mailbox; the cleanup deletes it.
     */
    async function scratchUser(tag) {
      const admin = superAdmin();
      const username = `export-${tag}-${crypto.randomBytes(4).toString("hex")}`;
      const user = {
        username,
        email: subAddress(shared.env.biberEmail, username),
        password: `${crypto.randomBytes(18).toString("base64url")}aA1!`,
      };
      user.id = await keycloakAdminCreateUser(
        fixture.context.request,
        keycloakBase(),
        realm(),
        { ...user, firstName: "Export", lastName: tag },
        admin.username,
        admin.password,
        admin.options,
      );
      world.users.push(user);
      await keycloakAdmin("POST", `organizations/${world.organization}/members`, JSON.stringify(user.id), [201]);
      return user;
    }

    async function joinGroup(groupId, user) {
      await keycloakAdmin("PUT", `organizations/${world.organization}/groups/${groupId}/members/${user.id}`, undefined, [204]);
    }

    async function leaveGroup(groupId, user) {
      await keycloakAdmin("DELETE", `organizations/${world.organization}/groups/${groupId}/members/${user.id}`, undefined, [204]);
    }

    async function renameGroup(groupId, name) {
      const group = await keycloakAdmin("GET", `organizations/${world.organization}/groups/${groupId}`, undefined, [200]);
      await keycloakAdmin("PUT", `organizations/${world.organization}/groups/${groupId}`, { ...group, name }, [204]);
    }

    /**
     * Args:
     *   body: the async work done while the realm stores no admin event, so a
     *     join inside it leaves no membership event, as one older than the
     *     event retention does.
     *
     * Returns:
     *   What `body` returns; the previous events configuration is restored.
     */
    async function withoutAdminEvents(body) {
      const config = await keycloakAdmin("GET", "events/config", undefined, [200]);
      await keycloakAdmin("PUT", "events/config", { ...config, adminEventsEnabled: false }, [204]);
      try {
        return await body();
      } finally {
        await keycloakAdmin("PUT", "events/config", config, [204]);
      }
    }

    function isAccountRead(candidate) {
      return (
        candidate.method() === "GET" &&
        candidate.url().split("?")[0].replace(/\/$/, "") === `${keycloakBase()}/realms/${realm()}/account` &&
        Boolean(candidate.headers().authorization)
      );
    }

    /**
     * Args:
     *   user: a scratch user carrying `age`, a result of `ageIdentity`.
     */
    async function registerRecipient(user) {
      const context = await world.browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        const profileRead = page.waitForRequest(isAccountRead, { timeout: resolveTimeout(LOGIN_MS) });
        await gotoOnion(page, `${keycloakBase()}/realms/${realm()}/account/`);
        await performKeycloakLoginForm(page, user.username, user.password);
        const read = await profileRead;
        const response = await read.response();
        expect(Boolean(response && response.ok()), `${LABEL}: the account console of ${user.username} must read its profile`).toBe(
          true,
        );
        const profile = await response.json();
        const update = await workspaces.http(context, "POST", `${keycloakBase()}/realms/${realm()}/account/`, {
          headers: { Authorization: read.headers().authorization, "Content-Type": "application/json" },
          data: {
            username: profile.username,
            email: profile.email,
            firstName: profile.firstName,
            lastName: profile.lastName,
            attributes: { ...(profile.attributes || {}), [RECIPIENT_ATTRIBUTE]: [user.age.recipient] },
          },
        });
        await workspaces.expectStatus(update, [204], `${LABEL}: ${user.username}'s own write of ${RECIPIENT_ATTRIBUTE}`);
      } finally {
        await context.close();
      }
    }

    /**
     * Args:
     *   tag: a word naming the Owner's part in the test.
     *   aged: whether the join leaves no membership event, as an Owner past the age window.
     *   recipient: whether the Owner registers an age recipient.
     *
     * Returns:
     *   A scratch user that is a direct member of the pinned Owner group.
     */
    async function owner(tag, { aged, recipient }) {
      const user = await scratchUser(tag);
      const join = () => joinGroup(world.ownerGroup, user);
      await (aged ? withoutAdminEvents(join) : join());
      if (recipient) {
        user.age = workspaces.ageIdentity();
        await registerRecipient(user);
      }
      return user;
    }

    async function exportTemplate() {
      const project = await workspaces.namedProject(shared, fixture.page, exportProjectName());
      return {
        project,
        template: await workspaces.namedTemplate(
          shared,
          fixture.page,
          project.id,
          `${EXPORT_TEMPLATE_PREFIX} ws-${fixture.workspace}`,
        ),
      };
    }

    async function exportFor(user, what) {
      const { project, template } = await exportTemplate();
      return workspaces.runTemplate(
        shared,
        fixture.page,
        project.id,
        template.id,
        { WORKSPACE: fixture.workspace, EXPORT_FOR: user.id },
        EXPORT_RUN_MS,
        `${LABEL}: ${what}`,
      );
    }

    function printsLink(run) {
      return run.lines.some((line) => PRESIGNED.test(line));
    }

    async function runStandingExport() {
      const what = `${LABEL}: the export for the standing Owner`;
      const run = await exportFor(world.standing, "the export for the standing Owner");
      workspaces.expectSucceeded(run, what);
      const link = workspaces.lastLine(run.lines);
      expect(/^https:\/\/\S+$/.test(link), `${what}: the last output line must be the presigned link`).toBe(true);
      const url = new URL(link);
      expect(url.pathname, `${what}: the link must name the object of task ${run.task.id}`).toMatch(
        new RegExp(`/exports/ws-${fixture.workspace}/${run.task.id}\\.tar$`),
      );
      const signed = AMZ_DATE.exec(url.searchParams.get("X-Amz-Date") || "");
      expect(Boolean(signed), `${what}: the link must carry its X-Amz-Date`).toBe(true);
      expect(url.searchParams.get("X-Amz-Expires"), `${what}: the link must last ${LINK_SECONDS} seconds`).toBe(String(LINK_SECONDS));
      const response = await workspaces.http(fixture.context, "GET", link);
      await workspaces.expectStatus(response, [200], `${what}: the presigned link right after the task`);
      return {
        run,
        link,
        key: `ws-${fixture.workspace}/${run.task.id}.tar`,
        signedAt: Date.UTC(signed[1], signed[2] - 1, signed[3], signed[4], signed[5], signed[6]),
        archive: await response.body(),
        lastModified: Date.parse(response.headers()["last-modified"]),
      };
    }

    function standingOwnerExport() {
      if (!standingExport) {
        standingExport = runStandingExport();
      }
      return standingExport;
    }

    function openArchive(exported) {
      const members = workspaces.readTar(exported.archive);
      const member = (name) => members.find((candidate) => candidate.name === name).data;
      return { members, member };
    }

    function passphraseOf(exported) {
      const sealed = openArchive(exported).member("passphrase.age");
      return workspaces.ageDecrypt(sealed, world.standing.age.privateKey).toString("utf8");
    }

    function expectedEntries() {
      return Object.fromEntries(
        Object.entries(world.tenant).flatMap(([path, fields]) =>
          Object.entries(fields).map(([field, value]) => [`${path}#${field}`, value]),
        ),
      );
    }

    /**
     * Args:
     *   projectId: the export project.
     *   markers: the random marker this probe task plants, then the markers
     *     of earlier probe tasks it looks for.
     *   what: what the failure messages name.
     *
     * Returns:
     *   `points`, the writable mounts of the export runner, each holding a
     *   file of this task, and `survived`, how many files of the earlier
     *   markers this task found.
     */
    async function persistenceProbe(projectId, markers, what) {
      const run = await workspaces.runProbe(shared, fixture, projectId, PERSISTENCE_PROBE, markers, what);
      workspaces.expectSucceeded(run, what);
      const lines = (kind) => workspaces.probeLines(run, kind);
      expect(lines("root"), `${what}: the root filesystem of the export runner must be read-only`).toEqual(["ro"]);
      const mounts = lines("mount").map((line) => {
        const at = line.lastIndexOf(" ");
        return { point: line.slice(0, at), state: line.slice(at + 1) };
      });
      expect(
        mounts.filter((mount) => mount.state !== "planted").map((mount) => mount.point),
        `${what}: the probe must plant a file in every writable mount`,
      ).toEqual([]);
      const points = mounts.map((mount) => mount.point);
      for (const point of PERSISTENCE_TMPFS) {
        expect(points.includes(point), `${what}: ${point} must be a writable mount of the export runner`).toBe(true);
      }
      const covers = Object.fromEntries(lines("covers").map((line) => line.split(" ")));
      for (const [label, accepted] of Object.entries(PERSISTENCE_COVERS)) {
        expect(
          accepted.includes(covers[label]),
          `${what}: ${label} must be ${accepted.join(" or ")} (yes: on a planted mount, ro: not writable), the probe reported ${covers[label]}`,
        ).toBe(true);
      }
      expect(lines("control"), `${what}: the probe must find the file it planted in each writable mount`).toEqual([String(points.length)]);
      return { points, survived: Number(lines("survived")[0]) };
    }

    async function openMailbox(browser) {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        await webmailSsoLogin(page, shared.env.biberUsername, shared.env.biberPassword, webmailBase());
        return { context, page };
      } catch (error) {
        await context.close();
        throw error;
      }
    }

    /**
     * Args:
     *   mail: the result of `openMailbox`.
     *   subject: the subject the messages carry.
     *
     * Returns:
     *   The `mimeParts` of every message with that subject in biber's INBOX and Junk.
     */
    async function messages(mail, subject) {
      const found = [];
      for (const mailbox of MAILBOXES) {
        await gotoOnion(mail.page, `${webmailBase()}/?_task=mail&_mbox=${encodeURIComponent(mailbox)}`, {
          waitUntil: "domcontentloaded",
        });
        await mail.page.locator(MESSAGE_LIST).first().waitFor({ state: "visible", timeout: resolveTimeout(LOGIN_MS) });
        const rows = await mail.page
          .locator(MESSAGE_ROWS)
          .filter({ hasText: subject })
          .evaluateAll((elements) => elements.map((element) => element.id));
        for (const row of rows) {
          const uid = encodeURIComponent(row.replace(/^rcmrow/, ""));
          const response = await workspaces.http(
            mail.context,
            "GET",
            `${webmailBase()}/?_task=mail&_action=viewsource&_uid=${uid}&_mbox=${encodeURIComponent(mailbox)}`,
          );
          await workspaces.expectStatus(response, [200], `${LABEL}: the source of message ${row} in ${mailbox}`);
          found.push(mimeParts(await response.text()));
        }
      }
      return found;
    }

    /**
     * Args:
     *   mail: the result of `openMailbox`.
     *   subject: the subject the messages carry.
     *   needles: the lines every counted message body holds.
     *   count: how many such messages have to arrive.
     *
     * Returns:
     *   Every message that holds all needles.
     */
    async function awaitMessages(mail, subject, needles, count) {
      let matching = [];
      await expect
        .poll(
          async () => {
            matching = (await messages(mail, subject)).filter((message) => needles.every((needle) => message.body.includes(needle)));
            return matching.length;
          },
          {
            timeout: resolveTimeout(MAIL_MS),
            intervals: [MAIL_POLL_INTERVAL_MS],
            message: `${LABEL}: biber's mailbox must hold ${count} message(s) "${subject}" naming ${needles.join(" / ")}`,
          },
        )
        .toBeGreaterThanOrEqual(count);
      return matching;
    }

    function expectToEveryOwner(message, owners, what) {
      for (const user of owners) {
        expect(message.to.includes(user.email), `${LABEL}: ${what} must go to the Owner ${user.username}`).toBe(true);
      }
    }

    test.beforeAll(async ({ browser }) => {
      workspaces.skipUnlessWorkspaces();
      shared.skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(SETUP_MS));
      fixture = workspaces.workspaceFixture();
      world = { browser, users: [], tenantPaths: [] };
      await workspaces.openWorkspace(shared, browser, fixture, "", LABEL);
      world.organization = await markedOrganization();
      const groups = await keycloakAdmin("GET", `organizations/${world.organization}/groups?first=0&max=100`, undefined, [200]);
      const groupId = (name) => {
        const group = groups.find((candidate) => candidate.name === name);
        expect(Boolean(group), `${LABEL}: apply must create the organization group ${name}`).toBe(true);
        return group.id;
      };
      world.ownerGroup = groupId(OWNER_GROUP);
      world.viewerGroup = groupId(VIEWER_GROUP);
      const salt = crypto.randomBytes(8).toString("hex");
      world.tenant = {
        "probe/alpha": { token: `${salt}<&>"'token` },
        "probe/beta": { password: `pässwörd-${salt}`, username: `probe-${salt}` },
      };
      const token = await workspaces.storeVaultToken(fixture.context);
      for (const [path, data] of Object.entries(world.tenant)) {
        const full = `ws-${fixture.workspace}/${path}`;
        world.tenantPaths.push(full);
        await workspaces.vaultWrite(fixture.context, token, TENANT_MOUNT, full, data);
      }
      world.standing = await owner("standing", { aged: true, recipient: true });
      world.second = await owner("second", { aged: true, recipient: false });
    });

    test.afterAll(async () => {
      if (!fixture || !fixture.context) {
        return;
      }
      test.setTimeout(resolveTimeout(CLEANUP_MS));
      const failures = [];
      const admin = superAdmin();
      for (const user of world.users) {
        try {
          await keycloakAdminDeleteUser(
            fixture.context.request,
            keycloakBase(),
            realm(),
            user.id,
            admin.username,
            admin.password,
            admin.options,
          );
        } catch (error) {
          failures.push(error);
        }
      }
      if (world.tenantPaths.length > 0) {
        try {
          const token = await workspaces.storeVaultToken(fixture.context);
          for (const path of world.tenantPaths) {
            await workspaces.vaultDestroy(fixture.context, token, TENANT_MOUNT, path);
          }
        } catch (error) {
          failures.push(error);
        }
      }
      try {
        await workspaces.closeWorkspace(shared, fixture, LABEL);
      } catch (error) {
        failures.push(error);
      }
      if (failures.length > 0) {
        throw new AggregateError(failures, `${LABEL}: the export cleanup failed: ${failures.map((failure) => failure.message).join("; ")}`);
      }
    });

    test("export: the owner opens the database", async () => {
      test.setTimeout(resolveTimeout(EXPORT_RUN_MS + LOGIN_MS));
      const exported = await standingOwnerExport();
      const { members, member } = openArchive(exported);
      expect(
        members.map((candidate) => `${candidate.name}:${candidate.type}`).sort(),
        `${LABEL}: the archive must hold exactly secrets.kdbx and passphrase.age as regular files`,
      ).toEqual(ARCHIVE_MEMBERS);
      const entries = workspaces.readKdbx(member("secrets.kdbx"), passphraseOf(exported));
      const opened = Object.fromEntries(entries.map((entry) => [entry.Title, entry.Password]));
      const expected = expectedEntries();
      expect(Object.keys(opened).sort(), `${LABEL}: the database must hold one entry per secret field of ws-${fixture.workspace}`).toEqual(
        Object.keys(expected).sort(),
      );
      for (const [title, value] of Object.entries(expected)) {
        expect(opened[title] === value, `${LABEL}: the entry ${title} must carry the value written to the tenant`).toBe(true);
      }
    });

    test("export: no plaintext outlives the task", async () => {
      test.setTimeout(resolveTimeout(EXPORT_RUN_MS + LOGIN_MS + 2 * workspaces.PROBE_RUN_MS));
      const exported = await standingOwnerExport();
      const { project, template } = await exportTemplate();
      const raw = await shared.apiResponse(fixture.page, "GET", `/project/${project.id}/tasks/${exported.run.task.id}/raw_output`);
      expect(raw.ok(), `${LABEL}: Semaphore must answer the raw output of task ${exported.run.task.id}`).toBe(true);
      const records = {
        "the task output": await raw.text(),
        "the task record": JSON.stringify(await shared.api(fixture.page, "GET", `/project/${project.id}/tasks/${exported.run.task.id}`)),
        "the template": JSON.stringify(template),
        "the template environment": JSON.stringify(
          await shared.api(fixture.page, "GET", `/project/${project.id}/environment/${template.environment_id}`),
        ),
      };
      const plaintexts = [["the database passphrase", passphraseOf(exported)]].concat(
        Object.keys(expectedEntries()).map((title) => [`the value of ${title}`, expectedEntries()[title]]),
      );
      for (const [where, text] of Object.entries(records)) {
        for (const [what, plaintext] of plaintexts) {
          expect(text.includes(plaintext), `${LABEL}: ${where} of the export must not carry ${what}`).toBe(false);
        }
      }
      const what = `${LABEL}: the persistence probes on the export runner after task ${exported.run.task.id}`;
      const first = crypto.randomBytes(16).toString("hex");
      const second = crypto.randomBytes(16).toString("hex");
      const planting = await persistenceProbe(project.id, [first], `${what}, first task`);
      const checking = await persistenceProbe(project.id, [second, first], `${what}, second task`);
      expect(checking.points, `${what}: both probe tasks must see the same writable mounts`).toEqual(planting.points);
      expect(checking.survived, `${what}: no file the first probe task planted may reach the next task`).toBe(0);
    });

    test("export: every owner is told", async ({ browser }) => {
      skipUnlessWebmail();
      test.setTimeout(resolveTimeout(EXPORT_RUN_MS + LOGIN_MS + MAIL_MS));
      const exported = await standingOwnerExport();
      const mail = await openMailbox(browser);
      try {
        const [notice] = await awaitMessages(
          mail,
          `Secret export of workspace ws-${fixture.workspace}`,
          [`Owner: ${world.standing.id}`, STARTS_NOW],
          1,
        );
        expectToEveryOwner(notice, [world.standing, world.second], "the export notice");
        expect(notice.body.includes(`Workspace: ws-${fixture.workspace}`), `${LABEL}: the export notice must name the workspace`).toBe(
          true,
        );
        const stamp = /^Time: (\S+)$/m.exec(notice.body);
        expect(Boolean(stamp), `${LABEL}: the export notice must name its time`).toBe(true);
        expect(
          Date.parse(stamp[1]) <= exported.lastModified,
          `${LABEL}: the export notice (${stamp[1]}) must leave before the upload of ${exported.key}`,
        ).toBe(true);
      } finally {
        await mail.context.close();
      }
    });

    test("export: refuses a non-owner and a missing recipient", async () => {
      test.setTimeout(resolveTimeout(2 * EXPORT_RUN_MS + LOGIN_MS));
      const outsider = await scratchUser("outsider");
      await joinGroup(world.viewerGroup, outsider);
      const outside = await exportFor(outsider, "the export for a member outside the Owner group");
      workspaces.expectRefused(outside, REFUSED_NON_OWNER, `${LABEL}: the export for a member outside the Owner group`);
      expect(printsLink(outside), `${LABEL}: the export for a member outside the Owner group must print no link`).toBe(false);
      const unsealed = await exportFor(world.second, "the export for an Owner without a recipient");
      workspaces.expectRefused(unsealed, REFUSED_NO_RECIPIENT, `${LABEL}: the export for an Owner without a recipient`);
      expect(printsLink(unsealed), `${LABEL}: the export for an Owner without a recipient must print no link`).toBe(false);
    });

    test("export: a new owner waits for the age window", async ({ browser }) => {
      skipUnlessWebmail();
      test.setTimeout(resolveTimeout(EXPORT_RUN_MS + 2 * LOGIN_MS + MAIL_MS));
      const newcomer = await owner("newcomer", { aged: false, recipient: true });
      try {
        const reason = `the owner joined less than ${minAgeDays()} days ago`;
        const run = await exportFor(newcomer, "the export for an Owner who just joined");
        workspaces.expectRefused(run, `export refused: ${reason}`, `${LABEL}: the export for an Owner who just joined`);
        expect(printsLink(run), `${LABEL}: the export for an Owner who just joined must print no link`).toBe(false);
        const mail = await openMailbox(browser);
        try {
          const [notice] = await awaitMessages(
            mail,
            `Secret export of workspace ws-${fixture.workspace}`,
            [`Owner: ${newcomer.id}`, `Refused: ${reason}`],
            1,
          );
          expectToEveryOwner(notice, [world.standing, world.second, newcomer], "the refusal notice");
        } finally {
          await mail.context.close();
        }
      } finally {
        await leaveGroup(world.ownerGroup, newcomer);
      }
    });

    test("export: a new owner is announced daily", async ({ browser }) => {
      skipUnlessWebmail();
      test.setTimeout(resolveTimeout(2 * ANNOUNCE_RUN_MS + LOGIN_MS + 2 * MAIL_MS));
      const joinedAfter = Date.now() - CLOCK_GRACE_MS;
      const newcomer = await owner("announced", { aged: false, recipient: false });
      const subject = `New Owner of workspace ws-${fixture.workspace}`;
      const needles = [`New Owner: ${newcomer.username} <${newcomer.email}> (${newcomer.id})`];
      const project = await workspaces.namedProject(shared, fixture.page, exportProjectName());
      const template = await workspaces.namedTemplate(shared, fixture.page, project.id, ANNOUNCE_TEMPLATE);
      const announce = async (what) => {
        const run = await workspaces.runTemplate(shared, fixture.page, project.id, template.id, {}, ANNOUNCE_RUN_MS, `${LABEL}: ${what}`);
        const tail = workspaces.outputTail(run.lines);
        expect(
          run.lines.some((line) => line.includes(`ws-${fixture.workspace}: announced ${newcomer.id}`)),
          `${LABEL}: ${what} must announce ${newcomer.username}; output tail:\n${tail}`,
        ).toBe(true);
        expect(
          run.lines.some((line) => line.includes(`announce owners failed: ws-${fixture.workspace}:`)),
          `${LABEL}: ${what} must not fail on ws-${fixture.workspace}; output tail:\n${tail}`,
        ).toBe(false);
        for (const standing of [world.standing, world.second]) {
          expect(
            run.lines.some((line) => line.includes(`ws-${fixture.workspace}: announced ${standing.id}`)),
            `${LABEL}: ${what} must not announce ${standing.username}, whose membership lies outside the window`,
          ).toBe(false);
        }
      };
      try {
        const mail = await openMailbox(browser);
        try {
          await announce("the first announce owners run");
          const first = await awaitMessages(mail, subject, needles, 1);
          expectToEveryOwner(first[0], [world.standing, world.second, newcomer], "the announcement");
          const joined = /^Joined: (\S+)$/m.exec(first[0].body);
          const firstExport = /^First export possible: (\S+)$/m.exec(first[0].body);
          expect(Boolean(joined && firstExport), `${LABEL}: the announcement must name the join and the first export day`).toBe(true);
          expect(Date.parse(joined[1]) >= joinedAfter, `${LABEL}: the announcement must name the join of ${newcomer.username}`).toBe(true);
          expect(
            Date.parse(firstExport[1]) - Date.parse(joined[1]),
            `${LABEL}: the first export day must lie ${minAgeDays()} days after the join`,
          ).toBe(minAgeDays() * DAY_MS);
          await announce("the second announce owners run");
          await awaitMessages(mail, subject, needles, first.length + 1);
        } finally {
          await mail.context.close();
        }
      } finally {
        await leaveGroup(world.ownerGroup, newcomer);
      }
    });

    test("export: only direct members of the pinned owner group count", async () => {
      test.setTimeout(resolveTimeout(4 * EXPORT_RUN_MS + LOGIN_MS));
      const viewer = await scratchUser("viewer");
      await joinGroup(world.viewerGroup, viewer);
      const nested = await scratchUser("nested");
      const subgroup = await keycloakAdmin(
        "POST",
        `organizations/${world.organization}/groups/${world.ownerGroup}/children`,
        { name: NESTED_GROUP },
        [201],
      );
      try {
        await joinGroup(subgroup.id, nested);
        const inner = await exportFor(nested, "the export for a member of a subgroup of the pinned group");
        workspaces.expectRefused(inner, REFUSED_NON_OWNER, `${LABEL}: the export for a member of a subgroup of the pinned group`);
        expect(printsLink(inner), `${LABEL}: the export for a member of a subgroup must print no link`).toBe(false);
        await renameGroup(world.ownerGroup, FORMER_OWNER_GROUP);
        try {
          await renameGroup(world.viewerGroup, OWNER_GROUP);
          try {
            const renamed = await exportFor(viewer, "the export for a member of the group renamed to Owner");
            workspaces.expectRefused(renamed, REFUSED_NON_OWNER, `${LABEL}: the export for a member of the group renamed to Owner`);
            expect(printsLink(renamed), `${LABEL}: the export for a member of the renamed group must print no link`).toBe(false);
            workspaces.expectSucceeded(
              await exportFor(world.standing, "the export for the standing Owner while the pinned group is renamed"),
              `${LABEL}: the export for the standing Owner while the pinned group is renamed`,
            );
          } finally {
            await renameGroup(world.viewerGroup, VIEWER_GROUP);
          }
        } finally {
          await renameGroup(world.ownerGroup, OWNER_GROUP);
        }
      } finally {
        await keycloakAdmin("DELETE", `organizations/${world.organization}/groups/${subgroup.id}`, undefined, [204]);
      }
    });

    test("export: the link and the object expire", async () => {
      test.setTimeout(resolveTimeout(EXPORT_RUN_MS + PRUNE_AGE_MS + 2 * CLOCK_GRACE_MS + 2 * PRUNE_RUN_MS));
      const exported = await standingOwnerExport();
      await sleepUntil(exported.signedAt + LINK_SECONDS * 1000 + CLOCK_GRACE_MS);
      const expired = await workspaces.http(fixture.context, "GET", exported.link);
      expect(expired.status(), `${LABEL}: the presigned link of ${exported.key} must answer 403 once its ${LINK_SECONDS} seconds passed`).toBe(
        403,
      );
      await sleepUntil(exported.lastModified + PRUNE_AGE_MS + CLOCK_GRACE_MS);
      const deleted = `prune exports: deleted ${exported.key}`;
      const project = await workspaces.namedProject(shared, fixture.page, exportProjectName());
      const template = await workspaces.namedTemplate(shared, fixture.page, project.id, PRUNE_TEMPLATE);
      let pruned = false;
      for (const task of await shared.api(fixture.page, "GET", `/project/${project.id}/templates/${template.id}/tasks`)) {
        if (Date.parse(task.created) < exported.lastModified) {
          continue;
        }
        const run = await workspaces.awaitTask(shared, fixture.page, project.id, task.id, PRUNE_RUN_MS, `${LABEL}: prune task ${task.id}`);
        pruned = pruned || run.lines.some((line) => line.includes(deleted));
      }
      if (!pruned) {
        const run = await workspaces.runTemplate(shared, fixture.page, project.id, template.id, {}, PRUNE_RUN_MS, `${LABEL}: prune exports`);
        expect(
          run.lines.some((line) => line.includes(`prune exports failed: ${exported.key}`)),
          `${LABEL}: prune exports must not fail on ${exported.key}; output tail:\n${workspaces.outputTail(run.lines)}`,
        ).toBe(false);
        pruned = run.lines.some((line) => line.includes(deleted));
      }
      expect(pruned, `${LABEL}: a prune exports run must delete ${exported.key} once it is older than an hour`).toBe(true);
    });

    test("export: apply creates the export template", async () => {
      test.setTimeout(resolveTimeout(CLEANUP_MS));
      const { project, template } = await exportTemplate();
      expect(
        workspaces.surveyOf(template),
        `${LABEL}: the export template must ask exactly WORKSPACE and EXPORT_FOR, both required environment variables`,
      ).toEqual(EXPORT_SURVEY);
      workspaces.expectLockedTemplate(template, LABEL);
      expect(template.runner_tag, `${LABEL}: the export template must run on the export runner`).toBe(exportRunnerTag());
      expect(
        (await shared.api(fixture.page, "GET", `/project/${project.id}/templates/${template.id}/perms`)).map((grant) => ({
          role_slug: grant.role_slug,
          permissions: grant.permissions,
        })),
        `${LABEL}: the export template must carry exactly the store's run-and-read grant`,
      ).toEqual([GUEST_GRANT]);
      const carrying = (await shared.api(fixture.page, "GET", "/runners")).filter((runner) =>
        (runner.tags || []).includes(exportRunnerTag()),
      );
      expect(carrying, `${LABEL}: exactly one runner must carry the tag ${exportRunnerTag()}`).toHaveLength(1);
      expect(carrying[0].tags, `${LABEL}: the export runner must serve no other tag`).toEqual([exportRunnerTag()]);
      expect(carrying[0].active, `${LABEL}: the export runner must be active`).toBe(true);
      await workspaces.destroyWorkspace(shared, fixture, LABEL);
      expect(
        await workspaces.namedTemplates(shared, fixture.page, project.id, template.name),
        `${LABEL}: destroy must remove ${template.name}`,
      ).toHaveLength(0);
    });
  });
};
