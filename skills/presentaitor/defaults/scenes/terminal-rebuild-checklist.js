film({ W: 1920, H: 1080, BPM: 110.0, BEATS: 112 });

const SHOTS = [];
const ROWS = 22;
const ROW_H = 34;
const CLEAN = (s) => s.replace(/[\p{Extended_Pictographic}️‍]/gu, "").replace(/\s{2,}/g, " ");
const LINES = DEPLOY_LINES.map(CLEAN);
const STOPS = [
  { line: 55, beat: 13, step: "TLS", title: "Certificates", sub: "TLS for every domain" },
  { line: 79, beat: 20, step: "DATABASE", title: "Own schema", sub: "in the shared Postgres" },
  { line: 90, beat: 28, step: "DOMAIN", title: "Mail domain", sub: "created through Stalwart's JMAP API" },
  { line: 100, beat: 37, step: "ACCOUNTS", title: "Mailboxes", sub: "alejandro · maria · helpdesk" },
  { line: 106, beat: 45, step: "SSO", title: "Single sign-on", sub: "authentication points at Keycloak" },
  { line: 108, beat: 55, step: "DKIM", title: "Signed mail", sub: "RSA DKIM key for the domain" },
  { line: 133, beat: 62, step: "KEYCLOAK", title: "Webmail client", sub: "registered in Keycloak" },
];
const RECAP_LINE = LINES.length - 1;
const CHECKS = ["Certificates", "Database", "Mail domain", "Mailboxes", "Single sign-on", "DKIM"];

function scrollKeys() {
  const k = [[B(9), 0]];
  STOPS.forEach((s, i) => {
    const prev = i ? STOPS[i - 1] : null;
    if (prev) k.push([B(s.beat) - 1.3, prev.line + 1]);
    k.push([B(s.beat), s.line + 1]);
  });
  k.push([B(68), STOPS[STOPS.length - 1].line + 1], [B(80), LINES.length]);
  return k;
}
const KEYS = [];

function linesAt(t) {
  if (t <= KEYS[0][0]) return 0;
  for (let i = 1; i < KEYS.length; i++) {
    const [t1, n1] = KEYS[i], [t0, n0] = KEYS[i - 1];
    if (t <= t1) return n0 + (n1 - n0) * E.inOut(clamp((t - t0) / Math.max(1e-6, t1 - t0)));
  }
  return LINES.length;
}

