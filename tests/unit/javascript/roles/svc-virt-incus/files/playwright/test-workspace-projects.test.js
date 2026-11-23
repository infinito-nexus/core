const test = require("node:test");
const assert = require("node:assert/strict");
const dns = require("node:dns");
const net = require("node:net");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SILENCE_MS = 300;
const MARKER = "playwrightfeedc0de";
const INSTANCE = "playwright-vm";
const NAMED_HOST = "incus-host.invalid";
const LOOPBACK = "127.0.0.1";
const SSH_PORT = 22;
const LISTENER_PORT = 8443;
const NO_OPEN_PORT = "no port of this address is known to be open";
const CONNECT_TIMEOUT = /did not complete its lookup and TCP connection before the probe timed out/;
const HOST_BANNER = "SSH-2.0-OpenSSH_10.0p2 Debian-7\r\n";
const INSTANCE_BANNER = `SSH-2.0-OpenSSH_10.0p2 Debian-7 ${MARKER}\r\n`;

/**
 * Args:
 *   actual: the value under assertion.
 *   message: the failure message.
 *
 * Returns:
 *   The matchers expectNoInstanceSsh calls, failing like Playwright's with the message.
 */
function expect(actual, message) {
  return {
    not: {
      toContain: (expected) => assert.equal(actual.includes(expected), false, message),
    },
  };
}

const playwrightTest = Object.assign(() => {}, { use: () => {}, describe: { serial: () => {} } });

/**
 * Args:
 *   _port: the port the probe dials.
 *   args: hostname, options and callback of the node:net lookup.
 *
 * Returns:
 *   Nothing; resolves through the host resolver, the way node:net does without a fake.
 */
function systemLookup(_port, ...args) {
  dns.lookup(...args);
}

let lookup = systemLookup;

const probeNet = {
  ...net,
  connect: (options) => net.connect({ ...options, lookup: (...args) => lookup(options.port, ...args) }),
};

test.afterEach(() => {
  lookup = systemLookup;
});

/**
 * Args:
 *   _port: the port the probe dials.
 *   _hostname: the name the probe resolves.
 *   options: the lookup options of node:net; `all` asks for a list of addresses.
 *   callback: receives (error, address, family) or, with `all`, (error, [{ address, family }]).
 *
 * Returns:
 *   Nothing; answers LOOPBACK on the next tick, the way a resolver that knows the name does.
 */
function resolvesToLoopback(_port, _hostname, options, callback) {
  process.nextTick(() =>
    options.all ? callback(null, [{ address: LOOPBACK, family: 4 }]) : callback(null, LOOPBACK, 4),
  );
}

/**
 * Args:
 *   _port: the port the probe dials.
 *   hostname: the name the probe resolves.
 *   _options: the lookup options of node:net.
 *   callback: receives the ENOTFOUND error a resolver without the name hands back.
 *
 * Returns:
 *   Nothing; fails the lookup on the next tick.
 */
function unknownName(_port, hostname, _options, callback) {
  process.nextTick(() => callback(Object.assign(new Error(`getaddrinfo ENOTFOUND ${hostname}`), { code: "ENOTFOUND" })));
}

/**
 * Returns:
 *   Nothing, and never calls back: an unreachable host whose connection stalls on every port until the probe times out.
 */
function stalled() {}

/**
 * Args:
 *   dropped: the port whose SYN the host drops.
 *
 * Returns:
 *   A lookup that stalls the connection to `dropped` and reaches LOOPBACK on every other port.
 */
function dropping(dropped) {
  return (port, ...args) => {
    if (port !== dropped) {
      resolvesToLoopback(port, ...args);
    }
  };
}

/**
 * Args:
 *   pending: a probe whose only timer is the socket's unref'd timeout.
 *
 * Returns:
 *   The probe's outcome, with the event loop held open until it settles, so node:test does not end the file first.
 */
async function heldOpen(pending) {
  const keepAlive = setInterval(() => {}, SILENCE_MS);
  try {
    return await pending;
  } finally {
    clearInterval(keepAlive);
  }
}

/**
 * Args:
 *   description: what the spec would annotate.
 *
 * Returns:
 *   Never; a probe that reached a conclusion must not annotate a skipped address.
 */
function noNote(description) {
  assert.fail(`no address may be skipped, but the probe noted: ${description}`);
}

const { sshBannerIfAny, expectNoInstanceSsh } = loadInternals(
  path.join(PROJECT_ROOT, "roles/svc-virt-incus/files/playwright/test-workspace-projects.js"),
  ["sshBannerIfAny", "expectNoInstanceSsh"],
  {
    "node:crypto": require("node:crypto"),
    "node:https": require("node:https"),
    "node:net": probeNet,
    "@playwright/test": { test: playwrightTest, expect },
    "./timeouts": { resolveTimeout: () => SILENCE_MS },
  },
  { URL, Buffer },
);

/**
 * Args:
 *   onConnection: handler of each accepted socket.
 *
 * Returns:
 *   The port the server listens on at LOOPBACK and a close() that drops every open socket first.
 */
