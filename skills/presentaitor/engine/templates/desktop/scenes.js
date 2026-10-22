film({ BPM: 120, BEATS: 32, holds: [[9.9, 2], [14.9, 2], [16.9, 2]] });

const APP = { name: "Appname", slogan: "Everything in its place." };
const WM = { size: 176, baseline: 700, row: 34 };
const SIDE = [
  { key: "inbox", label: "Inbox", color: "var(--accent)", y: 62, count: [12, 11] },
  { key: "today", label: "Today", color: "#E0A526", y: 96, count: [5] },
  { key: "upcoming", label: "Upcoming", color: "#8A62D6", y: 130, count: [] },
  { key: "launch", label: "Launch", color: "#2F9E6B", y: 208, count: [3, 4] },
  { key: "website", label: "Website", color: "#E0A526", y: 242, count: [7] },
  { key: "hiring", label: "Hiring", color: "#8A62D6", y: 276, count: [2] },
];
const INBOX = [["Reply to the design review", "Website", "Today"], ["Write the launch post", "", "Tomorrow"],
  ["Book the photo shoot", "Launch", "Fri"], ["Check the onboarding copy", "Website", "Fri"],
  ["Plan the hiring loop", "Hiring", "Mon"], ["Update the pricing page", "Website", "Mon"],
  ["Send the invoices", "", "Sep 30"], ["Order new badges", "", "Oct 2"]];
const LAUNCH = [["Write the launch post", "", "Tomorrow"], ["Book the photo shoot", "", "Fri"],
  ["Record the demo", "", "Fri"], ["Draft the release notes", "", "Mon"], ["Brief the support team", "", "Tue"],
  ["Schedule the newsletter", "", "Wed"]];
const ROW = { x: 268, y: 96, h: 56, w: 912 };
const SEARCH = { x: 904, y: 20, w: 264, h: 38, r: 19 };
const PALETTE = { x: 330, y: 128, w: 540, r: 16 };
const RESULTS = [["New task", "⌘N"], ["Go to Today", "⌘1"], ["Open Launch", ""], ["Open Website", ""]];
const FOUND = [["Open Launch", "↵"], ["Write the launch post", ""]];
const QUERY = "launch";
const W = (x, y) => ({ x: WIN.x + x, y: WIN.y + y });

const K = {};
function timeline() {
  Object.assign(K, {
    gather: B(2), open: B(3), side: B(4), rows: B(5), point: B(6), select: B(7), drag: B(8), drop: B(9),
    palette: B(10), type: B(10.5), found: B(10.5) + 0.2, enter: B(12), check: B(14), back: B(15), laptop: B(16),
    close: B(17), row: B(18), word: B(19), slogan: B(20),
  });
  POINTER.splice(0, POINTER.length,
    { t: 0, ...W(1010, 660) }, { t: K.point, ...W(420, ROW.y + ROW.h * 1.5), d: 0.6 },
    { t: K.drag + 0.05, ...W(110, 224), d: 0.75 },
    { t: B(13), ...W(ROW.x + 25, ROW.y + ROW.h / 2), d: 0.5 });
}
const POINTER = [];

