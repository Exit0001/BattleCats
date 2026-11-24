---
name: fix-angpao
description: "แก้ปัญหาระบบอั่งเป่า TrueWallet ใช้ไม่ได้ — Cloudflare บล็อก, proxy, 407, Expecting value error"
---

# แก้ปัญหาระบบอั่งเป่า (TrueWallet)

## เช็คก่อนเสมอ — คำสั่งเดียวรู้ผล

```bash
cd /battlecats && venv/bin/python check_angpao.py
```

ไม่กินโควตาซอง ไม่แลกซองจริง (ใช้ hash ปลอม) — บอกครบ 4 อย่าง:
proxy ต่อได้ไหม · IP เป็นไทยไหม · TrueMoney ตอบ JSON ไหม · ยิงตรงยังโดนบล็อกไหม

---

## สาเหตุที่ทำให้พัง + วิธีแก้

### 1. `Expecting value: line 1 column 1 (char 0)` (ลูกค้าเห็น)

**แปลว่า** TrueMoney ตอบ HTML (หน้า Cloudflare) แทน JSON → `resp.json()` พัง

**ดู log ว่าเป็นแบบไหน:**
```bash
journalctl -u battlecats --no-pager --since "1 hour ago" | grep -a ANGPAO | tail -5
```

| ข้อความใน body | ความหมาย | แก้ |
|----------------|----------|-----|
| `Just a moment...` | Cloudflare ให้พิสูจน์ว่าไม่ใช่บอท | เปลี่ยน `impersonate` เป็นเวอร์ชันใหม่กว่า |
| `Sorry, you have been blocked` | บล็อก IP ถาวร | ต้องใช้ proxy IP ไทย |

### 2. `407 Proxy Authentication Required`

proxy ปฏิเสธ — สาเหตุเรียงตามความน่าจะเป็น:

1. **IP ของ VPS หลุดจาก whitelist** ← เจอบ่อยสุด
   เข้า dashboard.iproyal.com → order → แท็บ **Whitelist** → เช็คว่ามี `187.77.156.253`
2. **โควตาหมด** — เช็คยอดคงเหลือใน dashboard
3. VPS เปลี่ยน IP — เช็คด้วย `curl -s https://api.ipify.org` แล้วเอา IP ใหม่ไป whitelist

### 3. IP ที่ออกไปไม่ใช่ไทย

ใน whitelist ต้องมี Configuration = `_country-th`
ถ้าหาย ให้สร้าง whitelist entry ใหม่โดยเลือก Country/Region = Thailand

### 4. ปิดระบบชั่วคราว (ฉุกเฉิน)

```python
# payment.py
ANGPAO_PROXY = ""      # ปิด proxy (จะกลับไปโดนบล็อก แต่ไม่ค้าง)
```

**ซ่อนปุ่มไม่ให้ลูกค้าเห็น** — แทรกก่อน `</head>` ของ 6 ไฟล์:
`orders.html` `wallet.html` `characters.html` `stages.html` `shop-codes.html` `cookie-run.html`

```html
<style id="hide-truewallet">#btnPayTrueMoney{display:none!important;}</style>
```

ID ปุ่มแต่ละหน้าไม่เหมือนกัน:

| ไฟล์ | ID ปุ่ม |
|------|---------|
| orders.html | `#btnPayTrueMoney` |
| wallet.html | `#tabTrueMoney` |
| characters.html | `#apBtnTM` |
| stages.html | `#pmBtnTM` |
| shop-codes.html | `#pdBtnTW` |
| cookie-run.html | `#tabTW` |

> เปิดกลับ = ลบ block นั้นทิ้ง · **ตรวจสมดุล `<div>` เทียบ git ทุกครั้งหลังแก้ HTML**

---

## ⚠️ กุญแจสำคัญ — ต้องครบ 2 อย่างพร้อมกัน

| ต้องมี | ทำไม |
|--------|------|
| **IP ไทย residential** | Cloudflare บล็อก IP ศูนย์ข้อมูล (VPS Hostinger มาเลเซีย) |
| **ลายนิ้วมือ TLS แบบ Chrome** | ต้องใช้ `curl_cffi` + `impersonate` — `curl` ธรรมดาโดน 403 แม้ IP ถูก |

**ขาดอย่างใดอย่างหนึ่ง = 403** (พิสูจน์แล้ว: proxy ไทย + curl ธรรมดา ยังโดนบล็อก)

---

## ค่าที่ใช้อยู่ (4 ก.ย. 2569)

```python
# payment.py
ANGPAO_PROXY = "http://geo.iproyal.com:12321"   # IPRoyal, whitelist IP ไม่ต้องใส่ user/pass

def _angpao_session_kwargs() -> dict:
    kw = {"impersonate": "chrome136"}
    if ANGPAO_PROXY:
        kw["proxies"] = {"http": ANGPAO_PROXY, "https": ANGPAO_PROXY}
    return kw
```

ใช้ที่ 3 จุดใน `payment.py` (redeem ร้านหลัก / code shop / cookie run)

**IPRoyal:** order `81487917` · 2 GB · $12.50 · **ไม่มีวันหมดอายุ**
whitelist IP `187.77.156.253` · Country `_country-th` · Rotation `Randomize IP`

**ใช้ ~10 KB ต่อซอง** → 2 GB ประมาณ 200,000 ซอง

---

## ประวัติปัญหา

**4 ก.ย. 2569 หลัง 11:00 น.** — Cloudflare ของ TrueMoney เริ่มบล็อก IP ของ VPS
- ตอนแรก `Just a moment...` แล้วยกระดับเป็น `Sorry, you have been blocked`
- ทดสอบ `impersonate` 7 เวอร์ชัน (chrome124-146) โดน 403 หมด → ยืนยันว่าเป็นการบล็อกที่ระดับ IP
- แม้แต่หน้าแรก `www.truemoney.com` ก็โดน = บล็อกทั้งโดเมน ไม่ใช่เฉพาะ API
- เน็ตบ้าน (IP residential ไทย) ใช้ได้ปกติ → พิสูจน์ว่าเป็นเรื่อง IP
- **แก้ด้วย IPRoyal residential proxy + chrome136** → กลับมาใช้ได้

> **ไม่เกี่ยวกับ Cloudflare ของเรา** — Cloudflare เราคุมขาเข้า (`battlecatpromax.cloud`)
> ส่วนนี้เป็นขาออกจาก VPS ไป TrueMoney ไม่ผ่านของเราเลย

---

## Deploy

```powershell
cd "c:\Users\modpo\OneDrive\เดสก์ท็อป\btc\BattleCats"
.\deploy-payment.ps1        # payment.py (รันเทส security ก่อนอัตโนมัติ)
```

HTML ต้องอัปแยกด้วย `Set-SCPItem` แล้ว restart service
