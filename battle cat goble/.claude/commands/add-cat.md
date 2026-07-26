# Add New Cat(s) to Shop

เมื่อมีตัวละครใหม่ในเกม ให้ทำตามขั้นตอนนี้ทีละขั้น

## ข้อมูลที่ต้องรู้ก่อน
- **Cat ID** — หมายเลข ID ในเกม
- **Tier** — `N` / `EX` / `RR` / `SR` / `UR` / `LR`
- **ชื่อ** — ชื่อภาษาอังกฤษ
- **URL รูป** — หาจาก [Battle Cats Wiki](https://battlecats.miraheze.org) → ดูชื่อไฟล์รูปที่หน้าตัวละคร

## ขั้นตอน

### 1. เพิ่มข้อมูลใน characters_data.js

เปิดไฟล์ `assets/characters_data.js` แล้วเพิ่มบรรทัดใหม่ **ก่อน `];`** (บรรทัดสุดท้าย):

```
[ID,"TIER","ชื่อ"],[ID2,"TIER","ชื่อ2"]
```

ตัวอย่าง:
```javascript
[866,"EX","Pac-Man Cat"],[867,"EX","Blinky Cat"]
```

> ⚠️ ตัวละครที่อยู่บรรทัดก่อน `];` ต้องลงท้ายด้วย `,` (comma)

### 2. หา URL รูปจาก Wikitide

รูปตัวละครอยู่ที่ `static.wikitide.net/battlecatswiki/` โดยใช้ MD5 hash ของชื่อไฟล์

รูปแบบชื่อไฟล์ที่ลอง (ตามลำดับ):
1. `{ID}_1.png` — เช่น `866_1.png`
2. `Gatyachara_{ID:03d}_f.png` — เช่น `Gatyachara_866_f.png`

**คำนวณ URL:**
```
hash = md5("{ชื่อไฟล์}")
URL = https://static.wikitide.net/battlecatswiki/{hash[0]}/{hash[:2]}/{ชื่อไฟล์}
```

เช็คว่า URL ถูกต้องโดยเปิดใน browser — ถ้า 404 ให้ไปหาชื่อไฟล์จริงในหน้า Wiki แล้วใช้ URL นั้นตรงๆ

### 3. โหลดรูปลง VPS ด้วย curl

SSH เข้า VPS แล้วรันคำสั่ง:

```bash
curl -L -A "Mozilla/5.0" -o /battlecats/pictures/cats/{ID}.png "{URL}"
```

เช็คว่าโหลดสำเร็จ (ไม่ใช่ HTML/404):
```bash
file /battlecats/pictures/cats/{ID}.png
```

ต้องได้ `PNG image data` ไม่ใช่ `HTML document`

### 4. Deploy characters.html ขึ้น VPS

เพิ่ม version ใน script tag ของ `characters.html` (เพิ่มตัวเลข v ทุกครั้งที่อัปเดต):
```html
<script src="assets/characters_data.js?v=3"></script>
```

แล้ว SCP ทั้งสองไฟล์ขึ้น VPS:
```
characters.html → /battlecats/
assets/characters_data.js → /battlecats/assets/
```

### 5. Purge Cloudflare Cache

1. เข้า [dash.cloudflare.com](https://dash.cloudflare.com)
2. เลือก domain **battlecatpromax.cloud**
3. **Caching** → **Configuration** → **Purge Everything**
4. ยืนยัน

### 6. ตรวจสอบ

เปิดเว็บ → ค้นหาชื่อหรือ ID ตัวละครใหม่ → ต้องเห็น card + รูปขึ้น

---

## VPS Credentials
- IP: `187.77.156.253`
- User: `root`
- Path: `/battlecats/`

## หมายเหตุ
- ถ้า Python httpx ดึงรูปไม่ได้ (Cloudflare block) → ใช้ `curl` บน VPS โดยตรงเท่านั้น
- ถ้า Cloudflare cache รูปเก่า → Purge Everything แก้ได้ทุกครั้ง
- ID ในเกมมีช่องว่าง (gap) เป็นเรื่องปกติ เช่น ไม่มี #860
