const net = require("node:net");

const { requireDotenvValue } = require("./dotenv");
const { resolveTimeout } = require("../../timeouts");

const SEQUENCE = 0x30;
const SET = 0x31;
const BOOLEAN = 0x01;
const INTEGER = 0x02;
const OCTET_STRING = 0x04;
const ENUMERATED = 0x0a;
const BIND_REQUEST = 0x60;
const UNBIND_REQUEST = 0x42;
const SEARCH_REQUEST = 0x63;
const SEARCH_RESULT_ENTRY = 0x64;
const SEARCH_RESULT_REFERENCE = 0x73;
const MODIFY_REQUEST = 0x66;
const SIMPLE_AUTHENTICATION = 0x80;
const PRESENT_FILTER = 0x87;

const LDAP_VERSION = 3;
const SCOPE_BASE_OBJECT = 0;
const NEVER_DEREF_ALIASES = 0;
const NO_LIMIT = 0;

const MODIFY_ADD = 0;
const MODIFY_DELETE = 1;
const MODIFY_REPLACE = 2;

const RESULT_SUCCESS = 0;
const RESULT_NO_SUCH_ATTRIBUTE = 16;
const RESULT_ATTRIBUTE_OR_VALUE_EXISTS = 20;

const OPERATION_TIMEOUT_MS = 30_000;

function encodeLength(length) {
  if (length < 0x80) {
    return Buffer.from([length]);
  }
  const bytes = [];
  for (let rest = length; rest > 0; rest = Math.floor(rest / 256)) {
    bytes.unshift(rest % 256);
  }
  return Buffer.from([0x80 | bytes.length, ...bytes]);
}

function element(tag, content) {
  return Buffer.concat([Buffer.from([tag]), encodeLength(content.length), content]);
}

function constructed(tag, parts) {
  return element(tag, Buffer.concat(parts));
}

function integer(tag, value) {
  const bytes = [];
  let rest = value;
  do {
    bytes.unshift(rest % 256);
    rest = Math.floor(rest / 256);
  } while (rest > 0);
  if (bytes[0] & 0x80) {
    bytes.unshift(0);
  }
  return element(tag, Buffer.from(bytes));
}

function octets(value) {
  return element(OCTET_STRING, Buffer.isBuffer(value) ? value : Buffer.from(value, "utf8"));
}

function readElement(buffer, offset) {
  if (offset + 2 > buffer.length) {
    return null;
  }
  let length = buffer[offset + 1];
  let start = offset + 2;
  if (length & 0x80) {
    const width = length & 0x7f;
    if (start + width > buffer.length) {
      return null;
    }
    length = 0;
    for (let index = 0; index < width; index += 1) {
      length = length * 256 + buffer[start + index];
    }
    start += width;
  }
  const end = start + length;
  return end > buffer.length ? null : { tag: buffer[offset], start, end };
}

function childrenOf(buffer, node) {
  const children = [];
  let offset = node.start;
  while (offset < node.end) {
    const child = readElement(buffer, offset);
    if (!child || child.end > node.end) {
      throw new Error("LDAP response is not valid BER");
    }
    children.push(child);
    offset = child.end;
  }
  return children;
}

function integerOf(buffer, node) {
  let value = 0;
  for (let index = node.start; index < node.end; index += 1) {
    value = value * 256 + buffer[index];
  }
  return value;
}

function resultOf(message) {
  const [code, , diagnostic] = childrenOf(message.bytes, message.op);
  return {
    code: integerOf(message.bytes, code),
    diagnostic: message.bytes.toString("utf8", diagnostic.start, diagnostic.end),
  };
}

function requireDn(dn, label) {
  if (typeof dn !== "string" || dn === "") {
    throw new Error(`${label} must be a non-empty DN, got ${JSON.stringify(dn)}`);
  }
  return dn;
}

function withinDeadline(promise, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded its deadline`)), resolveTimeout(OPERATION_TIMEOUT_MS));
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

function socketTarget(url) {
  const target = new URL(url);
  if (target.protocol === "ldap:" && target.hostname && target.port) {
    return { endpoint: { host: target.hostname, port: Number(target.port) }, label: target.host };
  }
  if (target.protocol === "ldapi:" && target.hostname && !target.port && ["", "/"].includes(target.pathname)) {
    const path = decodeURIComponent(target.hostname);
    return { endpoint: { path }, label: path };
  }
  throw new Error(`LDAP_URL must read ldap://<host>:<port> or ldapi://<percent-encoded socket path>, got ${url}`);
}

