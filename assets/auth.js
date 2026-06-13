/* Battle Cats Shop — Authentication System (Supabase Auth + localStorage fallback) */

// ── Auto-load Supabase SDK if not already present ─────────────
(function () {
  if (window.supabase && window.DB) return;
  if (window.supabase && !window.DB) {
    window.DB = window.supabase.createClient(
      'https://jpzceuxeelnwthaitkcw.supabase.co',
      'sb_publishable_VhQvIEjYgaDy0eW1qaIkyw_cxb5eZly'
    );
    return;
  }
  var s = document.createElement('script');
  s.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js';
  s.onload = function () {
    if (!window.DB) {
      window.DB = window.supabase.createClient(
        'https://jpzceuxeelnwthaitkcw.supabase.co',
        'sb_publishable_VhQvIEjYgaDy0eW1qaIkyw_cxb5eZly'
      );
    }
  };
  document.head.appendChild(s);
})();

var AUTH = (function () {
  'use strict';

  var SESSION_KEY = 'bc_session';
  var USERS_KEY   = 'bc_users';

  // ── Wait for DB to be ready (max 3s) ─────────────────────────
  function _waitDB() {
    return new Promise(function (resolve) {
      if (window.DB) { resolve(true); return; }
      var tries = 0;
      var t = setInterval(function () {
        tries++;
        if (window.DB) { clearInterval(t); resolve(true); }
        else if (tries >= 30) { clearInterval(t); resolve(false); }
      }, 100);
    });
  }

  function _hash(pw) { return btoa(unescape(encodeURIComponent(pw))); }

  // ── Session helpers ───────────────────────────────────────────
  function _localUser() {
    try { var s = JSON.parse(localStorage.getItem(SESSION_KEY)); return s ? s.username : null; }
    catch (e) { return null; }
  }
  function _localUsers() {
    try { return JSON.parse(localStorage.getItem(USERS_KEY) || '{}'); } catch (e) { return {}; }
  }
  function _setSession(u, hash) {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ username: u, hash: hash || '', at: Date.now() }));
  }

  // ── Public sync helpers ───────────────────────────────────────
  function getCurrentUser() { return _localUser(); }
  function isLoggedIn()     { return !!_localUser(); }

  // ── Register (Supabase profiles table — ไม่ต้อง email confirm) ─
  async function register(username, password) {
    username = (username || '').trim();
    password = (password || '').trim();
    if (!username || !password)  return { ok: false, err: 'กรอกข้อมูลให้ครบถ้วน' };
    if (username.length < 3)     return { ok: false, err: 'ชื่อผู้ใช้ต้องมีอย่างน้อย 3 ตัวอักษร' };
    if (password.length < 6)     return { ok: false, err: 'รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร' };

    var ready = await _waitDB();
    if (!ready) return { ok: false, err: 'เชื่อมต่อ Supabase ไม่ได้ กรุณารีเฟรชแล้วลองใหม่' };

    // ตรวจ username ซ้ำ
    var chk = await window.DB.from('profiles')
      .select('username', { count: 'exact', head: true })
      .eq('username', username);
    if ((chk.count || 0) > 0) return { ok: false, err: 'ชื่อผู้ใช้นี้ถูกใช้งานแล้ว' };

    var ins = await window.DB.from('profiles').insert([{
      username:      username,
      password_hash: _hash(password),
    }]);
    if (ins.error) return { ok: false, err: ins.error.message };

    _setSession(username, _hash(password));
    return { ok: true };
  }

  // ── Login (Supabase profiles → localStorage fallback) ─────────
  async function login(username, password) {
    username = (username || '').trim();
    password = (password || '').trim();
    if (!username || !password) return { ok: false, err: 'กรอกข้อมูลให้ครบถ้วน' };

    var ready = await _waitDB();
    if (ready) {
      var res = await window.DB.from('profiles')
        .select('username')
        .eq('username', username)
        .eq('password_hash', _hash(password))
        .maybeSingle();

      if (res.data) { _setSession(res.data.username, _hash(password)); return { ok: true }; }

      // username มีใน DB แต่ password ผิด
      var has = await window.DB.from('profiles')
        .select('username', { count: 'exact', head: true })
        .eq('username', username);
      if ((has.count || 0) > 0) return { ok: false, err: 'รหัสผ่านไม่ถูกต้อง' };
    }

    // Fallback: old localStorage accounts
    var users = _localUsers();
    if (!users[username]) return { ok: false, err: 'ไม่พบชื่อผู้ใช้นี้' };
    if (users[username].pw !== _hash(password)) return { ok: false, err: 'รหัสผ่านไม่ถูกต้อง' };
    _setSession(username, _hash(password));
    return { ok: true };
  }

  // ── Logout ────────────────────────────────────────────────────
  function logout() {
    localStorage.removeItem(SESSION_KEY);
    window.location.href = 'login.html';
  }

  function requireLogin() {
    if (!isLoggedIn()) { window.location.href = 'login.html'; return false; }
    return true;
  }

  // ── Order history (Supabase) ──────────────────────────────────
  function getUserOrders() { return []; } // deprecated — orders.html uses Supabase directly

  // ── Navbar badge injection ────────────────────────────────────
  function _injectNavBadge() {
    var nav = document.querySelector('.nav-container');
    if (!nav || document.getElementById('bc-nav-user')) return;

    var user = getCurrentUser();
    var el   = document.createElement('div');
    el.id    = 'bc-nav-user';
    el.style.cssText = 'display:flex;align-items:center;gap:8px;flex-shrink:0;';

    if (user) {
      el.innerHTML =
        '<a href="loyalty.html" id="bc-loyalty-badge" title="แต้มสะสม" ' +
        'style="font-size:12px;font-weight:700;color:#fbbf24;' +
        'background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.35);' +
        'padding:5px 12px;border-radius:20px;white-space:nowrap;text-decoration:none;' +
        "font-family:'Chakra Petch',sans-serif;transition:all 0.2s;display:none;" + '">🎁 —</a>' +
        '<span style="font-size:13px;font-weight:700;color:#fff;' +
        'background:rgba(124,58,237,0.3);border:1px solid rgba(124,58,237,0.5);' +
        'padding:5px 14px;border-radius:20px;white-space:nowrap;">👤 ' + user + '</span>' +
        '<button id="bc-logout-btn" style="font-size:12px;color:rgba(255,255,255,0.6);' +
        'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);' +
        'padding:5px 12px;border-radius:20px;cursor:pointer;' +
        "font-family:'Chakra Petch',sans-serif;transition:all 0.2s;" + '">ออก</button>';
      el.querySelector('#bc-logout-btn').addEventListener('click', function () {
        if (confirm('ออกจากระบบหรือไม่?')) logout();
      });
      // โหลด loyalty status และอัพเดท badge
      fetch('/api/loyalty/status?username=' + encodeURIComponent(user))
        .then(function(r) { return r.json(); })
        .then(function(d) {
          var badge = document.getElementById('bc-loyalty-badge');
          if (!badge) return;
          var cycles = d.available_cycles || 0;
          var pct    = d.progress_pct || 0;
          if (cycles > 0) {
            badge.textContent = '🎁 ' + cycles + ' รอบพร้อมแลก!';
            badge.style.background = 'rgba(251,191,36,0.22)';
            badge.style.borderColor = 'rgba(251,191,36,0.6)';
            badge.style.boxShadow = '0 0 10px rgba(251,191,36,0.25)';
          } else {
            badge.textContent = '🎁 ฿' + (d.progress_baht || 0) + '/200';
          }
          badge.style.display = '';
        })
        .catch(function() {});  // fail silently
    } else {
      el.innerHTML =
        '<a href="login.html" style="font-size:13px;font-weight:700;' +
        'color:rgba(255,255,255,0.9);background:linear-gradient(135deg,#7C3AED,#F43F5E);' +
        'padding:6px 16px;border-radius:20px;text-decoration:none;white-space:nowrap;' +
        'box-shadow:0 4px 16px rgba(124,58,237,0.3);transition:filter 0.2s;"' +
        ' onmouseover="this.style.filter=\'brightness(1.1)\'" onmouseout="this.style.filter=\'\'">🔑 เข้าสู่ระบบ</a>';
    }

    var cart = nav.querySelector('.nav-cart');
    if (cart) {
      nav.insertBefore(el, cart);
      cart.style.cursor = 'pointer';
      cart.title = 'ดูออเดอร์ของฉัน';
      cart.addEventListener('click', function () {
        window.location.href = 'orders.html';
      });
    } else {
      nav.appendChild(el);
    }
  }

  // ── Page loader ───────────────────────────────────────────────
  function _injectLoader() {
    var loader = document.createElement('div');
    loader.id = 'bc-page-loader';
    loader.innerHTML =
      '<div style="text-align:center;">' +
        '<div style="font-size:52px;animation:bc-paw-pulse 0.8s ease-in-out infinite;">🐾</div>' +
        '<div style="margin-top:18px;font-family:\'Chakra Petch\',sans-serif;font-size:15px;' +
             'font-weight:700;color:rgba(255,255,255,0.6);letter-spacing:1px;">กำลังโหลด...</div>' +
        '<div style="margin-top:16px;width:120px;height:3px;background:rgba(255,255,255,0.08);' +
             'border-radius:99px;overflow:hidden;">' +
          '<div id="bc-loader-bar" style="height:100%;width:0;' +
               'background:linear-gradient(90deg,#7C3AED,#F43F5E);' +
               'border-radius:99px;transition:width 0.4s ease;"></div>' +
        '</div>' +
      '</div>';
    loader.style.cssText =
      'position:fixed;inset:0;z-index:99999;background:#080616;' +
      'display:flex;align-items:center;justify-content:center;' +
      'transition:opacity 0.45s ease;';

    var style = document.createElement('style');
    style.textContent = '@keyframes bc-paw-pulse{0%,100%{transform:scale(1);}50%{transform:scale(1.18);}}';
    document.head.appendChild(style);
    document.body.prepend(loader);

    setTimeout(function () {
      var bar = document.getElementById('bc-loader-bar');
      if (bar) bar.style.width = '70%';
    }, 80);

    function _hide() {
      var bar = document.getElementById('bc-loader-bar');
      if (bar) bar.style.width = '100%';
      setTimeout(function () {
        loader.style.opacity = '0';
        setTimeout(function () { loader.remove(); }, 450);
      }, 200);
    }

    if (document.readyState === 'complete') { setTimeout(_hide, 300); }
    else { window.addEventListener('load', function () { setTimeout(_hide, 200); }); }
  }

  // ── Route guard ───────────────────────────────────────────────
  function _routeGuard() {
    var page = window.location.pathname.split('/').pop() || 'index.html';
    if (page === 'orders.html' && !isLoggedIn()) {
      window.location.replace('login.html');
    }
  }

  // ── Login-required modal ──────────────────────────────────────
  function _showLoginModal() {
    if (document.getElementById('bc-login-modal')) return;
    var overlay = document.createElement('div');
    overlay.id = 'bc-login-modal';
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:99998;background:rgba(0,0,0,0.72);' +
      'display:flex;align-items:center;justify-content:center;padding:20px;' +
      'animation:bc-modal-in 0.25s ease-out;';
    var style = document.createElement('style');
    style.textContent =
      '@keyframes bc-modal-in{from{opacity:0;}to{opacity:1;}}' +
      '@keyframes bc-card-in{from{opacity:0;transform:translateY(20px) scale(0.96);}to{opacity:1;transform:none;}}';
    document.head.appendChild(style);
    overlay.innerHTML =
      '<div style="background:linear-gradient(160deg,rgba(18,4,44,0.99),rgba(28,4,64,0.99));' +
           'border:1px solid rgba(124,58,237,0.3);border-radius:24px;padding:40px 36px;' +
           'max-width:380px;width:100%;text-align:center;box-shadow:0 40px 120px rgba(0,0,0,0.6);' +
           'animation:bc-card-in 0.3s ease-out;">' +
        '<div style="font-size:48px;margin-bottom:12px;">🔐</div>' +
        '<div style="font-family:\'Russo One\',sans-serif;font-size:20px;color:#fff;margin-bottom:8px;">กรุณาเข้าสู่ระบบก่อน</div>' +
        '<div style="font-family:\'Chakra Petch\',sans-serif;font-size:14px;color:rgba(255,255,255,0.55);margin-bottom:28px;line-height:1.6;">' +
          'ต้องมีบัญชีสมาชิกจึงจะสามารถ<br>เพิ่มสินค้าหรือสั่งซื้อได้' +
        '</div>' +
        '<a href="login.html" style="display:block;padding:13px;border-radius:12px;' +
           'background:linear-gradient(135deg,#7C3AED,#b75bff 45%,#F43F5E);' +
           'color:#fff;font-family:\'Chakra Petch\',sans-serif;font-size:15px;font-weight:700;' +
           'text-decoration:none;margin-bottom:12px;box-shadow:0 8px 24px rgba(124,58,237,0.35);">🔑 เข้าสู่ระบบ / สมัครสมาชิก</a>' +
        '<button onclick="document.getElementById(\'bc-login-modal\').remove()" ' +
           'style="width:100%;padding:11px;border-radius:12px;background:rgba(255,255,255,0.06);' +
           'border:1px solid rgba(255,255,255,0.12);color:rgba(255,255,255,0.5);' +
           'font-family:\'Chakra Petch\',sans-serif;font-size:14px;cursor:pointer;">ปิด</button>' +
      '</div>';
    overlay.addEventListener('click', function (e) { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
  }

  // ── Intercept guest purchase clicks ──────────────────────────
  function _interceptGuest() {
    if (isLoggedIn()) return;
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('button, a');
      if (!btn) return;
      var oc = btn.getAttribute('onclick') || '';
      if (oc.indexOf('addToCart') !== -1 || oc.indexOf('checkout') !== -1) {
        e.preventDefault();
        e.stopImmediatePropagation();
        _showLoginModal();
      }
    }, true);
  }

  // ── Boot ──────────────────────────────────────────────────────
  _injectLoader();
  _routeGuard();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      _injectNavBadge();
      _interceptGuest();
    });
  } else {
    _injectNavBadge();
    _interceptGuest();
  }

  return {
    register:       register,
    login:          login,
    logout:         logout,
    isLoggedIn:     isLoggedIn,
    getCurrentUser: getCurrentUser,
    requireLogin:   requireLogin,
    getUserOrders:  getUserOrders,
  };
})();
