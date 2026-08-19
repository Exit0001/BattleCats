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

  /* ── Mobile wallet chip (ใน mobile menu auth area) ─────────── */
  function injectMobileWalletChip() {
    // sync balance เข้า mobileAuthSlot หลัง mirrorAuth clone แล้ว
    function syncChip() {
      var badge  = document.getElementById('bc-wallet-badge');
      var mSlot  = document.getElementById('mobileAuthSlot');
      var mChip  = document.getElementById('bc-mobile-wallet');
      if (!badge || !mSlot) return;
      if (badge.style.display === 'none') return; // ยังโหลดไม่เสร็จ

      if (!mChip) {
        var chip = document.createElement('a');
        chip.id = 'bc-mobile-wallet';
        chip.href = 'wallet.html';
        chip.style.cssText = [
          'font-size:13px;font-weight:700;color:#34d399;',
          'background:rgba(52,211,153,0.12);border:1px solid rgba(52,211,153,0.35);',
          'padding:5px 12px;border-radius:20px;white-space:nowrap;text-decoration:none;',
          "font-family:'Chakra Petch',sans-serif;display:inline-flex;align-items:center;",
        ].join('');
        chip.textContent = badge.textContent;
        // เพิ่มไว้บน auth slot (ก่อน username/ออก)
        mSlot.insertBefore(chip, mSlot.firstChild);
      } else {
        mChip.textContent = badge.textContent;
      }
    }

    var badgeObs = new MutationObserver(syncChip);
    var tryObserve = setInterval(function() {
      var badge = document.getElementById('bc-wallet-badge');
      if (badge) {
        clearInterval(tryObserve);
        badgeObs.observe(badge, { childList: true, subtree: true, attributes: true, attributeFilter: ['style'] });
        syncChip();
      }
    }, 200);
  }

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
        var isEn = localStorage.getItem('bc_lang') === 'en';
        if (confirm(isEn ? 'Log out?' : 'ออกจากระบบหรือไม่?')) {
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

  /* ── Facebook Notice Banner ─────────────────────────────────── */
  function injectFbNotice() {
    if (document.getElementById('bc-fb-notice')) return;
    var bar = document.createElement('div');
    bar.id = 'bc-fb-notice';
    bar.style.cssText = 'background:linear-gradient(90deg,#7c2d12,#9a3412);border-bottom:1px solid rgba(251,146,60,0.4);padding:10px 16px;font-family:\'Chakra Petch\',sans-serif;font-size:13px;color:#fed7aa;position:relative;z-index:1000;';
    bar.innerHTML = [
      '<div style="max-width:900px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:10px;">',
        '<span style="flex:1;min-width:200px;">⚠️ <strong style="color:#fb923c;">Facebook ใช้งานไม่ได้ชั่วคราว</strong> — ติดต่อเราผ่าน Line OpenChat แทนได้เลยครับ</span>',
        '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">',
          '<a href="https://line.me/ti/g2/PUmYGL3dhCeY4UbjU6QuHIrVEg7f2G7xS21voQ?utm_source=invitation&utm_medium=link_copy&utm_campaign=default" target="_blank" ',
            'style="background:#06c755;color:#fff;padding:6px 14px;border-radius:8px;text-decoration:none;font-weight:700;font-size:12px;white-space:nowrap;">',
            '💬 เข้า Line OpenChat</a>',
          '<button onclick="document.getElementById(\'bc-fb-qr\').style.display=document.getElementById(\'bc-fb-qr\').style.display===\'none\'?\'block\':\'none\'" ',
            'style="background:rgba(255,255,255,0.15);color:#fed7aa;border:1px solid rgba(255,255,255,0.25);padding:6px 12px;border-radius:8px;cursor:pointer;font-family:\'Chakra Petch\',sans-serif;font-size:12px;white-space:nowrap;">',
            '📱 ดู QR Code</button>',
          '<button onclick="document.getElementById(\'bc-fb-notice\').style.display=\'none\'" ',
            'style="background:transparent;border:none;color:rgba(254,215,170,0.6);font-size:18px;cursor:pointer;padding:0 4px;line-height:1;">✕</button>',
        '</div>',
        '<div id="bc-fb-qr" style="display:none;width:100%;text-align:center;padding:10px 0;">',
          '<img src="/pictures/qr.jpg" alt="QR Line OpenChat" style="width:180px;height:180px;object-fit:contain;border-radius:12px;border:3px solid #06c755;">',
          '<div style="font-size:11px;color:rgba(254,215,170,0.7);margin-top:6px;">สแกน QR เพื่อเข้าร่วม Line OpenChat</div>',
        '</div>',
      '</div>'
    ].join('');
    document.body.insertBefore(bar, document.body.firstChild);
  }

  /* ── Boot ───────────────────────────────────────────────────── */
  function init() {
    injectCSS();
    updateLayout();
    injectMobileWalletChip();
    mirrorAuth();
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
