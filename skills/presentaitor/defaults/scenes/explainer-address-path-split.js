film({ W: 1920, H: 1080, FPS: 30, BPM: 110.0, BEATS: 164 });

const F = (n) => n / FILM.FPS;
const FOOT0 = F(949);
const COMPOSE = F(1047);
const KEYCLOAK = F(1547);
const SPLIT = F(1702);
const OPEN = F(2029);
const RECAP = B(145);
const NEXT = B(155);
const END = FILM.DURATION;
const ADDR = "4dl6yijmuksgh5bfaf3csqoelji7zptyuo6wy5g5prjpnk6vdbzfwnad.onion";
const SHORT = "…@4dl6yijm…zfwnad.onion";
const SHOTS = [];

const PS = 896 / 1920;
const PANEL_L = { x: 48, y: 300 };
const PANEL_R = { x: 976, y: 300 };
const pr = (p, x, y, w, h) => ({ x: p.x + x * PS, y: p.y + y * PS, w: w * PS, h: h * PS });

const RINGS = [
  { k: "rUrl", x: 70, y: 4, w: 1010, h: 42, t0: FOOT0 + 0.75, t1: COMPOSE + 1.2 },
  { k: "rFrom", x: 326, y: 119, w: 958, h: 38, t0: COMPOSE + 0.35, t1: COMPOSE + 4.5 },
  { k: "rTo", x: 326, y: 158, w: 926, h: 38, t0: COMPOSE + 4.95, t1: COMPOSE + 9.3 },
  { k: "rSend", x: 128, y: 670, w: 86, h: 46, t0: B(93) - 1.6, t1: KEYCLOAK - 0.15 },
  { k: "rRow", ...pr(PANEL_R, 442, 142, 474, 52), t0: F(1761) + 0.1, t1: OPEN - 0.3, thin: true },
  { k: "rMail", x: 194, y: 152, w: 260, h: 28, t0: OPEN + 0.6, t1: RECAP - 0.2 },
];
const PILLS = [
  { k: "pUrl", x: 1180, y: 170, t0: FOOT0 + 1.0, t1: COMPOSE + 1.2, kick: "TOR BROWSER", text: "webmail at a .onion address" },
  { k: "pFrom", x: 360, y: 320, t0: COMPOSE + 0.6, t1: COMPOSE + 4.5, kick: "SENDER · onion address", text: SHORT },
  { k: "pTo", x: 360, y: 420, t0: COMPOSE + 5.2, t1: COMPOSE + 9.3, kick: "RECIPIENT · onion address", text: SHORT },
  { k: "pKc", x: 120, y: 880, t0: KEYCLOAK + 0.3, t1: SPLIT - 0.1, kick: "RECIPIENT", text: "signs in over Tor" },
  { k: "pMail", x: 200, y: 300, t0: OPEN + 0.9, t1: RECAP - 0.2, kick: "FROM: … (ONION)", text: "onion → onion" },
];
const PLATES = [
  { k: "plA", name: "sender", x: 122, y: 55, w: 317, h: 52, fs: 24, spans: [[FOOT0, COMPOSE]] },
  { k: "plB", name: "recipient", ...pr(PANEL_R, 122, 55, 317, 52), fs: 13, spans: [[SPLIT, OPEN]] },
];
const TAGS = [
  { k: "tg0", text: "no IP address", at: B(23) },
  { k: "tg1", text: "no DNS", at: B(25) },
  { k: "tg2", text: "reachable only through Tor", at: B(27) },
];
const PATH = [[500, 520], [720, 450], [960, 640], [1200, 450], [1420, 520]];
const LEGS = [B(41), B(43), B(45), B(47), B(49)];
const TILES = [
  { k: "ti0", label: "Onion sender", at: B(146), icon: "out" },
  { k: "ti1", label: "Onion recipient", at: B(148), icon: "in" },
  { k: "ti2", label: "Webmail over Tor", at: B(150), icon: "web" },
];