function build(stage) {
  timeline();
  const side = SIDE.map((s) => `
    <div class="abs" data-k="side_${s.key}" style="left:12px;top:${s.y}px;width:224px;height:32px;border-radius:8px">
      <i class="abs" style="left:14px;top:9px;width:14px;height:14px;border-radius:5px;background:${s.color}"></i>
      <span class="abs t" style="left:40px;top:5px;font-size:16px;font-weight:500">${s.label}</span>
      <div class="abs mask" style="right:14px;top:6px;width:28px;height:20px"><div data-k="count_${s.key}" class="abs" style="right:0;top:0;width:28px;height:20px"></div></div>
    </div>`).join("");
  const row = ([title, tag, date], i, list) => `
    <div class="abs" data-k="${list}${i}" style="left:0;top:0;width:${ROW.w}px;height:${ROW.h}px;border-radius:10px">
      <div class="abs" style="left:16px;right:16px;bottom:0;height:1px;background:var(--hair)"></div>
      <i class="abs" data-k="${list}Box${i}" style="left:14px;top:17px;width:22px;height:22px;border-radius:50%;box-shadow:inset 0 0 0 1.6px var(--ink3)"></i>
      <span class="abs t" data-k="${list}Title${i}" style="left:54px;top:15px;font-size:17.5px;font-weight:500">${title}</span>
      ${tag ? `<span class="abs t" style="left:640px;top:15px;padding:0 10px;border-radius:8px;font-size:13.5px;font-weight:600;line-height:26px;background:var(--side);color:var(--ink2)">${tag}</span>` : ""}
      <span class="abs t" style="right:18px;top:16px;font-size:14.5px;color:var(--ink3)">${date}</span>
    </div>`;
  const results = (list, key) => list.map(([label, hint], i) => `
    <div class="abs" data-k="${key}${i}" style="left:8px;top:${64 + i * 46}px;width:${PALETTE.w - 16}px;height:42px;border-radius:9px">
      <span class="abs t" style="left:14px;top:9px;font-size:17px;font-weight:500">${label}</span>
      <span class="abs t" style="right:14px;top:10px;font-size:15px;color:var(--ink3)">${hint}</span>
    </div>`).join("");
  const app = `
    <div class="abs" data-k="sidebar" style="left:0;top:0;width:248px;height:${WIN.h}px;background:var(--side);box-shadow:inset -1px 0 0 var(--hair)">
      <div class="abs" data-k="sideSel" style="left:12px;width:224px;height:32px;border-radius:8px;background:var(--accentSoft)"></div>
      ${side}
      <span class="abs t" style="left:26px;top:180px;font-size:12px;font-weight:700;letter-spacing:.08em;color:var(--ink3)">PROJECTS</span>
    </div>
    <div class="abs mask" style="left:284px;top:16px;width:400px;height:44px"><div data-k="title" class="abs" style="left:0;top:0;width:400px;height:44px"></div></div>
    <div class="abs row" data-k="search" style="left:${SEARCH.x}px;top:${SEARCH.y}px;width:${SEARCH.w}px;height:${SEARCH.h}px;border-radius:${SEARCH.r}px;background:var(--side);padding:0 14px;gap:8px;font-size:15px;color:var(--ink3)">
      <i style="width:13px;height:13px;border-radius:50%;box-shadow:inset 0 0 0 2px var(--ink3)"></i><span>Search</span><span style="margin-left:auto">⌘K</span>
    </div>
    <div class="abs mask" data-k="list" style="left:${ROW.x}px;top:${ROW.y}px;width:${ROW.w}px;height:${WIN.h - ROW.y}px">
      ${INBOX.map((r, i) => row(r, i, "in")).join("")}${LAUNCH.map((r, i) => row(r, i, "la")).join("")}
    </div>
    <div class="abs" data-k="ghost" style="left:0;top:0;width:${ROW.w}px;height:${ROW.h}px;border-radius:12px;background:var(--winBg);box-shadow:0 18px 40px rgba(20,20,30,.22)">
      <i class="abs" style="left:14px;top:17px;width:22px;height:22px;border-radius:50%;box-shadow:inset 0 0 0 1.6px var(--ink3)"></i>
      <span class="abs t" style="left:54px;top:15px;font-size:17.5px;font-weight:500">${INBOX[1][0]}</span>
    </div>
    <div class="full" data-k="dim" style="background:rgba(10,10,14,.07)"></div>
    <div class="abs" data-k="palette" style="overflow:hidden;background:var(--winBg);box-shadow:0 28px 70px rgba(15,15,25,.28),0 0 0 1px var(--hair)">
      <div class="abs row" data-k="palIn" style="left:22px;top:0;height:60px;gap:12px;font-size:21px">
        <i style="width:16px;height:16px;border-radius:50%;box-shadow:inset 0 0 0 2.4px var(--ink3)"></i>
        <span class="t" data-k="query" style="line-height:60px"></span><i data-k="caret" style="width:2px;height:24px;background:var(--accent)"></i>
        <span class="t" data-k="hint" style="line-height:60px;color:var(--ink3)">Type a command</span>
      </div>
      <div class="abs" style="left:0;right:0;top:60px;height:1px;background:var(--hair)"></div>
      <div class="abs" data-k="palSel" style="left:8px;width:${PALETTE.w - 16}px;height:42px;border-radius:9px;background:var(--accentSoft)"></div>
      <div data-k="all">${results(RESULTS, "res")}</div><div data-k="found">${results(FOUND, "fnd")}</div>
    </div>`;
  stage.innerHTML = `
    <div class="full" style="background:var(--bg)"></div>
    ${desktopMarkup(app, { name: APP.name, icon: `<i class="abs" style="left:14px;top:14px;width:18px;height:18px;border-radius:50%;background:var(--accent)"></i>` })}
    <div class="full" data-k="word">
      <div class="abs" data-k="pill"></div>
      <div class="abs mask" data-k="wmClip" style="height:${WM.size * 1.3}px"><div data-k="wm" class="t" style="font-size:${WM.size}px;font-weight:700;letter-spacing:-.035em;line-height:1.3;transform-origin:0 50%">${APP.name}</div></div>
      <div class="abs mask" data-k="slClip" style="height:60px"><div data-k="sl" class="t" style="font-size:42px;font-weight:500;color:var(--ink2);line-height:58px">${APP.slogan}</div></div>
      <div class="abs" data-k="dot" style="width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;background:var(--accent)"></div>
    </div>`;
  collect(stage);
  $.titleRoll = roller($.title, "font-size:30px;font-weight:700;letter-spacing:-.4px");
  for (const s of SIDE) $["roll_" + s.key] = roller($["count_" + s.key], "font-size:13.5px;color:var(--ink3);right:0;left:auto");

  WM.textW = measure(APP.name, WM.size, 700, "letter-spacing:-.035em");
  const dot = 0.19 * WM.size, gap = 0.06 * WM.size;
  WM.left = Math.round((FILM.W - (WM.textW + gap + dot)) / 2);
  WM.top = Math.round(WM.baseline - WM.size * 0.98);
  WM.dotX = Math.round(WM.left + WM.textW + gap + dot / 2);
  WM.dotY = Math.round(WM.baseline - dot / 2 - 1);
  Object.assign($.wmClip.style, { left: WM.left + "px", top: WM.top + "px", width: WM.textW + 8 + "px" });
  const k = WM.row / WM.size, labelW = WM.textW * k;
  WM.pill = { w: labelW + 118, h: 78, r: 39 };
  WM.pill.w = Math.round(WM.pill.w);
  WM.pill.x = (FILM.W - WM.pill.w) / 2;
  WM.pill.y = (FILM.H - WM.pill.h) / 2;
  WM.rowDot = { x: WM.pill.x + 40, y: FILM.H / 2 };
  WM.rowText = { x: WM.pill.x + 70, y: Math.round(FILM.H / 2 - (WM.size * 1.3 * k) / 2) };
  const slW = measure(APP.slogan, 42, 500);
  Object.assign($.slClip.style, { left: Math.round((FILM.W - slW) / 2) + "px", top: WM.baseline + 58 + "px", width: slW + 4 + "px" });
}

