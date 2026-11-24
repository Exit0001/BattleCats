// promo.js — โปรลดราคาทั้งร้าน (แสดงผลหน้าเว็บ)
// ⚠️ วัน/เปอร์เซ็นต์ต้องตรงกับ PROMO_START / PROMO_END / PROMO_PERCENT ใน payment.py
//    เซิร์ฟเวอร์เป็นตัวคิดเงินจริงเสมอ ไฟล์นี้แค่โชว์ราคา (และยืนยันกับ /api/promo อีกที)
// ตะกร้าเก็บราคาเดิมไว้ ส่วนลดคิดตอนแสดงผล -> ของที่ใส่ก่อนวันโปร พอถึงวันโปรราคาลดเอง
(function () {
  var START   = new Date('2026-11-01T00:00:00+07:00').getTime();
  var END     = new Date('2026-11-11T00:00:00+07:00').getTime();  // หมด 10 พ.ย. 23:59
  var now     = Date.now();

  function num(n) { return Number(n).toLocaleString(); }

  var P = window.BCPromo = {
    percent: 25,
    active:  now >= START && now < END,

    // ราคาหลังลด ทีละชิ้น ปัดครึ่งขึ้น (ตรงกับ promo_price() ใน payment.py)
    price: function (p) {
      p = Number(p) || 0;
      if (!P.active || !p) return p;
      return Math.floor((p * (100 - P.percent) + 50) / 100);
    },

    // HTML ราคา: ช่วงโปร = ~~฿35~~ ฿26 / ปกติ = ฿35
    fmt: function (p) {
      p = Number(p) || 0;
      var d = P.price(p);
      if (d === p) return '฿' + num(p);
      return '<s class="bcp-old">฿' + num(p) + '</s> <span class="bcp-new">฿' + num(d) + '</span>';
    },

    // รวมราคาตะกร้า (ลดทีละแถวแล้วค่อยรวม)
    sum: function (items) {
      return (items || []).reduce(function (s, i) { return s + P.price(i.price); }, 0);
    },

    decorate: decorate,
  };

  // ── CSS ─────────────────────────────────────────────
  var css =
    '.bcp-old{text-decoration:line-through;opacity:.55;font-size:.75em;font-weight:400;}' +
    '.bcp-new{color:#FF4D92;font-weight:700;}' +
    '.price-old.bcp-added{margin-left:2px;}' +
    '.bcp-badge{position:absolute;top:10px;left:10px;z-index:3;background:linear-gradient(135deg,#e8002a,#ff4d92);' +
      'color:#fff;font-family:"Russo One",sans-serif;font-size:13px;padding:3px 9px;border-radius:8px;' +
      'box-shadow:0 2px 10px rgba(232,0,42,.45);letter-spacing:.5px;pointer-events:none;}' +
    '#bcp-banner{background:linear-gradient(90deg,#b0001f,#e8002a,#ff4d92);color:#fff;text-align:center;' +
      'font-family:"Chakra Petch",sans-serif;font-size:14px;font-weight:700;padding:9px 16px;line-height:1.5;}' +
    '#bcp-banner b{font-family:"Russo One",sans-serif;font-size:16px;font-weight:400;letter-spacing:.5px;}';
  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  function isEn() { return !!(window.bcLang && window.bcLang() === 'en'); }

  // ── แบนเนอร์บนสุดของหน้า ─────────────────────────────
  function banner() {
    var el = document.getElementById('bcp-banner');
    if (!P.active) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('div');
      el.id = 'bcp-banner';
      document.body.insertBefore(el, document.body.firstChild);
    }
    el.innerHTML = isEn()
      ? '🔥 <b>' + P.percent + '% OFF EVERYTHING</b> Nov 1–10 only · Card prices already discounted'
      : '🔥 <b>ลด ' + P.percent + '% ทุกอย่าง</b> 1–10 พ.ย. นี้เท่านั้น · ราคาบนการ์ดคือราคาลดแล้ว';
  }

  // ── การ์ดที่ใช้ .price-now (shop / แพ็คในหน้าตัวละคร / event pack) ──
  function decorate(root) {
    (root || document).querySelectorAll('.price-now').forEach(function (el) {
      if (!el.dataset.bcpOrig) {
        var n = parseInt(el.textContent.replace(/[^\d]/g, ''), 10);
        if (!n) return;  // "สอบถามราคา" ฯลฯ
        el.dataset.bcpOrig = n;
      }
      var orig = Number(el.dataset.bcpOrig);
      var box  = el.parentNode;
      var old  = box.querySelector('.price-old');
      var card = el.closest('.card');
      var badge = card && card.querySelector(':scope > .bcp-badge');
      if (old && old.dataset.bcpText == null) old.dataset.bcpText = old.textContent;

      if (P.active) {
        el.textContent = '฿' + num(P.price(orig));
        if (!old) {
          old = document.createElement('span');
          old.className = 'price-old bcp-added';
          box.appendChild(old);
        }
        old.textContent = '฿' + num(orig);
        if (card && !badge) {
          badge = document.createElement('div');
          badge.className = 'bcp-badge';
          badge.textContent = '-' + P.percent + '%';
          card.appendChild(badge);
        }
      } else {
        el.textContent = '฿' + num(orig);
        if (old) {
          if (old.classList.contains('bcp-added')) old.remove();
          else old.textContent = old.dataset.bcpText;
        }
        if (badge) badge.remove();
      }
    });
  }

  function applyAll() {
    banner();
    decorate(document);
    window.dispatchEvent(new CustomEvent('bcpromo:change', { detail: { active: P.active } }));
  }

  function start() {
    applyAll();
    // การ์ดที่สร้างทีหลังด้วย JS (event pack โหลดจาก Supabase ฯลฯ)
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.classList.contains('price-now') || n.querySelector('.price-now')) decorate(n.parentNode || n);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });

    // ยืนยันกับเวลาเซิร์ฟเวอร์ (เครื่องลูกค้าตั้งเวลาผิด / เทส local ด้วย PROMO_FORCE)
    fetch('/api/promo').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (!d) return;
      if (!!d.active !== P.active || (d.active && d.percent !== P.percent)) {
        P.active  = !!d.active;
        P.percent = d.percent || P.percent;
        applyAll();
      }
    }).catch(function () {});
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