async function openSession(url) {
  const { endpoint, label } = socketTarget(url);
  const socket = net.connect(endpoint);
  socket.setTimeout(resolveTimeout(OPERATION_TIMEOUT_MS));
  let received = Buffer.alloc(0);
  let pending = null;
  let failure = null;
  let nextId = 1;

  const fail = (error) => {
    failure = failure || error;
    if (pending) {
      pending.reject(failure);
      pending = null;
    }
  };

  const deliver = (message) => {
    if (message.id === 0) {
      socket.destroy(new Error(`${label} sent an LDAP notice of disconnection`));
      return;
    }
    if (!pending || message.id !== pending.id) {
      return;
    }
    if (message.op.tag === SEARCH_RESULT_ENTRY || message.op.tag === SEARCH_RESULT_REFERENCE) {
      pending.entries.push(message);
      return;
    }
    const { resolve, entries } = pending;
    pending = null;
    resolve({ result: message, entries });
  };

  socket.on("timeout", () => socket.destroy(new Error(`${label} did not answer the LDAP request in time`)));
  socket.on("error", fail);
  socket.on("close", () => fail(new Error(`${label} closed the LDAP connection`)));
  socket.on("data", (chunk) => {
    received = Buffer.concat([received, chunk]);
    try {
      let frame = readElement(received, 0);
      while (frame) {
        const bytes = received.subarray(0, frame.end);
        received = received.subarray(frame.end);
        const [id, op] = childrenOf(bytes, frame);
        deliver({ id: integerOf(bytes, id), bytes, op });
        frame = readElement(received, 0);
      }
    } catch (error) {
      socket.destroy(error);
    }
  });

  await new Promise((resolve, reject) => {
    socket.once("connect", resolve);
    socket.once("error", reject);
  });

  return {
    request(protocolOp) {
      if (failure) {
        return Promise.reject(failure);
      }
      const id = nextId;
      nextId += 1;
      return new Promise((resolve, reject) => {
        pending = { id, entries: [], resolve, reject };
        socket.write(constructed(SEQUENCE, [integer(INTEGER, id), protocolOp]));
      });
    },
    close() {
      if (!socket.destroyed) {
        socket.end(constructed(SEQUENCE, [integer(INTEGER, nextId), Buffer.from([UNBIND_REQUEST, 0x00])]), () =>
          socket.destroy(),
        );
      }
    },
  };
}

async function withLdapSession(body) {
  const url = requireDotenvValue(process.env.LDAP_URL, "LDAP_URL");
  const bindDn = requireDotenvValue(process.env.LDAP_BIND_DN, "LDAP_BIND_DN");
  const bindPassword = requireDotenvValue(process.env.LDAP_BIND_PASSWORD, "LDAP_BIND_PASSWORD");
  const session = await openSession(url);
  try {
    const { result } = await session.request(
      constructed(BIND_REQUEST, [
        integer(INTEGER, LDAP_VERSION),
        octets(bindDn),
        element(SIMPLE_AUTHENTICATION, Buffer.from(bindPassword, "utf8")),
      ]),
    );
    const bind = resultOf(result);
    if (bind.code !== RESULT_SUCCESS) {
      throw new Error(`LDAP bind as ${bindDn} answered result code ${bind.code}: ${bind.diagnostic}`);
    }
    return await body(session);
  } finally {
    session.close();
  }
}

async function modify(session, dn, changes, tolerated) {
  const { result } = await session.request(
    constructed(MODIFY_REQUEST, [
      octets(dn),
      constructed(
        SEQUENCE,
        changes.map(({ operation, type, values }) =>
          constructed(SEQUENCE, [
            integer(ENUMERATED, operation),
            constructed(SEQUENCE, [octets(type), constructed(SET, values.map(octets))]),
          ]),
        ),
      ),
    ]),
  );
  const outcome = resultOf(result);
  if (outcome.code !== RESULT_SUCCESS && !tolerated.includes(outcome.code)) {
    throw new Error(`LDAP modify of ${dn} answered result code ${outcome.code}: ${outcome.diagnostic}`);
  }
  return outcome.code;
}

