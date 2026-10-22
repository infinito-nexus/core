film({ W: 1920, H: 1080, BPM: 120, BEATS: 48 });

const APP = { name: "Appname", url: "appname.app", cta: "Get Appname", line: "Plan less. *Do more.*", facts: ["iPhone and Mac", "works offline", "no account needed"] };
const TASKS = [["Design review", "10:00"], ["Call with Lena", "12:30"], ["Gym", "18:00"], ["Plan the week", "20:00"]];
const WEEK = [["MON", 0.45], ["TUE", 0.72], ["WED", 0.55], ["THU", 0.92], ["FRI", 0.66], ["SAT", 0.28], ["SUN", 0.4]];
const HOME = { x: 1470, y: 968 };
const LEFT = { x: 40, y: 84, w: 620, h: 920 };
const RIGHT = { x: 680, y: 84, w: 1200, h: 920 };
const K = {};

const pebble = (id, face = true) => `<svg viewBox="0 0 200 210" width="100%" height="100%" style="overflow:visible">
  ${face ? `<ellipse cx="100" cy="204" rx="62" ry="7" fill="rgba(23,21,15,.12)"/>` : ""}
  <path d="M100 18 C156 18 186 64 186 116 C186 170 150 202 100 202 C50 202 14 170 14 116 C14 64 44 18 100 18Z" fill="var(--accent)"/>
  <path d="M58 40 C70 30 88 26 104 27" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="9" stroke-linecap="round"/>
  <g data-k="${id}Eyes"><ellipse cx="74" cy="104" rx="15" ry="19" fill="#fff"/><ellipse cx="126" cy="104" rx="15" ry="19" fill="#fff"/>
    <g data-k="${id}Pupils"><circle cx="76" cy="108" r="8" fill="var(--ink)"/><circle cx="128" cy="108" r="8" fill="var(--ink)"/></g></g>
  <path data-k="${id}Mouth" fill="var(--ink)"/></svg>`;

function face(id, { blink = 0, wide = 0, smile = 0.5, look = 0 }) {
  const open = Math.max(0.08, 1 - blink) * (1 + 0.35 * wide);
  $[id + "Eyes"].setAttribute("transform", `translate(0 ${(104 * (1 - open)).toFixed(2)}) scale(1 ${open.toFixed(3)})`);
  $[id + "Pupils"].setAttribute("transform", `translate(${(5 * look).toFixed(2)} 0)`);
  const o = 12 * wide, c = 14 * smile;
  $[id + "Mouth"].setAttribute("d", o > 1 ? `M100 ${(146 - o).toFixed(1)} a${(7 + o * 0.4).toFixed(1)} ${o.toFixed(1)} 0 1 0 0.1 0Z` : `M86 146 Q100 ${(146 + c).toFixed(1)} 114 146 Q100 ${(146 + c * 0.45).toFixed(1)} 86 146Z`);
}

