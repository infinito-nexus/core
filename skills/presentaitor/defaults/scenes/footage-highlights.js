film({ W: 1920, H: 1080, BPM: 110.0, BEATS: 140 });

const HL = [
  { k: "h0", x: 676, y: 409, w: 568, h: 24, t0: 21.4, t1: 28.8, cy: 340, step: "SPAM FILTER", title: "X-Spam-Status: No", sub: "Checked by the spam filter, let through." },
  { k: "h1", x: 676, y: 427, w: 568, h: 206, t0: 29.0, t1: 46.0, cy: 440, step: "DKIM", title: "Two signatures", sub: "Ed25519 and RSA, for d=infinito.test.\nOther mail servers can verify it." },
  { k: "h2", x: 676, y: 649, w: 568, h: 44, t0: 46.2, t1: 55.0, cy: 590, step: "ANTIVIRUS", title: "X-Virus-Scanned", sub: "clamav-milter · status: Clean" },
];
const RECAP = ["Spam checked", "DKIM signed", "Virus scanned"];
const R0 = 55.0, R1 = 64.8;
const NEXT = B(130);

function build(stage) {
  stage.innerHTML = `
    <div class="full" data-k="world">
      <div class="abs pill" data-k="kick" style="right:60px;top:960px"><span class="t kicker">04 · RECEIVE</span></div>

      <div class="abs pill" data-k="lt" style="left:60px;top:900px;padding:18px 30px">
        <div class="t" style="font-size:44px;font-weight:800;letter-spacing:-0.02em">Maria Nexus</div><br>
        <div class="t mono" style="font-size:24px;color:var(--ink2);margin-top:6px">maria@infinito.test · signs in</div>
      </div>

      <div class="abs pill" data-k="cap1" style="left:60px;top:940px"><span class="t" style="font-size:36px;font-weight:700">Alejandro's mail is already in her inbox</span></div>
      <div class="abs pill" data-k="cap2" style="left:60px;top:940px"><span class="t" style="font-size:36px;font-weight:700">Message headers: what happened on the way</span></div>

      ${HL.map((h) => `
        <div class="hl" data-k="${h.k}" style="left:${h.x}px;top:${h.y}px;width:${h.w}px;height:${h.h}px"></div>
        <div class="abs" data-k="${h.k}l" style="left:${h.x + h.w}px;top:${h.y + Math.min(h.h, 40) / 2 - 1.5}px;width:${1300 - h.x - h.w}px;height:3px;background:var(--accent2);transform-origin:0 50%"></div>
        <div class="call" data-k="${h.k}c" style="left:1300px;top:${h.cy}px">
          <div class="t kicker" style="font-size:24px">${h.step}</div><br>
          <div class="t mono" style="font-size:34px;margin-top:10px">${h.title}</div>
          ${h.sub.split("\n").map((s) => `<div style="font-size:26px;font-weight:500;color:var(--ink2);margin-top:8px;line-height:1.3">${s}</div>`).join("")}
        </div>`).join("")}

      <div class="call" data-k="rc" style="left:1300px;top:400px">
        <div class="t kicker" style="font-size:24px">ALL AUTOMATIC</div>
        ${RECAP.map((r, i) => `
          <div data-k="rc${i}" class="row" style="gap:20px;margin-top:20px">
            <svg width="44" height="44" viewBox="0 0 64 64"><circle cx="32" cy="32" r="29" fill="var(--accent)" stroke="var(--accent2)" stroke-width="3"/><path data-k="rcp${i}" d="M19 33 L28 42 L46 23" fill="none" stroke="var(--ink)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <div class="t" style="font-size:38px;font-weight:800">${r}</div>
          </div>`).join("")}
      </div>

      <div class="full center" data-k="end" style="background:var(--bg);flex-direction:column;gap:26px">
        <div class="mask" style="height:44px"><div data-k="nextK" class="t kicker">NEXT</div></div>
        <div class="mask" style="height:130px"><div data-k="nextT" class="t" style="font-size:104px;font-weight:800;letter-spacing:-0.04em">05 · Filters</div></div>
        <img data-k="logo" src="${ASSETS.img.logo}" style="width:120px;height:120px;border-radius:50%;margin-top:30px">
      </div>
    </div>
    ${scanLayer(0.06)}
    ${vignetteLayer(0.5)}
    ${grainLayer(0.08)}`;
  collect(stage);
}

function win(t, a, b, fi = 0.35, fo = 0.3) {
  return prog(t, a, fi, E.out) * (1 - prog(t, b - fo, fo, E.in));
}

function fade(el, p, dy = 16) {
  el.style.opacity = p.toFixed(3);
  setT(el, `translateY(${(dy * (1 - p)).toFixed(1)}px)`);
}

function apply(t) {
  grain(t);
  scan(t, (4 * Math.round(10 * FILM.DURATION)) / FILM.DURATION);

  fade($.kick, win(t, 0.3, NEXT));
  fade($.lt, win(t, 2.8, 7.6));
  fade($.cap1, win(t, 8.6, 13.6));
  fade($.cap2, win(t, 15.2, 20.8));

  HL.forEach((h) => {
    const p = win(t, h.t0, h.t1);
    $[h.k].style.opacity = p.toFixed(3);
    setT($[h.k], `scaleX(${(0.96 + 0.04 * p).toFixed(4)})`);
    const lp = prog(t, h.t0 + 0.2, 0.35, E.out) * (1 - prog(t, h.t1 - 0.3, 0.3, E.in));
    setT($[h.k + "l"], `scaleX(${lp.toFixed(4)})`);
    fade($[h.k + "c"], win(t, h.t0 + 0.35, h.t1));
  });

  const rp = win(t, R0, R1);
  HL.forEach((h, i) => {
    if (t >= R0) {
      const p = rp * prog(t, R0 + 0.3 + i * 0.6, 0.3, E.out);
      $[h.k].style.opacity = p.toFixed(3);
      setT($[h.k], "none");
    }
  });
  fade($.rc, rp);
  RECAP.forEach((_, i) => {
    const a = R0 + 0.3 + i * 0.6;
    $["rc" + i].style.opacity = prog(t, a, 0.3, E.out).toFixed(3);
    drawPath($["rcp" + i], prog(t, a + 0.1, 0.35, E.out));
  });

  const push = prog(t, NEXT, 0.55, E.inOut);
  $.end.style.opacity = t >= NEXT ? "1" : "0";
  setT($.end, `translateX(${(1920 * (1 - push)).toFixed(1)}px)`);
  rise($.nextK, prog(t, NEXT + 0.3, 0.5, E.out));
  rise($.nextT, prog(t, NEXT + 0.45, 0.55, E.out));
  const tail = B(138);
  const out = 1 - prog(t, tail, FILM.DURATION - tail, E.in);
  $.logo.style.opacity = (prog(t, NEXT + 0.8, 0.6, E.out) * out).toFixed(3);
  $.nextT.style.opacity = $.nextK.style.opacity = out.toFixed(3);
}
