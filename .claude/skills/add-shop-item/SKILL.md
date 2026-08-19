---
name: add-shop-item
description: "เพิ่มไอเทมใหม่เข้า shop.html พร้อมราคาและ backend ครบ — 4 ไฟล์ในครั้งเดียว"
---

# Add Shop Item Skill

เมื่อ user ต้องการเพิ่มไอเทมใหม่ใน shop ให้แก้ **4 ไฟล์** ตามลำดับนี้

---

## ข้อมูลที่ต้องรู้ก่อน

ถามถ้าไม่มีในข้อความ:

| Field | ตัวอย่าง |
|-------|---------|
| `key` | `base_material`, `catseye_z` |
| `label` | ชื่อไทย เช่น `Base Materials` |
| `max` | จำนวนสูงสุดต่อครั้ง เช่น `9999` |
| `amounts` | list จำนวน เช่น `[30, 100, 500, 999]` |
| `prices` | ราคาแต่ละ amount เช่น `[20, 49, 149, 249]` |
| `section` | section ที่จะวางใน shop เช่น `🧱 Base Materials` (ใหม่) หรือชื่อ section เดิม |
| `image` | path รูป เช่น `pictures/base_material.png` (ถ้าไม่มีใช้ onerror hide) |
| `has_warning` | `True/False` — แสดง warning ก่อนซื้อ |
| `runner_type` | `simple` (edit item ปกติ) / `special` (เขียน handler เองเช่น base_material) / `cli_only` (ต้องทำมือ) |

---

## ไฟล์ที่ต้องแก้ (ครบทุกครั้ง)

### 1. `config.py` — เพิ่มใน ITEM_MAP และ AMOUNT_OPTIONS

```python
# ใน ITEM_MAP
"key": {"max": 9999, "has_warning": False, "label": "Label ที่แสดง",
        "note": "คำอธิบายเพิ่มเติม (optional)"},

# ใน AMOUNT_OPTIONS
"key": [30, 100, 500, 999],
```

---

### 2. `payment.py` — เพิ่มใน ITEM_PRICE

```python
# ใน dict ITEM_PRICE (ก่อนบรรทัด # Per-cat services)
"key": {
    30:  20,
    100: 49,
    500: 149,
    999: 249,
},
```

> ⚠️ ถ้าลืมเพิ่มตรงนี้ order จะสร้างด้วย amount=฿0 และ deduct_wallet จะ error ทันที

---

### 3. `runner.py` — เพิ่มใน `_edit_item()`

**กรณี simple** — ไอเทมที่ใช้ key → menu_no ตรงๆ ไม่ต้องทำอะไรพิเศษ (มีอยู่แล้ว)

**กรณี special** — เขียน handler แยกก่อน `return` ปกติ:

```python
if key == "key_name":
    # logic พิเศษ เช่น วนลูปหลาย index
    for i, obj in enumerate(save_file.something.items):
        old = obj.amount
        obj.amount = min(old + amount, max_val)
        self._log(f"[ITEM] Item#{i}: {old} + {amount} → {obj.amount}")
    return
```

**กรณี cli_only** — บันทึกใน ITEM_MAP แต่ runner จะ skip (ต้องทำมือผ่าน BCSFE CLI)

---

### 4. `shop.html` — เพิ่ม card(s) ใน section

**เพิ่มใน section เดิม** — หา `</div>` ปิด grid แล้วแทรก card ก่อน

**สร้าง section ใหม่** — วางหลัง section สุดท้ายก่อน `</div>` ปิด container:

```html
<!-- SECTION NAME -->
<h2 class="section-title" style="margin-top: 32px;">🧱 ชื่อ Section</h2>
<div class="grid grid-4">

  <div class="card">
    <div class="card-picture"><img loading="lazy" src="pictures/key_30.jpg" width="200" onerror="this.style.display='none'"></div>
    <div class="card-name">Label x30</div>
    <div class="card-desc">+30 ทุกชนิด ครบทั้ง 16 ประเภท</div>
    <div class="card-price"><span class="price-now">฿20</span></div>
    <button class="btn btn-primary" onclick="addToCart('Label x30', 20)" style="width:100%; margin-top:auto;"><span data-i18n="add_to_cart">เพิ่มลงตะกร้า</span></button>
  </div>

  <!-- ทำซ้ำสำหรับ x100, x500, x999 -->

</div>
```

**เพิ่มใน PRODUCT_MAP** (ใน `<script>` ของ shop.html):

```javascript
'Label x30':  { key: 'key', amount: 30 },
'Label x100': { key: 'key', amount: 100 },
'Label x500': { key: 'key', amount: 500 },
'Label x999': { key: 'key', amount: 999 },
```

**เพิ่มใน MAX_VALUES**:

```javascript
key: 9999,
```

---

## Deploy หลังแก้ครบ

```powershell
$pass = ConvertTo-SecureString "SZ/(-6p-x/(yXXQW" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("root", $pass)
$base = "c:\Users\modpo\OneDrive\เดสก์ท็อป\btc\BattleCats"

Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "$base\payment.py" -Destination "/battlecats/" -Force -AcceptKey
Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "$base\runner.py"  -Destination "/battlecats/" -Force -AcceptKey
Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "$base\config.py"  -Destination "/battlecats/" -Force -AcceptKey
Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "$base\shop.html"  -Destination "/battlecats/" -Force -AcceptKey

# อัพรูป (ถ้ามี)
# Set-SCPItem ... -Path "$base\pictures\key_30.jpg" -Destination "/battlecats/pictures/" ...

$ssh = New-SSHSession -ComputerName "187.77.156.253" -Credential $cred -AcceptKey -Force
Invoke-SSHCommand -SSHSession $ssh -Command "systemctl restart battlecats"
Remove-SSHSession $ssh
```

---

## Checklist ก่อน deploy

- [ ] `config.py` — มี key ใน ITEM_MAP และ AMOUNT_OPTIONS
- [ ] `payment.py` — มี key ใน ITEM_PRICE พร้อมราคาทุก amount
- [ ] `runner.py` — มี handler ถ้าเป็น special case
- [ ] `shop.html` — มี card, PRODUCT_MAP, MAX_VALUES ครบ
- [ ] รูปอัพโหลดแล้ว (ถ้ามี)
- [ ] เทสใน local ก่อนด้วย test_no_payment.html

---

## หมายเหตุ

- **ลืม payment.py** = order amount=฿0 → deduct_wallet error ทันที
- **ลืม PRODUCT_MAP** = กดเพิ่มลงตะกร้าแล้วส่ง key ผิดไป backend
- **ลืม MAX_VALUES** = frontend validate ผิด
- ทำ local ก่อนเสมอ แล้วค่อย deploy VPS