function build(stage) {
  Object.assign(K, { h1: B(1) + 0.15, h2: B(3), h3: B(5), meet: B(9), f1: B(13), f2: B(21), f3: B(29), end: B(37), out: B(46.5), home: B(47) });
  const rows = TASKS.map(([name, time], i) => `
    <div class="abs row" style="left:36px;top:${150 + i * 132}px;width:1008px;height:104px;gap:26px;border-top:${i ? "1px solid var(--hair)" : "0"}">
      <div style="position:relative;width:30px;height:30px">${check("chk" + i)}</div>
      <div class="abs" style="left:60px;top:28px"><div class="mask" style="position:relative"><span class="t" style="font-size:38px;font-weight:600">${name}</span><div class="abs" data-k="strike${i}" style="left:0;top:25px;height:3px;width:100%;background:var(--ink3);transform-origin:0 50%;transform:scaleX(0)"></div></div></div>
      <span class="abs kit-mono" style="right:10px;top:38px;font-size:24px">${time}</span></div>`).join("");
  const phoneRows = TASKS.map(([name, time], i) => `<div class="abs row" style="left:22px;top:${150 + i * 74}px;width:300px;height:60px;border-radius:16px;background:#fff;gap:12px;padding:0 16px">
      <span style="width:20px;height:20px;border-radius:6px;border:2px solid var(--hair2)"></span><span class="t" style="font-size:19px;font-weight:600">${name}</span><span class="t kit-mono" style="margin-left:auto;font-size:15px">${time}</span></div>`).join("");

  stage.innerHTML = `
    ${scene("hookScene", "var(--bg)", `
      <div class="abs" style="left:150px;top:210px">${headline("h1", "Twelve tabs.", { size: 116 })}</div>
      <div class="abs" style="left:150px;top:360px">${headline("h2", "Three calendars.", { size: 116 })}</div>
      <div class="abs" style="left:150px;top:510px">${headline("h3", "Zero *plan.*", { size: 116 })}</div>
      <div class="abs" style="left:150px;top:380px">${headline("meet", "Meet *Appname.*", { size: 116 })}</div>
      <div class="abs" data-k="phone" style="left:1250px;top:170px;width:364px;height:760px;border-radius:60px;background:#1B1A17;box-shadow:0 30px 60px rgba(23,21,15,.18)">
        <div class="abs" style="left:12px;top:12px;width:340px;height:736px;border-radius:48px;background:var(--bg);overflow:hidden">
          <div class="abs" style="left:112px;top:12px;width:96px;height:28px;border-radius:14px;background:#1B1A17"></div>
          <div class="abs t" style="left:24px;top:78px;font-size:34px;font-weight:700;letter-spacing:-.02em">Today</div>${phoneRows}
          <div class="abs center" style="left:240px;top:604px;width:62px;height:62px;border-radius:20px;background:var(--accent);color:#fff;font-size:34px;font-weight:300">+</div></div></div>`)}
    ${scene("f1", "var(--field1)", `
      ${panel("f1L", LEFT, "var(--panel)", `<div class="abs" style="left:40px;top:100px">${headline("f1h", "Your day,\nin *one list.*", { size: 78 })}</div>`)}
      ${panel("f1R", RIGHT, "var(--panel)", `${card("f1c", { x: 60, y: 100, w: 1080, h: 720 }, `
        <div class="abs t" style="left:36px;top:40px;font-size:40px;font-weight:700;letter-spacing:-.02em">Today</div>
        <div class="abs kit-mono mask" style="right:36px;top:52px;width:220px;height:28px;text-align:right"><div data-k="doneRoll" class="abs" style="right:0;top:0;width:220px;height:28px"></div></div>${rows}`)}`)}`)}
    ${scene("f2", "var(--field2)", `
      ${panel("f2L", LEFT, "var(--panel)", `<div class="abs" style="left:40px;top:100px">${headline("f2h", "Twenty-five\nminutes.\n*Nothing else.*", { size: 78 })}</div>`)}
      ${panel("f2R", RIGHT, "var(--panel)", `
        ${card("f2c", { x: 60, y: 100, w: 540, h: 720 }, `<div class="abs" style="left:60px;top:100px;width:420px;height:420px">${ring("focusRing", 420)}
          <div class="abs center" data-k="focusTime" style="left:0;top:0;width:420px;height:420px;font-size:92px;font-weight:700;letter-spacing:-.03em;font-variant-numeric:tabular-nums;white-space:nowrap"></div></div>
          <div class="abs kit-mono" style="left:0;width:540px;top:590px;text-align:center;font-size:22px">DEEP WORK · DESIGN REVIEW</div>`)}
        ${card("f2d", { x: 630, y: 100, w: 510, h: 200 }, `<div class="abs t" style="left:34px;top:56px;font-size:34px;font-weight:600">Do not disturb</div>
          <div class="abs kit-mono" style="left:34px;top:108px;font-size:20px">UNTIL 10:25</div><div class="abs" style="right:34px;top:80px;width:64px;height:38px">${toggle("dnd")}</div>`)}
        ${card("f2e", { x: 630, y: 330, w: 510, h: 490 }, `<div class="abs kit-mono" style="left:34px;top:34px;font-size:20px">HELD FOR LATER</div>
          <div class="abs mask" style="left:34px;top:82px;width:300px;height:130px"><div data-k="heldRoll" class="abs" style="left:0;top:0;width:300px;height:130px"></div></div>
          <div class="abs t" style="left:36px;top:230px;font-size:30px;color:var(--ink2)">notifications,<br>until you're done</div>`)}`)}`)}
    ${scene("f3", "var(--field3)", `
      ${panel("f3L", LEFT, "var(--panel)", `<div class="abs" style="left:40px;top:100px">${headline("f3h", "Your week,\n*adding up.*", { size: 78 })}</div>`)}
      ${panel("f3R", RIGHT, "var(--panel)", `${card("f3c", { x: 60, y: 100, w: 1080, h: 720 }, `
        <div class="abs kit-mono" style="left:40px;top:40px;font-size:20px">THIS WEEK</div>
        <div class="abs mask" style="left:40px;top:76px;width:500px;height:110px"><div data-k="weekRoll" class="abs" style="left:0;top:0;width:500px;height:110px"></div></div>
        <div class="abs" style="left:218px;top:290px;width:650px;height:360px">${bars("wk", WEEK.map(([d]) => d))}</div>`)}`)}`)}
    ${scene("endScene", "var(--bg)", `
      <div class="abs" data-k="glow" style="left:560px;top:140px;width:800px;height:800px;border-radius:50%;background:radial-gradient(circle, rgba(210,98,42,.16) 0%, rgba(210,98,42,0) 70%)"></div>
      <div class="abs row" data-k="lockup" style="left:0;top:330px;width:1920px;justify-content:center;gap:34px">
        <div class="center" data-k="icon" style="width:150px;height:150px;border-radius:36px;background:var(--accent);color:#fff;font-size:92px;font-weight:800">A</div>
        <div class="mask" style="height:176px"><div data-k="wordmark" class="t" style="font-size:154px;font-weight:700;letter-spacing:-.045em">${APP.name}</div></div></div>
      <div class="abs hl-center" style="left:0;top:540px;width:1920px">${headline("tag", APP.line, { size: 74, color: "var(--ink2)", weight: 600 })}</div>
      <div class="abs row" style="left:0;top:690px;width:1920px;justify-content:center;gap:34px">
        <div class="center" data-k="cta" style="height:78px;padding:0 44px;border-radius:39px;background:var(--accent);color:#fff;font-size:30px;font-weight:700">${APP.cta}</div>
        <div class="row" style="font-family:var(--mono);font-size:34px;min-width:260px">${[...APP.url].map((ch, i) => `<span data-k="url${i}">${ch}</span>`).join("")}</div></div>
      <div class="abs kit-mono" data-k="facts" style="left:0;top:940px;width:1920px;text-align:center;font-size:22px">${APP.facts.join("&nbsp;&nbsp;·&nbsp;&nbsp;")}</div>`)}
    <div class="abs" data-k="badge" style="left:${LEFT.x + 40}px;top:${LEFT.y + LEFT.h - 190}px;width:150px;height:150px;border-radius:50%;background:#fff;border:5px solid var(--accent);overflow:hidden">
      <div class="abs" style="left:-6px;top:6px;width:162px;height:170px">${pebble("bd", false)}</div></div>
    ${character("hero", pebble("hr"), 420, 441)}`;
  collect(stage);
  K.done = roller($.doneRoll, "font-family:var(--mono);font-size:22px;color:var(--ink3);right:0;left:auto");
  K.held = roller($.heldRoll, "font-size:110px;font-weight:700;letter-spacing:-.04em");
  K.week = roller($.weekRoll, "font-size:92px;font-weight:700;letter-spacing:-.04em");
  const iconBox = $.icon.getBoundingClientRect(), stageBox = stage.getBoundingClientRect(), k = FILM.W / stageBox.width;
  K.onIcon = { x: (iconBox.left - stageBox.left + iconBox.width / 2) * k, y: (iconBox.top - stageBox.top) * k + 6 };
}

function heroAt(t) {
  let x = HOME.x, y = HOME.y, s = 1, hop = 0, squash = 0, lean = 0, on = true;
  const look = -0.9 * pulse(t, K.h1, 1.2) - 0.7 * prog(t, K.h2, 0.3) * (1 - prog(t, K.meet, 0.3));
  const shock = pulse(t, K.h3 + 0.15, 0.9);
  if (t >= K.meet && t < K.end + 0.2) {
    const f = clamp((t - K.meet) / 0.55);
    x = lerp(HOME.x, 2250, f);
    hop = 260 * 4 * f * (1 - f);
    on = f < 1;
  }
  if (t >= K.end + 0.2 && t < K.home) {
    const f = clamp((t - K.end - 0.2) / 0.6);
    x = lerp(2250, K.onIcon.x, f);
    y = lerp(HOME.y, K.onIcon.y, f);
    s = lerp(1, 0.42, f);
    hop = 300 * 4 * f * (1 - f);
    squash = -0.25 * pulse(t, K.end + 0.8, 0.3);
  }
  if (t >= K.home) {
    const f = clamp((t - K.home) / 0.6);
    x = lerp(K.onIcon.x, HOME.x, f);
    y = lerp(K.onIcon.y, HOME.y, f);
    s = lerp(0.42, 1, E.out(f));
    hop = 320 * 4 * f * (1 - f);
    squash = -0.25 * pulse(t, K.home + 0.6, 0.3) * (1 - prog(t, K.home + 0.9, 0.2));
  }
  squash += -0.2 * pulse(t, K.h3 + 0.1, 0.25) + 0.12 * shock;
  lean = 0.06 * look;
  show($.hero, on);
  characterAt("hero", t, { x, y, s, hop, squash, lean });
  const blink = Math.max(pulse(t, B(4), 0.16), pulse(t, B(41.5), 0.16), pulse(t, B(44), 0.16));
  const glad = prog(t, K.end + 0.8, 0.3) - prog(t, K.home + 0.6, 0.3);
  face("hr", { blink, wide: shock, smile: 0.5 + 0.5 * glad - 0.6 * shock, look });
}

function apply(t) {
  sceneAt("hookScene", t, -1, K.f1 + 0.6);
  headlineAt("h1", t, K.h1, K.meet);
  headlineAt("h2", t, K.h2, K.meet + 0.05);
  headlineAt("h3", t, K.h3, K.meet + 0.1);
  headlineAt("meet", t, K.meet + 0.35);
  const up = clamp(spring(t, K.meet + 0.25, 0.55, 0.8), 0, 1.05);
  show($.phone, t >= K.meet + 0.2);
  setT($.phone, `translateY(${((1 - up) * 900).toFixed(2)}px)`);

  sceneAt("f1", t, K.f1, K.f2 + 0.6);
  driftAt($.f1L, t, K.f1);
  driftAt($.f1R, t, K.f1, 160);
  headlineAt("f1h", t, K.f1 + 0.3);
  cardAt("f1c", t, K.f1 + 0.5);
  [B(15), B(16), B(17)].forEach((at, i) => {
    checkAt("chk" + i, t, at);
    setT($["strike" + i], `scaleX(${prog(t, at + 0.08, 0.3, E.out).toFixed(4)})`);
  });
  roll(K.done, t, [{ t: K.f1 + 0.5, v: "0 OF 4 DONE" }, { t: B(15), v: "1 OF 4 DONE" }, { t: B(16), v: "2 OF 4 DONE" }, { t: B(17), v: "3 OF 4 DONE" }]);

  sceneAt("f2", t, K.f2, K.f3 + 0.6);
  driftAt($.f2L, t, K.f2);
  driftAt($.f2R, t, K.f2, 160);
  headlineAt("f2h", t, K.f2 + 0.3);
  cardAt("f2c", t, K.f2 + 0.5);
  cardAt("f2d", t, K.f2 + 0.62);
  cardAt("f2e", t, K.f2 + 0.74);
  const run = prog(t, B(22), B(28) - B(22), E.linear);
  ringAt("focusRing", run);
  const left = Math.round(25 * 60 * (1 - run));
  $.focusTime.textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
  toggleAt("dnd", t, B(22.5));
  roll(K.held, t, [{ t: K.f2 + 0.74, v: "0" }, ...[3, 5, 6, 7].map((v, i) => ({ t: B(24 + i), v: String(v) }))]);

  sceneAt("f3", t, K.f3, K.end + 0.6);
  driftAt($.f3L, t, K.f3);
  driftAt($.f3R, t, K.f3, 160);
  headlineAt("f3h", t, K.f3 + 0.3);
  cardAt("f3c", t, K.f3 + 0.5);
  barsAt("wk", WEEK.map(([, v]) => v), t, B(30));
  roll(K.week, t, [{ t: K.f3 + 0.5, v: "0 tasks" }, { t: B(31), v: "31 tasks" }]);

  const badge = clamp(spring(t, K.f1 + 0.6, 0.45, 0.7), 0, 1.1) * (1 - prog(t, K.end, 0.3, E.in));
  show($.badge, badge > 0.001);
  setT($.badge, `scale(${badge.toFixed(4)})`);
  face("bd", { blink: pulse(t, B(18), 0.16) + pulse(t, B(26), 0.16), smile: 0.4 + 0.6 * Math.max(pulse(t, B(17), 0.6), pulse(t, B(31), 0.6)), look: 0.6 });

  sceneAt("endScene", t, K.end);
  const clear = prog(t, K.out, 0.45, E.in);
  const iconP = clamp(spring(t, K.end + 0.35, 0.45, 0.72), 0, 1.1);
  setT($.icon, `scale(${(iconP * (1 - clear)).toFixed(4)})`);
  setT($.wordmark, TRAVEL((1 - clamp(spring(t, K.end + 0.5, 0.5, 0.86), 0, 1.02)) + clear));
  headlineAt("tag", t, B(39), K.out);
  const cta = clamp(spring(t, B(41), 0.42, 0.74), 0, 1.08) * (1 - clear);
  setT($.cta, `scale(${cta.toFixed(4)})`);
  [...APP.url].forEach((_, i) => show($["url" + i], t >= B(41.6) + i * 0.05 && clear < 0.5));
  $.facts.style.opacity = (prog(t, B(43), 0.5) * (1 - clear)).toFixed(3);
  $.glow.style.opacity = (prog(t, K.end + 0.3, 0.8) * (1 - clear)).toFixed(3);

  heroAt(t);
}

function cues() {
  const wipe = (t) => ["whoosh", t - 0.05, { pan: 0.5 }];
  return [
    ...headlineCues("h1", K.h1), ...headlineCues("h2", K.h2), ...headlineCues("h3", K.h3),
    ["hop", K.meet], ["whoosh", K.meet + 0.2, { pan: 0.3, gain: -2 }], ...headlineCues("meet", K.meet + 0.35),
    wipe(K.f1), ...headlineCues("f1h", K.f1 + 0.3), ["thud", K.f1 + 0.62],
    ...[15, 16, 17].map((b, i) => ["pop", B(b), { note: 5 + i }]),
    wipe(K.f2), ...headlineCues("f2h", K.f2 + 0.3), ["thud", K.f2 + 0.62], ["click", B(22.5)],
    ...[24, 25, 26, 27].map((b) => ["tick", B(b), { gain: 3 }]),
    wipe(K.f3), ...headlineCues("f3h", K.f3 + 0.3), ["thud", K.f3 + 0.62],
    ...WEEK.map((_, i) => ["blip", B(30) + i * 0.12, { note: 5 + i }]),
    wipe(K.end), ["pop", K.end + 0.4, { note: 7 }], ["hop", K.end + 0.2], ["thud", K.end + 0.8, { gain: -3 }], ["chime", K.end + 0.55],
    ...headlineCues("tag", B(39)), ["pop", B(41), { note: 9 }],
    ...[...APP.url].map((_, i) => ["tick", B(41.6) + i * 0.05]),
    ["hop", K.home], ["thud", K.home + 0.6, { gain: -3 }],
  ];
}