function build(stage) {
  KEYS.push(...scrollKeys());
  stage.innerHTML = `
    <div class="full" data-k="world">
      <div class="shot" data-k="s1">
        <div data-k="term" class="abs term" style="left:80px;top:140px;width:1120px;height:900px">
          <div class="bar"><i></i><i></i><i></i><span class="t mono" style="font-size:20px;color:var(--ink3);margin-left:18px">infinito-nexus — deploy</span></div>
          <div class="abs row" style="left:28px;top:70px;height:40px"><span class="t mono" style="font-size:24px;color:var(--accent2)">$&nbsp;</span><span data-k="cmd" class="t mono" style="font-size:24px"></span><span data-k="caret" style="width:12px;height:28px;margin-left:4px;background:var(--ink)"></span></div>
          <div class="abs" style="left:0;top:122px;width:1120px;height:${ROWS * ROW_H}px;overflow:hidden">
            <div data-k="hl" class="abs" style="left:0;width:1120px;height:${ROW_H}px;background:rgba(20,44,173,0.55);border-left:5px solid var(--accent2)"></div>
            <div data-k="rows" class="abs" style="left:28px;top:0;width:1070px">
              ${Array.from({ length: ROWS }, (_, i) => `<div data-k="r${i}" class="row-line mono"></div>`).join("")}
            </div>
          </div>
        </div>
        ${kicker("k1", "02 · DEPLOY", 80, 80, 800)}
        <div data-k="card" class="abs" style="left:1260px;top:380px;width:600px">
          <div class="mask" style="height:44px"><div data-k="cStep" class="t kicker">&nbsp;</div></div>
          <div class="mask" style="height:110px;margin-top:12px"><div data-k="cTitle" class="t" style="font-size:76px;font-weight:800;letter-spacing:-0.03em">&nbsp;</div></div>
          <div class="mask" style="height:50px;margin-top:6px"><div data-k="cSub" class="t" style="font-size:32px;font-weight:500;color:var(--ink2)">&nbsp;</div></div>
          <div class="row" style="gap:10px;margin-top:40px">${STOPS.map((_, i) => `<div data-k="dot${i}" style="width:44px;height:6px;border-radius:3px;background:var(--hair)"></div>`).join("")}</div>
        </div>
        <div data-k="recap" class="abs center" style="left:0;top:470px;width:1920px;height:220px;background:rgba(10,13,26,0.92);border-top:2px solid var(--accent2);border-bottom:2px solid var(--accent2);flex-direction:column;gap:18px">
          <div class="t mono" style="font-size:34px;color:var(--ink2)">ok=<span data-k="okN">0</span>&nbsp;&nbsp;changed=306&nbsp;&nbsp;unreachable=0</div>
          <div data-k="failed" class="t mono" style="font-size:88px;color:var(--ink)">failed=<span style="color:var(--accent2)">0</span></div>
        </div>
      </div>

      <div class="shot" data-k="s2">
        ${kicker("k2", "ONE COMMAND GAVE YOU", 360, 200, 1200)}
        ${CHECKS.map((c, i) => `
          <div data-k="ck${i}" class="abs row" style="left:${360 + (i % 2) * 620}px;top:${300 + Math.floor(i / 2) * 150}px;gap:28px">
            <svg width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="29" fill="var(--accent)" stroke="var(--accent2)" stroke-width="3"/><path data-k="ckp${i}" d="M19 33 L28 42 L46 23" fill="none" stroke="var(--ink)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <div class="t" style="font-size:52px;font-weight:800">${c}</div>
          </div>`).join("")}
      </div>

      <div class="shot center" data-k="s3" style="flex-direction:column;gap:26px">
        <div class="mask" style="height:44px"><div data-k="nextK" class="t kicker">NEXT</div></div>
        <div class="mask" style="height:130px"><div data-k="nextT" class="t" style="font-size:104px;font-weight:800;letter-spacing:-0.04em">03 · Send mail</div></div>
        <img data-k="logo" src="${ASSETS.img.logo}" style="width:120px;height:120px;border-radius:50%;margin-top:30px">
      </div>
    </div>
    ${scanLayer(0.06)}
    ${vignetteLayer(0.5)}
    ${grainLayer(0.08)}`;
  collect(stage);
  SHOTS.push(
    { k: "s1", t0: 0 },
    { k: "s2", t0: B(89), join: ["push", 0.55, { dir: "up" }] },
    { k: "s3", t0: B(101), join: ["push", 0.55, { dir: "left" }] },
  );
}

function kicker(k, text, x, y, w) {
  return `<div class="abs mask" style="left:${x}px;top:${y}px;width:${w}px;height:44px"><div data-k="${k}" class="t kicker">${text}</div></div>`;
}

function setCard(t, s, i) {
  const p = prog(t, B(s.beat) - 0.2, 0.45, E.out);
  $.cStep.textContent = `STEP ${i + 1} / ${STOPS.length} · ${s.step}`;
  $.cTitle.textContent = s.title;
  $.cSub.textContent = s.sub;
  rise($.cStep, p);
  rise($.cTitle, prog(t, B(s.beat) - 0.1, 0.45, E.out));
  rise($.cSub, prog(t, B(s.beat), 0.45, E.out));
}