const ONION = `
  <path d="M50 12 C50 22 56 28 64 34 C76 43 84 53 84 66 C84 81 69 90 50 90 C31 90 16 81 16 66 C16 53 24 43 36 34 C44 28 50 22 50 12 Z"/>
  <path d="M50 34 C44 42 32 50 32 66 C32 77 40 84 50 84 C60 84 68 77 68 66 C68 50 56 42 50 34 Z"/>
  <path d="M50 50 C47 56 44 61 44 68 C44 75 47 79 50 80 C53 79 56 75 56 68 C56 61 53 56 50 50 Z"/>
  <path d="M50 12 C52 8 56 6 61 6"/>`;
const onion = (size, sw = 4) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 100 100" fill="none" stroke="var(--ink)" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round">${ONION}</svg>`;
const ENVELOPE = `<rect x="4" y="4" width="92" height="62" rx="8" fill="var(--bg2)"/><path d="M7 9 L50 40 L93 9"/>`;
const ICONS = {
  out: `<g transform="translate(-8 4) scale(0.86)">${ONION}</g><path d="M66 30 L92 6 M74 6 L92 6 L92 24" stroke="var(--accent2)"/>`,
  in: `<g transform="translate(-8 4) scale(0.86)">${ONION}</g><path d="M92 6 L68 30 M68 12 L68 30 L86 30" stroke="var(--accent2)"/>`,
  web: `<rect x="6" y="14" width="88" height="72" rx="8"/><path d="M6 32 H94"/><circle cx="16" cy="23" r="2.5"/><circle cx="25" cy="23" r="2.5"/><rect x="28" y="46" width="44" height="30" rx="4" stroke="var(--accent2)"/><path d="M30 49 L50 63 L70 49" stroke="var(--accent2)"/>`,
};

const kick = (k, text, x, y, w, align = "left") =>
  `<div class="abs mask" style="left:${x}px;top:${y}px;width:${w}px;height:44px;text-align:${align}"><div data-k="${k}" class="t kicker">${text}</div></div>`;

function build(stage) {
  stage.innerHTML = `
    <div class="full" data-k="world">
      <div class="full" data-k="sF"></div>

      ${PLATES.map((p) => `<div data-k="${p.k}" class="abs center" style="left:${p.x}px;top:${p.y}px;width:${p.w}px;height:${p.h}px;background:rgba(10,13,26,0.97);border-radius:${p.fs > 20 ? 6 : 3}px"><div class="t mono" style="font-size:${p.fs}px;color:var(--ink)">${p.name}</div></div>`).join("")}

      <div data-k="split" class="full">
        <div class="abs panel" style="left:${PANEL_L.x - 2}px;top:${PANEL_L.y - 2}px;width:900px;height:508px"></div>
        <div class="abs panel" style="left:${PANEL_R.x - 2}px;top:${PANEL_R.y - 2}px;width:900px;height:508px"></div>
        ${kick("spKL", "SENDER · onion address", PANEL_L.x, 176, 896)}
        ${kick("spKR", "RECIPIENT · onion address", PANEL_R.x, 176, 896)}
        <div class="abs mask" style="left:${PANEL_L.x}px;top:222px;width:896px;height:56px"><div data-k="spAL" class="t mono" style="font-size:36px">${SHORT}</div></div>
        <div class="abs mask" style="left:${PANEL_R.x}px;top:222px;width:896px;height:56px"><div data-k="spAR" class="t mono" style="font-size:36px">${SHORT}</div></div>
        <div data-k="spSL" class="abs pill row" style="left:${PANEL_L.x}px;top:836px;gap:14px;padding:10px 22px"><i style="width:14px;height:14px;border-radius:50%;background:var(--accent2)"></i><div class="t" style="font-size:30px;font-weight:800">Sent</div></div>
        <div data-k="spSR" class="abs pill row" style="left:${PANEL_R.x}px;top:836px;gap:14px;padding:10px 22px"><i style="width:14px;height:14px;border-radius:50%;background:var(--accent2)"></i><div class="t" style="font-size:30px;font-weight:800">New mail arrived</div></div>
        <div data-k="spNote" class="abs center" style="left:0;top:950px;width:1920px;height:40px"><div class="t mono" style="font-size:24px;color:var(--ink2)">Demo: both mailboxes on one node</div></div>
      </div>

      ${RINGS.map((r) => `<div data-k="${r.k}" class="abs ring" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;${r.thin ? "border-width:3px;border-radius:6px" : ""}"></div>`).join("")}
      ${PILLS.map((p) => `
        <div data-k="${p.k}" class="abs pill" style="left:${p.x}px;top:${p.y}px">
          <div class="t kicker" style="font-size:22px">${p.kick}</div><br>
          <div class="t" style="font-size:34px;font-weight:800;margin-top:4px">${p.text}</div>
        </div>`).join("")}

      <div data-k="demo" class="abs center" style="left:1772px;top:7px;width:124px;height:32px;border-radius:16px;border:2px solid var(--accent2);background:rgba(10,13,26,0.9)"><div class="t mono" style="font-size:18px;letter-spacing:0.16em;color:var(--ink)">DEMO</div></div>

      <div class="shot center" data-k="s1" style="flex-direction:column">
        <div data-k="onion1" style="margin-bottom:30px">${onion(150, 3.6)}</div>
        <div class="mask" style="height:44px"><div data-k="k1" class="t kicker">08 · TOR</div></div>
        <div class="mask" style="height:172px"><div data-k="title1" class="t h1">Mail over Tor<span style="color:var(--accent2)">.</span></div></div>
        <svg width="760" height="20" viewBox="0 0 760 20" style="margin-top:8px;overflow:visible"><path data-k="under1" d="M0 10 L760 10" stroke="var(--accent2)" stroke-width="10" stroke-linecap="round"/></svg>
      </div>

      <div class="shot" data-k="s2">
        <div class="abs" style="left:120px;top:376px;width:1200px;height:44px"><div data-k="k2" class="abs mask" style="left:0;top:0;width:1200px;height:44px"></div></div>
        <div data-k="card" class="abs row" style="left:120px;top:446px;width:1680px;height:150px;border:3px solid var(--accent2);border-radius:24px;background:var(--bg2);padding:0 40px">
          <div class="mask" data-k="pre" style="width:0;height:60px"><div class="t mono" style="font-size:40px;line-height:60px;color:var(--accent2)">you@</div></div>
          <div class="t mono" style="font-size:40px;line-height:60px"><span data-k="addr"></span><span data-k="caret" style="color:var(--accent2)">▍</span></div>
        </div>
        <div class="abs mask" style="left:122px;top:620px;width:1200px;height:40px"><div data-k="count" class="t mono" style="font-size:26px;color:var(--ink3)">56 characters, ending in .onion</div></div>
        <div class="abs row" style="left:120px;top:730px;gap:26px">
          ${TAGS.map((g) => `<div data-k="${g.k}" class="tag"><span class="t">${g.text}</span></div>`).join("")}
        </div>
      </div>

      <div class="shot" data-k="s3">
        ${kick("k3", "ONION TO ONION", 0, 150, 1920, "center")}
        <div data-k="cloud" class="abs" style="left:590px;top:330px;width:740px;height:420px;border:3px dashed rgba(79,107,255,0.45);border-radius:210px;background:rgba(20,44,173,0.12)"></div>
        <div class="abs mask" style="left:590px;top:762px;width:740px;height:44px;text-align:center"><div data-k="cloudK" class="t kicker" style="font-size:24px;color:var(--ink2)">TOR NETWORK</div></div>
        <svg class="abs" style="left:0;top:0;overflow:visible" width="1920" height="1080" viewBox="0 0 1920 1080" fill="none">
          <path data-k="route" d="${PATH.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" ")}" stroke="var(--accent2)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="2 14"/>
          <path data-k="routeDraw" d="${PATH.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" ")}" stroke="var(--accent2)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>
        </svg>
        ${[1, 2, 3].map((i) => `<div data-k="hop${i}" class="abs hop center" style="left:${PATH[i][0] - 46}px;top:${PATH[i][1] - 46}px"><div class="t mono" style="font-size:30px">${i}</div></div>`).join("")}
        <div data-k="nodeL" class="abs node" style="left:120px;top:390px;width:380px;height:260px">${onion(110)}<div class="t mono" style="font-size:28px">x7k2m9…q4vd.onion</div></div>
        <div data-k="nodeR" class="abs node" style="left:1420px;top:390px;width:380px;height:260px">${onion(110)}<div class="t mono" style="font-size:28px">pz3r8t…n6wd.onion</div></div>
        <svg data-k="env" class="abs" style="left:-48px;top:-34px;overflow:visible" width="96" height="68" viewBox="0 0 100 70" fill="none" stroke="var(--ink)" stroke-width="5" stroke-linejoin="round" stroke-linecap="round">${ENVELOPE}</svg>
        <div class="abs center" style="left:0;top:850px;width:1920px;height:96px"><div class="mask" style="height:96px"><div data-k="cap3" class="t" style="font-size:66px;font-weight:800;letter-spacing:-0.03em">Onion to onion, <span style="color:var(--accent2)">inside Tor</span></div></div></div>
      </div>

      <div class="shot" data-k="s7">
        ${kick("k7", "IN THIS CHAPTER", 0, 210, 1920, "center")}
        ${TILES.map((tl, i) => `
          <div data-k="${tl.k}" class="abs tile" style="left:${260 + i * 500}px;top:320px;width:400px;height:380px">
            <svg width="150" height="150" viewBox="0 0 100 100" fill="none" stroke="var(--ink)" stroke-width="4" stroke-linejoin="round" stroke-linecap="round">${ICONS[tl.icon]}</svg>
            <div class="t" style="font-size:40px;font-weight:800;margin-top:30px">${tl.label}</div>
          </div>`).join("")}
        <div data-k="nextBox" class="full center" style="flex-direction:column;gap:26px">
          <div class="mask" style="height:44px"><div data-k="nextK" class="t kicker">NEXT</div></div>
          <div class="mask" style="height:136px"><div data-k="nextT" class="t" style="font-size:104px;font-weight:800;letter-spacing:-0.04em">09 · Moving from Mailu</div></div>
          <img data-k="logo" src="${ASSETS.img.logo}" style="width:120px;height:120px;border-radius:50%;margin-top:30px">
        </div>
      </div>
      <div data-k="fadeOut" class="full" style="background:var(--bg);opacity:0"></div>
    </div>
    ${scanLayer(0.06)}
    <div data-k="vigM" class="full" style="pointer-events:none;background:radial-gradient(ellipse at 50% 50%,transparent 55%,rgba(0,0,0,0.5) 100%)"></div>
    <div data-k="vigF" class="full" style="pointer-events:none;background:radial-gradient(ellipse at 50% 50%,transparent 55%,rgba(0,0,0,0.2) 100%)"></div>
    ${grainLayer(0.08)}`;
  collect(stage);
  $.kRoll = roller($.k2, "");
  $.k2.querySelectorAll("span").forEach((s) => s.classList.add("kicker"));
  $.preW = measure("you@", 40, 600, "font-family:var(--mono);letter-spacing:-0.01em");
  SHOTS.push(
    { k: "s1", t0: 0 },
    { k: "s2", t0: B(13), join: ["push", 0.6, { dir: "left" }] },
    { k: "s3", t0: B(37), join: ["push", 0.6, { dir: "left" }] },
    { k: "sF", t0: FOOT0, join: ["push", 0.6, { dir: "up" }] },
    { k: "s7", t0: RECAP, join: ["cover", 0.6, { dir: "left" }] },
  );
}

function fade(t, t0, t1, d = 0.35) {
  return prog(t, t0, d, E.out) * (1 - prog(t, t1 - d, d, E.in));
}

function envAt(t) {
  if (t <= LEGS[0]) return PATH[0];
  for (let i = 0; i < LEGS.length - 1; i++) {
    if (t < LEGS[i + 1]) {
      const p = prog(t, LEGS[i], LEGS[i + 1] - LEGS[i], E.inOut);
      return [lerp(PATH[i][0], PATH[i + 1][0], p), lerp(PATH[i][1], PATH[i + 1][1], p)];
    }
  }
  return PATH[PATH.length - 1];
}

function apply(t) {
  sequence(t, SHOTS);
  grain(t);
  scan(t, (4 * Math.round(10 * FILM.DURATION)) / FILM.DURATION);

  const footage = t >= FOOT0 && t < RECAP + 0.6;
  $.vigF.style.opacity = footage ? "1" : "0";
  $.vigM.style.opacity = footage ? "0" : "1";
  $.demo.style.opacity = (t >= FOOT0 + 0.6 && t < RECAP ? 1 : 0).toFixed(3);

  PLATES.forEach((p) => {
    $[p.k].style.opacity = p.spans.some(([a, b]) => t >= a && t < b) ? "1" : "0";
  });

  RINGS.forEach((r) => {
    const o = fade(t, r.t0, r.t1);
    const s = spring(t, r.t0, 0.4, 0.8);
    $[r.k].style.opacity = o.toFixed(3);
    setT($[r.k], `scale(${(1.06 - 0.06 * s).toFixed(4)})`);
  });
  PILLS.forEach((p) => {
    const o = fade(t, p.t0, p.t1);
    const s = spring(t, p.t0, 0.4, 0.85);
    $[p.k].style.opacity = o.toFixed(3);
    setT($[p.k], `translateY(${(18 * (1 - s)).toFixed(1)}px)`);
  });

  const onSplit = t >= SPLIT && t < OPEN;
  show($.split, onSplit);
  if (onSplit) {
    rise($.spKL, prog(t, SPLIT + 0.15, 0.5, E.out));
    rise($.spAL, prog(t, SPLIT + 0.3, 0.5, E.out));
    rise($.spKR, prog(t, SPLIT + 0.45, 0.5, E.out));
    rise($.spAR, prog(t, SPLIT + 0.6, 0.5, E.out));
    const sl = spring(t, SPLIT + 0.5, 0.4, 0.85);
    $.spSL.style.opacity = clamp(sl * 1.5).toFixed(3);
    setT($.spSL, `translateY(${(16 * (1 - sl)).toFixed(1)}px)`);
    const sr = spring(t, F(1761), 0.4, 0.85);
    $.spSR.style.opacity = clamp(sr * 1.5).toFixed(3);
    setT($.spSR, `translateY(${(16 * (1 - sr)).toFixed(1)}px)`);
    $.spNote.style.opacity = prog(t, SPLIT + 1.2, 0.5, E.out).toFixed(3);
  }

  const lg = spring(t, 0.15, 0.5, 0.8);
  $.onion1.style.opacity = clamp(lg * 1.4).toFixed(3);
  setT($.onion1, `scale(${(0.6 + 0.4 * lg).toFixed(4)})`);
  rise($.k1, prog(t, 0.4, 0.5, E.out));
  rise($.title1, prog(t, 0.55, 0.6, E.out));
  drawPath($.under1, prog(t, B(3), 0.8, E.inOut));

  roll($.kRoll, t, [{ t: B(13) + 0.35, v: "AN ONION ADDRESS" }, { t: B(33), v: "AN ONION MAIL ADDRESS" }]);
  const typeAt = B(15);
  const typed = typewriter(ADDR, t, typeAt, 34);
  $.addr.textContent = typed;
  const doneTyping = typed.length === ADDR.length;
  $.caret.style.opacity = (t < typeAt - 0.6 ? 0 : !doneTyping || caret(t) ? 1 : 0).toFixed(0);
  if (t >= B(33)) $.caret.style.opacity = "0";
  const pre = spring(t, B(33), 0.4, 0.82);
  $.pre.style.width = (clamp(pre, 0, 1.2) * $.preW).toFixed(2) + "px";
  const cardIn = spring(t, B(13) + 0.4, 0.45, 0.85);
  $.card.style.opacity = clamp(cardIn * 1.5).toFixed(3);
  setT($.card, `translateY(${(30 * (1 - cardIn)).toFixed(1)}px)`);
  const flash = pulse(t, B(33), 0.6);
  $.card.style.boxShadow = `0 0 ${(60 * flash).toFixed(1)}px rgba(79,107,255,${(0.7 * flash).toFixed(3)})`;
  rise($.count, prog(t, typeAt + 2.0, 0.5, E.out));
  TAGS.forEach((g) => {
    const p = spring(t, g.at, 0.36, 0.75);
    $[g.k].style.opacity = clamp(p * 1.6).toFixed(3);
    setT($[g.k], `translateY(${(40 * (1 - p)).toFixed(1)}px)`);
  });
  if (t >= B(33) && t < B(33) + 0.4) moveCamera($.s2, shake(t, B(33), 0.35, 5));

  rise($.k3, prog(t, B(37) + 0.35, 0.5, E.out));
  const nl = spring(t, B(37) + 0.5, 0.42, 0.82);
  const nr = spring(t, B(38) + 0.5, 0.42, 0.82);
  $.nodeL.style.opacity = clamp(nl * 1.5).toFixed(3);
  setT($.nodeL, `translateY(${(40 * (1 - nl)).toFixed(1)}px)`);
  const arrive = pulse(t, LEGS[4], 0.9);
  $.nodeR.style.opacity = clamp(nr * 1.5).toFixed(3);
  setT($.nodeR, `translateY(${(40 * (1 - nr)).toFixed(1)}px) scale(${(1 + 0.05 * arrive).toFixed(4)})`);
  $.nodeR.style.boxShadow = `0 0 ${(70 * arrive).toFixed(1)}px rgba(79,107,255,${(0.8 * arrive).toFixed(3)})`;
  $.cloud.style.opacity = prog(t, B(39), 0.6, E.out).toFixed(3);
  rise($.cloudK, prog(t, B(39) + 0.2, 0.5, E.out));
  drawPath($.routeDraw, prog(t, B(40), 0.9, E.inOut));
  $.route.style.opacity = "0";
  [1, 2, 3].forEach((i) => {
    const h = $["hop" + i];
    const p = spring(t, B(39) + 0.15 * i, 0.35, 0.75);
    const pass = pulse(t, LEGS[i] - 0.15, 0.8);
    const idle = 0.5 + 0.5 * Math.sin((t - B(39)) * 3.2 + i * 1.7);
    const g = 18 + 14 * idle + 50 * pass;
    h.style.opacity = clamp(p * 1.6).toFixed(3);
    setT(h, `scale(${(0.5 + 0.5 * p + 0.16 * pass).toFixed(4)})`);
    h.style.boxShadow = `0 0 ${g.toFixed(1)}px ${(g / 3).toFixed(1)}px rgba(79,107,255,${(0.45 + 0.4 * pass).toFixed(3)})`;
  });
  const [ex, ey] = envAt(t);
  const envIn = prog(t, LEGS[0] - 0.4, 0.4, E.out);
  const envOut = prog(t, LEGS[4] + 0.1, 0.35, E.in);
  $.env.style.opacity = (envIn * (1 - envOut)).toFixed(3);
  setT($.env, `translate(${ex.toFixed(1)}px,${(ey - 60).toFixed(1)}px) scale(${(1 - 0.4 * envOut).toFixed(4)})`);
  rise($.cap3, prog(t, B(51), 0.6, E.out));

  rise($.k7, prog(t, RECAP + 0.35, 0.5, E.out));
  const tilesOut = prog(t, NEXT - 0.5, 0.45, E.in);
  $.k7.parentElement.style.opacity = (1 - tilesOut).toFixed(3);
  TILES.forEach((tl, i) => {
    const p = spring(t, tl.at, 0.36, 0.8);
    $[tl.k].style.opacity = (clamp(p * 1.6) * (1 - tilesOut)).toFixed(3);
    setT($[tl.k], `translateY(${(80 * (1 - p) - 40 * tilesOut).toFixed(1)}px)`);
  });
  show($.nextBox, t >= NEXT);
  rise($.nextK, prog(t, NEXT + 0.1, 0.5, E.out));
  rise($.nextT, prog(t, NEXT + 0.25, 0.55, E.out));
  const lgo = spring(t, NEXT + 0.6, 0.5, 0.85);
  $.logo.style.opacity = clamp(lgo * 1.4).toFixed(3);
  setT($.logo, `scale(${(0.8 + 0.2 * lgo).toFixed(4)})`);
  $.fadeOut.style.opacity = prog(t, END - 2.0, 1.9, E.in).toFixed(3);
}
