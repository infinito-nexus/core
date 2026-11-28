const dgram = require("node:dgram");
const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");

const TXT = 16;
const RRSIG = 46;

/**
 * Args:
 *   raw: the KNOT_SERVERS value as the container sees it, still dotenv-quoted.
 *
 * Returns:
 *   One { host, port } per comma-separated host:port entry.
 */
function knotServers(raw) {
  return decodeDotenvQuotedValue(raw || "")
    .split(",")
    .filter(Boolean)
    .map((entry) => {
      const colon = entry.lastIndexOf(":");
      return { host: entry.slice(0, colon), port: Number(entry.slice(colon + 1)) };
    });
}

const zone = decodeDotenvQuotedValue(process.env.KNOT_ZONE || "").replace(/\.$/, "");
if (!zone) {
  throw new Error("KNOT_ZONE must be set by the role's playwright.env");
}
const servers = knotServers(process.env.KNOT_SERVERS);

function question(name, type) {
  const header = Buffer.from([0x4b, 0x6e, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]);
  const labels = name
    .split(".")
    .filter(Boolean)
    .flatMap((label) => [Buffer.from([label.length]), Buffer.from(label, "ascii")]);
  const tail = Buffer.alloc(4);
  tail.writeUInt16BE(type, 0);
  tail.writeUInt16BE(1, 2);
  const dnssecOk = Buffer.from([0x00, 0x00, 0x29, 0x10, 0x00, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00]);
  return Buffer.concat([header, ...labels, Buffer.from([0]), tail, dnssecOk]);
}

function skipName(buffer, start) {
  let offset = start;
  while (buffer[offset] !== 0) {
    if ((buffer[offset] & 0xc0) === 0xc0) {
      return offset + 2;
    }
    offset += buffer[offset] + 1;
  }
  return offset + 1;
}

function parse(buffer) {
  const count = buffer.readUInt16BE(6);
  let offset = skipName(buffer, 12) + 4;
  const records = [];
  for (let index = 0; index < count; index += 1) {
    offset = skipName(buffer, offset);
    const type = buffer.readUInt16BE(offset);
    const length = buffer.readUInt16BE(offset + 8);
    records.push({ type, data: buffer.subarray(offset + 10, offset + 10 + length) });
    offset += 10 + length;
  }
  return { rcode: buffer[3] & 0x0f, records };
}

function text(record) {
  const parts = [];
  let offset = 0;
  while (offset < record.data.length) {
    const length = record.data[offset];
    parts.push(record.data.subarray(offset + 1, offset + 1 + length).toString("utf8"));
    offset += length + 1;
  }
  return parts.join("");
}

function query(server, name, type) {
  return new Promise((resolve, reject) => {
    const socket = dgram.createSocket(server.host.includes(":") ? "udp6" : "udp4");
    const timer = setTimeout(() => {
      socket.close();
      reject(new Error(`${server.host}:${server.port} did not answer ${name}`));
    }, 5000);
    socket.once("message", (message) => {
      clearTimeout(timer);
      socket.close();
      resolve(parse(message));
    });
    socket.send(question(name, type), server.port, server.host);
  });
}

test("dns: the subzone is signed and transferred", async () => {
  expect(servers.length, "KNOT_SERVERS must name the primary").toBeGreaterThan(0);
  const canaries = [];
  for (const server of servers) {
    const answer = await query(server, `_canary.${zone}`, TXT);
    expect(answer.rcode, `${server.host} must answer NOERROR`).toBe(0);
    const texts = answer.records.filter((record) => record.type === TXT).map(text);
    expect(texts, `${server.host} must hold one canary`).toHaveLength(1);
    expect(
      answer.records.some((record) => record.type === RRSIG),
      `${server.host} must answer with an RRSIG`,
    ).toBe(true);
    canaries.push(texts[0]);
  }
  expect(new Set(canaries).size, "every secondary must hold the primary's canary").toBe(1);
});
