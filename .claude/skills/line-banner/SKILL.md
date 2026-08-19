---
name: line-banner
description: "เพิ่ม/อัปเดต LINE OpenChat banner ในหน้า HTML ของร้าน BattleCats — banner สีเขียวด้านบนสุด มีปุ่มคลิกเลย, QR Code popup, checkbox ไม่แสดงอีก (localStorage)"
---

# LINE OpenChat Banner Skill

เพิ่ม banner แจ้งช่องทาง LINE OpenChat ในทุกหน้าของร้าน

## Banner HTML (วางหลัง `<body>` ก่อน `<nav>`)

```html
<!-- LINE OpenChat Banner -->
<div id="line-banner" style="display:none;background:#06C755;color:#fff;z-index:9999;font-family:'Chakra Petch',sans-serif;font-size:14px;position:relative;">
  <div style="display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:8px 14px;padding:9px 52px 9px 16px;">
    <span>💬 สามารถทักเข้า OpenChat มาสอบถามพูดคุยกันได้</span>
    <a href="https://line.me/ti/g2/PUmYGL3dhCeY4UbjU6QuHIrVEg7f2G7xS21voQ" target="_blank" rel="noopener"
       style="color:#fff;font-weight:700;text-decoration:underline;white-space:nowrap;">คลิกเลย</a>
    <button onclick="document.getElementById('line-qr-modal').style.display='flex';"
            style="background:rgba(0,0,0,0.25);border:1.5px solid rgba(255,255,255,0.5);color:#fff;font-family:'Chakra Petch',sans-serif;font-size:12px;font-weight:700;border-radius:6px;padding:3px 9px;cursor:pointer;white-space:nowrap;">📷 QR Code</button>
    <label style="display:inline-flex;align-items:center;gap:5px;font-size:12px;cursor:pointer;white-space:nowrap;background:rgba(0,0,0,0.18);border-radius:6px;padding:3px 9px;">
      <input type="checkbox" id="line-banner-no-show" style="cursor:pointer;width:14px;height:14px;"> ไม่แสดงอีก
    </label>
  </div>
  <button onclick="if(document.getElementById('line-banner-no-show').checked)localStorage.setItem('lineBannerHidden','1');document.getElementById('line-banner').style.display='none';"
          style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;color:#fff;font-size:22px;cursor:pointer;line-height:1;padding:0 4px;" aria-label="ปิด">×</button>
</div>
<script>if(!localStorage.getItem('lineBannerHidden'))document.getElementById('line-banner').style.display='block';</script>

<!-- QR Code Modal -->
<div id="line-qr-modal" onclick="if(event.target===this)this.style.display='none';"
     style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:99999;align-items:center;justify-content:center;">
  <div style="background:#fff;border-radius:18px;padding:20px;text-align:center;max-width:280px;width:90%;position:relative;">
    <button onclick="document.getElementById('line-qr-modal').style.display='none';"
            style="position:absolute;top:10px;right:12px;background:none;border:none;font-size:22px;cursor:pointer;color:#333;line-height:1;">×</button>
    <div style="font-family:'Chakra Petch',sans-serif;font-size:14px;font-weight:700;color:#06C755;margin-bottom:12px;">💬 LINE OpenChat</div>
    <img src="pictures/qr.jpg" alt="LINE QR Code" style="width:100%;max-width:220px;border-radius:10px;">
    <div style="font-family:'Chakra Petch',sans-serif;font-size:12px;color:#555;margin-top:10px;">สแกน QR เพื่อเข้ากลุ่ม</div>
  </div>
</div>
```

## พฤติกรรม

| การกระทำ | ผล |
|---|---|
| เปิดหน้าใหม่ | banner ขึ้นเสมอ (ถ้าไม่เคยกด ไม่แสดงอีก) |
| กด × ธรรมดา | ปิดแค่หน้านั้น หน้าอื่นขึ้นใหม่ |
| ติ๊ก ☑ ไม่แสดงอีก แล้วกด × | เก็บ localStorage → ไม่ขึ้นอีก |
| กด 📷 QR Code | popup QR ขึ้น กดนอก popup หรือ × เพื่อปิด |
| กด คลิกเลย | เปิด LINE OpenChat ในแท็บใหม่ |

## หน้าที่มี banner (BattleCats TH)

- index.html, shop.html, shop-codes.html, characters.html
- stages.html, orders.html, loyalty.html, wallet.html

**ไม่ใส่ใน:** admin.html, orders_manager.html, cr_orders_manager.html, test_no_payment.html, login.html

## LINE OpenChat URL

```
https://line.me/ti/g2/PUmYGL3dhCeY4UbjU6QuHIrVEg7f2G7xS21voQ
```

## QR รูป

```
/battlecats/pictures/qr.jpg  (VPS)
pictures/qr.jpg               (local)
```

## วิธีเพิ่มใน Goble Project

ใช้ HTML เดียวกัน เปลี่ยนแค่ path รูป QR ถ้าต่างกัน

## วิธี Deploy

```powershell
$password = ConvertTo-SecureString "SZ/(-6p-x/(yXXQW" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("root", $password)
$files = @("index.html","shop.html","shop-codes.html","characters.html","stages.html","orders.html","loyalty.html","wallet.html")
foreach ($f in $files) {
  Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path ".\$f" -Destination "/battlecats/" -AcceptKey
}
```
