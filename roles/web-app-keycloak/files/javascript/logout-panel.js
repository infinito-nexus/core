(function () {
  const config = window.__INFINITO_LOGOUT__ || {};
  const origin = config.origin || "";
  const CATALOGUE = config.i18n || {};
  const LOGOUT_PATH = "/protocol/openid-connect/logout";
  const START_GRACE = 20000;
  const SWEEP_LIMIT = 60000;
  const BUSY = "#8a6d00";
  const OK = "#1d6f2b";
  const WARN = "#9b2226";

  let box, status, hint, counter, list;
  const rows = {};
  let finished = false;
  let startTimer, sweepTimer;

  function speak() {
    const tags = [document.documentElement.lang, navigator.language];
    for (let i = 0; i < tags.length; i += 1) {
      const tag = String(tags[i] || "").toLowerCase();
      if (CATALOGUE[tag]) { return CATALOGUE[tag]; }
      const base = tag.split("-")[0];
      if (CATALOGUE[base]) { return CATALOGUE[base]; }
    }
    return CATALOGUE.en;
  }

  const s = speak();

  function fill(pattern, values) {
    return pattern.replace(/\{(\w+)\}/g, function (whole, key) {
      return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : whole;
    });
  }

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function build() {
    if (box) { return; }
    box = document.getElementById("infinito-logout-status");
    if (box) { box.textContent = ""; } else {
      box = document.createElement("div");
      box.id = "infinito-logout-status";
      (document.querySelector("#kc-content-wrapper") || document.body).appendChild(box);
    }
    box.setAttribute("role", "status");
    box.setAttribute("aria-live", "polite");
    box.setAttribute("dir", s.dir);
    box.style.cssText = "max-width:34rem;margin:1.5rem auto;padding:1rem 1.25rem;border:1px solid rgba(0,0,0,.15);border-left-width:5px;border-radius:.5rem;background:rgba(255,255,255,.94);color:#222;font:14px/1.6 system-ui,sans-serif;text-align:start";
    status = box.appendChild(document.createElement("p"));
    status.style.cssText = "margin:0;font-weight:700;font-size:15px";
    hint = box.appendChild(document.createElement("p"));
    hint.style.cssText = "margin:.1rem 0 .5rem";
    counter = box.appendChild(document.createElement("p"));
    counter.style.cssText = "margin:0 0 .4rem;font-size:13px;opacity:.75";
    list = box.appendChild(document.createElement("ul"));
    list.style.cssText = "list-style:none;margin:0;padding:0";
  }

  function say(headline, note, tone) {
    build();
    status.textContent = headline;
    hint.textContent = note;
    status.style.color = tone;
    box.style.borderLeftColor = tone;
  }

  function pace() {
    if (window.location.hostname.slice(-6) === ".onion") {
      return ` ${s.pace_tor}`;
    }
    return ` ${s.pace}`;
  }

  function label(host) {
    const bare = host.split("://").pop().split("/")[0];
    const first = bare.split(".")[0];
    if (!first) { return bare; }
    return first.charAt(0).toUpperCase() + first.slice(1);
  }

  function row(host) {
    build();
    if (!rows[host]) {
      const item = list.appendChild(document.createElement("li"));
      item.style.cssText = "display:flex;justify-content:space-between;align-items:baseline;gap:1rem;padding:.25rem 0;border-top:1px solid rgba(0,0,0,.08)";
      const name = item.appendChild(document.createElement("span"));
      name.textContent = label(host);
      name.title = host;
      const right = item.appendChild(document.createElement("span"));
      right.style.cssText = "text-align:end;white-space:nowrap";
      rows[host] = { right: right, ok: null };
    }
    return rows[host];
  }

  function mark(host, glyph, text, tone, offerManual) {
    const entry = row(host);
    entry.right.textContent = "";
    const state = entry.right.appendChild(document.createElement("span"));
    state.textContent = `${glyph} ${text}`;
    state.style.color = tone;
    if (offerManual) {
      const link = entry.right.appendChild(document.createElement("a"));
      link.href = `${host}/logout?manual=1`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = s.manual;
      link.style.cssText = "margin-inline-start:.6rem";
    }
  }

  function each(fn) {
    let host;
    for (host in rows) {
      if (Object.prototype.hasOwnProperty.call(rows, host)) { fn(host); }
    }
  }

  function tally() {
    let total = 0;
    let done = 0;
    each(function (host) {
      total += 1;
      if (rows[host].ok === true) { done += 1; }
    });
    build();
    counter.textContent = total ? fill(s.counter, { done: done, total: total }) : "";
  }

  function hold(event) {
    if (finished) { return; }
    event.preventDefault();
    event.returnValue = "";
  }

  function unhold() {
    clearTimeout(startTimer);
    clearTimeout(sweepTimer);
    window.removeEventListener("beforeunload", hold);
  }

  function noStart() {
    unhold();
    say(s.no_check, s.no_check_hint, WARN);
    build();
    if (!list.children.length) {
      const item = list.appendChild(document.createElement("li"));
      const link = item.appendChild(document.createElement("a"));
      link.href = origin;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = s.open_logout;
    }
  }

  function stalled() {
    unhold();
    each(function (host) {
      if (rows[host].ok !== true) { mark(host, "⚠️", s.st_unconfirmed, WARN, true); }
    });
    say(s.stalled, s.stalled_hint, WARN);
    tally();
  }

  function handle(report) {
    if (report.type === "start") {
      clearTimeout(startTimer);
      say(s.running, s.keep_open + pace(), BUSY);
      report.domains.forEach(function (host) { mark(host, "🔄", s.st_pending, BUSY, false); });
      tally();
      window.addEventListener("beforeunload", hold);
      clearTimeout(sweepTimer);
      sweepTimer = setTimeout(stalled, SWEEP_LIMIT);
    } else if (report.type === "host") {
      row(report.host).ok = report.ok;
      mark(report.host, report.ok ? "✅" : "❌", report.ok ? s.st_done : s.st_failed, report.ok ? OK : WARN, !report.ok);
      tally();
    } else if (report.type === "done") {
      finished = true;
      unhold();
      tally();
      if (report.failed) {
        say(fill(s.partial, { failed: report.failed, total: report.total }), s.partial_hint, WARN);
      } else {
        say(s.all_done, s.may_close, OK);
      }
    }
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== origin) { return; }
    const report = event.data;
    if (!report || report.source !== "universal-logout") { return; }
    ready(function () { handle(report); });
  });

  if (window.location.pathname.indexOf(LOGOUT_PATH) !== -1) {
    ready(function () {
      say(s.checking, s.keep_closed + pace(), BUSY);
      window.addEventListener("beforeunload", hold);
      startTimer = setTimeout(noStart, START_GRACE);
    });
  }
})();
