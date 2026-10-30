film({ W: 1920, H: 1080, BPM: 110.0, BEATS: 80 });

const SHOTS = [];
const CHAPTERS = ["Deploy", "Mail", "Filters", "Admin", "Calendars", "Tor"];
const CHAPTER_BEATS = [58, 60, 62, 66, 69, 72];
const TILES = [
  { k: "tMail", label: "Mail", icon: '<rect x="8" y="18" width="84" height="60" rx="8"/><path d="M10 22 L50 52 L90 22"/>' },
  { k: "tCal", label: "Calendars", icon: '<rect x="10" y="18" width="80" height="66" rx="8"/><path d="M10 38 H90 M32 10 V26 M68 10 V26"/><path d="M28 54 H40 M46 54 H58 M64 54 H76 M28 68 H40 M46 68 H58"/>' },
  { k: "tCon", label: "Contacts", icon: '<circle cx="50" cy="36" r="16"/><path d="M18 86 C22 64 36 58 50 58 C64 58 78 64 82 86"/>' },
];

const kicker = (k, text, x, y, w) =>
  `<div class="abs mask" style="left:${x}px;top:${y}px;width:${w}px;height:44px"><div data-k="${k}" class="t kicker">${text}</div></div>`;

function build(stage) {
  stage.innerHTML = `
    <div class="full" data-k="world">
      <div class="shot center" data-k="s1" style="flex-direction:column;gap:44px">
        <img data-k="logo1" src="${ASSETS.img.logo}" style="width:360px;height:360px;border-radius:50%">
        <div data-k="title1" class="t h1 mono" style="font-size:96px">&nbsp;</div>
      </div>

      <div class="shot" data-k="s2">
        ${kicker("k2", "UNTIL NOW", 260, 330, 800)}
        <div class="abs" style="left:260px;top:390px"><div data-k="mail2" class="t h1">Mail,</div></div>
        <div class="abs" style="left:260px;top:560px;width:1400px;height:200px">
          <div data-k="bolted" class="t h1" style="color:var(--ink3);transform-origin:0 50%">bolted on.</div>
          <div data-k="built" class="abs t h1" style="left:0;top:0;color:var(--ink)">built in<span style="color:var(--accent2)">.</span></div>
        </div>
      </div>

      <div class="shot center" data-k="s3">
        <svg data-k="env" class="abs" style="left:810px;top:390px;overflow:visible" width="300" height="300" viewBox="0 0 100 100" fill="none" stroke="var(--ink)" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round">
          <rect x="8" y="22" width="84" height="56" rx="6"/><path data-k="flap" d="M10 26 L50 54 L90 26"/>
        </svg>
        <div data-k="server" class="abs" style="left:610px;top:300px;width:700px;height:400px;border:3px solid var(--accent2);border-radius:22px;background:var(--bg2)">
          <div class="abs" style="left:40px;top:44px;right:40px;height:76px;border-radius:12px;background:rgba(79,107,255,0.10);border:2px solid var(--hair)"></div>
          <div class="abs" style="left:40px;top:144px;right:40px;height:76px;border-radius:12px;background:rgba(79,107,255,0.10);border:2px solid var(--hair)"></div>
          <div data-k="led1" class="abs" style="left:70px;top:72px;width:20px;height:20px;border-radius:50%;background:var(--accent2)"></div>
          <div data-k="led2" class="abs" style="left:70px;top:172px;width:20px;height:20px;border-radius:50%;background:var(--accent2)"></div>
          <div class="abs mask" style="left:40px;top:262px;width:640px;height:90px"><div data-k="domain" class="t mono" style="font-size:44px;color:var(--ink)">&nbsp;</div></div>
        </div>
        ${kicker("k3", "EVERY DEPLOYMENT", 610, 230, 700)}
      </div>

      <div class="shot" data-k="s4">
        ${TILES.map((tl, i) => `
          <div data-k="${tl.k}" class="abs tile" style="left:${330 + i * 450}px;top:330px">
            <svg width="150" height="150" viewBox="0 0 100 100" fill="none" stroke="var(--ink)" stroke-width="4" stroke-linejoin="round" stroke-linecap="round">${tl.icon}</svg>
            <div class="t" style="font-size:48px;font-weight:800;margin-top:28px">${tl.label}</div>
            <svg data-k="${tl.k}Lock" class="abs" style="right:22px;top:22px" width="56" height="56" viewBox="0 0 100 100" fill="var(--accent2)"><rect x="18" y="44" width="64" height="48" rx="10"/><path d="M32 46 V32 C32 14 68 14 68 32 V46" fill="none" stroke="var(--accent2)" stroke-width="11"/></svg>
          </div>`).join("")}
        <div data-k="ssoBar" class="abs" style="left:330px;top:800px;width:1260px;height:6px;border-radius:3px;background:var(--accent2);transform-origin:50% 50%"></div>
        <div class="abs center" style="left:0;top:830px;width:1920px;height:90px">
          <div class="mask" style="height:90px"><div data-k="sso" class="t" style="font-size:56px;font-weight:800">One account. Single sign-on.</div></div>
        </div>
        <svg data-k="bigLock" class="abs" style="left:900px;top:140px;overflow:visible" width="120" height="140" viewBox="0 0 100 116">
          <rect x="6" y="50" width="88" height="62" rx="14" fill="var(--accent)" stroke="var(--accent2)" stroke-width="4"/>
          <path data-k="shackle" d="M24 54 V34 C24 6 76 6 76 34 V54" fill="none" stroke="var(--ink)" stroke-width="12" stroke-linecap="round"/>
        </svg>
        ${kicker("k4", "ON YOUR OWN INFRASTRUCTURE", 330, 230, 1260)}
      </div>

      <div class="shot center" data-k="s5" style="flex-direction:column">
        ${kicker("k5", "THE MAIL SERVER", 0, 330, 1920)}
        <div data-k="stalwart" class="t" style="font-size:220px;font-weight:800;letter-spacing:-0.045em">Stalwart</div>
        <svg class="abs" style="left:560px;top:700px;overflow:visible" width="800" height="20" viewBox="0 0 800 20"><path data-k="under" d="M0 10 L800 10" stroke="var(--accent2)" stroke-width="10" stroke-linecap="round"/></svg>
      </div>

      <div class="shot" data-k="s6">
        ${kicker("k6", "IN THIS SERIES", 160, 300, 1600)}
        ${CHAPTERS.map((c, i) => `
          <div data-k="ch${i}" class="abs chip" style="left:${160 + i * 270}px;top:420px">
            <div class="t mono" style="font-size:26px;color:var(--ink3)">0${i + 2}</div>
            <div class="t" style="font-size:38px;font-weight:800;margin-top:14px">${c}</div>
          </div>`).join("")}
        <div data-k="rail" class="abs" style="left:160px;top:660px;width:1600px;height:4px;border-radius:2px;background:var(--accent2);transform-origin:0 50%"></div>
      </div>

      <div class="shot center" data-k="s7" style="flex-direction:column;gap:36px">
        <img data-k="logo2" src="${ASSETS.img.logo}" style="width:220px;height:220px;border-radius:50%">
        <div data-k="title2" class="t mono" style="font-size:56px">Infinito.Nexus 15.0</div>
      </div>
    </div>
    ${scanLayer(0.06)}
    ${vignetteLayer(0.5)}
    ${grainLayer(0.08)}`;
  collect(stage);
  SHOTS.push(
    { k: "s1", t0: 0 },
    { k: "s2", t0: B(9), join: ["push", 0.55, { dir: "up" }] },
    { k: "s3", t0: B(17), join: ["zoom", 0.5] },
    { k: "s4", t0: B(27), join: ["cover", 0.55, { dir: "left" }] },
    { k: "s5", t0: B(49), join: ["iris", 0.45, { x: "50%", y: "50%" }] },
    { k: "s6", t0: B(57), join: ["push", 0.55, { dir: "left" }] },
    { k: "s7", t0: B(75), join: ["dissolve", 0.5] },
  );
}

