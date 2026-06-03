/* Battle Cats Shop — Supabase Client + PromptPay Config */
var DB = window.supabase.createClient(
  'https://jpzceuxeelnwthaitkcw.supabase.co',
  'sb_publishable_VhQvIEjYgaDy0eW1qaIkyw_cxb5eZly'
);

// ╔══════════════════════════════════════════════════╗
// ║  PromptPay — ใส่เบอร์โทรหรือเลขประจำตัวที่นี่    ║
// ║  เช่น '0812345678' หรือ '1234567890123'          ║
// ╚══════════════════════════════════════════════════╝
var PROMPTPAY_ID = ''; // ← ใส่เบอร์ PromptPay ของคุณ

// ── PromptPay QR Generator (EMVCo standard) ────────────────────
var PromptPay = (function () {
  function crc16(str) {
    var c = 0xFFFF;
    for (var i = 0; i < str.length; i++) {
      c ^= str.charCodeAt(i) << 8;
      for (var j = 0; j < 8; j++) {
        c = (c & 0x8000) ? ((c << 1) ^ 0x1021) & 0xFFFF : (c << 1) & 0xFFFF;
      }
    }
    return c.toString(16).toUpperCase().padStart(4, '0');
  }

  function tlv(tag, val) {
    return tag + ('00' + val.length).slice(-2) + val;
  }

  function qrString(idOrPhone, amount) {
    var id = (idOrPhone || '').replace(/\D/g, '');
    // Mobile: 0xxxxxxxxx → 0066xxxxxxxxx
    if (id.length === 10 && id.charAt(0) === '0') id = '0066' + id.slice(1);
    // Tax/Citizen ID: 13 digits stays as-is

    var acct = tlv('00', 'A000000677010111') + tlv('01', id);
    var payload =
      tlv('00', '01') +
      tlv('01', '12') +
      tlv('29', acct) +
      tlv('52', '0000') +
      tlv('53', '764') +
      (amount ? tlv('54', parseFloat(amount).toFixed(2)) : '') +
      tlv('58', 'TH') +
      tlv('59', 'BattleCatsShop') +
      tlv('60', 'Bangkok') +
      '6304';

    return payload + crc16(payload);
  }

  return { qrString: qrString };
})();