function apply(t) {
  const v = camera(t);
  const cls = prog(t, K.close, 0.45, E.inOut);
  const worldOn = t >= K.open && t < K.row;
  show($.world, worldOn);
  if (worldOn) {
    placeWorld(v, {
      rect: t < K.open + 0.9 ? mixRect(pillInWindow(), FULL, prog(t, K.open + 0.1, 0.7, E.smooth)) : FULL,
      chrome: prog(t, K.open + 0.45, 0.35, E.out),
      desk: prog(t, K.back + 0.15, 0.85, E.smooth),
      hw: prog(t, K.laptop, 0.6, E.out),
      lid: 1 - cls,
    });
    applyApp(t);
    placePointer(t, POINTER, [K.select, K.drag, K.check], K.point - 0.12, K.close);
    $.pointer.style.opacity = (prog(t, K.point - 0.12, 0.2, E.out) * (1 - typing(t))).toFixed(3);
  }
  applyWord(t, v);
}

const typing = (t) => (t < K.palette || t > K.enter + 0.3 ? 0 : Math.min(prog(t, K.palette, 0.15), 1 - prog(t, K.enter + 0.15, 0.15)));

function camera(t) {
  return cameraAt(t, [
    { t: 0, ...WHOLE_WINDOW },
    { t: K.side + 0.2, ...onWindow(600, 390, 1.14) },
    { t: K.drop + 0.4, ...onWindow(600, 384, 1.165), d: K.palette - K.drop - 0.4 },
    { t: K.palette, ...onWindow(600, 340, 1.19) },
    { t: K.enter + 0.15, ...onWindow(600, 390, 1.14) },
    { t: K.check + 0.4, ...onWindow(600, 384, 1.165), d: K.back - K.check - 0.4 },
    { t: K.back, ...WHOLE_SCREEN },
    { t: K.laptop, ...WHOLE_LAPTOP },
  ]);
}

function pillInWindow() {
  const v = WHOLE_WINDOW, p = WM.pill;
  return { x: (p.x - FILM.W / 2) / v.z + v.cx - WIN.x, y: (p.y - FILM.H / 2) / v.z + v.cy - WIN.y, w: p.w / v.z, h: p.h / v.z, r: p.r / v.z };
}

