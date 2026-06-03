/* Battle Cats Shop — Notification System */
var NOTIFY = (function () {
  'use strict';

  // ╔══════════════════════════════════════════════╗
  // ║  ตั้งค่า Discord Webhook URL ที่นี่           ║
  // ║  วิธีสร้าง: Discord Server → Edit Channel   ║
  // ║  → Integrations → Webhooks → New Webhook    ║
  // ╚══════════════════════════════════════════════╝
  var DISCORD_WEBHOOK = ''; // ← วาง URL ตรงนี้

  function _fmt(n) { return (n || 0).toLocaleString('en-US'); }

  // ── Discord embed ─────────────────────────────────────────────
  async function discord(order) {
    if (!DISCORD_WEBHOOK) return;
    try {
      var items = (order.items || [])
        .map(function (i) { return '• ' + (i.name || '-') + ' — ฿' + _fmt(i.price); })
        .join('\n') || '-';

      var serverMap = { '1':'🌍 EN/TH/EU', '2':'🇯🇵 JP', '3':'🇰🇷 KR', '4':'🇹🇼 TW' };
      var serverLabel = serverMap[order.server] || order.server || '-';

      await fetch(DISCORD_WEBHOOK, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          embeds: [{
            title: '🛍️ ออเดอร์ใหม่! #' + (order.id || '').substring(0, 8).toUpperCase(),
            color: 0x7C3AED,
            fields: [
              { name: '👤 ลูกค้า',        value: order.username || '-',    inline: true },
              { name: '💰 ยอดรวม',       value: '฿' + _fmt(order.total), inline: true },
              { name: '🌐 Server',        value: serverLabel,              inline: true },
              { name: '📱 ติดต่อ',        value: order.contact  || '-',    inline: true },
              { name: '🔑 Transfer Code', value: '```\n' + (order.transfer_code || '-') + '\n```' },
              { name: '🔐 Confirm Code',  value: '```\n' + (order.confirm_code  || '-') + '\n```' },
              { name: '📦 สินค้า',        value: items },
            ],
            footer: { text: 'Battle Cats Shop — ' + new Date().toLocaleString('th-TH') },
            timestamp: new Date().toISOString(),
          }],
        }),
      });
    } catch (e) {
      console.warn('[NOTIFY] Discord failed:', e.message);
    }
  }

  return { discord: discord };
})();
