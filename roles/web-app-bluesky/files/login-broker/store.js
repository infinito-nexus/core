"use strict";

const fs = require("node:fs");

/**
 * Persistent map from Keycloak username to the broker's PDS account.
 *
 * @param {string} file JSON file inside the broker's volume
 * @returns {{get: function(string): (object|null), set: function(string, object): void, delete: function(string): void, ownerOf: function(string): (string|null)}}
 *   get returns {handle, did, appPasswordEnc} or null; set and delete write
 *   the file through a rename; ownerOf names the username that holds a handle
 */
function openStore(file) {
  const entries = new Map(
    fs.existsSync(file) ? Object.entries(JSON.parse(fs.readFileSync(file, "utf8"))) : [],
  );

  function save() {
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(Object.fromEntries(entries)), { mode: 0o600 });
    fs.renameSync(tmp, file);
  }

  return {
    get: (username) => entries.get(username) || null,
    set: (username, entry) => {
      entries.set(username, entry);
      save();
    },
    delete: (username) => {
      entries.delete(username);
      save();
    },
    ownerOf: (handle) => {
      for (const [username, entry] of entries) {
        if (entry.handle === handle) return username;
      }
      return null;
    },
  };
}

module.exports = { openStore };
