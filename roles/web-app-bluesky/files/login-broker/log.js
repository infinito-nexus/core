"use strict";

/**
 * One-line rendering of a request-derived value for the console log.
 *
 * @param {*} value value to log
 * @returns {string} value as a string, each CR/LF run turned into one space and every other control character dropped
 */
function logSafe(value) {
  // eslint-disable-next-line no-control-regex -- intentional: strip control chars to prevent log injection
  return String(value).replace(/[\r\n]+/g, " ").replace(/[\n\x00-\x1f\x7f]/g, "");
}

module.exports = { logSafe };
