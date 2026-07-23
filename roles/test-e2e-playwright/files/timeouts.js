/**
 * Shared timeout helper for every Playwright spec (staged next to the spec as
 * `./timeouts`; persona flows reach it via `../timeouts`). Scales a base
 * timeout by the global `TIMEOUT_FACTOR` and, when the target is a `.onion`
 * (Tor) service, by an extra multiplier — Tor circuits add per-request latency.
 */

function _canonicalDomain() {
  const raw = process.env.CANONICAL_DOMAIN || "";
  const unquoted =
    raw.length >= 2 && raw.startsWith('"') && raw.endsWith('"') ? raw.slice(1, -1) : raw;
  return unquoted.trim();
}

function isOnionTarget() {
  return /\.onion$/i.test(_canonicalDomain());
}

function timeoutFactor() {
  const f = Number(process.env.PLAYWRIGHT_TIMEOUT_FACTOR);
  return Number.isFinite(f) && f > 0 ? f : 1;
}

function onionTimeoutMultiplier() {
  const m = Number(process.env.PLAYWRIGHT_ONION_TIMEOUT_MULTIPLIER);
  return Number.isFinite(m) && m > 0 ? m : 5;
}

/**
 * Effective timeout (ms) for the current run: `base * TIMEOUT_FACTOR`, times the
 * onion multiplier when the target is a `.onion` service.
 */
function resolveTimeout(baseMs) {
  const onionMult = isOnionTarget() ? onionTimeoutMultiplier() : 1;
  return Math.round(baseMs * timeoutFactor() * onionMult);
}

module.exports = {
  isOnionTarget,
  timeoutFactor,
  onionTimeoutMultiplier,
  resolveTimeout,
};