function applyApp(t) {
  setT($.sidebar, `translateX(${((1 - clamp(spring(t, K.side, 0.55, 0.86), 0, 1)) * -260).toFixed(2)}px)`);
  roll($.titleRoll, t, [{ t: K.side + 0.08, v: "Inbox" }, { t: K.enter + 0.1, v: "Launch" }]);
  setT($.search, `scale(${clamp(spring(t, K.side + 0.14, 0.45, 0.8), 0, 1.05).toFixed(4)})`);
  for (const s of SIDE) {
    const steps = s.count.map((c, i) => ({ t: i ? K.drop + 0.12 : K.side + 0.2, v: String(c) }));
    roll($["roll_" + s.key], t, steps);
    const flash = s.key === "launch" ? pulse(t, K.drop + 0.05, 0.5) : 0;
    $["side_" + s.key].style.background = flash > 0 ? `rgba(47,158,107,${(0.18 * flash).toFixed(3)})` : "";
  }
  const sel = track(t, SIDE[0].y, [{ t: K.enter + 0.05, to: SIDE[3].y, spring: [0.4, 0.86] }]);
  $.sideSel.style.top = sel.toFixed(2) + "px";

  const leave = (i) => prog(t, K.enter + i * 0.025, 0.26, E.in);
  INBOX.forEach((_, i) => {
    const el = $["in" + i];
    const enter = clamp(spring(t, K.rows + i * 0.05, 0.5, 0.86), 0, 1.02);
    const gap = i > 1 ? clamp(spring(t, K.drag + 0.25, 0.45, 0.86), 0, 1) : 0;
    const out = leave(i);
    setT(el, `translate(${(-out * 60).toFixed(2)}px,${((i - gap) * ROW.h + (1 - enter) * 34).toFixed(2)}px)`);
    el.style.clipPath = `inset(0 ${(out * 100).toFixed(2)}% 0 0)`;
    const selected = i === 1 && t >= K.select + 0.06 && t < K.drag + 0.1;
    el.style.background = selected ? "var(--accent)" : "";
    el.style.color = selected ? "#fff" : "";
    show(el, t >= K.rows + i * 0.05 && out < 1 && !(i === 1 && t >= K.drag + 0.1));
  });
  LAUNCH.forEach((_, i) => {
    const el = $["la" + i], at = K.enter + 0.3 + i * 0.05;
    setT(el, `translateY(${(i * ROW.h + (1 - clamp(spring(t, at, 0.5, 0.86), 0, 1.02)) * 34).toFixed(2)}px)`);
    show(el, t >= at);
  });
  const done = prog(t, K.check + 0.05, 0.3, E.out);
  $.laBox0.style.background = done > 0 ? `rgba(47,158,107,${done.toFixed(3)})` : "";
  $.laBox0.style.boxShadow = `inset 0 0 0 1.6px ${done > 0.5 ? "#2F9E6B" : "var(--ink3)"}`;
  $.laTitle0.style.color = done > 0.5 ? "var(--ink3)" : "";
  $.laTitle0.style.textDecoration = done > 0.5 ? "line-through" : "";

  applyDrag(t);
  applyPalette(t);
}

function applyDrag(t) {
  const on = t >= K.drag + 0.1 && t < K.drop + 0.35;
  show($.ghost, on);
  if (!on) return;
  const p = pointerAt(t, POINTER);
  const lift = clamp(spring(t, K.drag + 0.1, 0.35, 0.8), 0, 1);
  const into = prog(t, K.drop, 0.3, E.inOut);
  const held = { x: p.x - WIN.x - 40, y: p.y - WIN.y - ROW.h / 2, w: 360, h: ROW.h, r: 12 };
  const start = { x: ROW.x, y: ROW.y + ROW.h, w: ROW.w, h: ROW.h, r: 10 };
  const target = { x: 12, y: SIDE[3].y, w: 224, h: 32, r: 8 };
  const r = into > 0 ? mixRect(held, target, into) : mixRect(start, held, lift);
  rectCss($.ghost, r);
  $.ghost.style.opacity = (1 - prog(t, K.drop + 0.15, 0.2)).toFixed(3);
}

