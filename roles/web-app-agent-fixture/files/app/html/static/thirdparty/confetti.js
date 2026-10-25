// nocheck: mirrored-unit-test - seeded vendored fixture, not role logic
(function (global) {
  function burst(count) {
    var pieces = [];
    for (var i = 0; i < (count || 80); i++) {
      pieces.push({
        x: Math.random() * global.innerWidth,
        y: -20,
        r: 4 + Math.random() * 6,
        vx: -2 + Math.random() * 4,
        vy: 2 + Math.random() * 4,
        hue: Math.floor(Math.random() * 360)
      });
    }
    return pieces;
  }

  function render(ctx, pieces) {
    pieces.forEach(function (p) {
      ctx.fillStyle = "hsl(" + p.hue + ",90%,60%)";
      ctx.fillRect(p.x, p.y, p.r, p.r);
      p.x += p.vx;
      p.y += p.vy;
    });
  }

  global.Confetti = { burst: burst, render: render };
})(window);