async function readAttributes(session, dn, types) {
  const { result, entries } = await session.request(
    constructed(SEARCH_REQUEST, [
      octets(dn),
      integer(ENUMERATED, SCOPE_BASE_OBJECT),
      integer(ENUMERATED, NEVER_DEREF_ALIASES),
      integer(INTEGER, NO_LIMIT),
      integer(INTEGER, NO_LIMIT),
      element(BOOLEAN, Buffer.from([0x00])),
      element(PRESENT_FILTER, Buffer.from("objectClass", "utf8")),
      constructed(SEQUENCE, types.map(octets)),
    ]),
  );
  const outcome = resultOf(result);
  if (outcome.code !== RESULT_SUCCESS || entries.length !== 1) {
    throw new Error(
      `LDAP read of ${dn} answered result code ${outcome.code} with ${entries.length} entries: ${outcome.diagnostic}`,
    );
  }
  const byName = Object.fromEntries(types.map((type) => [type.toLowerCase(), []]));
  const { bytes, op } = entries[0];
  const [, attributeList] = childrenOf(bytes, op);
  for (const attribute of childrenOf(bytes, attributeList)) {
    const [type, values] = childrenOf(bytes, attribute);
    const name = bytes.toString("utf8", type.start, type.end).toLowerCase();
    if (name in byName) {
      byName[name] = childrenOf(bytes, values).map((value) => Buffer.from(bytes.subarray(value.start, value.end)));
    }
  }
  return Object.fromEntries(types.map((type) => [type, byName[type.toLowerCase()]]));
}

function memberChange(operation, memberDn) {
  return {
    operation,
    type: requireDotenvValue(process.env.LDAP_GROUP_MEMBER_ATTRIBUTE, "LDAP_GROUP_MEMBER_ATTRIBUTE"),
    values: [requireDn(memberDn, "memberDn")],
  };
}

/**
 * Add `memberDn` to the directory group `groupDn`.
 *
 * Args:
 *   groupDn: DN of the groupOfNames entry.
 *   memberDn: DN of the entry to list in the group's member attribute.
 *
 * Returns:
 *   true when this call added the member, false when it was already listed.
 */
async function ldapAddGroupMember(groupDn, memberDn) {
  const change = memberChange(MODIFY_ADD, memberDn);
  const code = await withLdapSession((session) =>
    modify(session, requireDn(groupDn, "groupDn"), [change], [RESULT_ATTRIBUTE_OR_VALUE_EXISTS]),
  );
  return code === RESULT_SUCCESS;
}

/**
 * Remove `memberDn` from the directory group `groupDn`.
 *
 * Args:
 *   groupDn: DN of the groupOfNames entry.
 *   memberDn: DN of the entry to drop from the group's member attribute.
 *
 * Returns:
 *   true when this call removed the member, false when it was not listed.
 */
async function ldapRemoveGroupMember(groupDn, memberDn) {
  const change = memberChange(MODIFY_DELETE, memberDn);
  const code = await withLdapSession((session) =>
    modify(session, requireDn(groupDn, "groupDn"), [change], [RESULT_NO_SUCH_ATTRIBUTE]),
  );
  return code === RESULT_SUCCESS;
}

/**
 * Run `body` while `memberDn` is a member of `groupDn` in the directory, removing the membership afterwards only when this call granted it.
 *
 * Args:
 *   groupDn: DN of the groupOfNames entry.
 *   memberDn: DN of the entry to list in the group's member attribute.
 *   body: async function executed while the membership holds.
 *
 * Returns:
 *   the value `body` resolves to.
 */
async function withLdapGroupMember(groupDn, memberDn, body) {
  const added = await ldapAddGroupMember(groupDn, memberDn);
  try {
    return await body();
  } finally {
    if (added) {
      await withinDeadline(ldapRemoveGroupMember(groupDn, memberDn), `Removing ${memberDn} from ${groupDn}`).catch(
        (error) => console.warn(`Cleanup removal of ${memberDn} from ${groupDn} failed: ${error}`),
      );
    }
  }
}

/**
 * Run `body` while the directory entry `dn` carries `attributes`, restoring the previous values afterwards.
 *
 * Args:
 *   dn: DN of the entry to change.
 *   attributes: map of attribute name to the single value (string or Buffer) to write.
 *   body: async function executed while the values hold.
 *
 * Returns:
 *   the value `body` resolves to.
 */
async function withLdapAttributes(dn, attributes, body) {
  const entryDn = requireDn(dn, "dn");
  const types = Object.keys(attributes);
  const previous = await withLdapSession(async (session) => {
    const before = await readAttributes(session, entryDn, types);
    await modify(
      session,
      entryDn,
      types.map((type) => ({ operation: MODIFY_REPLACE, type, values: [attributes[type]] })),
      [],
    );
    return before;
  });
  try {
    return await body();
  } finally {
    await withinDeadline(
      withLdapSession((session) =>
        modify(
          session,
          entryDn,
          types.map((type) => ({ operation: MODIFY_REPLACE, type, values: previous[type] })),
          [],
        ),
      ),
      `Restoring ${types.join(", ")} of ${entryDn}`,
    ).catch((error) => console.warn(`Cleanup restore of ${types.join(", ")} on ${entryDn} failed: ${error}`));
  }
}

module.exports = {
  ldapAddGroupMember,
  ldapRemoveGroupMember,
  withLdapGroupMember,
  withLdapAttributes,
};
