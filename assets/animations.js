/* Battle Cats Shop — Shared Animation Enhancers */
(function () {
  'use strict';

  // ── 1. Scroll Reveal ─────────────────────────────────────────
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var siblings = Array.from(entry.target.parentNode.children);
          var idx = siblings.indexOf(entry.target);
          setTimeout(function () {
            entry.target.classList.remove('anim-hidden');
            entry.target.classList.add('anim-visible');
          }, idx * 75);
          io.unobserve(entry.target);
        });
      },
      { threshold: 0.08, rootMargin: '0px 0px -30px 0px' }
    );

    document.querySelectorAll('.card, .trust-card, .review-card').forEach(function (el) {
      el.classList.add('anim-hidden');
      io.observe(el);
    });
  }

  // ── 2. Cart badge bounce ──────────────────────────────────────
  var badge = document.getElementById('cartCount');
  if (badge) {
    new MutationObserver(function () {
      badge.classList.remove('bounce');
      void badge.offsetWidth;
      badge.classList.add('bounce');
      badge.addEventListener('animationend', function () {
        badge.classList.remove('bounce');
      }, { once: true });
    }).observe(badge, { characterData: true, childList: true, subtree: true });
  }

  // ── 3. Timer digit flip (index.html countdown) ───────────────
  document.querySelectorAll('.timer-num').forEach(function (el) {
    new MutationObserver(function () {
      el.classList.remove('flip');
      void el.offsetWidth;
      el.classList.add('flip');
      el.addEventListener('animationend', function () {
        el.classList.remove('flip');
      }, { once: true });
    }).observe(el, { characterData: true, childList: true, subtree: true });
  });

  // ── 4. Ripple effect on buttons ───────────────────────────────
  // Uses a wrapper span so overflow:hidden doesn't clip button's own box-shadow
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.btn, .test-button');
    if (!btn || btn.disabled) return;

    if (window.getComputedStyle(btn).position === 'static') {
      btn.style.position = 'relative';
    }

    var wrap = btn.querySelector('.bc-ripple-wrap');
    if (!wrap) {
      wrap = document.createElement('span');
      wrap.className = 'bc-ripple-wrap';
      wrap.style.cssText = 'position:absolute;inset:0;overflow:hidden;border-radius:inherit;pointer-events:none;z-index:0;';
      btn.insertBefore(wrap, btn.firstChild);
    }

    var rect = btn.getBoundingClientRect();
    var size = Math.max(rect.width, rect.height) * 1.8;
    var r = document.createElement('span');
    r.style.cssText = [
      'position:absolute',
      'width:' + size + 'px',
      'height:' + size + 'px',
      'left:' + (e.clientX - rect.left - size / 2) + 'px',
      'top:' + (e.clientY - rect.top - size / 2) + 'px',
      'border-radius:50%',
      'background:rgba(255,255,255,0.2)',
      'transform:scale(0)',
      'animation:ripple 0.55s ease-out forwards',
      'pointer-events:none',
    ].join(';');

    wrap.appendChild(r);
    r.addEventListener('animationend', function () { r.remove(); }, { once: true });
  });

  // ── 5. Toast notifications (replaces alert) ───────────────────
  var _native = window.alert.bind(window);

  function injectToastCSS() {
    if (document.getElementById('bc-toast-css')) return;
    var s = document.createElement('style');
    s.id = 'bc-toast-css';
    s.textContent = [
      '#bc-toasts{position:fixed;top:80px;right:20px;display:flex;flex-direction:column;gap:10px;z-index:99999;pointer-events:none;}',
      '.bc-t{background:rgba(17,8,38,0.96);backdrop-filter:blur(18px);border:1px solid rgba(139,61,255,0.45);',
      'color:#fff;padding:14px 20px;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.45);',
      "font-family:'Kanit',sans-serif;font-size:15px;min-width:220px;max-width:360px;",
      'pointer-events:auto;animation:bcIn .28s ease-out forwards;line-height:1.5;}',
      '.bc-t.out{animation:bcOut .28s ease-in forwards;}',
      '@keyframes bcIn{from{transform:translateX(120px);opacity:0}to{transform:translateX(0);opacity:1}}',
      '@keyframes bcOut{from{transform:translateX(0);opacity:1}to{transform:translateX(120px);opacity:0}}',
    ].join('');
    document.head.appendChild(s);
  }

  function showToast(msg) {
    injectToastCSS();
    var wrap = document.getElementById('bc-toasts');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'bc-toasts';
      document.body.appendChild(wrap);
    }
    var t = document.createElement('div');
    t.className = 'bc-t';
    t.textContent = msg;
    wrap.appendChild(t);
    setTimeout(function () {
      t.classList.add('out');
      t.addEventListener('animationend', function () { t.remove(); }, { once: true });
    }, 3200);
  }

  window.alert = function (msg) {
    if (typeof msg === 'string' && document.readyState !== 'loading') {
      showToast(msg);
    } else {
      _native(msg);
    }
  };


  // ── 6. Floating particle system ──────────────────────────────
  (function () {
    var container = document.createElement('div');
    container.id = 'bc-particles';
    document.body.appendChild(container);

    var COLORS = [
      'rgba(124,58,237,', // purple
      'rgba(244,63,94,',  // rose
      'rgba(79,209,255,', // cyan
      'rgba(255,216,78,', // yellow
    ];

    function spawn() {
      var p    = document.createElement('div');
      var size = Math.random() * 5 + 2;
      var x    = Math.random() * 100;
      var dur  = Math.random() * 10 + 8;
      var del  = Math.random() * 12;
      var col  = COLORS[Math.floor(Math.random() * COLORS.length)];
      var opa  = (Math.random() * 0.4 + 0.2).toFixed(2);

      p.style.cssText = [
        'position:absolute',
        'width:'    + size + 'px',
        'height:'   + size + 'px',
        'left:'     + x    + '%',
        'bottom:-8px',
        'border-radius:50%',
        'background:' + col + opa + ')',
        'box-shadow:0 0 ' + (size * 2) + 'px ' + col + '0.5)',
        'animation:bc-float-up ' + dur + 's ' + del + 's ease-in infinite',
      ].join(';');
      container.appendChild(p);
    }

    // Only spawn if user has no motion preference
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      for (var i = 0; i < 28; i++) spawn();
    }
  })();

  // ── 7. Mouse parallax on hero ─────────────────────────────────
  (function () {
    var hero = document.querySelector('.hero');
    if (!hero) return;

    // Inject parallax layer
    var layer = document.createElement('div');
    layer.className = 'hero-parallax';
    hero.appendChild(layer);

    var tX = 0, tY = 0, cX = 0, cY = 0;

    document.addEventListener('mousemove', function (e) {
      tX = (e.clientX / window.innerWidth  - 0.5) * 22;
      tY = (e.clientY / window.innerHeight - 0.5) * 12;
    });

    // Smooth lerp
    (function lerp() {
      cX += (tX - cX) * 0.06;
      cY += (tY - cY) * 0.06;
      layer.style.transform = 'translate(' + cX.toFixed(2) + 'px,' + cY.toFixed(2) + 'px)';
      requestAnimationFrame(lerp);
    })();
  })();

  // ── 8. Section title scroll reveal ───────────────────────────
  (function () {
    if (!('IntersectionObserver' in window)) return;
    var stIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add('st-visible');
        stIO.unobserve(e.target);
      });
    }, { threshold: 0.2 });

    document.querySelectorAll('.section-title').forEach(function (el) {
      stIO.observe(el);
    });
  })();

  // ── 9. Price counter pop on card enter viewport ───────────────
  (function () {
    if (!('IntersectionObserver' in window)) return;
    var pcIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var price = e.target.querySelector('.price-now');
        if (price) {
          price.classList.remove('popped');
          void price.offsetWidth;
          price.classList.add('popped');
          price.addEventListener('animationend', function () {
            price.classList.remove('popped');
          }, { once: true });
        }
        pcIO.unobserve(e.target);
      });
    }, { threshold: 0.5 });

    document.querySelectorAll('.card').forEach(function (el) {
      pcIO.observe(el);
    });
  })();

})();
