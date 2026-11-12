const fs = require("node:fs");
const vm = require("node:vm");

const STUB_MODULE = new Proxy({}, { get: () => () => undefined });

/**
 * Loads a CommonJS file into its own context and hands out functions it does not export.
 *
 * Args:
 *   file: absolute path of the file.
 *   names: names of its top-level functions to return.
 *   modules: module per `require` request; every other request gets a module whose exports are no-op functions.
 *   globals: the context's global object, e.g. the `document` and `getComputedStyle` its `page.evaluate` callbacks read; later changes to it are seen by those callbacks.
 *
 * Returns:
 *   An object holding each named function.
 */
function loadInternals(file, names, modules, globals) {
  const module = { exports: {} };
  Object.assign(globals, {
    exports: module.exports,
    module,
    process,
    require: (request) => (request in modules ? modules[request] : STUB_MODULE),
  });
  vm.createContext(globals);
  return vm.runInContext(`${fs.readFileSync(file, "utf8")}\n;({ ${names.join(", ")} });`, globals, { filename: file });
}

module.exports = { loadInternals };