function apply(t) {
  sequence(t, SHOTS);
  grain(t);
  scan(t, (4 * Math.round(10 * FILM.DURATION)) / FILM.DURATION);

  const tin = spring(t, 0.15, 0.45, 0.85);
  $.term.style.opacity = clamp(tin * 1.5).toFixed(3);
  setT($.term, `translateY(${(40 * (1 - tin)).toFixed(1)}px)`);
  rise($.k1, prog(t, 0.3, 0.5, E.out));
  $.cmd.textContent = typewriter(DEPLOY_CMD, t, B(4), 22);
  const typing = t >= B(4) && t < B(4) + DEPLOY_CMD.length / 22;
  show($.caret, t < B(9) && (typing || caret(t)));

  const n = linesAt(t);
  const top = Math.max(0, n - ROWS);
  const first = Math.floor(top);
  const frac = top - first;
  setT($.rows, `translateY(${(-frac * ROW_H).toFixed(2)}px)`);
  for (let i = 0; i < ROWS; i++) {
    const idx = first + i;
    $["r" + i].textContent = idx < Math.floor(n) + (frac > 0 ? 1 : 0) && idx < LINES.length ? LINES[idx] : "";
  }

  let active = -1;
  STOPS.forEach((s, i) => { if (t >= B(s.beat) - 0.25 && t < (STOPS[i + 1] ? B(STOPS[i + 1].beat) - 1.3 : B(68))) active = i; });
  if (active >= 0) {
    const s = STOPS[active];
    const row = s.line - top;
    $.hl.style.top = `${(row * ROW_H).toFixed(1)}px`;
    $.hl.style.opacity = prog(t, B(s.beat) - 0.25, 0.25, E.out).toFixed(3);
    for (let i = 0; i < ROWS; i++) $["r" + i].style.color = first + i === s.line ? "var(--ink)" : "";
    setCard(t, s, active);
    $.card.style.opacity = "1";
  } else {
    $.hl.style.opacity = "0";
    for (let i = 0; i < ROWS; i++) $["r" + i].style.color = "";
    const last = STOPS.filter((s) => t >= B(s.beat)).length - 1;
    if (last >= 0) {
      setCard(t, STOPS[last], last);
      $.card.style.opacity = (1 - prog(t, B(68), 0.4, E.in)).toFixed(3);
    } else $.card.style.opacity = "0";
  }
  STOPS.forEach((s, i) => { $["dot" + i].style.background = t >= B(s.beat) - 0.25 ? "var(--accent2)" : "var(--hair)"; });

  const rc = spring(t, B(81), 0.35, 0.8);
  $.recap.style.opacity = clamp(rc * 1.6).toFixed(3);
  setT($.recap, `scaleY(${(0.6 + 0.4 * rc).toFixed(4)})`);
  $.okN.textContent = countUp(t, B(81), 1.4, 0, 2561);
  setT($.failed, `scale(${(1 + 0.06 * pulse(t, B(83), 0.4)).toFixed(4)})`);
  if (t >= B(81) && t < B(82)) moveCamera($.world, shake(t, B(81), 0.4, 8));
  else moveCamera($.world, {});

  rise($.k2, prog(t, B(89) + 0.3, 0.5, E.out));
  const ckBeats = [90, 91, 92, 93, 94, 95].map((b) => B(b) + 0.4);
  CHECKS.forEach((_, i) => {
    const p = spring(t, ckBeats[i], 0.3, 0.8);
    $["ck" + i].style.opacity = clamp(p * 1.6).toFixed(3);
    setT($["ck" + i], `translateX(${(-30 * (1 - p)).toFixed(1)}px)`);
    drawPath($["ckp" + i], prog(t, ckBeats[i] + 0.1, 0.35, E.out));
  });

  rise($.nextK, prog(t, B(101) + 0.3, 0.5, E.out));
  rise($.nextT, prog(t, B(101) + 0.45, 0.55, E.out));
  const lo = prog(t, B(101) + 0.8, 0.6, E.out) * (1 - prog(t, B(109), FILM.DURATION - B(109), E.in));
  $.logo.style.opacity = lo.toFixed(3);
  $.nextT.style.opacity = $.nextK.style.opacity = (1 - prog(t, B(109), FILM.DURATION - B(109), E.in)).toFixed(3);
}