function applyPalette(t) {
  const open = clamp(spring(t, K.palette, 0.42, 0.84), 0, 1.02), close = prog(t, K.enter + 0.05, 0.34, E.inOut);
  const on = t >= K.palette && close < 1;
  show($.palette, on);
  show($.dim, on);
  if (!on) return;
  $.dim.style.opacity = (Math.min(open, 1) * (1 - close)).toFixed(3);
  const typed = Math.max(0, Math.min(QUERY.length, Math.floor((t - K.type) / 0.08) + 1));
  const narrowed = t >= K.found;
  const h = 60 + 8 + (narrowed ? FOUND.length : RESULTS.length) * 46 + 4;
  const card = { x: PALETTE.x, y: PALETTE.y, w: PALETTE.w, h: track(t, 60 + 8 + RESULTS.length * 46 + 4, [{ t: K.found, to: h, spring: [0.35, 0.9] }]), r: PALETTE.r };
  const rect = close > 0 ? mixRect(card, { x: 12, y: SIDE[3].y, w: 224, h: 32, r: 8 }, close) : mixRect({ ...SEARCH }, card, open);
  rectCss($.palette, rect);
  const inner = 1 - prog(t, K.enter + 0.05, 0.15);
  for (const key of ["palIn", "palSel", "all", "found"]) $[key].style.opacity = (prog(t, K.palette + 0.12, 0.15) * inner).toFixed(3);
  $.query.textContent = t >= K.type ? QUERY.slice(0, typed) : "";
  show($.hint, t < K.type);
  show($.caret, Math.floor((t - K.palette) / 0.45) % 2 === 0 || (t >= K.type && t < K.type + QUERY.length * 0.08 + 0.2));
  show($.all, !narrowed);
  show($.found, narrowed);
  $.palSel.style.top = "64px";
  setT($.fnd0, `scale(${press(t, K.enter, 0.97).toFixed(4)})`);
}

function applyWord(t, v) {
  const k = WM.row / WM.size;
  const g = t < K.row ? prog(t, K.gather, 0.55, E.inOut) : 1 - prog(t, K.word, 0.6, E.inOut);
  const leave = prog(t, K.open + 0.05, 0.3, E.in);
  const arrive = prog(t, K.row + 0.35, 0.35, E.out);
  const letters = t < K.open + 0.4 || t >= K.row + 0.35;
  show($.wmClip, letters);
  show($.dot, letters);
  show($.slClip, t < K.open || t >= K.slogan);

  const x = lerp(WM.left, WM.rowText.x, g), y = lerp(WM.top, WM.rowText.y, g);
  $.wmClip.style.transformOrigin = "0 0";
  setT($.wmClip, `translate(${(x - WM.left).toFixed(2)}px,${(y - WM.top).toFixed(2)}px) scale(${lerp(1, k, g).toFixed(4)})`);
  if (t < K.row) sink($.wm, leave);
  else rise($.wm, arrive);
  const beat = 1 + 0.1 * pulse(t, 0, 0.32);
  const size = t < K.row ? 1 - leave : arrive;
  setT($.dot, T(lerp(WM.dotX, WM.rowDot.x, g), lerp(WM.dotY, WM.rowDot.y, g), lerp(1, 26 / 34, g) * beat * size));

  const pillOn = (t >= K.gather && t < K.open + 0.02) || (t >= K.row && t < K.word + 0.45);
  show($.pill, pillOn);
  if (!pillOn) return;
  let pill, white = 1;
  if (t < K.row) {
    const w = WM.pill.w * prog(t, K.gather + 0.2, 0.35, E.out);
    pill = { ...WM.pill, w, x: FILM.W / 2 - w / 2 };
  } else {
    const deckWorld = { x: -LAPTOP.bezel - LAPTOP.deckOver, y: SCREEN.H + LAPTOP.bezel, w: SCREEN.W + 2 * (LAPTOP.bezel + LAPTOP.deckOver), h: LAPTOP.deckH };
    const a = toStage(v, deckWorld.x, deckWorld.y);
    const m = prog(t, K.row, 0.5, E.smooth), shrink = prog(t, K.word, 0.45, E.in);
    pill = mixRect({ x: a.x, y: a.y, w: deckWorld.w * v.z, h: deckWorld.h * v.z, r: 0 }, WM.pill, m);
    pill = { ...pill, w: pill.w * (1 - shrink), x: pill.x + (pill.w * shrink) / 2 };
    white = m;
  }
  const mix = (c) => `color-mix(in srgb, var(--winBg) ${(white * 100).toFixed(1)}%, var(${c}))`;
  $.pill.style.background = `linear-gradient(180deg,${mix("--metal1")},${mix("--metal2")})`;
  rectCss($.pill, pill);
}
