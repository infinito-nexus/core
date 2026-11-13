const { createHmac } = require("node:crypto");

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
const STEP_MS = 30_000;

/**
 * Args:
 *   secret: unpadded base32 secret that an app's TOTP setup shows its user.
 *   now: Unix time in milliseconds the code has to be valid at.
 *
 * Returns:
 *   The six-digit RFC 6238 code of the 30-second step that holds now.
 */
function totpCode(secret, now = Date.now()) {
  const bits = [...secret.toUpperCase()].map((char) => BASE32.indexOf(char).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from(bits.match(/.{8}/g).map((byte) => Number.parseInt(byte, 2)));
  const step = Buffer.alloc(8);
  step.writeBigUInt64BE(BigInt(Math.floor(now / STEP_MS)));
  const digest = createHmac("sha1", key).update(step).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

module.exports = { totpCode };