function apply(t) {
  sequence(t, SHOTS);
  grain(t);
  scan(t, (4 * Math.round(10 * FILM.DURATION)) / FILM.DURATION);

  const lg = spring(t, B(1) + 0.1, 0.5, 0.8);
  $.logo1.style.opacity = clamp(lg * 1.4).toFixed(3);
  setT($.logo1, `scale(${(0.6 + 0.4 * lg).toFixed(4)})`);
  $.title1.innerHTML = t < B(3) ? "&nbsp;" : scramble("Infinito.Nexus 15.0", t, B(3), 1.0, 2);

  rise($.k2, prog(t, B(9) + 0.3, 0.5, E.out));
  rise($.mail2, prog(t, B(9) + 0.4, 0.5, E.out));
  const loose = prog(t, B(10), 0.6, E.out);
  const snap = spring(t, B(13), 0.28, 0.7);
  $.bolted.style.opacity = (loose * (1 - clamp(snap * 2))).toFixed(3);
  setT($.bolted, `translate(${(40 * (1 - loose)).toFixed(1)}px, ${(18 * loose).toFixed(1)}px) rotate(${(-7 * loose).toFixed(2)}deg)`);
  $.built.style.opacity = clamp(snap * 2).toFixed(3);
  setT($.built, `translateY(${(-30 * (1 - snap)).toFixed(1)}px)`);
  if (t >= B(13)) moveCamera($.world, shake(t, B(13), 0.35, 6));
  else moveCamera($.world, {});

  const grow = prog(t, B(19), 0.7, E.inOut);
  $.env.style.opacity = (1 - grow).toFixed(3);
  setT($.env, `scale(${(1 + 1.2 * grow).toFixed(4)})`);
  $.server.style.opacity = grow.toFixed(3);
  setT($.server, `scale(${(0.45 + 0.55 * grow).toFixed(4)})`);
  rise($.k3, prog(t, B(19) + 0.3, 0.5, E.out));
  $.domain.textContent = t < B(21) ? " " : typewriter("mail.your-domain.org", t, B(21), 18);
  $.led1.style.opacity = (0.45 + 0.55 * (0.5 + 0.5 * Math.cos((t - B(21)) * 7))).toFixed(3);
  $.led2.style.opacity = (0.45 + 0.55 * (0.5 + 0.5 * Math.cos((t - B(21)) * 5 + 1))).toFixed(3);

  const land = [B(27) + 0.5, B(29), B(31)];
  TILES.forEach((tl, i) => {
    const p = spring(t, land[i], 0.36, 0.8);
    $[tl.k].style.opacity = clamp(p * 1.6).toFixed(3);
    setT($[tl.k], `translateY(${(80 * (1 - p)).toFixed(1)}px)`);
    const lp = spring(t, B(45) + i * 0.12, 0.25, 0.7);
    $[tl.k + "Lock"].style.opacity = clamp(lp * 2).toFixed(3);
    setT($[tl.k + "Lock"], `scale(${(0.4 + 0.6 * lp).toFixed(4)})`);
  });
  rise($.k4, prog(t, B(27) + 0.2, 0.5, E.out));
  setT($.ssoBar, `scaleX(${prog(t, B(37), 0.6, E.out).toFixed(4)})`);
  rise($.sso, prog(t, B(37) + 0.2, 0.5, E.out));
  const lockIn = spring(t, B(42), 0.3, 0.8);
  $.bigLock.style.opacity = clamp(lockIn * 2).toFixed(3);
  setT($.bigLock, `translateY(${(-40 * (1 - lockIn)).toFixed(1)}px)`);
  setT($.shackle, `translateY(${(-16 * (1 - prog(t, B(43), 0.25, E.in))).toFixed(1)}px)`);

  rise($.k5, prog(t, B(49) + 0.2, 0.5, E.out));
  const rev = spring(t, B(49), 0.4, 0.75);
  $.stalwart.style.opacity = clamp(rev * 1.5).toFixed(3);
  setT($.stalwart, `scale(${(0.86 + 0.14 * rev).toFixed(4)})`);
  if (t >= B(49) && t < B(53)) glitch($.stalwart, t, B(49) + 0.05, 0.25, 10);
  drawPath($.under, prog(t, B(50), 0.7, E.inOut));

  rise($.k6, prog(t, B(57) + 0.2, 0.5, E.out));
  setT($.rail, `scaleX(${prog(t, B(57) + 0.3, 7.2, E.inOut).toFixed(4)})`);
  CHAPTERS.forEach((_, i) => {
    const on = prog(t, B(CHAPTER_BEATS[i]), 0.35, E.out);
    const el = $["ch" + i];
    el.style.opacity = (0.28 + 0.72 * on).toFixed(3);
    el.style.borderColor = on > 0.5 ? "var(--accent2)" : "var(--hair)";
    el.style.background = on > 0.5 ? "rgba(20,44,173,0.35)" : "transparent";
    setT(el, `translateY(${(-14 * on).toFixed(1)}px)`);
  });

  const end = spring(t, B(75) + 0.2, 0.5, 0.85);
  const out = prog(t, B(79), FILM.DURATION - B(79), E.in);
  $.logo2.style.opacity = $.title2.style.opacity = (clamp(end * 1.4) * (1 - out)).toFixed(3);
  setT($.logo2, `scale(${(0.8 + 0.2 * end).toFixed(4)})`);
}
