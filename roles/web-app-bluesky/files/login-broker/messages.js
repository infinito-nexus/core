"use strict";

const MESSAGES = {
  handle_title: "Choose your {site} handle",
  handle_intro: "Your handle is your public address on {site}. Your username is longer than the {max} characters a handle may have, so choose one once. You keep signing in with your usual account.",
  handle_label: "Handle",
  handle_hint: "{min} to {max} lowercase letters, digits and hyphens, with at least one hyphen and none at the start or end. It must not contain {prefix}.",
  handle_preview: "Your handle will be",
  handle_submit: "Create my account",
  handle_taken: "This handle is already taken. Choose another one.",
  handle_expired: "This form has expired. Check the handle and submit it again.",
  handle_refused: "Cross-origin handle submission refused.",
  label_charset: "Use lowercase letters, digits and hyphens only.",
  label_length: "Use {min} to {max} characters.",
  label_hyphen: "Include at least one hyphen (-).",
  label_prefix: "Do not use {prefix} anywhere in the handle.",
  label_edge: "Do not start or end the handle with a hyphen.",
};

/**
 * @param {string} key key of MESSAGES
 * @param {Object<string, string|number>} [vars] value of every {placeholder} in the text
 * @returns {string} the English text with its placeholders filled in
 */
function t(key, vars) {
  if (!(key in MESSAGES)) throw new Error(`Unknown message: ${key}`);
  return MESSAGES[key].replace(/\{(\w+)\}/g, (_, name) => {
    if (!vars || !(name in vars)) throw new Error(`Message ${key} needs {${name}}`);
    return String(vars[name]);
  });
}

module.exports = { MESSAGES, t };
