/* Battle Cats Shop — Mobile Navigation */
(function () {
  'use strict';

  var BP = 768;

  /* ── Inject styles fresh (bypass cache) ─────────────────────── */
  function injectCSS() {
    if (document.getElementById('bc-nav-css')) return;
    var s = document.createElement('style');
    s.id = 'bc-nav-css';
    s.textContent = [
      /* hamburger button */
      '.hamburger{display:none;flex-direction:column;justify-content:center;align-items:center;',
      'gap:5px;background:rgba(255,255,255,0.07);border:1px solid rgba(124,58,237,0.45);',
      'border-radius:10px;width:40px;height:40px;cursor:pointer;padding:0;flex-shrink:0;',
      'transition:background 0.18s;}',
      '.hamburger:hover{background:rgba(124,58,237,0.22);}',
      '.hamburger span{display:block;width:18px;height:2px;background:#C4B5FD;border-radius:2px;',
      'transition:transform 0.25s ease,opacity 0.25s ease;pointer-events:none;}',
      '.hamburger.open span:nth-child(1){transform:translateY(7px) rotate(45deg);}',
      '.hamburger.open span:nth-child(2){opacity:0;transform:scaleX(0);}',
      '.hamburger.open span:nth-child(3){transform:translateY(-7px) rotate(-45deg);}',

      /* mobile dropdown panel */
      '#mobileNav{position:absolute;left:20px;right:20px;top:calc(100% + 4px);',
      'background:rgba(8,4,20,0.97);backdrop-filter:blur(28px);-webkit-backdrop-filter:blur(28px);',
      'border:1px solid rgba(124,58,237,0.35);border-radius:18px;padding:10px 10px 14px;',
      'z-index:999;box-shadow:0 20px 60px rgba(0,0,0,0.6),0 0 0 1px rgba(124,58,237,0.08)inset;',
      'animation:bcNavDrop 0.22s cubic-bezier(0.34,1.56,0.64,1);}',
      '@keyframes bcNavDrop{from{opacity:0;transform:translateY(-10px) scale(0.97);}to{opacity:1;transform:none;}}',

      /* nav link items */
      '#mobileNav ul{list-style:none;margin:0;padding:0;}',
      '#mobileNav ul li a{display:flex;align-items:center;gap:10px;',
      'padding:12px 14px;color:rgba(210,190,255,0.78);',
      "font-family:'Chakra Petch',sans-serif;font-size:15px;font-weight:700;",
      'text-decoration:none;border-radius:12px;border:1px solid transparent;',
      'transition:all 0.16s;letter-spacing:0.2px;}',
      '#mobileNav ul li a:hover{background:rgba(124,58,237,0.16);border-color:rgba(124,58,237,0.32);color:#EDE6FF;}',
      '#mobileNav ul li a.active{background:rgba(124,58,237,0.22);border-color:rgba(124,58,237,0.42);color:#FFD84E;}',

      /* auth slot */
      '.mobile-nav-auth{margin-top:8px;padding:10px 4px 0;',
      'border-top:1px solid rgba(255,255,255,0.07);display:flex;flex-wrap:wrap;gap:8px;align-items:center;}',
    ].join('');
    document.head.appendChild(s);
  }

  /* ── Layout switch (JS-driven, no CSS cache dependency) ─────── */
  function updateLayout() {
    var mobile = window.innerWidth <= BP;
    var btn    = document.getElementById('hamburgerBtn');
    var links  = document.querySelector('.nav-links');
    var logo   = document.querySelector('.nav-logo');
    var navCon = document.querySelector('.nav-container');
    var auth   = document.getElementById('bc-nav-user');
    var menu   = document.getElementById('mobileNav');

    if (btn)    btn.style.display    = mobile ? 'flex'     : 'none';
    if (links)  links.style.display  = mobile ? 'none'     : '';
    if (auth)   auth.style.display   = mobile ? 'none'     : '';
    if (navCon) navCon.style.position = mobile ? 'relative' : '';

    if (logo) {
      if (mobile) {
        logo.style.cssText += ';position:absolute;left:50%;transform:translateX(-50%);font-size:15px;';
      } else {
        logo.style.position = '';
        logo.style.left = '';
        logo.style.transform = '';
        logo.style.fontSize = '';
      }
    }

    if (!mobile && menu && menu.style.display === 'block') closeMobileMenu();
  }

  /* ── Toggle / close ─────────────────────────────────────────── */
  function toggleMobileMenu() {
    var btn  = document.getElementById('hamburgerBtn');
    var menu = document.getElementById('mobileNav');
    if (!btn || !menu) return;
    var opening = menu.style.display !== 'block';
    menu.style.display = opening ? 'block' : 'none';
    btn.classList.toggle('open', opening);
  }

  function closeMobileMenu() {
    var btn  = document.getElementById('hamburgerBtn');
    var menu = document.getElementById('mobileNav');
    if (!btn || !menu) return;
    menu.style.display = 'none';
    btn.classList.remove('open');
  }

  window.toggleMobileMenu = toggleMobileMenu;
  window.closeMobileMenu  = closeMobileMenu;

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeMobileMenu();
  });

  window.addEventListener('resize', updateLayout);

  /* ── Mirror auth badge into mobile menu ─────────────────────── */
  function mirrorAuth() {
    var slot  = document.getElementById('mobileAuthSlot');
    var badge = document.getElementById('bc-nav-user');
    if (!slot || !badge || document.getElementById('bc-nav-user-mobile')) return;

    var clone = badge.cloneNode(true);
    clone.id = 'bc-nav-user-mobile';
    clone.style.cssText = 'display:flex;align-items:center;gap:10px;flex-wrap:wrap;';

    var logoutBtn = clone.querySelector('button');
    if (logoutBtn) {
      var newBtn = logoutBtn.cloneNode(true);
      newBtn.addEventListener('click', function () {
        if (confirm('ออกจากระบบหรือไม่?')) {
          localStorage.removeItem('bc_session');
          window.location.href = 'login.html';
        }
      });
      logoutBtn.parentNode.replaceChild(newBtn, logoutBtn);
    }

    slot.appendChild(clone);
    updateLayout();
  }

  var observer = new MutationObserver(function () {
    if (document.getElementById('bc-nav-user')) {
      observer.disconnect();
      mirrorAuth();
    }
  });

  /* ── Boot ───────────────────────────────────────────────────── */
  function init() {
    injectCSS();
    updateLayout();
    mirrorAuth();
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
