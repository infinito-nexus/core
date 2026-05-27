/**
 * Dotenv-quote decoders shared by every Playwright spec.
 *
 * `docker --env-file` preserves the surrounding double-quotes that the
 * project's `dotenv_quote` Jinja filter emits, so specs MUST decode
 * the quoted values before building URLs or typing credentials. The
 * `$$` -> `$` replacement undoes the dollar-sign escape that
 * `dotenv_quote` applies on the way out.
 *
 *   `decodeDotenvQuotedValue(raw)` returns the decoded string (or
 *   the input untouched when it is not a doubly-quoted dotenv value).
 *
 *   `normalizeBaseUrl(raw)` decodes AND strips a trailing slash so
 *   callers can append paths without `//` accidents.
 */

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) {
    return value;
  }
  if (!(value.startsWith('"') && value.endsWith('"'))) {
    return value;
  }
  const encoded = value.slice(1, -1);
  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

function normalizeBaseUrl(value) {
  return decodeDotenvQuotedValue(value || "").replace(/\/$/, "");
}

module.exports = { decodeDotenvQuotedValue, normalizeBaseUrl };