async function serve(onConnection) {
  const sockets = new Set();
  const server = net.createServer((socket) => {
    sockets.add(socket);
    onConnection(socket);
  });
  await new Promise((resolve) => server.listen(0, LOOPBACK, resolve));
  return {
    port: server.address().port,
    close: () => {
      for (const socket of sockets) {
        socket.destroy();
      }
      return new Promise((resolve) => server.close(resolve));
    },
  };
}

test("a port that speaks hands back its SSH banner", async () => {
  const sshd = await serve((socket) => socket.end(INSTANCE_BANNER));
  try {
    assert.equal(await sshBannerIfAny(LOOPBACK, sshd.port), INSTANCE_BANNER);
  } finally {
    await sshd.close();
  }
});

test("a refused port reads as silence", async () => {
  const closed = await serve(() => {});
  await closed.close();
  assert.equal(await sshBannerIfAny(LOOPBACK, closed.port), "");
});

test("a port that accepts and never speaks reads as silence", async () => {
  const mute = await serve(() => {});
  try {
    assert.equal(await sshBannerIfAny(LOOPBACK, mute.port), "");
  } finally {
    await mute.close();
  }
});

test("a port that hangs up without a banner reads as silence", async () => {
  const hangup = await serve((socket) => socket.end());
  try {
    assert.equal(await sshBannerIfAny(LOOPBACK, hangup.port), "");
  } finally {
    await hangup.close();
  }
});

test("a named host the resolver knows is probed at its address", async () => {
  const sshd = await serve((socket) => socket.end(INSTANCE_BANNER));
  lookup = resolvesToLoopback;
  try {
    assert.equal(await sshBannerIfAny(NAMED_HOST, sshd.port), INSTANCE_BANNER);
  } finally {
    await sshd.close();
  }
});

test("negative control: a host that does not resolve is an error, never silence", async () => {
  lookup = unknownName;
  await assert.rejects(sshBannerIfAny(NAMED_HOST, SSH_PORT), (error) => error.code === "ENOTFOUND");
});

test("negative control: a connection that never completes is an error, never silence", async () => {
  lookup = stalled;
  await assert.rejects(heldOpen(sshBannerIfAny(NAMED_HOST, SSH_PORT)), CONNECT_TIMEOUT);
});

test("a reachable host that drops its SSH port reads as silence", async () => {
  const listener = await serve(() => {});
  lookup = dropping(SSH_PORT);
  try {
    await heldOpen(expectNoInstanceSsh({ host: NAMED_HOST, openPort: listener.port, reason: NO_OPEN_PORT }, SSH_PORT, MARKER, INSTANCE, noNote));
  } finally {
    await listener.close();
  }
});

test("negative control: an unreachable host fails the host check, never silence", async () => {
  lookup = stalled;
  await assert.rejects(
    heldOpen(expectNoInstanceSsh({ host: NAMED_HOST, openPort: LISTENER_PORT, reason: NO_OPEN_PORT }, SSH_PORT, MARKER, INSTANCE, noNote)),
    new RegExp(`${NAMED_HOST.replace(/\./g, "\\.")} is unreachable: neither port ${SSH_PORT} nor its open port ${LISTENER_PORT}`),
  );
});

test("a host address without a known open port is noted with its reason when its SSH port stalls", async () => {
  const notes = [];
  lookup = stalled;
  await heldOpen(
    expectNoInstanceSsh({ host: NAMED_HOST, openPort: null, reason: NO_OPEN_PORT }, SSH_PORT, MARKER, INSTANCE, (description) =>
      notes.push(description),
    ),
  );
  assert.deepEqual(notes, [`${NAMED_HOST}:${SSH_PORT} did not connect and was not probed further: ${NO_OPEN_PORT}`]);
});

test("negative control: a host address that serves the marked banner of the instance is caught", async () => {
  const forward = await serve((socket) => socket.end(INSTANCE_BANNER));
  try {
    await assert.rejects(
      expectNoInstanceSsh({ host: LOOPBACK, openPort: null, reason: NO_OPEN_PORT }, forward.port, MARKER, INSTANCE, noNote),
      new RegExp(`${INSTANCE} must not answer SSH on 127\\.0\\.0\\.1:${forward.port}`),
    );
  } finally {
    await forward.close();
  }
});

test("the host's own sshd and a closed host port do not count as the instance", async () => {
  const hostSshd = await serve((socket) => socket.end(HOST_BANNER));
  const closed = await serve(() => {});
  await closed.close();
  try {
    await expectNoInstanceSsh({ host: LOOPBACK, openPort: null, reason: NO_OPEN_PORT }, hostSshd.port, MARKER, INSTANCE, noNote);
    await expectNoInstanceSsh({ host: LOOPBACK, openPort: null, reason: NO_OPEN_PORT }, closed.port, MARKER, INSTANCE, noNote);
  } finally {
    await hostSshd.close();
  }
});
