/*! gitlab-custom-login-page | MIT | https://github.com/Ar4ikov/gitlab-custom-login-page
   Animated GitLab sign-in page: abstract background + random project logos with depth blur, grain
   and a cursor-driven focus pull. Injected into /users/sign_in by nginx sub_filter. No dependencies.

   Options (data-* attributes of the <script> tag, or window.LOGIN_SKIN before it loads):
     data-base     where the assets live                     default "/-/login-skin/"
     data-concept  "random" or a concept name               default "random"
     data-layouts  comma list of scatter,orbit,corners      default all three
     data-count    "min-max" logos per page load            default "15-20"
     data-grain    0..1 film grain strength                 default 0.38
   Logos come from <base>logos/manifest.json: {"logos":["a.png",...],"pinned":"pinned.png"}.
   The pinned logo (optional) is shown on every load, always sharp. */
(function () {
  'use strict';
  var script = document.currentScript;
  var BASE = (script && script.getAttribute('data-base')) || '/-/login-skin/';

  var LOGOS = [], ALWAYS = null, LOGO_DIR = 'logos/';   // filled from logos/manifest.json

  // Concepts: background art + layout + base colour. `pos`/`size` are CSS background-position/size.
  var CONCEPTS = {
    nebula:  { title: 'Peach nebula', bg: 'nebula.webp',  pos: 'center bottom', size: '118% 70%', base: '#08060d' },
    aurora:  { title: 'Aurora',                bg: 'aurora.webp', pos: 'center 78%', size: 'cover',   base: '#05070f' },
    glass:   { title: 'Liquid glass',         bg: 'glass.webp',   pos: 'center',        size: 'cover', o: 0.5, base: '#09070c' },
    orb:     { title: 'Grain orb',       bg: 'orb.webp',      pos: 'center 38%',    size: 'auto 96vh', o: 0.8, base: '#07060b' },
    ink:     { title: 'Ink',               bg: 'ink.webp',      pos: 'center bottom', size: 'auto 64vh', o: 0.5, fade: '100% 64vh', base: '#07060a' },
    voxels:  { title: 'Voxel drift',      bg: 'voxels.webp',    pos: 'center 36%',    size: 'auto 128vh', o: 0.42, base: '#06080b' },
    topo:    { title: 'Contour lines',              bg: 'topo.webp',     pos: 'center bottom', size: 'cover',    base: '#08070c' },
    prism:   { title: 'Prism',                bg: 'prism.webp',   pos: 'center',        size: 'cover', o: 0.42, base: '#08080d' }
  };
  var DEFAULTS = { concept: 'random', count: [15, 20], grain: 0.38, layouts: null };

  var rnd = Math.random, PI = Math.PI;
  function rr(a, b) { return a + rnd() * (b - a); }
  function shuffle(a) { for (var i = a.length - 1; i > 0; i--) { var j = (rnd() * (i + 1)) | 0, t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function el(tag, cls, parent) { var e = document.createElement(tag); if (cls) e.className = cls; if (parent) parent.appendChild(e); return e; }
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  var BLURS = [0, 4.5, 13];   // px: sharp / mid / heavy layer of every logo (cross-faded for focus pulls)
  function filtersSvg() {
    var s = '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>';
    BLURS.forEach(function (b, i) {
      var k = 0.26 + i * 0.26;                                   // grain contrast grows with blur
      s += '<filter id="ls-f' + i + '" x="-70%" y="-70%" width="240%" height="240%" color-interpolation-filters="sRGB">' +
        (b ? '<feGaussianBlur in="SourceGraphic" stdDeviation="' + b + '" result="b"/>' : '<feOffset in="SourceGraphic" result="b"/>') +
        '<feTurbulence type="fractalNoise" baseFrequency="' + (0.95 - i * 0.12) + '" numOctaves="2" seed="' + (7 + i * 13) + '" result="n"/>' +
        '<feColorMatrix in="n" type="saturate" values="0" result="g"/>' +
        '<feComponentTransfer in="g" result="gn">' +
        '<feFuncR type="linear" slope="' + (k * 3.2) + '" intercept="' + (0.5 - k * 1.6) + '"/>' +
        '<feFuncG type="linear" slope="' + (k * 3.2) + '" intercept="' + (0.5 - k * 1.6) + '"/>' +
        '<feFuncB type="linear" slope="' + (k * 3.2) + '" intercept="' + (0.5 - k * 1.6) + '"/>' +
        '<feFuncA type="discrete" tableValues="1 1"/></feComponentTransfer>' +
        '<feBlend in="gn" in2="b" mode="overlay" result="o"/>' +
        '<feComposite in="o" in2="b" operator="in"/>' +
        '</filter>';
    });
    return s + '</defs></svg>';
  }

  var CSS = [
    'body.login-page{background:var(--ls-base,#08060d) !important;background-image:none !important}',
    'body.login-page::before,body.login-page::after{display:none !important}',
    'body.login-page>*:not(#ls-root){position:relative;z-index:1}',
    '#ls-root{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none;contain:strict;background:var(--ls-base,#08060d)}',
    '#ls-root .ls-bg{position:absolute;inset:0;background-repeat:no-repeat;opacity:0;transform:scale(1.06);transition:opacity 1.8s ease,transform 3.2s cubic-bezier(.2,.7,.2,1)}',
    '#ls-root.ls-on .ls-bg{opacity:var(--ls-bg-o,.92);transform:none}',
    '#ls-root .ls-stage{position:absolute;inset:0}',
    '#ls-root .ls-item{position:absolute;left:0;top:0;will-change:transform,opacity;opacity:0;' +
      'transform:translate3d(var(--x),var(--y),0) translate(-50%,-50%) translate(calc(var(--mx,0)*var(--p)*1px),calc(var(--my,0)*var(--p)*1px)) scale(.72) rotate(calc(var(--r) - 14deg));' +
      'transition:opacity 1.1s ease var(--dl),transform 1.5s cubic-bezier(.16,.9,.24,1) var(--dl)}',
    '#ls-root.ls-on .ls-item{opacity:var(--o);transform:translate3d(var(--x),var(--y),0) translate(-50%,-50%) translate(calc(var(--mx,0)*var(--p)*1px),calc(var(--my,0)*var(--p)*1px)) scale(1) rotate(var(--r))}',
    '#ls-root.ls-settled .ls-item{transition:transform .5s ease-out}',
    '#ls-root .ls-float{animation:ls-float var(--fd) ease-in-out var(--fdl) infinite alternate}',
    '#ls-root .ls-float{position:relative;width:var(--s);height:var(--s)}',
    '#ls-root .ls-item img{position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:contain;-webkit-user-drag:none;user-select:none;will-change:opacity}',
    '#ls-root .ls-item.ls-tile img{border-radius:23%}',
    '@keyframes ls-float{from{transform:translate3d(0,0,0) rotate(0)}to{transform:translate3d(var(--fx),var(--fy),0) rotate(var(--fr))}}',
    '#ls-root .ls-grain{position:absolute;inset:-2px;opacity:var(--ls-grain,.5);mix-blend-mode:overlay;background-size:220px 220px}',
    '#ls-root .ls-vignette{position:absolute;inset:0;background:radial-gradient(ellipse 46% 52% at 50% 38%,var(--ls-base,#08060d) 0%,transparent 100%);opacity:.62}',
    '@media (prefers-reduced-motion:reduce){#ls-root .ls-float{animation:none}#ls-root .ls-item,#ls-root .ls-bg{transition-duration:.01s}}'
  ].join('\n');

  var NOISE = "url(\"data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter><rect width="220" height="220" filter="url(#n)"/></svg>') + "\")";

  function safeRect(W, H) {
    var m = document.querySelector('.login-page main.content') || document.querySelector('.login-page .container');
    var r = m && m.getBoundingClientRect();
    var cx = r && r.width > 100 ? r.left + r.width / 2 : W / 2, top = r && r.width > 100 ? Math.max(0, r.top) : H * 0.08;
    var w = Math.min(W, 540), h = Math.max(r ? r.height : 0, 500);     // the form is mounted later, <main> may still be short
    return { x0: cx - w / 2 - 26, x1: cx + w / 2 + 26, y0: Math.max(0, top - 110), y1: Math.min(H, top + h + 26) };
  }
  function hitsRect(x, y, rad, s) {
    var cx = Math.max(s.x0, Math.min(x, s.x1)), cy = Math.max(s.y0, Math.min(y, s.y1));
    var dx = x - cx, dy = y - cy; return dx * dx + dy * dy < rad * rad;
  }

  /* each layout returns [{x,y,size,z,rot}] ; z in 0..1 (0 far, 1 near), focus plane at ~0.45 */
  var LAYOUTS = {
    scatter: function (n, W, H, u, safe) {
      var out = [], i, tries, relax;
      for (i = 0; i < n; i++) {
        var z = i === 0 ? 0.47 : Math.pow(rnd(), 0.85);
        var size = (i === 0 ? rr(15, 18) : 4.5 + z * z * 17 + rr(0, 2.5)) * u;
        for (tries = 0, relax = 1; tries < 400; tries++) {
          if (tries % 60 === 59) relax *= 0.85;
          var x = rr(-0.03, 1.03) * W, y = rr(-0.04, 1.04) * H, rad = size * 0.56, ok = true;
          if (i === 0) { x = rr(0.08, 0.92) * W; y = rr(0.12, 0.88) * H; }
          if (hitsRect(x, y, rad * (z > 0.8 ? 0.55 : 1.05), safe)) continue;
          for (var k = 0; k < out.length; k++) {
            var o = out[k], d = Math.hypot(o.x - x, o.y - y);
            if (d < (o.size * 0.56 + rad) * 0.92 * relax) { ok = false; break; }
          }
          if (ok) break;
        }
        out.push({ x: x, y: y, size: size, z: z, rot: i === 0 ? rr(-9, 9) : rr(-34, 34) });
      }
      return out;
    },
    orbit: function (n, W, H, u, safe) {
      var cx = (safe.x0 + safe.x1) / 2, cy = (safe.y0 + safe.y1) / 2, out = [];
      var rx0 = (safe.x1 - safe.x0) / 2, ry0 = (safe.y1 - safe.y0) / 2;
      var rings = [{ k: 1.32, z: 0.46, s: 9.5 }, { k: 1.95, z: 0.72, s: 13.5 }, { k: 2.7, z: 0.98, s: 20 }];
      var per = [Math.round(n * 0.3), Math.round(n * 0.38)]; per.push(n - per[0] - per[1]);
      var idx = 0;
      rings.forEach(function (rg, ri) {
        var a0 = rr(0, 2 * PI), m = per[ri];
        for (var j = 0; j < m; j++, idx++) {
          var a = a0 + (j + rr(-0.22, 0.22)) * 2 * PI / m;
          var kx = rg.k * rr(0.94, 1.08) * Math.max(1, (W / H) * 0.62), ky = rg.k * rr(0.94, 1.08);
          out.push({ x: cx + Math.cos(a) * rx0 * kx, y: cy + Math.sin(a) * ry0 * ky, size: rg.s * rr(0.8, 1.15) * u,
                     z: Math.min(1, rg.z + rr(-0.05, 0.05)), rot: rr(-26, 26) });
        }
      });
      // the always-on logo: sharp ring, left or right of the form
      var side = rnd() < 0.5 ? -1 : 1;
      out[0] = { x: cx + side * rx0 * rr(1.75, 2.05), y: cy + ry0 * rr(-0.25, 0.45), size: rr(15, 18) * u, z: 0.47, rot: rr(-8, 8) };
      return out;
    },
    corners: function (n, W, H, u, safe) {
      var out = [], flip = rnd() < 0.5;
      var A = flip ? [0, H] : [0, 0], B = flip ? [W, 0] : [W, H];
      for (var i = 0; i < n; i++) {
        var c = i % 2 ? A : B, t = Math.pow(rnd(), 0.7);          // t: distance from the corner
        var ang = rr(0, PI / 2), dist = (0.06 + t * 0.62) * Math.min(W, H) * 1.05;
        var sx = c[0] === 0 ? 1 : -1, sy = c[1] === 0 ? 1 : -1;
        var z = 1 - t * 0.62 + rr(-0.06, 0.06);
        out.push({ x: c[0] + sx * Math.cos(ang) * dist * (W / H > 1.3 ? 1.35 : 1), y: c[1] + sy * Math.sin(ang) * dist,
                   size: (6 + (1 - t) * 17 + rr(0, 2)) * u, z: Math.max(0.2, Math.min(1, z)), rot: rr(-30, 30) });
      }
      var s2 = rnd() < 0.5 ? A : B;
      out[0] = { x: s2[0] === 0 ? W * rr(0.13, 0.2) : W * rr(0.8, 0.87), y: s2[1] === 0 ? H * rr(0.2, 0.3) : H * rr(0.68, 0.78),
                 size: rr(15, 18) * u, z: 0.47, rot: rr(-8, 8) };
      return out.filter(function (o, i) { return i === 0 || !hitsRect(o.x, o.y, o.size * 0.5, safe); });
    }
  };

  var FOCUS0 = 0.46, items = [], focus = { z: FOCUS0, target: FOCUS0 };
  var root, state = {};
  function render(opts) {
    var cfg = {}, k;
    for (k in DEFAULTS) cfg[k] = DEFAULTS[k];
    for (k in (opts || {})) cfg[k] = opts[k];
    if (cfg.concept === 'random') { var ks = Object.keys(CONCEPTS); cfg.concept = ks[(rnd() * ks.length) | 0]; }
    var C = CONCEPTS[cfg.concept] || CONCEPTS.nebula;
    var names = (cfg.layouts || Object.keys(LAYOUTS)).filter(function (x) { return LAYOUTS[x]; });
    if (!names.length) names = Object.keys(LAYOUTS);
    var layout = LAYOUTS[cfg.layout] ? cfg.layout : names[(rnd() * names.length) | 0];
    state = { cfg: cfg, concept: cfg.concept, layout: layout };

    if (!document.getElementById('ls-style')) { var st = el('style', null, document.head); st.id = 'ls-style'; st.textContent = CSS; }
    if (root) root.remove();
    root = el('div'); root.id = 'ls-root'; root.setAttribute('aria-hidden', 'true');
    root.className = 'ls-' + layout;
    root.innerHTML = filtersSvg();
    document.body.style.setProperty('--ls-base', C.base);
    root.style.setProperty('--ls-base', C.base);
    root.style.setProperty('--ls-grain', cfg.grain);

    var W = window.innerWidth, H = window.innerHeight, u = Math.min(W, H * 1.25) / 100, mobile = W < 720;
    var bg = el('div', 'ls-bg', root);
    bg.style.backgroundPosition = C.pos; bg.style.backgroundSize = C.size;
    root.style.setProperty('--ls-bg-o', C.o || 0.92);
    var pre = new Image(); pre.onload = function () { bg.style.backgroundImage = 'url("' + pre.src + '")'; }; pre.src = BASE + 'bg/' + (cfg.bg || C.bg);
    if (C.fade) { var ms = bg.style; ms.webkitMaskImage = ms.maskImage = 'linear-gradient(to top,#000 45%,transparent 97%)'; ms.webkitMaskSize = ms.maskSize = C.fade; ms.webkitMaskPosition = ms.maskPosition = C.pos; ms.webkitMaskRepeat = ms.maskRepeat = 'no-repeat'; }
    el('div', 'ls-vignette', root);

    var stage = el('div', 'ls-stage', root), plane = stage;
    var n = Math.round(rr(cfg.count[0], cfg.count[1])); if (mobile) n = Math.round(n * 0.55);
    var picks = (ALWAYS ? [ALWAYS] : []).concat(shuffle(LOGOS.slice()).slice(0, n - (ALWAYS ? 1 : 0)));
    var pts = picks.length ? LAYOUTS[layout](picks.length, W, H, u, safeRect(W, H)).slice(0, picks.length) : [];
    items = [];
    var order = shuffle(pts.map(function (_, i) { return i; }));       // random appearance sequence
    pts.forEach(function (p, i) {
      var L = picks[i];
      var it = el('div', 'ls-item' + (L.t ? '' : ' ls-tile'), plane), fl = el('div', 'ls-float', it), imgs = [];
      for (var q = BLURS.length - 1; q >= 0; q--) {
        var img = el('img', null, fl); img.alt = ''; img.decoding = 'async'; img.src = BASE + LOGO_DIR + L.f;
        img.style.filter = 'url(#ls-f' + q + ')'; imgs[q] = img;
      }
      if (L.always) it.className += ' ls-always';
      items.push({ z: p.z, imgs: imgs, fl: fl, it: it, t: -1, cx: 0, cy: 0, r: p.size / 2 });
      var s = it.style;
      s.setProperty('--x', p.x.toFixed(1) + 'px'); s.setProperty('--y', p.y.toFixed(1) + 'px');
      s.setProperty('--s', Math.max(28, p.size).toFixed(1) + 'px'); s.setProperty('--r', p.rot.toFixed(1) + 'deg');
      s.setProperty('--o', '1');
      s.setProperty('--p', ((p.z - 0.45) * 46).toFixed(1));
      s.setProperty('--dl', (0.25 + order.indexOf(i) * 0.085 + rr(0, 0.06)).toFixed(2) + 's');
      s.zIndex = L.always ? '200' : String(Math.round(p.z * 100));
      fl.style.setProperty('--fd', rr(9, 19).toFixed(1) + 's'); fl.style.setProperty('--fdl', (-rr(0, 12)).toFixed(1) + 's');
      var amp = 4 + p.z * 16;
      fl.style.setProperty('--fx', rr(-amp, amp).toFixed(1) + 'px'); fl.style.setProperty('--fy', rr(-amp, amp).toFixed(1) + 'px');
      fl.style.setProperty('--fr', rr(-5, 5).toFixed(1) + 'deg');
    });
    var grain = el('div', 'ls-grain', root); grain.style.backgroundImage = NOISE;

    document.body.insertBefore(root, document.body.firstChild);
    var rOn = root, on = function () { if (rOn === root) root.classList.add('ls-on'); };
    requestAnimationFrame(function () { requestAnimationFrame(on); }); setTimeout(on, 250);   // timer fallback: rAF is paused in background tabs
    // drop logos covered by the sign-in form by more than a quarter; the always-on logo is moved instead
    var sr = safeRect(W, H);
    function cover(r) {
      var ix = Math.min(r.right, sr.x1) - Math.max(r.left, sr.x0), iy = Math.min(r.bottom, sr.y1) - Math.max(r.top, sr.y0);
      return ix > 0 && iy > 0 ? (ix * iy) / Math.max(1, r.width * r.height) : 0;
    }
    var scx = (sr.x0 + sr.x1) / 2, scy = (sr.y0 + sr.y1) / 2;
    items = items.filter(function (o) {
      var r = o.it.getBoundingClientRect();
      if (cover(r) < 0.25) return true;
      var w = r.width, h = r.height, x = r.left + w / 2, y = r.top + h / 2, sz = w / 0.72;
      if (o.it.classList.contains('ls-always')) {
        var below = H - sr.y1 > sz * 0.9;                                // free strip under the form (phones) or beside it
        x = below ? rr(0.25, 0.75) * W : (sr.x0 > sz ? sr.x0 - sz * 0.75 : Math.min(W - sz * 0.5, sr.x1 + sz * 0.75));
        y = below ? Math.min(H - sz * 0.55, sr.y1 + sz * 0.62) : rr(0.3, 0.6) * H;
      } else {
        // slide the logo away from the form centre until it is clear; give up if it leaves the screen
        var dx = x - scx, dy = (y - scy) * 0.6, d = Math.hypot(dx, dy) || 1, ok = false;
        dx /= d; dy /= d;
        for (var st = 0; st < 40 && !ok; st++) {
          x += dx * 18; y += dy * 18;
          ok = cover({ left: x - w / 2, right: x + w / 2, top: y - h / 2, bottom: y + h / 2, width: w, height: h }) < 0.08;
        }
        if (!ok || x < -w * 0.3 || x > W + w * 0.3 || y < -h * 0.3 || y > H + h * 0.3) { o.it.remove(); return false; }
      }
      o.it.style.setProperty('--x', x.toFixed(1) + 'px'); o.it.style.setProperty('--y', y.toFixed(1) + 'px');
      return true;
    });
    focus.z = focus.target = FOCUS0; applyFocus(true);
    var r0 = root; setTimeout(function () { if (r0 === root) { root.classList.add('ls-settled'); measure(); } }, 4200);
    return state;
  }

  /* ---- focus pull: the focal plane glides to the depth of the logo nearest to the cursor ---- */
  var fraf = 0, mraf = 0, mouse = null;
  function clamp(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function measure() {
    items.forEach(function (o) { var r = o.it.getBoundingClientRect(); o.cx = r.left + r.width / 2; o.cy = r.top + r.height / 2; });
  }
  function applyFocus(force) {
    items.forEach(function (o) {
      var t = clamp(Math.abs(o.z - focus.z) * 2.1);                 // 0 sharp .. 1 fully defocused
      if (!force && Math.abs(t - o.t) < 0.004) return;
      o.t = t;
      o.imgs[0].style.opacity = clamp(1 - t * 2.4).toFixed(3);
      o.imgs[1].style.opacity = clamp(Math.min(t * 3.4, 2.6 - t * 2.6)).toFixed(3);
      o.imgs[2].style.opacity = clamp(t * 2.6 - 1.2).toFixed(3);
      o.fl.style.opacity = (1 - t * 0.42).toFixed(3);
    });
  }
  function focusTick() {
    fraf = 0;
    var d = focus.target - focus.z;
    focus.z += d * 0.07;                                            // slow, lens-like glide
    if (Math.abs(d) < 0.002) focus.z = focus.target;
    applyFocus(false);
    if (focus.z !== focus.target) fraf = requestAnimationFrame(focusTick);
  }
  function retarget() {
    var best = null, bd = 1e9;
    if (mouse) items.forEach(function (o) {
      var d = Math.hypot(o.cx - mouse.x, o.cy - mouse.y) - o.r;     // distance to the logo's edge
      if (d < bd) { bd = d; best = o; }
    });
    var reach = Math.min(window.innerWidth, window.innerHeight) * 0.16;
    focus.target = best && bd < reach ? best.z : FOCUS0;
    if (!fraf && focus.z !== focus.target) fraf = requestAnimationFrame(focusTick);
  }
  if (!reduced) {
    window.addEventListener('mousemove', function (e) {
      mouse = { x: e.clientX, y: e.clientY };
      if (mraf || !root) return;
      mraf = requestAnimationFrame(function () {
        mraf = 0;
        if (!mouse || !root) return;
        root.style.setProperty('--mx', ((mouse.x / window.innerWidth) * 2 - 1).toFixed(3));
        root.style.setProperty('--my', ((mouse.y / window.innerHeight) * 2 - 1).toFixed(3));
        if (!items.length || !items[0].cx) measure();
        retarget();
      });
    }, { passive: true });
    document.addEventListener('mouseleave', function () { mouse = null; retarget(); });
  }
  var rt = 0, lw = window.innerWidth;
  window.addEventListener('resize', function () {
    clearTimeout(rt); rt = setTimeout(function () { if (Math.abs(window.innerWidth - lw) > 40) { lw = window.innerWidth; render(state.cfg); } }, 350);
  });

  window.LoginSkin = { render: render, concepts: CONCEPTS, layouts: Object.keys(LAYOUTS), state: function () { return state; } };
  var auto = window.LOGIN_SKIN || {};
  function attr(n) { return script && script.getAttribute('data-' + n); }
  if (attr('concept')) auto.concept = attr('concept');
  if (attr('layouts')) auto.layouts = attr('layouts').split(',').map(function (x) { return x.trim(); });
  if (attr('grain')) auto.grain = parseFloat(attr('grain'));
  if (attr('count')) { var c = attr('count').split('-').map(Number); if (c[0] > 0) auto.count = [c[0], c[1] || c[0]]; }
  function setLogos(m, dir) {
    if (dir) LOGO_DIR = dir;
    LOGOS = ((m && m.logos) || []).map(function (x) { return typeof x === 'string' ? { f: x } : x; });
    ALWAYS = m && m.pinned ? { f: m.pinned, t: 1, always: 1 } : null;
  }
  function loadLogos() {
    if (auto.logos) { setLogos(auto); return Promise.resolve(); }
    return fetch(BASE + 'logos/manifest.json', { cache: 'no-cache' })
      .then(function (r) { return r.ok ? r.json() : {}; }).then(setLogos, function () { setLogos({}); });
  }
  var ready = loadLogos();
  window.LoginSkin.ready = ready;
  window.LoginSkin.setLogos = setLogos;
  function boot() { if (auto.manual) return; if (document.body && /login-page/.test(document.body.className)) ready.then(function () { render(auto); }); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
